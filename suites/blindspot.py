"""Blindspot register — pre-commit the shape of the unmonitored at a live criticality.

Implements blindspot-model/MODEL.md (the C4 compose): dominant observers' monitored
dimensions are enumerable (P2); the resolving event tends to arrive from the complement
(P1); a list written BEFORE resolution is a measurement, after is a story (P3).

Registrations are immutable once written — a changed read is a NEW dated registration.
Each registration also opens a row in predict/ledger.json (generic schema) so the
weekly grading loop codes the arrival dimension at resolve_by.

  python -m suites.blindspot --register --case hormuz --criticality "the Strait of Hormuz shipping crisis"
  python -m suites.blindspot --list
"""
from __future__ import annotations

import argparse
import datetime
import json
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
REPO = ROOT.parent / "blindspot-model"
RDIR = REPO / "registrations"
LEDGER = REPO / "predict" / "ledger.json"

REGISTER = """You have LIVE WEB ACCESS. Today is {today}. You are building a BLIND-SPOT REGISTRATION
for a live criticality — a situation where a transition is likely but the outcome is still open.
The theory: whatever dominant observers monitor gets managed (hedged, priced, pre-empted), so the
RESOLVING event tends to arrive from an unmonitored dimension. Your job is to enumerate the
monitored set from real evidence, then name the complement IN ADVANCE.

THE CRITICALITY: {criticality}

Step 1 — DOMINANT OBSERVERS: the 4-8 entities whose sensing actually shapes responses here
(ministries, central banks, markets/exchanges, agencies, insurers, wire services, specialized
analysts). For each, from findable evidence (what they publish, brief, price, or poll): their
monitored dimensions — the indicators and data inputs their abstraction cycle consumes.

Step 2 — THE MONITORED SET: the union, as 6-12 named dimensions (concrete: "tanker transit
counts", "official rhetoric escalation", "insurance premia", not vague categories).

Step 3 — THE COMPLEMENT (the registration's core): 3-6 BLIND-SPOT dimensions that are
(a) causally coupled to how this criticality could resolve, (b) absent or only weakly present
in the monitored set, (c) concrete enough that after resolution a grader could code whether the
resolving event arrived from one. For each: a one-line coupling mechanism (HOW it could resolve
the criticality). Do not pad with sci-fi; each must be a real, currently-unwatched channel.

Step 4 — RESOLUTION RULE: what event would count as "the criticality resolved" and a realistic
resolve-by date (when an outcome should be codable, not when everything is settled forever).

Return ONLY JSON:
{"criticality":"...","observers":[{"who":"...","monitors":["..."]}],
"monitored_set":["..."],
"blindspots":[{"dimension":"...","coupling":"how it could resolve this","weakly_monitored_by":"who half-watches it, or none"}],
"resolution_rule":"what counts as resolved + how to code the arrival dimension",
"resolve_by":"YYYY-MM-DD","honest_note":"weakest link in this registration"}"""


def cmd_register(case: str, criticality: str, model: str) -> None:
    RDIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    rf = RDIR / f"{case}.{today}.json"
    if rf.exists():
        raise SystemExit(f"{rf.name} exists — registrations are immutable; "
                         f"re-run tomorrow or use a new case slug")
    p = REGISTER.replace("{today}", today).replace("{criticality}", criticality)
    r = chat(model + ":online", [{"role": "user", "content": p}],
             temperature=0.3, max_tokens=3500)
    d = parse_json(r.text) if not r.error else None
    if not d or not d.get("blindspots"):
        raise SystemExit(f"registration failed: {r.error or 'unparseable'}")
    d["case"], d["registered"] = case, today
    rf.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    # open the graded row: the weak claim (consequence 1) is what the loop codes
    dims = "; ".join(b["dimension"] for b in d["blindspots"])
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    led = json.load(LEDGER.open(encoding="utf-8")) if LEDGER.exists() else {"predictions": []}
    led["predictions"].append({
        "made_on": today, "case": case, "entity": d.get("criticality", criticality),
        "claim": (f"When this criticality resolves, the resolving event arrives from an "
                  f"UNMONITORED dimension — and specifically from one of the registered "
                  f"blind spots: {dims}"),
        "resolution_criteria": (
            f"Code the resolving event's arrival dimension against the registration "
            f"{rf.name}. HIT if it arrived from a registered blind-spot dimension; "
            f"PARTIAL if from an unmonitored dimension NOT on the list (weak claim holds, "
            f"strong fails); MISS if from a dimension in the monitored set. "
            f"Resolution rule: {d.get('resolution_rule','')}"),
        "confidence": 0.6, "resolve_by": d.get("resolve_by", ""),
        "mechanism": "P1: watched dimensions get managed; residual surprise concentrates "
                     "in the complement (blindspot-model MODEL.md)",
        "registration": rf.name, "status": "open"})
    json.dump(led, LEDGER.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[{case}] registered {len(d['blindspots'])} blind spots · "
          f"{len(d.get('monitored_set', []))} monitored dims · resolve_by {d.get('resolve_by','?')}")
    for b in d["blindspots"]:
        print(f"  BLIND: {b['dimension'][:70]}")
        print(f"         {b.get('coupling','')[:100]}")
    print(f"  rule: {d.get('resolution_rule','')[:110]}")
    print(f"  weakest: {d.get('honest_note','')[:110]}")
    print(f"-> {rf}")


def cmd_list() -> None:
    if RDIR.exists():
        for f in sorted(RDIR.glob("*.json")):
            d = json.load(f.open(encoding="utf-8"))
            print(f"  [{d.get('resolve_by','?')}] {d.get('case','?')} — "
                  f"{len(d.get('blindspots', []))} blind spots · {d.get('criticality','')[:60]}")
    if LEDGER.exists():
        for p in json.load(LEDGER.open(encoding="utf-8"))["predictions"]:
            print(f"  [{p['status']:>8}] {p.get('case','')} (by {p.get('resolve_by','')})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Pre-register blind-spot lists for live criticalities.")
    ap.add_argument("--register", action="store_true")
    ap.add_argument("--case", default="")
    ap.add_argument("--criticality", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="registrations are graded commitments — STRONG tier")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.list:
        cmd_list(); return
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    if a.register:
        if not (a.case and a.criticality):
            raise SystemExit("--register needs --case and --criticality")
        cmd_register(a.case, a.criticality, a.model)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
