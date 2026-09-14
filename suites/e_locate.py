"""Locate models and open questions on the emergence ladder — as SPANS, not points.

A theory is rarely about one floor. Thermodynamics runs from molecular motion to
engines to economies; a theory of institutions touches individual minds below it
and states above. Collapsing that to a single level throws away the part that
matters: WHERE a theory stops working.

So every locator here is a SPAN [lo, hi], and the schema already carries one
(`e_span` in the reality-map projection). This suite fills it for things that
have no assignment yet — canon controls and open questions — and reports what
the span implies.

WHAT A SPAN MEANS HERE

  lo   the lowest floor at which the theory still says something specific.
       Below lo it either says nothing, or degenerates to a truism.
  hi   the highest floor at which it still constrains. Above hi, the mechanism
       it names is swamped by mechanisms it does not name.

The BOUNDARIES are the claim, not the middle. "Supply and demand spans E11-E12"
is uninteresting; "supply and demand stops constraining below E11 because there
is no medium of exchange" is a statement that can be wrong.

WHAT THIS REFUSES

  - No span without a stated reason at each end. A bare [9, 13] is a guess
    wearing brackets.
  - No full-ladder spans. [0, 14] means "applies to everything", which is
    unfalsifiable and almost always means the theory was not examined.
  - No locating a theory by its VOCABULARY. A theory that uses the word
    "selection" is not thereby at the floor where biological selection lives.

  python -m suites.e_locate --canon
  python -m suites.e_locate --gaps
  python -m suites.e_locate --report
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from harness.fleet import MODELS_DIR, ROOT

PROJ = ROOT / "map" / "projections" / "em-ladder.v1.json"

FLOOR_NAMES = {
    0: "physics", 1: "particles", 2: "atoms", 3: "chemistry", 4: "compounds",
    5: "replicators", 6: "organisms", 7: "nervous systems", 8: "individual minds",
    9: "attention and memes", 10: "institutions", 11: "economy", 12: "states",
    13: "civilisations", 14: "planetary",
}


def load_proj() -> dict:
    if not PROJ.exists():
        raise SystemExit(f"  no projection at {PROJ}")
    return json.loads(PROJ.read_text(encoding="utf-8"))


def spans(proj: dict) -> dict:
    out = {}
    for slug, a in (proj.get("assignments") or {}).items():
        s = a.get("e_span")
        if isinstance(s, list) and len(s) == 2:
            out[slug] = (int(s[0]), int(s[1]))
    return out


def coverage(sp: dict) -> collections.Counter:
    """How many things claim each floor. A floor nothing spans is a gap in what
    the fleet can currently see -- which is the useful output."""
    c = collections.Counter()
    for lo, hi in sp.values():
        for f in range(lo, hi + 1):
            c[f] += 1
    return c


def report(proj: dict) -> None:
    sp = spans(proj)
    cov = coverage(sp)
    print(f"\n  {len(sp)} located across the ladder\n")
    print("  floor                         span count")
    for f in range(15):
        n = cov.get(f, 0)
        bar = "#" * min(n, 30)
        flag = "   <- NOTHING SPANS THIS" if n == 0 else ""
        print(f"  E{f:<3} {FLOOR_NAMES[f]:<22} {n:>3} {bar}{flag}")

    full = [s for s, (lo, hi) in sp.items() if lo <= 1 and hi >= 13]
    if full:
        print(f"\n  near-full-ladder spans ({len(full)}) -- these usually mean")
        print("  the theory was not examined, not that it applies everywhere:")
        for s in full:
            print(f"    {s}  {sp[s]}")

    narrow = sorted(sp.items(), key=lambda kv: kv[1][1] - kv[1][0])[:5]
    print("\n  narrowest spans (the most constrained, therefore most testable):")
    for s, (lo, hi) in narrow:
        print(f"    {s:<26} E{lo}-E{hi}  ({FLOOR_NAMES[lo]} -> {FLOOR_NAMES[hi]})")

    # A coverage map is only a map of the fleet if the spans were CHOSEN.
    # new_model defaults to 9,13 -- so a fleet where everything shares that span
    # is reporting the default, and the uncovered floors below are an artefact.
    counts = collections.Counter(sp.values())
    top, n = counts.most_common(1)[0] if counts else ((0, 0), 0)
    if n > 1 and n >= 0.6 * len(sp):
        print()
        print(f"  WARNING: {n} of {len(sp)} share the span "
              f"E{top[0]}-E{top[1]},")
        print("  which is new_model's default. Spans nobody chose describe the")
        print("  scaffold, not the fleet -- treat the coverage above as unset")
        print("  rather than as a finding, and set spans with reasons first.")

    gaps = [f for f in range(15) if cov.get(f, 0) == 0]
    if gaps:
        print(f"\n  UNCOVERED FLOORS ({len(gaps)}): "
              + ", ".join(f"E{f} {FLOOR_NAMES[f]}" for f in gaps))
        print("  Nothing in this instance says anything specific at these")
        print("  floors. That is a map of what it structurally cannot see.")


def list_unlocated() -> list:
    """Models with no e_span. Canon cards and anything scaffolded without one."""
    proj = load_proj()
    assigned = set(proj.get("assignments") or {})
    out = []
    for d in sorted(MODELS_DIR.glob("*/MODEL.md")):
        slug = d.parent.name
        if slug not in assigned:
            out.append(slug)
    for d in sorted(MODELS_DIR.glob("*/models/*.md")):
        slug = d.stem
        if slug not in assigned:
            out.append(f"{d.parent.parent.name}:{slug}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--report", action="store_true", help="coverage and gaps")
    ap.add_argument("--unlocated", action="store_true", help="what has no span yet")
    a = ap.parse_args()

    if a.unlocated:
        u = list_unlocated()
        print(f"\n  {len(u)} without an e_span:")
        for s in u:
            print(f"    {s}")
        if u:
            print("\n  A span needs a REASON at each end. Add to the projection's")
            print("  assignments as: {\"e_span\": [lo, hi], \"span_why\":")
            print("  {\"lo\": \"...\", \"hi\": \"...\"}} -- a bare span is a guess")
            print("  wearing brackets.")
        return

    report(load_proj())


if __name__ == "__main__":
    main()
