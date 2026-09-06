"""Human audit sample — the guard against the LLM-judgment monoculture.

Everything that judges in this fleet (coders, graders, precedent-taggers, assessors) is
an LLM. Correlated grader/instrument error is the October gradings' named validity
threat, and no amount of cross-family model choice fully removes it. This tool makes
the cheap structural fix operational: after any grading pass, sample K graded claims
(stratified across instruments and verdicts), and emit ONE human-checkable audit sheet
— claim, criteria, machine verdict, machine-cited evidence, and an empty human-verdict
column. The user fills the column; disagreements estimate the machine grading error
rate, which then qualifies every Brier number the fleet reports.

Sampling is seeded from the asof date, so the sheet is reproducible and cannot be
quietly re-rolled until a flattering sample appears.

  python -m suites.audit_sample --asof 2026-10-06 --k 15
  # -> <main-instance>/audits/audit_2026-10-06.md  (human fills VERDICT column)
  python -m suites.audit_sample --score audits/audit_2026-10-06.md
  # -> compares filled column vs machine verdicts, reports disagreement rate
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]

def _models_dir(root):
    """Where THIS instance's model repos live.

    fleet.json may set models_dir to give the instance a private namespace;
    without it, models are siblings of the instance (the original layout).
    Two instances under one parent otherwise read each other's models.
    """
    try:
        import json as _json
        cfg = _json.load((root / "fleet.json").open(encoding="utf-8"))
        if cfg.get("models_dir"):
            return (root / cfg["models_dir"]).resolve()
    except Exception:
        pass
    return root.parent


TOOLS = _models_dir(ROOT)

from harness.fleet import MODEL_REPOS
LEDGERS = [(m, f"{m}/predict/ledger.json") for m in MODEL_REPOS]
GRADED = {"hit", "partial", "miss", "unresolvable"}


def collect_graded() -> list[dict]:
    out = []
    for label, rel in LEDGERS:
        p = TOOLS / rel
        if not p.exists():
            continue
        d = json.load(p.open(encoding="utf-8"))
        rows = d.get("predictions", d) if isinstance(d, dict) else d
        for r in rows:
            if r.get("status") in GRADED:
                out.append({"instrument": label, **r})
    return out


def make_sheet(asof: str, k: int) -> Path:
    rows = collect_graded()
    if not rows:
        raise SystemExit("no graded claims yet -- run after a grading pass")
    rng = random.Random(int(hashlib.sha256(asof.encode()).hexdigest(), 16))
    # stratify: at least one per verdict class present, rest random
    by_v = {}
    for r in rows:
        by_v.setdefault(r["status"], []).append(r)
    sample = [rng.choice(v) for v in by_v.values()]
    pool = [r for r in rows if r not in sample]
    rng.shuffle(pool)
    sample += pool[:max(0, k - len(sample))]
    outdir = ROOT / "audits"
    outdir.mkdir(exist_ok=True)
    L = [f"# Human audit sample — {asof}",
         f"{len(sample)} of {len(rows)} graded claims (seeded by date; reproducible).",
         "Fill **HUMAN VERDICT** (hit/partial/miss/unresolvable) by checking each claim",
         "against its criteria YOURSELF (primary sources). Then run:",
         f"`python -m suites.audit_sample --score audits/audit_{asof}.md`", ""]
    for i, r in enumerate(sample, 1):
        L += [f"## {i}. [{r['instrument']}] {r.get('claim','')[:140]}",
              f"- criteria: {r.get('resolution_criteria', r.get('criteria',''))[:250]}",
              f"- machine verdict: **{r['status']}**",
              f"- machine evidence: {r.get('what_happened','')[:300]}",
              f"- id: `{r.get('entity','')}|{r.get('made_on','')}`",
              f"- HUMAN VERDICT: ____", ""]
    out = outdir / f"audit_{asof}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print(f"-> {out} ({len(sample)} claims; fill HUMAN VERDICT and --score it)")
    return out


def score(path: Path) -> None:
    txt = path.read_text(encoding="utf-8")
    machine, human = [], []
    for block in txt.split("## ")[1:]:
        mv = hv = None
        for line in block.splitlines():
            if line.startswith("- machine verdict:"):
                mv = line.split("**")[1].strip()
            if line.startswith("- HUMAN VERDICT:"):
                hv = line.split(":", 1)[1].strip().strip("_ ").lower()
        if mv and hv and hv in GRADED:
            machine.append(mv)
            human.append(hv)
    if not human:
        raise SystemExit("no filled HUMAN VERDICT lines found")
    agree = sum(m == h for m, h in zip(machine, human))
    n = len(human)
    print(f"audited {n} · agreement {agree}/{n} = {agree/n:.0%} · "
          f"estimated machine grading error rate {(n-agree)/n:.0%}")
    print("QUALIFY every fleet Brier/hit-rate with this error rate when reporting.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Human audit sheet for machine gradings.")
    ap.add_argument("--asof", default=datetime.date.today().isoformat())
    ap.add_argument("--k", type=int, default=15)
    ap.add_argument("--score", metavar="SHEET")
    a = ap.parse_args()
    if a.score:
        score(Path(a.score))
    else:
        make_sheet(a.asof, a.k)


if __name__ == "__main__":
    main()
