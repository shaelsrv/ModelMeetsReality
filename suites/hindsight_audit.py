"""Audit backfilled claims for parametric-hindsight leakage.

The limitation (imports/README): for backfilled archives the extractor's WEIGHTS contain
events after `made_on`, so claim selection and criteria phrasing could be shaped by known
outcomes even though the prompt forbids browsing and hindsight. That cannot be fully
prevented — but one form of it can be DETECTED: a criteria that names a product, term,
figure, or event that did not publicly exist on `made_on` proves the phrasing came from
after the claim's date.

This is the checkable audit the README promises. Per claim, an LLM is asked one narrow,
parametric-answerable question: "which named things in this text did not exist on date
D?" — exactly the kind of question parametric knowledge CAN answer, unlike "what
happened last week".

Scope: only claims where extraction happened meaningfully after made_on (default >30
days) — the same-day ingest path is structurally clean and auditing it wastes calls.

Output: `imports/hindsight_audit_<asof>.json` + a summary. Flagged claims get
`hindsight_flag: true` written back to their ledger row (a mark, not a verdict —
graders and readers see it; the claim still resolves normally).

  python -m suites.hindsight_audit --asof 2026-08-26
  python -m suites.hindsight_audit --asof 2026-08-26 --min-gap-days 30 --apply-flags
"""
from __future__ import annotations

import argparse
import datetime
import glob
import json
import os
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

AUDIT_PROMPT = """Anachronism check on RESOLUTION CRITERIA. The criteria below were
authored recently for a claim published {made_on}; if they name something that did not
publicly exist on {made_on}, the phrasing leaked from after the claim's date.

Audit ONLY the criteria. The claim is context: it is taken from the source post itself,
published {made_on}, so every term appearing in the claim existed by that date BY
CONSTRUCTION and is exempt — never flag a term the claim already contains.

CLAIM (dated source text — its terms are exempt):
{claim}

CRITERIA (the text under audit):
{criteria}

List each specific named thing that appears in the CRITERIA but NOT in the claim —
product names, model/version names, initiatives, events, venues — and that you are
CONFIDENT did not publicly exist or was not publicly announced by {made_on}. Precision
over recall: flag only when you are sure of the first-public date; if a name is
ambiguous, could refer to something older, or you are unsure when it became public, do
NOT flag it — say so under "uncertain" instead. Generic settling venues (an annual
report, a 10-Q, "manufacturer announcements") are never anachronisms. An empty list is
the expected answer.

Return ONLY JSON:
{"anachronisms":[{"term":"...","first_public":"YYYY-MM (approx)","why":"..."}],
"uncertain":["..."],
"clean": true|false}"""


def audit_claim(r: dict, model: str) -> dict | None:
    p = (AUDIT_PROMPT.replace("{made_on}", r.get("made_on", ""))
         .replace("{claim}", r.get("claim", ""))
         .replace("{criteria}", r.get("criteria", "")))
    res = chat(model, [{"role": "user", "content": p}], temperature=0.0, max_tokens=1500)
    return parse_json(res.text) if not res.error else None


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit backfill claims for hindsight leakage.")
    ap.add_argument("--asof", required=True, help="YYYY-MM-DD (stamps the report)")
    ap.add_argument("--pattern", default=str(ROOT / "imports" / "*.claims.jsonl"))
    ap.add_argument("--min-gap-days", type=int, default=30,
                    help="audit only claims extracted this many days after made_on")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="extraction-shaped task -> non-reasoning model (LEARNINGS 3)")
    ap.add_argument("--apply-flags", action="store_true",
                    help="write hindsight_flag: true back to flagged ledger rows")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    from suites.grade_claims import _load_env, load_ledger, save_ledger
    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY not set (checked .env)")

    asof_d = datetime.date.fromisoformat(a.asof)
    results, flagged, audited = [], 0, 0
    for f in sorted(glob.glob(a.pattern)):
        path = Path(f)
        rows = load_ledger(path)
        dirty = False
        for r in rows:
            made = r.get("made_on", "")
            try:
                gap = (asof_d - datetime.date.fromisoformat(made)).days
            except ValueError:
                continue
            # Extraction date isn't stored per claim; the archive was imported within
            # days of the audit, so asof - made_on approximates the backfill gap.
            if gap < a.min_gap_days or "hindsight_audit" in r:
                continue
            if a.limit and audited >= a.limit:
                break
            d = audit_claim(r, a.model)
            audited += 1
            if d is None:
                print(f"  {r['id']}: audit call failed -- skipped, retry next run")
                continue
            anach = d.get("anachronisms", []) or []
            r["hindsight_audit"] = a.asof
            if anach:
                flagged += 1
                r["hindsight_flag"] = True
                print(f"  FLAGGED {r['id']}: "
                      + "; ".join(f"{x['term']} ({x.get('first_public','?')})" for x in anach))
            results.append({"id": r["id"], "made_on": made, "anachronisms": anach})
            dirty = True
        if dirty and a.apply_flags:
            save_ledger(path, rows)
        elif dirty:
            # audit stamps are only persisted with --apply-flags; without it the run
            # is a read-only report and re-runs re-audit the same claims.
            pass

    out = ROOT / "imports" / f"hindsight_audit_{a.asof}.json"
    out.write_text(json.dumps(
        {"asof": a.asof, "model": a.model, "min_gap_days": a.min_gap_days,
         "audited": audited, "flagged": flagged, "results": results},
        indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\naudited {audited} backfill claim(s): {flagged} flagged -> {out.name}"
          + ("" if a.apply_flags else "   (report only; --apply-flags to persist)"))


if __name__ == "__main__":
    main()
