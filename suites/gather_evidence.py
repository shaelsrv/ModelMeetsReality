"""Gather evidence for due claims, so grading has something to look at.

The grading pass deliberately refuses to grade from memory (see `grade_claims.py`:
a plain completion call answers from parametric recall and names sources it never
opened). This is the pass that gives it eyes: for every claim whose resolve date has
arrived, search the web against the criteria that were frozen at extraction, and
write what is found to `<claim_id>.md`.

TWO RULES THAT KEEP THIS FROM CONTAMINATING THE MEASUREMENT:

  * SEARCH THE CRITERIA, NOT THE CLAIM'S CONCLUSION. The query is built from the
    observable the criteria name -- "ASML 2030 annual report EUV system shipments",
    not "was my-model right about ASML". Searching for a verdict finds a verdict;
    searching for an observable finds a fact. This is the same discipline that keeps
    extraction from seeing outcomes, applied to retrieval.
  * REPORT, DO NOT JUDGE. The gatherer states what it found and explicitly flags
    what it could NOT establish. It never renders hit/miss -- that is grading's job,
    and separating them is what stops one model from both choosing the evidence and
    scoring against it.

Evidence files are written once and reused. Re-running skips claims that already
have one unless `--refresh`, so a grading loop is cheap to repeat.

Usage:
    python -m suites.gather_evidence --pattern "imports/*.claims.jsonl" --asof 2026-08-26
    python -m suites.gather_evidence --ledger imports/<slug>.claims.jsonl --asof 2026-08-26
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.openrouter import chat  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


GATHER_PROMPT = """Find out what actually happened, so someone else can grade a
prediction against it. You are gathering evidence. You are NOT deciding whether the
prediction was right -- someone else does that, and mixing the two jobs corrupts both.

THE OBSERVABLE TO ESTABLISH (this is what to search for):
{criteria}

For context only -- the prediction this evidence will be used to grade:
  "{claim}"
  made {made_on} by {analyst}, resolve-by {resolve_by}. Today is {asof}.

Search for the OBSERVABLE, not for a verdict. Look for the figure, filing,
announcement, or report the criteria name. Do not search for whether the predictor
was right; that phrasing finds opinions about them instead of facts about the world.

PRIMARY SOURCE OR IT DOES NOT COUNT. Go to the thing itself: the company's own
newsroom or investor-relations page, the SEC filing, the regulator's release, the
standards body, the paper. AI-news aggregators, SEO round-ups, content farms, and
"analysis of" articles are NOT evidence -- they restate, mangle figures, and cite
each other in circles. If a number only appears on such a site and never in a
primary or established-trade source, treat that number as UNESTABLISHED and say so.

Grade your own sourcing in the report:
  [PRIMARY]   the company/agency/author's own publication or filing
  [TRADE]     established trade or wire press with a named reporter
  [WEAK]      aggregator, SEO site, or unattributed round-up -- explicitly discount
Tag every source line with one of these. A finding resting only on [WEAK] sources
belongs under "What could NOT be established", not under "What the sources say".

Report:

## What the sources say
The specific findings, with figures and dates. Quote sparingly (under 15 words) and
attribute every number to a named source.

## What could NOT be established
Be explicit and generous here. If the exact figure the criteria demand was never
published, say so. If you found something adjacent but not the thing itself, say
exactly how it differs. A gap named here is worth more than a gap papered over --
the grader is instructed to return "insufficient" rather than guess, and it can only
do that if you tell it what is missing.

## Sources
Full URLs, one per line, each tagged [PRIMARY] / [TRADE] / [WEAK] and with a
one-line note on what it establishes.

Write nothing else. No verdict, no "this suggests the prediction was correct", no
score. If you find nothing usable, say that plainly under both headings.
"""


def gather_one(claim: dict, asof: str, model: str) -> str:
    p = GATHER_PROMPT.format(
        criteria=claim["criteria"], claim=claim["claim"],
        made_on=claim.get("made_on", ""), analyst=claim.get("analyst", ""),
        resolve_by=claim.get("resolve_by", ""), asof=asof)
    for attempt in range(3):
        r = chat(model, [{"role": "user", "content": p}], temperature=0.0, max_tokens=2500)
        if r.text.strip():
            return r.text.strip()
        if attempt < 2:
            time.sleep(8 * (attempt + 1))
    return ""


def run(paths: list[Path], asof: str, model: str, outdir: Path,
        refresh: bool = False, limit: int = 0) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    due: list[dict] = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            if c.get("status") != "open":
                continue
            if (c.get("resolve_by") or "9999") > asof:
                continue
            if not refresh and (outdir / f"{c['id']}.md").exists():
                continue
            due.append(c)
    if limit:
        due = due[:limit]

    print(f"  {len(due)} claim(s) need evidence as of {asof}")
    ok = 0
    for i, c in enumerate(due, 1):
        print(f"    [{i}/{len(due)}] {c['id']}: {c['claim'][:64]}", flush=True)
        text = gather_one(c, asof, model)
        if not text:
            print(f"        no response -- skipped, will retry on next run")
            continue
        hdr = (
            f"# Evidence for {c['id']}\n"
            f"gathered {asof} by {model} (web retrieval)\n\n"
            f"CLAIM (context only): {c['claim']}\n"
            f"MADE: {c.get('made_on','')} by {c.get('analyst','')}  "
            f"RESOLVE BY: {c.get('resolve_by','')}\n"
            f"CRITERIA SEARCHED: {c['criteria']}\n\n---\n\n"
        )
        (outdir / f"{c['id']}.md").write_text(hdr + text + "\n", encoding="utf-8")
        ok += 1
        time.sleep(1.0)

    return {"due": len(due), "gathered": ok, "outdir": str(outdir)}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Gather web evidence for due claims, for a later grading pass.")
    ap.add_argument("--ledger")
    ap.add_argument("--pattern", default=str(ROOT / "imports" / "*.claims.jsonl"))
    ap.add_argument("--asof", required=True, help="YYYY-MM-DD")
    ap.add_argument("--outdir", default=str(ROOT / "imports" / "evidence"))
    # :online gives OpenRouter web retrieval -- the same mechanism suites/model_watch.py
    # already uses. Without it the gatherer is as blind as the grader was.
    ap.add_argument("--model", default=os.environ.get(
        "EVIDENCE_MODEL", "anthropic/claude-sonnet-4:online"))
    ap.add_argument("--refresh", action="store_true", help="re-gather even if a file exists")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY not set (checked .env).")
    if ":online" not in a.model:
        print(f"  WARNING: {a.model} has no :online suffix -- it will answer from "
              f"memory, which is exactly what this pass exists to avoid.")

    paths = [Path(a.ledger)] if a.ledger else [Path(f) for f in sorted(glob.glob(a.pattern))]
    if not paths:
        raise SystemExit("no ledgers matched")

    res = run(paths, a.asof, a.model, Path(a.outdir), a.refresh, a.limit)
    print(f"\n  gathered {res['gathered']}/{res['due']} -> {res['outdir']}")
    print(f"  next: python -m suites.grade_claims --asof {a.asof} "
          f"--evidence-dir {res['outdir']}")


if __name__ == "__main__":
    main()
