"""The scheduled grading loop — legitimacy accrues on a schedule, not on attention.

One entry point that, for everything with a due date, does the whole resolution cycle:

  1. IMPORTED ANALYSTS — gather evidence for due claims (web pass), grade them against
     it, refresh the legitimacy report. (suites/gather_evidence + suites/grade_claims)
  2. INSTRUMENTS — assess every private ledger's due predictions, each through the
     route that owns it:
       * attention live watch  -> my-model/explore/live_predictions.py --assess
       * my-model action watch-> my-model/explore/action_watch.py --assess
       * my-model/my-model-> suites/model_watch.py --repo <r> --assess
       * signal ledgers + E-1  -> the generic assessor below (same ledger schema)
     E (my-model) is ASSESS-ONLY by standing instruction: the loop grades its due
     claims but can never invoke ensemble_round — the freeze is on new predictions,
     and October's grading is exactly what the frozen claims exist for.
  3. ONE sync at the end (grades/unseals/deploys/notifies the public ledger). The
     bespoke assess scripts each auto-sync after a round; SKIP_AUTO_SYNC=1 defers them
     all to this single pass, so a loop run costs one deploy, not five.

A missing OPENROUTER_API_KEY is FATAL, never a quiet no-op: a scheduled task inherits
no exported key, and a loop that silently does nothing forever is an error masquerading
as a low count (docs/LEARNINGS.md, cross-project learning 4 — and it bit this exact
codebase the day this was written).

  python -m suites.grading_loop --dry          # what is due, run nothing
  python -m suites.grading_loop                # full pass as of today
  python -m suites.grading_loop --asof 2026-10-02
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT.parent

# ledger -> assess route. "bespoke"/"model_watch" spawn the script that owns the
# ledger (learnings, per-entity prompts); "generic" is handled here (shared schema:
# claim / resolution_criteria / confidence / resolve_by / status).
from harness.fleet import INSTRUMENT_LEDGERS


def _due(ledger_path: Path, asof: str) -> int:
    try:
        d = json.load(ledger_path.open(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    rows = d.get("predictions", d) if isinstance(d, dict) else d
    return sum(1 for p in rows
               if p.get("status") == "open" and (p.get("resolve_by") or "9999") <= asof)


def _assess_generic(ledger_path: Path, asof: str, model: str) -> int:
    """Assess due rows of a bare ledger (no watch.json / bespoke script). Reuses
    model_watch's ASSESS_PROMPT so verdicts are produced identically everywhere."""
    from harness.openrouter import chat
    from harness.actors import parse_json
    from suites.model_watch import ASSESS_PROMPT
    d = json.load(ledger_path.open(encoding="utf-8"))
    rows = d.get("predictions", d) if isinstance(d, dict) else d
    graded = 0
    for p in rows:
        if p.get("status") != "open" or (p.get("resolve_by") or "9999") > asof:
            continue
        q = (ASSESS_PROMPT.replace("{today}", asof).replace("{made_on}", p.get("made_on", ""))
             .replace("{name}", p.get("name", p.get("mechanism", "the watched system")))
             .replace("{resolve_by}", p.get("resolve_by", ""))
             .replace("{claim}", p.get("claim", ""))
             .replace("{criteria}", p.get("resolution_criteria", ""))
             .replace("{confidence}", str(p.get("confidence")))
             .replace("{mechanism}", p.get("mechanism", "")))
        r = chat(model + ":online", [{"role": "user", "content": q}],
                 temperature=0.3, max_tokens=1400)
        v = parse_json(r.text) if not r.error else None
        if not v or v.get("verdict") not in ("hit", "miss", "partial", "unresolvable"):
            print(f"      ! {p.get('claim','')[:60]}: {r.error or 'unparseable'} -- stays open")
            continue
        p["status"], p["assessed_on"] = v["verdict"], asof
        p["what_happened"] = v.get("what_happened", "")[:500]
        if v.get("learning"):
            p["learning"] = v["learning"]
        graded += 1
        print(f"      {v['verdict'].upper():>12} {p.get('claim','')[:70]}")
        time.sleep(0.6)
    if graded:
        json.dump(d, ledger_path.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return graded


def _run(cmd: list[str], cwd: Path, env: dict) -> None:
    r = subprocess.run([sys.executable] + cmd, cwd=cwd, env=env,
                       capture_output=True, text=True, timeout=1800)
    for line in (r.stdout or "").strip().splitlines():
        print("      " + line)
    if r.returncode != 0:
        print(f"      ! exit {r.returncode}: {(r.stderr or '').strip()[:300]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Grade everything due; one sync at the end.")
    ap.add_argument("--asof", default=datetime.date.today().isoformat())
    ap.add_argument("--dry", action="store_true", help="list what is due, run nothing")
    # CROSS-FAMILY GRADING RULE (2026-08-27): the assessor family must differ from the
    # family that produced the claims (instrument rounds default to gpt-4o), so grader
    # and predictor errors decorrelate. The LLM-judgment monoculture is the fleet's
    # named validity threat; this is the cheap structural mitigation.
    ap.add_argument("--model", default="anthropic/claude-sonnet-4", help="generic-assessor model (cross-family rule)")
    ap.add_argument("--skip-imports", action="store_true")
    ap.add_argument("--skip-monitors", action="store_true")
    a = ap.parse_args()

    from suites.grade_claims import _load_env
    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("FATAL: OPENROUTER_API_KEY not set (checked .env). A scheduled "
                         "loop without a key would silently no-op forever.")

    print(f"[grading loop] asof {a.asof}" + (" (DRY)" if a.dry else ""))
    env = {**os.environ, "SKIP_AUTO_SYNC": "1"}

    # 1 — imported analysts
    if not a.skip_imports:
        import glob as _g
        n_due = sum(_due_jsonl(Path(f), a.asof)
                    for f in _g.glob(str(ROOT / "imports" / "*.claims.jsonl")))
        print(f"  imports: {n_due} claim(s) due")
        if n_due and not a.dry:
            _run(["-m", "suites.gather_evidence", "--asof", a.asof], ROOT, env)
            _run(["-m", "suites.grade_claims", "--asof", a.asof,
                  "--evidence-dir", str(ROOT / "imports" / "evidence")], ROOT, env)

    # 2 — instruments
    total_due = 0
    for rel, route, args, cwd_repo in INSTRUMENT_LEDGERS:
        path = TOOLS / rel
        n = _due(path, a.asof)
        total_due += n
        if not n:
            continue
        print(f"  {rel}: {n} due ({route})")
        if a.dry:
            continue
        if route == "bespoke":
            _run(args, TOOLS / cwd_repo, env)
        elif route == "model_watch":
            _run(["-m", "suites.model_watch", "--repo", args[0], "--assess"], ROOT, env)
        else:
            _assess_generic(path, a.asof, a.model)
    if not total_due:
        print("  instruments: nothing due")

    # 2.6 — classifiers: annotate any new claims (idempotent; cheap-tier)
    if not a.dry:
        _run(["-m", "suites.classify", "--all"], ROOT, env)

    # 2.7 — trajectory: append newly graded outcomes to the longitudinal store,
    # then postmortem them (why correct / why wrong; lessons feed learnings ledgers)
    if not a.dry:
        _run(["-m", "suites.trajectory"], ROOT, env)
        _run(["-m", "suites.postmortem", "--run"], ROOT, env)

    print("[grading loop] done")


def _due_jsonl(path: Path, asof: str) -> int:
    n = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("status") == "open" and (r.get("resolve_by") or "9999") <= asof:
            n += 1
    return n


if __name__ == "__main__":
    main()
