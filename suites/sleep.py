"""Sleep — offline consolidation, ordered by meta-level.

Waking work adds artifacts; nothing ever compresses them. Sleep is the missing
phase: replay what happened, write the gist, strengthen links worth keeping, and
let the rest fade — with one structural constraint the fleet's shape imposes.

THE LEVEL CONSTRAINT. A level-1 model's evidence IS level-0's output; a level-2
model reads level-1's record. Consolidating a level silently degrades every level
above it. So:

  · consolidate bottom-up, lowest level first
  · never compress an artifact a LIVE higher-level claim still depends on
  · verdicts (graded outcomes, refutations, postmortems, attributions) never decay
  · canon models are controls — frozen until their comparison window closes

Phase 1 of this file is deliberately read-only: `--dependency-report` shows what
would be pinned and what would be compressed, so the ordering is checkable BEFORE
it can do damage. Consolidation itself is gated behind --consolidate.

  python -m suites.sleep --dependency-report
  python -m suites.sleep --consolidate --dry-run
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT.parent
PROJ = ROOT / "map" / "projections" / "em-ladder.v1.json"

# artifact kinds that carry a verdict — pinned unconditionally, at every level
VERDICT_KINDS = {"graded_claim", "postmortem", "attribution", "study_result",
                 "refutation", "trial"}

# what a live claim at level N reads from below. Approximate by design: dependencies
# are stated in prose, not as structured references, so this errs toward pinning.
DEPENDS = {
    1: {"graded_claim", "open_claim", "model_doc", "trace", "registration"},
    2: {"graded_claim", "postmortem", "attribution", "trajectory", "model_doc",
        "study_result", "open_claim"},
}


def levels() -> dict:
    if not PROJ.exists():
        raise SystemExit("no projection — run suites.reality_map --build first")
    d = json.load(PROJ.open(encoding="utf-8"))
    return {s: a.get("level", 0) for s, a in d["assignments"].items()}


def open_claims(repo: str) -> list:
    out = []
    for rel in ("predict/ledger.json", "predict/live_ledger.json",
                "signals/signal_ledger.json"):
        f = TOOLS / repo / rel
        if not f.exists():
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for r in (d.get("predictions", d) if isinstance(d, dict) else d):
            if r.get("status", "open") == "open":
                out.append({"claim": r.get("claim", "")[:160],
                            "resolve_by": r.get("resolve_by", ""),
                            "depends_on": r.get("depends_on")})
    return out


def index_rows() -> list:
    rows = []
    for p in sorted(TOOLS.iterdir()):
        f = p / "index.jsonl"
        if p.is_dir() and f.exists():
            for l in f.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    rows.append(json.loads(l))
    return rows


def analyse() -> dict:
    lv = levels()
    rows = index_rows()
    by_repo_kind = defaultdict(int)
    for r in rows:
        by_repo_kind[(r["repo"], r["kind"])] += 1

    # who is still reading, and therefore what must stay uncompressed
    live = {1: [], 2: []}
    for repo, level in lv.items():
        if level == 0:
            continue
        oc = open_claims(repo)
        if oc:
            live[level].append({"repo": repo, "open": len(oc), "claims": oc,
                                "declared": sum(1 for c in oc if c.get("depends_on")),
                                "earliest": min((c["resolve_by"] or "9999") for c in oc)})

    # Verdicts are pinned everywhere, unconditionally.
    pinned_kinds = set(VERDICT_KINDS)
    reasons = {k: "verdict — never decays" for k in VERDICT_KINDS}
    # Precise pins from claims that DECLARE what they read (suites.depends).
    precise = set()            # (repo, kind) pairs
    precise_kinds = set()      # kinds pinned fleet-wide by a claim naming no repo
    n_declared = n_fallback = 0
    for level, readers in live.items():
        for r in readers:
            for c in r["claims"]:
                dep = c.get("depends_on")
                if not dep:
                    n_fallback += 1
                    # undeclared: fall back to kind-level pinning for this level
                    for k in DEPENDS.get(level, set()):
                        pinned_kinds.add(k)
                        reasons.setdefault(
                            k, f"undeclared level-{level} claim — conservative pin")
                    continue
                n_declared += 1
                kinds = set(dep.get("kinds") or [])
                repos = set(dep.get("repos") or [])
                if kinds and repos:
                    for rp in repos:
                        for k in kinds:
                            precise.add((rp, k))
                elif kinds:
                    precise_kinds |= kinds
                elif repos:
                    for rp in repos:
                        precise.add((rp, "*"))

    plan = []
    for (repo, kind), n in sorted(by_repo_kind.items(), key=lambda x: -x[1]):
        level = lv.get(repo, 0)
        if kind in pinned_kinds:
            verdict, why = "PIN", reasons.get(kind, "dependency")
        elif (repo, kind) in precise or (repo, "*") in precise:
            verdict, why = "PIN", "named by a declared dependency"
        elif kind in precise_kinds:
            verdict, why = "PIN", "kind named by a declared dependency"
        elif repo == "canon":
            verdict, why = "PIN", "canon control — frozen until comparison closes"
        else:
            verdict, why = "compress", "no live dependency"
        plan.append({"repo": repo, "level": level, "kind": kind, "fragments": n,
                     "verdict": verdict, "why": why})
    return {"levels": lv, "live_readers": live, "pinned_kinds": sorted(pinned_kinds),
            "plan": plan, "total_fragments": len(rows),
            "declared": n_declared, "fallback": n_fallback}


def main():
    ap = argparse.ArgumentParser(description="Sleep: level-ordered consolidation.")
    ap.add_argument("--dependency-report", action="store_true")
    ap.add_argument("--consolidate", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.consolidate and not a.dry_run:
        raise SystemExit("consolidation is not implemented yet — phase 1 is the "
                         "dependency report. Run --dependency-report first.")

    d = analyse()
    lv = d["levels"]
    from collections import Counter
    print(f"[sleep] {d['total_fragments']} fragments · levels "
          f"{dict(Counter(lv.values()))}")

    print("\n  LIVE READERS (their open claims pin the layers below):")
    for level in (2, 1):
        rs = d["live_readers"][level]
        if not rs:
            print(f"    level {level}: none — layers below are free to consolidate")
            continue
        for r in rs:
            print(f"    level {level}  {r['repo']:<24} {r['open']:>3} open claims "
                  f"({r['declared']} declare deps) earliest {r['earliest']}")

    print(f"\n  PINNED KINDS ({len(d['pinned_kinds'])}): {', '.join(d['pinned_kinds'])}")

    pin = [p for p in d["plan"] if p["verdict"] == "PIN"]
    comp = [p for p in d["plan"] if p["verdict"] == "compress"]
    n_pin = sum(p["fragments"] for p in pin)
    n_comp = sum(p["fragments"] for p in comp)
    print(f"\n  WOULD PIN      {n_pin:>5} fragments ({len(pin)} repo/kind groups)")
    print(f"  WOULD COMPRESS {n_comp:>5} fragments ({len(comp)} groups)")
    if comp:
        print("\n  compressible, largest first:")
        for p in comp[:12]:
            print(f"    L{p['level']}  {p['repo']:<24} {p['kind']:<14} {p['fragments']:>4}")
    print("\n  Nothing has been compressed — this report is read-only.")


if __name__ == "__main__":
    main()
