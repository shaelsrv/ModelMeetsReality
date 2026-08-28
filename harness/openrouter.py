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

    data = json.dumps(body).encode()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # OpenRouter asks for these for attribution/ranking; harmless if unset.
        "HTTP-Referer": "https://example.com",
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
