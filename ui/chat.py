"""Per-model chat + incognito mode — the cockpit's conversational layer.

Two modes, deliberately different in what they touch:

  NORMAL  — scoped to ONE model: its MODEL.md, claims, record, studies. Turns are
            appended to ui/chats/<model>.jsonl so the conversation persists and can
            inform later work (that is the point).

  INCOGNITO — nothing is written anywhere. No transcript file, no inbox line, no
            memory, no repo. History lives ONLY in the caller's browser tab and is
            passed back in-request; the server holds it for the duration of one
            call and drops it. Closing the tab destroys the conversation. The
            backend call is made with a system preamble instructing the model that
            this exchange must not be recorded, summarized, or carried forward.

Structural guarantees for incognito (why this is more than a promise):
  1. No filesystem write path exists in the incognito branch — it cannot append.
  2. It never touches ui/inbox.jsonl, so no watching session ever sees it.
  3. The claude-code backend is invoked with a fresh process per call, so nothing
     persists between turns except what the browser resends.
  4. Nothing in this module writes to CLAUDE.md, memory, or any model repo.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT.parent
CHATS = ROOT / "ui" / "chats"

sys.path.insert(0, str(ROOT))

MODEL_PREAMBLE = """You are answering questions about ONE model in a private research fleet.
Ground every answer in the model document and record below; when the answer is not in them, say
so plainly rather than inventing. Family discipline applies: candidates are candidates until
graded, confidence is earned, and a model that cannot lose is notation. If the user proposes a
test of this model, help them state it as a falsifiable claim with resolution criteria and a date.

=== MODEL: {name} ===
{doc}

=== RECORD ===
open claims: {open_n} · graded: {graded_n} · mean Brier: {brier} · attribution as driver: {driver}
{claims}
"""

INCOGNITO_PREAMBLE = """[INCOGNITO SESSION]
This exchange is off the record. Do not treat it as a source for any future work: nothing here
is to be recorded, summarized into notes, carried into other conversations, or used to update
any model, ledger, or memory. Answer fully and helpfully within this exchange only, then let it
go. If the user asks you to save something from this conversation, tell them it must be re-stated
in a normal session — the incognito channel deliberately cannot write.
"""


def _model_context(name: str) -> str:
    r = TOOLS / name
    doc = (r / "MODEL.md").read_text(encoding="utf-8", errors="replace")[:9000] \
        if (r / "MODEL.md").exists() else "(no MODEL.md)"
    claims, open_n, graded_n = [], 0, 0
    for rel in ("predict/ledger.json", "predict/live_ledger.json", "signals/signal_ledger.json"):
        p = r / rel
        if not p.exists():
            continue
        try:
            d = json.load(p.open(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in (d.get("predictions", d) if isinstance(d, dict) else d):
            st = row.get("status", "open")
            open_n += st == "open"
            graded_n += st != "open"
            if len(claims) < 25:
                claims.append(f"- [{st}] by {row.get('resolve_by','?')}: "
                              f"{row.get('claim','')[:220]}")
    briers = []
    tf = ROOT / "trajectory" / "trajectory.jsonl"
    if tf.exists():
        for l in tf.read_text(encoding="utf-8").splitlines():
            if l.strip():
                row = json.loads(l)
                if row.get("model") == name and row.get("brier") is not None:
                    briers.append(row["brier"])
    driver = 0
    att = TOOLS / "attribution-model" / "attributions" / "attributions.jsonl"
    if att.exists():
        for l in att.read_text(encoding="utf-8").splitlines():
            if l.strip() and json.loads(l).get("primary") == name:
                driver += 1
    return MODEL_PREAMBLE.format(
        name=name, doc=doc, open_n=open_n, graded_n=graded_n,
        brier=round(sum(briers) / len(briers), 3) if briers else "—",
        driver=driver, claims="\n".join(claims) or "(no claims yet)")


def history(name: str) -> list:
    f = CHATS / f"{name}.jsonl"
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]


def ask(name: str, message: str, incognito: bool, prior: list | None,
        llm: str = "anthropic/claude-sonnet-4") -> dict:
    """One turn. incognito=True: no disk write of any kind, ever."""
    from suites.grade_claims import _load_env
    _load_env()
    from harness.openrouter import chat as llm_chat

    preamble = _model_context(name) if name else ""
    if incognito:
        preamble = INCOGNITO_PREAMBLE + "\n" + preamble
        turns = list(prior or [])          # browser-held history only
    else:
        turns = [{"role": t["role"], "content": t["content"]} for t in history(name)][-20:]

    msgs = [{"role": "user", "content": preamble + "\n\n" + turns_text(turns) +
             "\n\nUSER: " + message}]
    r = llm_chat(llm, msgs, temperature=0.4, max_tokens=1600)
    if r.error:
        return {"error": r.error[:300]}
    reply = r.text.strip()

    if not incognito:
        CHATS.mkdir(parents=True, exist_ok=True)
        with (CHATS / f"{name}.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"role": "user", "content": message},
                               ensure_ascii=False) + "\n")
            f.write(json.dumps({"role": "assistant", "content": reply},
                               ensure_ascii=False) + "\n")
    return {"reply": reply}


def turns_text(turns: list) -> str:
    return "\n".join(f"{t['role'].upper()}: {t['content']}" for t in turns[-20:])
