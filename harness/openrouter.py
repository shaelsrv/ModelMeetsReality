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


@dataclass
class ChatResult:
    text: str
    model: str
    usage: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    error: Optional[str] = None
    # URLs the provider actually retrieved for this completion. Empty when the
    # call did not research. This is the audit trail: a claim that cites a URL
    # absent from here is an invented citation, and validate_citations() below
    # is what stops it reaching the ledger.
    citations: list = field(default_factory=list)
    researched: bool = False


def _annotations(choice: dict) -> list:
    """Pull url_citation annotations off a completion. Providers differ on where
    they hang them, so check both documented spots rather than assuming one."""
    msg = choice.get("message") or {}
    out = []
    for a in (msg.get("annotations") or []):
        u = (a.get("url_citation") or {}) if isinstance(a, dict) else {}
        if u.get("url"):
            out.append({"url": u["url"], "title": u.get("title", "")})
    return out


def validate_citations(cited: list[str], retrieved: list[dict]) -> tuple[list, list]:
    """Split claimed URLs into (grounded, invented) against what was retrieved.

    A model asked to cite its sources will sometimes produce plausible URLs it
    never opened. Sealing such a claim would launder a fabrication into the
    ledger under the appearance of evidence, so citations are checked against
    the provider's own annotation list rather than trusted.
    """
    have = {r["url"].rstrip("/") for r in retrieved}
    # Host+path prefix match: providers routinely return a canonicalised or
    # redirect-resolved form of the URL the model echoes back.
    def seen(u: str) -> bool:
        u = (u or "").rstrip("/")
        return any(u == h or u.startswith(h) or h.startswith(u) for h in have)
    # Only judge things that are actually URLs. A lens sometimes puts its search
    # QUERY in the sources list ('(search: "foo" OR "bar")'), which is not a
    # fabricated citation -- it is a non-URL, and flagging it as invented cries
    # wolf on the one check that must stay trustworthy.
    urls = [u for u in cited if str(u).strip().lower().startswith(('http://', 'https://'))]
    grounded = [u for u in urls if seen(u)]
    invented = [u for u in urls if not seen(u)]
    return grounded, invented


def chat(
    model: str,
    messages: list[dict],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2400,
    tools: Optional[list] = None,
    research: bool = False,
    max_results: int = 5,
    retries: int = 3,
    timeout: int = 120,
) -> ChatResult:
    """Send a chat completion to one model via OpenRouter. Returns a ChatResult;
    never raises for an API error — it carries `error` so a benchmark run can score a
    model as 'failed to respond' rather than crashing the whole sweep."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        return ChatResult(text="", model=model, error="OPENROUTER_API_KEY not set")

    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        body["tools"] = tools
    # Web research. Billed PER REQUEST, so the caller's searches-per-lens cap is
    # the real cost lever, not max_results.
    if research:
        body["plugins"] = [{"id": "web", "max_results": max_results}]

    data = json.dumps(body).encode()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # OpenRouter asks for these for attribution/ranking; harmless if unset.
        # Attribution headers are OPTIONAL and were shipping a specific domain on
        # every call made from anyone else's install. Overridable, defaulting
        # to nothing identifying.
        "HTTP-Referer": os.environ.get("OPENROUTER_REFERER", ""),
        "X-Title": "Copilot Reality Benchmark",
    }

    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(f"{BASE}/chat/completions", data=data, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                j = json.loads(resp.read().decode())
            choice = (j.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            cits = _annotations(choice)
            return ChatResult(text=text, model=model, usage=j.get("usage", {}), raw=j,
                              citations=cits, researched=bool(research))
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
import re as _re
import shutil as _shutil
import subprocess as _sp

_CLAUDE_BIN = os.environ.get("CLAUDE_CODE_BIN", "claude")


_URL_RE = _re.compile(r'https?://[^\s\"\\\'\\<>)\]]+')


def _parse_stream(out: str):
    """Read a --output-format stream-json transcript: return (result_event, urls).

    The URLs are harvested from the WebSearch tool RESULTS, not from the model's
    prose — that is the whole point. A URL here is one the tool actually returned,
    so a citation matching it is grounded and one that does not is invented.
    """
    result, urls = None, []
    seen = set()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("type") == "result":
            result = d
            continue
        # tool results arrive as 'user' events carrying tool_result content
        if d.get("type") == "user":
            for u in _URL_RE.findall(json.dumps(d)):
                u = u.rstrip(r'\\.,);')
                if u not in seen:
                    seen.add(u)
                    urls.append({"url": u, "title": ""})
    return result, urls


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
    # When researching, ask for the STREAM so the WebSearch tool events (and the
    # URLs they actually returned) are visible. Plain --output-format json gives
    # only the final text, which would leave a researched read unauditable: the
    # model's cited URLs could not be checked against anything, and an invented
    # citation would sail into the ledger looking like evidence.
    cmd = [_CLAUDE_BIN, "-p", "--model", _claude_model(model),
           "--output-format", "stream-json" if online else "json"]
    if online:
        cmd += ["--verbose", "--allowedTools", "WebSearch"]
    last = None
    for attempt in range(retries):
        try:
            r = _sp.run(cmd, input=prompt, capture_output=True,
                        timeout=max(timeout, 540),
                        encoding="utf-8", errors="replace")
            out = (r.stdout or "").strip()
            if not out:
                last = f"empty output (rc={r.returncode}): {(r.stderr or '')[:200]}"
                continue
            if online:
                j, cits = _parse_stream(out)
                if j is None:
                    last = "claude-code: no result event in stream"
                    continue
                if j.get("is_error"):
                    last = f"claude-code error: {str(j.get('result'))[:200]}"
                    continue
                return ChatResult(text=j.get("result") or "", model=model,
                                  usage=j.get("usage", {}), raw=j,
                                  citations=cits, researched=True)
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


def _is_local(base: str) -> bool:
    """Does this base URL point at something on the user's own machine?

    Takes the URL rather than reading the environment, because compat_check needs
    to test candidate URLs it is not currently configured with.
    """
    b = (base or "").lower()
    return any(h in b for h in ("localhost", "127.0.0.1", "0.0.0.0", "[::1]",
                                "host.docker.internal", "ollama", "lmstudio"))


def _is_local_base() -> bool:
    """The configured base, for the dispatcher's degradation branch."""
    return _is_local(os.environ.get("OPENROUTER_BASE", BASE))


def chat(model, messages, *, temperature=0.3, max_tokens=2400, tools=None,
         research=False, max_results=5, retries=3, timeout=120):
    """One signature across three backends (compat doctrine: every change must work
    on all three installation levels).

    `research=True` asks the backend to search the web before answering. Support is
    NOT uniform, and the difference is surfaced rather than hidden:

      openrouter  — native `plugins:[{id:"web"}]`; citations returned.
      claude-code — WebSearch via the CLI's allow-list (the ":online" suffix path).
      local       — Ollama / LM Studio have no web capability. The call still runs
                    and answers from the brief alone, returning researched=False so
                    the caller can label the read honestly. Degrading loudly beats
                    crashing (self-host must keep working) and beats degrading
                    silently (a brief-only read must never be filed as researched).
    """
    backend = os.environ.get("LLM_BACKEND", "openrouter")
    if backend == "claude-code":
        r = _chat_claude_code(model if not research else _with_online(model), messages,
                              max_tokens=max_tokens, timeout=timeout, retries=retries)
        # The CLI does not hand back a citation list, so a claude-code read is
        # researched but unauditable — callers must not treat it as grounded.
        r.researched = bool(research)
        return r
    if research and _is_local_base():
        r = _chat_openrouter(model, messages, temperature=temperature,
                             max_tokens=max_tokens, tools=tools,
                             retries=retries, timeout=timeout)
        r.researched = False
        r.raw = dict(r.raw or {}, degraded="local backend has no web search")
        return r
    return _chat_openrouter(model, messages, temperature=temperature,
                            max_tokens=max_tokens, tools=tools,
                            research=research, max_results=max_results,
                            retries=retries, timeout=timeout)


def _with_online(model: str) -> str:
    return model if ":online" in model else f"{model}:online"
