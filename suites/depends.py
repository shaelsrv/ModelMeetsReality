"""Claim dependencies — let a claim name the evidence it will be graded against.

Sleep's dependency report pinned 1047 of 1314 fragments because dependencies were
inferred by artifact KIND: one open level-2 claim about grading throughput
pinned every model document in the fleet. The fix is to let claims say what they
actually read.

A claim may carry:
    "depends_on": {"repos": ["my-model"], "kinds": ["graded_claim"],
                   "fragment_ids": ["a1b2..."], "until": "2026-10-15"}

Any subset is allowed; the more specific, the less sleep has to pin. A claim with
NO depends_on falls back to kind-level pinning — conservative, so undeclared
claims are never harmed by consolidation.

  python -m suites.depends --audit                 # who declares, who falls back
  python -m suites.depends --infer --repo my-meta-model --dry-run
  python -m suites.depends --infer --repo my-meta-model --write
"""
from __future__ import annotations

import argparse
import json
import re
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

LEDGERS = ("predict/ledger.json", "predict/live_ledger.json", "signals/signal_ledger.json")

# phrase -> artifact kind, for inferring what an existing claim reads
CUES = {
    "graded_claim": ["graded", "grading", "resolve", "resolved", "hit rate", "brier",
                     "outcome", "verdict", "cohort"],
    "postmortem": ["postmortem", "earned", "lucky", "lesson"],
    "attribution": ["attribution", "attributed", "mechanism drove", "driver"],
    "open_claim": ["open claim", "open row", "registered claim", "pre-registered"],
    "trace": ["narrative", "weave", "vocabulary adoption", "trace"],
    "registration": ["blind spot", "blindspot", "registration", "monitored"],
    "study_result": ["study", "h0", "h1", "sample", "statistic"],
    "model_doc": ["premise", "consequence", "deletion clause", "model document"],
    "trial": ["trial", "refuted", "refutation", "termination rule"],
}


def ledger_files(repo: str | None = None):
    for p in sorted(TOOLS.iterdir()):
        if not p.is_dir() or (repo and p.name != repo):
            continue
        for rel in LEDGERS:
            f = p / rel
            if f.exists():
                yield p.name, f


def load(f: Path):
    try:
        return json.load(f.open(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def rows_of(d):
    return d.get("predictions", d) if isinstance(d, dict) else d


def infer(claim: str, mechanism: str = "") -> dict:
    """Guess what a claim reads, from its own wording. Conservative: only kinds
    with an explicit cue are named; everything else stays unpinned by this claim."""
    text = f"{claim} {mechanism}".lower()
    kinds = sorted({k for k, cues in CUES.items() if any(c in text for c in cues)})
    repos = sorted({p.name for p in TOOLS.iterdir()
                    if p.is_dir() and len(p.name) > 4 and p.name in text})
    out = {}
    if kinds:
        out["kinds"] = kinds
    if repos:
        out["repos"] = repos
    return out


def audit() -> dict:
    declared = fallback = 0
    per_repo = {}
    for repo, f in ledger_files():
        d = load(f)
        if not d:
            continue
        for r in rows_of(d):
            if r.get("status", "open") != "open":
                continue
            has = bool(r.get("depends_on"))
            declared += has
            fallback += not has
            s = per_repo.setdefault(repo, {"declared": 0, "fallback": 0})
            s["declared" if has else "fallback"] += 1
    return {"declared": declared, "fallback": fallback, "per_repo": per_repo}


def main():
    ap = argparse.ArgumentParser(description="Declare what claims depend on.")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--infer", action="store_true")
    ap.add_argument("--repo")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.audit:
        d = audit()
        tot = d["declared"] + d["fallback"]
        print(f"[depends] {tot} open claims · {d['declared']} declare dependencies · "
              f"{d['fallback']} fall back to kind-level pinning")
        for repo, s in sorted(d["per_repo"].items(), key=lambda x: -x[1]["fallback"]):
            if s["fallback"] or s["declared"]:
                print(f"  {repo:<26} declared {s['declared']:>3} · fallback {s['fallback']:>3}")
        return

    if a.infer:
        changed = 0
        for repo, f in ledger_files(a.repo):
            d = load(f)
            if not d:
                continue
            rows = rows_of(d)
            touched = False
            for r in rows:
                if r.get("status", "open") != "open" or r.get("depends_on"):
                    continue
                dep = infer(r.get("claim", ""), r.get("mechanism", ""))
                if not dep:
                    continue
                dep["until"] = r.get("resolve_by", "")
                dep["inferred"] = True
                if a.write:
                    r["depends_on"] = dep
                    touched = True
                changed += 1
                print(f"  {repo}/{r.get('resolve_by','?')}: "
                      f"kinds={dep.get('kinds', [])} repos={dep.get('repos', [])}")
                print(f"     {r.get('claim','')[:100]}")
            if touched and a.write:
                json.dump(d, f.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\n{'wrote' if a.write else 'would set'} depends_on for {changed} claim(s)")
        if not a.write:
            print("  (add --write to persist)")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
