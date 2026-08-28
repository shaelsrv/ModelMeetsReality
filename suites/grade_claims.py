"""Grade resolved claims, and accrue legitimacy from the outcomes.

This is the pass that turns a ledger into a track record. It runs SEPARATELY from
extraction, and that separation is the whole methodology: the extractor never sees
outcomes, so it cannot select or phrase claims toward what happened. Here, and only
here, do we look at the world.

LEGITIMACY IS EARNED, NOT CONFERRED. It comes from resolved claims -- never from
institution, affiliation, or audience size. A famous analyst with no resolved claims
has NO legitimacy; they are unmeasured, which is not the same as bad. It accrues per
(analyst, mechanism), because a person is not one model: someone can forecast chip
supply well and macroeconomics badly, and one blended number would hide that.

TIME-ORDERING. Legitimacy at time T uses only claims resolved BEFORE T. Otherwise a
score silently gains hindsight, which is the same contamination the extraction split
exists to prevent -- applied to scoring.

Grading is deliberately conservative:
  * Grade ONLY against the criteria frozen at extraction. Not against what the claim
    "really meant". If the criteria cannot be checked, the verdict is `unresolvable`
    and the claim is EXCLUDED from scoring rather than guessed at.
  * `unresolvable` never counts for or against anyone. A ledger that quietly converts
    unclear claims into hits is a marketing device, not a measurement.

THE GRADER MUST HAVE EVIDENCE. A plain completion call answers from parametric
memory: it will recall -- or invent -- what happened and name a source it never
opened. Measured on the first backfill run, every verdict came back `unresolvable`
with the model saying so outright ("knowledge cutoff Oct 2024", "no post-2024
sources can be consulted"). It failed honestly, but it could not measure anything.

So grading takes evidence as INPUT. Either:
  * `--evidence-dir DIR`  -- a file per claim id (`<claim_id>.md`), gathered by a
    browsing pass beforehand, or
  * `--evidence-cmd CMD`  -- a command run per claim; its stdout is the evidence.
Without evidence a claim stays OPEN and is reported as such. It is never guessed at,
and never silently converted into `unresolvable`, because those are different things:
  * `unresolvable`   -- the world did not settle it (excluded from scoring, forever)
  * `open` + no evidence -- WE could not check it yet (retry later)

Usage:
    # 1. gather evidence (any browsing tool writes <claim_id>.md into a directory)
    # 2. grade against it
    python -m suites.grade_claims --ledger imports/<slug>.claims.jsonl \
        --asof 2026-08-25 --evidence-dir imports/evidence
    python -m suites.grade_claims --report --asof 2026-08-25
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from harness.openrouter import chat  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _load_env() -> None:
    """Load .env if present. Without the key, chat() returns empty text -- which is
    indistinguishable from a rate limit, and cost a debugging cycle before this."""
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


VERDICTS = ("hit", "partial", "miss", "unresolvable", "insufficient")
# "insufficient" is NOT a status we persist -- it means we could not look hard
# enough yet, so the claim stays `open` for a later, better-evidenced pass.

GRADE_PROMPT = """Grade this prediction against its RESOLUTION CRITERIA and what
actually happened.

CLAIM:        {claim}
MADE ON:      {made_on}   (by {analyst})
RESOLVE BY:   {resolve_by}
CRITERIA:     {criteria}
TODAY:        {asof}

EVIDENCE GATHERED FOR THIS CLAIM:
{evidence}

Grade ONLY against the criteria as written, using ONLY the evidence above. Do not
grade from your own recollection: if the evidence does not settle it, say so rather
than filling the gap from memory. Do not grade against what you think the claim
"really meant", and do not rescue a claim whose criteria were badly written -- that
is a cost the ledger pays, not the claimant.

WEIGH THE SOURCES. Evidence lines are tagged [PRIMARY] (the company's or agency's own
publication or filing), [TRADE] (established trade press), or [WEAK] (aggregator, SEO
site, unattributed round-up). A verdict resting only on [WEAK] sources is not a
verdict: return "insufficient". Aggregators restate and mangle figures, so a number
appearing nowhere primary or trade has not been established, however often repeated.
Anything the evidence lists under "What could NOT be established" is NOT established
-- never fill that gap from your own memory.

STRICTNESS CUTS BOTH WAYS. Being conservative means not inflating a claim into a hit;
it does NOT mean failing a claim the evidence substantively supports. Two errors to
avoid, both seen in practice:
  * NAMING. If the evidence shows the predicted thing exists and does what was
    predicted, a different product name or label is not a miss. ("Trn2 UltraServers"
    vs "Trainium2-ultra" is the same referent.) Grade the substance.
  * SCOPE. If the criteria's observable is clearly satisfied but the evidence's
    examples sit slightly outside the stated window or sample, that is "partial",
    not "miss" -- unless the timing IS the claim.
Reserve "miss" for a claim the world actually contradicted, and say which evidence
contradicts it. If you are failing a claim on a technicality rather than on the
world, the honest verdict is "partial".

Verdicts:
  hit          -- the criteria are satisfied
  partial      -- the criteria are partially satisfied (direction right, magnitude or
                  timing off; or one of several conjoined conditions failed)
  miss         -- the criteria are not satisfied
  unresolvable -- THE WORLD did not settle it: the criteria refer to something that
                  was never published or never became checkable. EXCLUDED from
                  scoring, counts for and against no one.
  insufficient -- the EVIDENCE ABOVE is too thin for you to tell. Different from
                  unresolvable: the claim may well be checkable, we just have not
                  looked hard enough. The claim stays open for a later pass.
                  Choose this over guessing, always.

Return JSON only, no fences:
{{
  "verdict": "hit" | "partial" | "miss" | "unresolvable" | "insufficient",
  "what_happened": "<2-3 sentences: the actual outcome, with the figure or event that settles it>",
  "evidence": "<the specific source that settles it, named>",
  "confidence": <0.0-1.0, your confidence in THIS grading>
}}
"""


def _brier(p: float, outcome: float) -> float:
    return (p - outcome) ** 2


OUTCOME_VALUE = {"hit": 1.0, "partial": 0.5, "miss": 0.0}


def load_ledger(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def save_ledger(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_evidence(claim_id: str, evidence_dir: str, evidence_cmd: str) -> str:
    """Evidence for one claim, from a prepared file or a per-claim command."""
    if evidence_dir:
        for ext in (".md", ".txt", ".json"):
            f = Path(evidence_dir) / f"{claim_id}{ext}"
            if f.exists():
                return f.read_text(encoding="utf-8")[:20000]
    if evidence_cmd:
        import subprocess
        try:
            out = subprocess.run(evidence_cmd.replace("{id}", claim_id), shell=True,
                                 capture_output=True, text=True, timeout=180)
            if out.stdout.strip():
                return out.stdout[:20000]
        except (subprocess.TimeoutExpired, OSError):
            pass
    return ""


def grade_ledger(path: Path, asof: str, model: str, force: bool = False,
                 limit: int = 0, evidence_dir: str = "", evidence_cmd: str = "") -> dict:
    rows = load_ledger(path)
    due = [r for r in rows
           if (force or r.get("status") == "open") and r.get("resolve_by", "") <= asof]
    if limit:
        due = due[:limit]

    if not due:
        n_open = sum(1 for r in rows if r.get("status") == "open")
        return {"ledger": str(path), "graded": 0, "due": 0, "open": n_open}

    print(f"  {path.name}: {len(due)} due of {len(rows)}")
    graded, no_ev = 0, 0
    for r in due:
        ev = load_evidence(r["id"], evidence_dir, evidence_cmd)
        if not ev.strip():
            # No evidence is not a verdict. Leave it open and say so -- a grader
            # without eyes answers from memory, which is not a measurement.
            no_ev += 1
            print(f"    {r['id']}: NO EVIDENCE -- left open (gather first)")
            continue
        p = GRADE_PROMPT.format(
            claim=r["claim"], made_on=r.get("made_on", ""), analyst=r.get("analyst", ""),
            resolve_by=r["resolve_by"], criteria=r["criteria"], asof=asof, evidence=ev)
        # Grading is one call per claim, so a batch hits rate limits that surface
        # as empty responses. An ungraded claim is not a neutral outcome -- it
        # silently withholds legitimacy -- so retry rather than skip.
        v = None
        for attempt in range(4):
            res = chat(model, [{"role": "user", "content": p}],
                       temperature=0.0, max_tokens=3000)
            txt = res.text.strip()
            if txt:
                t = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.MULTILINE).strip()
                s, e = t.find("{"), t.rfind("}")
                try:
                    v = json.loads(t if s == -1 else t[s:e + 1])
                    break
                except json.JSONDecodeError:
                    pass
            if attempt < 3:
                time.sleep(8 * (attempt + 1))   # rate limits surface as empty text
        if v is None:
            print(f"    {r['id']}: grading failed after retries -- left OPEN, not scored")
            continue
        verdict = str(v.get("verdict", "")).lower()
        if verdict not in VERDICTS:
            print(f"    {r['id']}: bad verdict {verdict!r}")
            continue
        if verdict == "insufficient":
            # We could not look hard enough; the claim is still checkable. Stays open.
            print(f"    {r['id']}: INSUFFICIENT evidence -- stays open")
            continue
        r["status"] = verdict
        r["graded_on"] = asof
        r["what_happened"] = v.get("what_happened", "")
        r["grading_evidence"] = v.get("evidence", "")
        r["grading_confidence"] = v.get("confidence")
        r["graded_by"] = model
        graded += 1
        print(f"    {r['id']}: {verdict.upper():12s} {r['claim'][:60]}", flush=True)
        time.sleep(0.6)   # pace the batch; grading is one call per claim

    save_ledger(path, rows)
    return {"ledger": str(path), "graded": graded, "due": len(due),
            "no_evidence": no_ev,
            "open": sum(1 for r in rows if r.get("status") == "open")}


def legitimacy(rows: list[dict], asof: str = "") -> dict:
    """Earned legitimacy for one model, from resolved claims only.

    Time-ordered: with `asof`, only claims whose `resolve_by` is on or before that
    date count, so a score computed for a past date cannot see later resolutions.
    """
    # Time-ordering keys off resolve_by, not graded_on: a claim counts once the
    # world has settled it, and only if that happened on or before `asof`. Keying
    # off graded_on would make a score depend on when we happened to run the pass.
    scored = [r for r in rows
              if r.get("status") in OUTCOME_VALUE
              and (not asof or (r.get("resolve_by") or "9999") <= asof)]
    n = len(scored)
    if n == 0:
        return {"n_resolved": 0, "status": "unearned",
                "note": "no resolved claims -- unmeasured, which is not the same as low"}

    briers, hits = [], 0
    for r in scored:
        o = OUTCOME_VALUE[r["status"]]
        briers.append(_brier(float(r.get("speaker_p", 0.5)), o))
        hits += 1 if r["status"] == "hit" else 0
    brier = sum(briers) / n

    # Reference: predicting their own base rate every time. Beating it means the
    # per-claim confidence carried information, not just an average optimism.
    base = sum(OUTCOME_VALUE[r["status"]] for r in scored) / n
    base_brier = sum(_brier(base, OUTCOME_VALUE[r["status"]]) for r in scored) / n
    # base_brier == 0 means every outcome was identical (degenerate baseline). If the
    # analyst's brier is also 0 they matched it; otherwise skill is UNDEFINED (null),
    # never 0.0 -- printing 0 would read "matched baseline" for someone strictly worse.
    if base_brier > 0:
        skill = round((base_brier - brier) / base_brier, 3)
    elif brier == 0:
        skill = 0.0
    else:
        skill = None

    return {
        "n_resolved": n,
        "status": "earned" if n >= 3 else "provisional",
        "hit_rate": round(hits / n, 3),
        "mean_outcome": round(base, 3),
        "brier": round(brier, 4),
        "baseline_brier": round(base_brier, 4),
        "skill_vs_own_baseline": skill,
        "mean_stated_p": round(sum(float(r.get("speaker_p", 0.5)) for r in scored) / n, 3),
        "unresolvable_excluded": sum(1 for r in rows if r.get("status") == "unresolvable"),
    }


def report(pattern: str, asof: str = "") -> dict:
    """Legitimacy per (analyst, mechanism) -- never one number per person.

    (analyst, mechanism) keys pass through imports/identity.json, the human-confirmed
    alias map (see merge_identity.py) -- so one source recorded under two names
    accrues ONE track record, while the ledger files stay untouched."""
    try:
        from suites.merge_identity import load_identity, canonical
        ident = load_identity()
    except ImportError:
        ident, canonical = {}, lambda a, m, _i: (a, m)
    out = defaultdict(list)
    for f in sorted(glob.glob(pattern)):
        # Unclustered claims (below CLUSTER_FLOOR) are recorded and graded but never
        # given a headline score -- a Brier over 1-2 outcomes is noise, not a track
        # record. They still resolve, so a later re-cluster can pick them up scored.
        if Path(f).stem.endswith("-unclustered.claims"):
            continue
        rows = load_ledger(Path(f))
        if not rows:
            continue
        key = canonical(rows[0].get("analyst", "?"),
                        rows[0].get("mechanism") or Path(f).stem, ident)
        out[key].extend(rows)

    table = []
    for (analyst, mech), rows in sorted(out.items()):
        lg = legitimacy(rows, asof)
        table.append({"analyst": analyst, "mechanism": mech,
                      "n_claims": len(rows), **lg})

    table.sort(key=lambda r: (r.get("status") != "earned", r.get("brier", 9)))
    return {"asof": asof or "now", "models": table}


def _print_report(rep: dict) -> None:
    print(f"\n  LEGITIMACY as of {rep['asof']}  (earned from resolved claims only)\n")
    hdr = f"  {'analyst':<16}{'mechanism':<40}{'claims':>7}{'resolved':>9}{'hit':>6}{'brier':>8}  status"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for m in rep["models"]:
        hit = f"{m['hit_rate']:.2f}" if m.get("n_resolved") else "  -"
        br = f"{m['brier']:.3f}" if m.get("n_resolved") else "    -"
        print(f"  {m['analyst'][:15]:<16}{m['mechanism'][:39]:<40}{m['n_claims']:>7}"
              f"{m['n_resolved']:>9}{hit:>6}{br:>8}  {m['status']}")
    unearned = [m for m in rep["models"] if m["status"] == "unearned"]
    if unearned:
        print(f"\n  {len(unearned)} model(s) unearned: no resolved claims yet. "
              f"Unmeasured, not low.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Grade resolved claims; accrue earned legitimacy.")
    ap.add_argument("--ledger", help="one .claims.jsonl to grade")
    ap.add_argument("--all", action="store_true", help="grade every ledger in imports/")
    ap.add_argument("--pattern", default=str(ROOT / "imports" / "*.claims.jsonl"))
    ap.add_argument("--asof", default="", help="YYYY-MM-DD; claims due on/before this are graded")
    ap.add_argument("--model", default=os.environ.get("GRADE_MODEL", "anthropic/claude-sonnet-4"),
                    help="grading model; sonnet-4 measured at 139 completion tokens per "
                         "verdict vs gpt-5's 1737 for the same call")
    ap.add_argument("--report", action="store_true", help="print legitimacy, grade nothing")
    ap.add_argument("--force", action="store_true", help="re-grade already-graded claims")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--evidence-dir", default="",
                    help="directory of <claim_id>.md evidence files, gathered by a "
                         "browsing pass BEFORE grading")
    ap.add_argument("--evidence-cmd", default="",
                    help="command run per claim ({id} substituted); stdout is the evidence")
    a = ap.parse_args()

    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY") and not a.report:
        raise SystemExit("OPENROUTER_API_KEY not set (checked .env). Grading calls "
                         "would return empty text and look like rate limits.")

    if not a.asof:
        raise SystemExit("--asof YYYY-MM-DD is required: grading is time-ordered, and "
                         "the date is what keeps a score from seeing later outcomes.")

    if a.report:
        rep = report(a.pattern, a.asof)
        _print_report(rep)
        out = ROOT / "imports" / f"legitimacy_{a.asof}.json"
        out.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  -> {out}")
        return

    targets = [Path(a.ledger)] if a.ledger else [Path(f) for f in sorted(glob.glob(a.pattern))]
    if not targets:
        raise SystemExit("no ledgers matched")

    tot = 0
    for t in targets:
        r = grade_ledger(t, a.asof, a.model, a.force, a.limit,
                         a.evidence_dir, a.evidence_cmd)
        tot += r["graded"]
    print(f"\n  graded {tot} claim(s) as of {a.asof}")
    if tot:
        _print_report(report(a.pattern, a.asof))


if __name__ == "__main__":
    main()
