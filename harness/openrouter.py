"""One gateway, N models — the OpenRouter adapter.

The whole benchmark rests on apples-to-apples: the SAME prompt sent to many models
through one API surface, so a difference in output is a difference in the model, not
the plumbing. OpenRouter gives us that (OpenAI-compatible /chat/completions over a
single key). A GCP/Vertex adapter can slot in behind the same `chat()` signature later.

Env:
  OPENROUTER_API_KEY   required to make real calls
  OPENROUTER_BASE      optional, defaults to https://openrouter.ai/api/v1

No SDK dependency — plain urllib, so the harness runs with a bare Python 3.12.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Optional

BASE = os.environ.get("OPENROUTER_BASE", "https://openrouter.ai/api/v1")


def _is_local(base: str) -> bool:
    """Is this endpoint on the machine (or the docker host), not the internet?

    Decides whether an API key is required. Local servers — Ollama on 11434,
    LM Studio on 1234, llama.cpp — accept requests with no credential, so
    demanding one only prevents fully-offline operation.

    `host.docker.internal` counts: from inside a container that name resolves to
    the host, which is exactly how a sandboxed run reaches a local model without
    the container itself having internet.
    """
    b = base.lower()
    return any(h in b for h in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]",
                                "host.docker.internal", "ollama", "lmstudio"))


@dataclass
class ChatResult:
    text: str
    model: str
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    error: Optional[str] = None


def chat(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2400,
    tools: Optional[list] = None,
    retries: int = 3,
    timeout: int = 120,
) -> ChatResult:
    """Send a chat completion to one model via OpenRouter. Returns a ChatResult;
    never raises for an API error — it carries `error` so a benchmark run can score a
    model as 'failed to respond' rather than crashing the whole sweep."""
    # A LOCAL server (Ollama, LM Studio, llama.cpp) needs no key, and demanding
    # one made fully-local operation impossible: the fleet refused to start
    # before it ever reached the endpoint. So a key is required only when
    # talking to a REMOTE host — pointing OPENROUTER_BASE at localhost is itself
    # the statement that no credential is involved.
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key and not _is_local(BASE):
        return ChatResult(
            text="", model=model,
            error="OPENROUTER_API_KEY not set (not needed for a local "
                  "OPENROUTER_BASE such as http://localhost:11434/v1)")

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools

    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if not _is_local(BASE):
        # OpenRouter asks for these for attribution/ranking. They are not sent
        # to a local server: a self-hosted endpoint has no use for them, and a
        # fully-offline setup should not be quietly announcing a referer.
        headers["HTTP-Referer"] = "https://example.com"
        headers["X-Title"] = "Copilot Reality Benchmark"

    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{BASE}/chat/completions", data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                j = json.loads(resp.read().decode())
            choice = (j.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            return ChatResult(text=text, model=model, usage=j.get("usage", {}), raw=j)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            last_err = f"HTTP {e.code}: {detail}"
            # 429 / 5xx are worth a backoff; 4xx (bad model id, auth) are not.
            if e.code in (429, 500, 502, 503, 529) and attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            break
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            break
    return ChatResult(text="", model=model, error=last_err)


# A small default roster to benchmark. Override with --models or MODELS env.
# (IDs are OpenRouter slugs; edit freely — the harness treats these as opaque.)
DEFAULT_MODELS = [
    "anthropic/claude-sonnet-4",
    "openai/gpt-5",
    "google/gemini-2.5-pro",
    "meta-llama/llama-3.3-70b-instruct",
    "deepseek/deepseek-chat",
]


def roster(arg: Optional[str] = None) -> list[str]:
    """Resolve the model list: explicit CSV arg > MODELS env > DEFAULT_MODELS."""
    src = arg or os.environ.get("MODELS")
    if src:
        return [m.strip() for m in src.split(",") if m.strip()]
    return list(DEFAULT_MODELS)


# ---------------------------------------------------------------------------
# Pluggable backends (LLM_BACKEND env):
#   openrouter        (default) — the path above; OPENROUTER_BASE overrides let any
#                     OpenAI-compatible endpoint serve (Ollama: http://localhost:11434/v1)
#   claude-code       — shell out to the `claude` CLI in print mode, so runs bill the
#                     user's EXISTING Claude subscription/limits instead of an API key.
#                     ":online" model suffix maps to allowing the WebSearch tool.
# The chat() signature is identical across backends; suites never know the difference.
# ---------------------------------------------------------------------------
import shutil as _shutil
import subprocess as _sp

_CLAUDE_BIN = os.environ.get("CLAUDE_CODE_BIN", "claude")


def _claude_model(model: str) -> str:
    m = model.lower()
    for name in ("opus", "sonnet", "haiku"):
        if name in m:
            return name
    return "sonnet"  # non-Anthropic slugs run as sonnet on this backend


def _chat_claude_code(model, messages, *, max_tokens, timeout, retries) -> "ChatResult":
    if not _shutil.which(_CLAUDE_BIN):
        return ChatResult(text="", model=model,
                          error=f"claude-code backend: '{_CLAUDE_BIN}' not on PATH")
    online = ":online" in model
    prompt = chr(10).join(
        (("[system] " + m["content"]) if m.get("role") == "system" else m["content"])
        for m in messages)
    # prompt via STDIN: Windows argv caps ~32k chars and corpora exceed it
    cmd = [_CLAUDE_BIN, "-p", "--model", _claude_model(model),
           "--output-format", "json"]
    # In the agent sandbox --bare is a security CONTROL, not a preference: its
    # documented behaviour is that OAuth and the keychain are never read, so
    # auth is strictly the API key passed in. That is what keeps the operator's
    # subscription credential out of a container built to handle hostile input.
    # The image sets CLAUDE_CODE_SIMPLE=1; on the host this is a no-op.
    if os.environ.get("CLAUDE_CODE_SIMPLE") == "1":
        cmd.insert(1, "--bare")
    if online:
        cmd += ["--allowedTools", "WebSearch"]
    last = None
    for attempt in range(retries):
        try:
            r = _sp.run(cmd, input=prompt, capture_output=True,
                        timeout=max(timeout, 300),
                        encoding="utf-8", errors="replace")
            out = (r.stdout or "").strip()
            if not out:
                last = f"empty output (rc={r.returncode}): {(r.stderr or '')[:200]}"
                continue
            j = json.loads(out)
            if j.get("is_error"):
                last = f"claude-code error: {str(j.get('result'))[:200]}"
                continue
            return ChatResult(text=j.get("result") or "", model=model,
                              usage=j.get("usage", {}), raw=j)
        except (_sp.TimeoutExpired, json.JSONDecodeError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return ChatResult(text="", model=model, error=last)


_chat_openrouter = chat


def chat(model, messages, *, temperature=0.3, max_tokens=2400, tools=None,
         retries=3, timeout=120):
    backend = os.environ.get("LLM_BACKEND", "openrouter")
    if backend == "claude-code":
        return _chat_claude_code(model, messages, max_tokens=max_tokens,
                                 timeout=timeout, retries=retries)
    return _chat_openrouter(model, messages, temperature=temperature,
                            max_tokens=max_tokens, tools=tools,
                            retries=retries, timeout=timeout)
