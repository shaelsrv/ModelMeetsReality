"""Decision trace — for any event: who holds the power, what model of the choices they
hold, and which choice they take.

The pressure model (sister B) run at the individual-decision grain. For a named event:

  1. IDENTIFY the person in the position of power — the one whose next choice actually
     moves the stakes (not the loudest actor; the one holding the decision).
  2. RECONSTRUCT their choice-model: the branches available AS THEY LIKELY SEE THEM,
     each branch's stakes placed on the self-ladder (body / habit-competence /
     role-status / identity / meaning) with the FORM that installed each stake (state,
     party, market, electorate, peers, legacy/ideology) and its credibility — because
     per the model, felt pressure is Sum p(b)*|dStakes/dChoice| over INSTALLED branches,
     and installation fidelity (phi), provenance, and update latency shape what the
     holder actually feels vs what is broadcast at them.
  3. PREDICT the choice: a probability over branches, with resolution criteria and a
     date — appended to my-model/predict/ledger.json as a normal claim, graded by
     the weekly loop like everything else.

Traces persist to my-model/traces/<slug>.json (+ TRACES.md index). The ledger path
is PRIVATE (only B's signals ledger is registered in the public sync); publishing these
as a B-2 public ledger is a user decision.

  python -m suites.decision_trace --event "September my-model rate decision"
  python -m suites.decision_trace --event "my-model-US my-model de-my-model" --horizon 45
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.openrouter import chat  # noqa: E402
from harness.actors import parse_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT.parent
from harness.fleet import DECISION_REPO as REPO  # set decision_repo in fleet.json

TRACE_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. You are running the pressure model below
as a decision-tracing instrument on a live event.

=== THE MODEL ===
{model_text}
=== END MODEL ===

EVENT: {event}

STEP 1 — THE HOLDER. Identify the person in the position of power: the one whose next choice
actually moves the stakes on this event (there may be a short ranked list; pick the primary and
say why the power sits there — office, veto, timing). INCUMBENCY CHECK (mandatory): VERIFY via
web search that the person holds the office TODAY, {today} — officeholders change; deaths,
term expiries, and successions are exactly what parametric memory gets wrong. State the date of
the source confirming incumbency. If the office recently changed hands, the NEW holder is the
subject. Also verify the current state of the event (cite 2-3 dated items).

STEP 2 — THE OFFICE'S CHOICE SET AND ITS PUBLIC PRESSURE LANDSCAPE. This is institutional
analysis of a public office, not psychological profiling: model the POSITION, never the person's
inner life (the instrument's position/personal-power boundary). Lay out the option set facing
the office (include the do-nothing/delay option; include options publicly foreclosed by prior
commitments, noting the commitment). For each option, list the publicly documented stakes bearing
on the OFFICE, classified by layer (institutional mandate / operational-competence / role-status /
institutional identity / stated mission), and for each stake name the INSTALLING FORM (statute or
mandate, party or coalition, markets, electorate, press, allied institutions, precedent), its
severity, and its credibility (has the consequence been demonstrated recently? enforcement or
market reactions count as demonstrations).

STEP 3 — THE PRESSURE READ. Applying the model's calculus to the office's publicly documented
stake landscape: which option carries the least institutional pressure, is the office near
saturation (many high-severity stakes pulling in conflict), and is there a dilemma signature
(no low-pressure option -> expect delay or reframing)?

STEP 4 — THE CHOICE. A probability distribution over the branches (must sum to ~1.0), the single
predicted choice, a resolve-by date ({resolve_by} unless the event has its own natural date), and
CONCRETE resolution criteria (an observable action, not a mood).

Return ONLY JSON:
{"event":"...","observed":[{"item":"...","date":"..."}],
"holders":[{"name":"...","position":"...","why_primary":"..."}],
"branches":[{"choice":"...","stakes":[{"layer":"mandate|operational|role-status|institutional-identity|mission",
"stake":"...","installed_by":"...","severity":"low|med|high","credibility":"low|med|high"}],
"foreclosed":false}],
"pressure_read":"one paragraph: least-pressure branch, saturation, dilemma signature if any",
"low_provenance_stakes":["..."],
"choice_distribution":[{"choice":"...","p":0.0}],
"predicted_choice":"...","p":0.0,"resolve_by":"YYYY-MM-DD",
"resolution_criteria":"observable that settles it"}"""


VERIFY_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. Who CURRENTLY holds this office:
{position}?
Search for the current officeholder AS OF TODAY. Deaths, term expiries, and successions are the
entire point of this check -- do not answer from memory, and prefer sources dated within the last
few months. Return ONLY JSON:
{"holder":"full name","since":"YYYY-MM (approx)","source":"name of source","source_date":"YYYY-MM-DD (approx)"}"""


def verify_holder(position: str, model: str, today: str) -> dict | None:
    """The incumbency gate. Instructions inside the trace prompt proved insufficient
    (the tool's first runs produced a dead president and an expired Fed chair even with
    an explicit check demanded) -- so verification is a separate, narrow call whose only
    job is the officeholder. Cheap verifier gating a strong output, per the family
    playbook."""
    r = chat(model + ":online", [{"role": "user", "content":
                                  VERIFY_PROMPT.replace("{today}", today)
                                  .replace("{position}", position)}],
             temperature=0.0, max_tokens=600)
    return parse_json(r.text) if not r.error else None


def _same_person(a: str, b: str) -> bool:
    """Shared-surname is NOT identity: dynastic succession (Ali -> my-model my-model)
    slipped through a bare token-overlap match and let a deceased holder pass the gate.
    Same person iff >=2 shared name tokens, or one side is a single token (bare surname
    like 'Powell' vs 'Jerome Powell')."""
    at, bt = set(a.lower().split()), set(b.lower().split())
    shared = at & bt
    return len(shared) >= 2 or (len(shared) >= 1 and min(len(at), len(bt)) == 1)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def trace(event: str, model: str, horizon: int) -> None:
    rdir = TOOLS / REPO
    model_text = (rdir / "MODEL.md").read_text(encoding="utf-8")[:9000]
    today = datetime.date.today().isoformat()
    resolve_by = (datetime.date.today() + datetime.timedelta(days=horizon)).isoformat()
    p = (TRACE_PROMPT.replace("{today}", today).replace("{model_text}", model_text)
         .replace("{event}", event).replace("{resolve_by}", resolve_by))
    print(f"[decision-trace] {event}")
    d = None
    for attempt in range(3):
        r = chat(model + ":online", [{"role": "user", "content": p}],
                 temperature=0.3 if attempt == 0 else 0.2, max_tokens=5500)
        d = parse_json(r.text) if not r.error else None
        if d and d.get("holders") and d.get("predicted_choice"):
            break
        d = None
    if not d:
        raise SystemExit(f"trace failed after retries: {r.error or 'unparseable'}")

    # incumbency gate: verify the claimed holder; on mismatch, one corrected re-trace
    h0 = d["holders"][0]
    v = verify_holder(h0.get("position", ""), model, today)
    if v and v.get("holder") and not _same_person(v["holder"], h0.get("name", "")):
        print(f"  ! incumbency gate: trace named {h0.get('name')} but current "
              f"{h0.get('position')} is {v['holder']} (since {v.get('since','?')}, "
              f"{v.get('source','?')}) -- re-tracing for the correct holder")
        p2 = p + ("\n\nCORRECTION (verified " + today + "): the current "
                  f"{h0.get('position')} is {v['holder']} (since {v.get('since','?')}, "
                  f"per {v.get('source','?')}). Redo the ENTIRE trace for {v['holder']} "
                  f"as the holder. Do not use {h0.get('name')}.")
        r = chat(model + ":online", [{"role": "user", "content": p2}],
                 temperature=0.3, max_tokens=5500)
        d = parse_json(r.text) if not r.error else None
        if not d or not d.get("holders") or not d.get("predicted_choice"):
            raise SystemExit("corrected re-trace failed")
        if not _same_person(d["holders"][0].get("name", ""), v["holder"]):
            raise SystemExit(f"incumbency gate: re-trace still names "
                             f"{d['holders'][0].get('name')} -- refusing to record")
        d["incumbency_verified"] = v
    elif v:
        d["incumbency_verified"] = v
    else:
        d["incumbency_verified"] = None
        print("  ! incumbency verification unavailable -- trace recorded UNVERIFIED")
    d["traced_on"] = today
    d["traced_with"] = model

    tdir = rdir / "traces"
    tdir.mkdir(exist_ok=True)
    slug = slugify(event)
    (tdir / f"{slug}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    h = d["holders"][0]
    print(f"  holder: {h.get('name','?')} ({h.get('position','?')})")
    for b in d.get("branches", []):
        top = max(b.get("stakes", []), key=lambda s: {"low": 0, "med": 1, "high": 2}
                  .get(s.get("severity"), 0), default={})
        fc = " [foreclosed]" if b.get("foreclosed") else ""
        print(f"    branch: {b.get('choice','')[:70]}{fc}"
              + (f"  <- top stake: {top.get('stake','')[:50]} ({top.get('installed_by','?')})"
                 if top else ""))
    print(f"  pressure read: {d.get('pressure_read','')[:140]}")
    for c in d.get("choice_distribution", []):
        print(f"    p={c.get('p')} {c.get('choice','')[:70]}")
    print(f"  PREDICTED [{d.get('p')}]: {d['predicted_choice'][:90]} (by {d.get('resolve_by')})")

    # the prediction is a normal B claim: append to the (private) predict ledger
    lpath = rdir / "predict" / "ledger.json"
    lpath.parent.mkdir(exist_ok=True)
    led = (json.load(lpath.open(encoding="utf-8")) if lpath.exists()
           else {"predictions": [], "learnings": [], "rounds": 0})
    led["rounds"] += 1
    led["predictions"].append({
        "entity": f"decision:{slug}"[:80], "name": f"{h.get('name','?')} — {event}"[:90],
        "made_on": today, "resolve_by": d.get("resolve_by") or resolve_by,
        "round": led["rounds"], "status": "open",
        "claim": f"{h.get('name','?')} will {d['predicted_choice']}"[:250],
        "resolution_criteria": d.get("resolution_criteria", ""),
        "confidence": d.get("p"), "mechanism": "my-model decision trace: "
        + d.get("pressure_read", "")[:200],
        "trace": f"traces/{slug}.json"})
    json.dump(led, lpath.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)

    # index
    idx = tdir / "TRACES.md"
    line = (f"- {today} **{event}** → {h.get('name','?')} ({h.get('position','?')}): "
            f"predicts *{d['predicted_choice'][:80]}* (p={d.get('p')}, by {d.get('resolve_by')}) "
            f"— `{slug}.json`\n")
    prev = idx.read_text(encoding="utf-8") if idx.exists() else "# Decision traces\n\n"
    idx.write_text(prev + line, encoding="utf-8")
    print(f"  -> traces/{slug}.json + ledger claim appended ({len(led['predictions'])} total)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Who holds the power, what model of the choices, which choice (pressure model).")
    ap.add_argument("--event", required=True)
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="gpt-4o:online proved refusal- and parse-flaky on this task; sonnet held")
    ap.add_argument("--horizon", type=int, default=45)
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY not set")
    trace(a.event, a.model, a.horizon)


if __name__ == "__main__":
    main()
