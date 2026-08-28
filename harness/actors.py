"""The three simulated actors that stand in for a ChatGPT/Claude Project.

- Sim-Assistant — the thing UNDER TEST. We fake the Project mechanics around a model:
  injected project-instructions (persistent system text), a fake-memory blob carried
  across "sessions", and (later) a stubbed/live web tool. Whatever model we point this
  at is what we're benchmarking.
- Sim-User — a persona with a POV, answering an installer interview or reacting.
- Judge — a SEPARATE model that scores a transcript/output against a rubric and, for the
  epistemic suites, against a ground-truth reality pack. Kept separate on purpose: a model
  should not grade itself.

All three are just `openrouter.chat` with different system prompts. Keeping them here
(not scattered in suites) means every suite composes the same well-defined actors.
"""
from __future__ import annotations

import json
from typing import Optional

from harness.openrouter import chat, ChatResult


# ── Sim-Assistant: fake the Project around a model under test ──────────────────

def as_project_assistant(
    model: str,
    project_instructions: str,
    user_message: str,
    *,
    memory: Optional[dict] = None,
    history: Optional[list[dict]] = None,
    temperature: float = 0.4,
    max_tokens: int = 2600,
    online: bool = False,
) -> ChatResult:
    """Run ONE assistant turn as if inside a ChatGPT/Claude Project.

    project_instructions -> the persistent system prompt (PERMANENT_INSTRUCTIONS, or a
    BOOTSTRAP prompt). memory -> a JSON blob representing what the Project "remembers"
    from earlier sessions (this is how we test Claim Tracker across time). history ->
    prior turns in THIS session (for the multi-turn interview).

    online=True gives the assistant WEB RETRIEVAL via OpenRouter's ':online' plugin — the
    real ChatGPT/Claude Project has web, and the no-web harness systematically under-grounds
    briefings (measured: grounding 51/100). This is the parametric-vs-retrieval track the
    benchmark spec calls for; flip it to test whether grounded briefings clear the bar."""
    sys = project_instructions.strip()
    if memory:
        sys += (
            "\n\n[PROJECT MEMORY — what you remember from earlier sessions. Treat as your"
            " own persistent memory; use it, and when a task asks what changed since before,"
            " compare against it.]\n" + json.dumps(memory, ensure_ascii=False, indent=1)
        )
    msgs = [{"role": "system", "content": sys}]
    if history:
        msgs.extend(history)
    msgs.append({"role": "user", "content": user_message})
    call_model = f"{model}:online" if (online and not model.endswith(":online")) else model
    return chat(call_model, msgs, temperature=temperature, max_tokens=max_tokens)


# ── Sim-User: a persona that drives an interview ──────────────────────────────

USER_SYS = """You are role-playing a real person using an AI assistant. Stay in character.
You are NOT the assistant — you are the human answering it. Reply as the user would:
briefly, in plain language, one message at a time. Do not narrate or break character.
Your persona and point of view:
{persona}

Answer the assistant's questions from this persona. If asked something you don't know,
say so plainly. If asked to approve something, decide as this persona reasonably would.
Keep replies short — a sentence or two — like a real chat."""


def as_user(model: str, persona: str, assistant_message: str,
            history: Optional[list[dict]] = None, temperature: float = 0.6) -> ChatResult:
    """Produce the user's next reply given what the assistant just said."""
    msgs = [{"role": "system", "content": USER_SYS.format(persona=persona.strip())}]
    # From the user's vantage, the assistant's messages are the 'user' role turns.
    if history:
        msgs.extend(history)
    msgs.append({"role": "user", "content": assistant_message})
    return chat(model, msgs, temperature=temperature, max_tokens=400)


# ── Judge: score against a rubric (+ reality pack for epistemic suites) ────────

JUDGE_SYS = """You are a rigorous, skeptical evaluation judge for an AI system's output.
You do not praise; you score against the rubric exactly. Be calibrated and specific:
cite the evidence in the OUTPUT for each score. When a REALITY reference is provided, it
is the ground truth — grade the output's accuracy and calibration against it, and count
any claim that contradicts the reference as an error, and any overconfident claim about
something the reference marks uncertain as a calibration failure.

Return ONLY a JSON object, no prose around it, of the exact shape:
{schema}"""


def judge(model: str, rubric: str, output: str, *, reality: str = "",
          schema: str = "", temperature: float = 0.0) -> ChatResult:
    """Score one OUTPUT with a JUDGE model. `reality` is the ground-truth pack (may be
    empty for purely mechanical suites). `schema` is the exact JSON shape to return."""
    parts = ["## RUBRIC\n" + rubric.strip()]
    if reality:
        parts.append("## REALITY REFERENCE (ground truth — grade against this)\n" + reality.strip())
    parts.append("## OUTPUT TO SCORE\n" + output.strip())
    msgs = [
        {"role": "system", "content": JUDGE_SYS.format(schema=schema.strip() or "{...}")},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    return chat(model, msgs, temperature=temperature, max_tokens=1800)


def parse_json(text: str) -> Optional[dict]:
    """Best-effort JSON extraction from a judge reply. Handles ```json fences anywhere,
    stray prose before/after, and models that wrap the object in commentary. Falls back to
    the outermost {...} span."""
    import re
    t = (text or "").strip()
    # 1) a fenced block anywhere (```json ... ``` or ``` ... ```)
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2) the outermost brace span, tried whole then trimmed from the right
    a, b = t.find("{"), t.rfind("}")
    if a != -1 and b != -1 and b > a:
        span = t[a : b + 1]
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            # some models append trailing prose after a valid object; retry shrinking b
            for end in range(b, a, -1):
                if t[end] == "}":
                    try:
                        return json.loads(t[a : end + 1])
                    except json.JSONDecodeError:
                        continue
    return None
