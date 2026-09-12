"""Propose a v2 from what actually happened — per entity, and never silently.

THE ASK: when claims are graded, the next version of a model should be revised
so it would have been right about the outcomes — including per-entity, so a
model that was right about one actor and wrong about another fixes the second
without breaking the first.

THE DANGER, NAMED. "Revise until it fits" is curve-fitting with a workflow. A
model refitted to its own graded outcomes explains the past perfectly and has
demonstrated nothing. Four guards, none invented here — each is discipline the
harness already applies elsewhere:

  1. REFITTED PREMISES ARE HINDSIGHT. A premise revised to fit graded outcomes
     ships at confidence: low, marked REFITTED, NOT YET ESTABLISHED. It earns a
     tier on its NEXT graded claims, never on the fit. Same rule as any
     back-tested claim: fitting the past earns no predictive credit.

  2. THE DELETION CLAUSE OUTRANKS REVISION. If the grades show the MECHANISM
     failed rather than a parameter, the model retires. Refitting a dead
     mechanism is how a model becomes unfalsifiable by patching, which every
     deletion clause in this harness exists to prevent.

  3. v1 STAYS GRADED. Versioning appends; it never rewrites. v1's record stays
     attributed to v1, because "did v2 beat v1" is only a question if v1's
     record survives being superseded.

  4. THE OPERATOR ACCEPTS, NOT THE SUITE. This writes a PROPOSAL. Nothing is
     applied. An automatic refit would be a model editing itself to agree with
     events, which is the failure in its purest form.

  python -m suites.refit --model ai-pressure
  python -m suites.refit --model ai-pressure --ledger path/to/graded.json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from harness.fleet import MODELS_DIR

HIT = {"hit", "correct", "true"}
MISS = {"miss", "wrong", "false", "refuted"}


def load_rows(model: str, ledger: str | None) -> list:
    f = Path(ledger) if ledger else MODELS_DIR / model / "predict" / "ledger.json"
    if not f.exists():
        return []
    d = json.loads(f.read_text(encoding="utf-8"))
    return d.get("predictions", d if isinstance(d, list) else [])


def unwatched_names(model: str, rows: list) -> list:
    """Proper nouns the graded record kept naming that this model never watched.

    WHY A v2 MUST WIDEN. A model that only ever watches its original list can
    never be surprised by the world -- and worse, refitting tends to NARROW it,
    because the entities it got right are the ones it keeps. Over versions that
    converges on a model that is correct about a shrinking set, which reads as
    improvement and is the opposite.

    So the refit proposal has to carry the entities the evidence named. The
    mining is deliberately dumb -- capitalised runs, frequency, minus what is
    already watched -- because a candidate list a human vetoes is useful and a
    clever list that auto-registers is not.
    """
    wf = MODELS_DIR / model / "watch.json"
    watched = set()
    if wf.exists():
        try:
            for e in json.loads(wf.read_text(encoding="utf-8")).get("entities", []):
                watched.add(str(e.get("id", "")).lower())
                watched.add(str(e.get("name", "")).lower())
        except ValueError:
            pass

    blob = " ".join(str(r.get(k, "")) for r in rows
                    for k in ("claim", "mechanism", "what_happened",
                              "resolution_criteria"))
    # Capitalised multi-word runs and all-caps acronyms; drop sentence-openers
    # by requiring the term to recur.
    # Allow a trailing number so "Article 91" and "GPT-6" survive intact --
    # splitting on the digit yielded a bare "Article", which is not an entity.
    cand = re.findall(
        r"\b(?:[A-Z][a-zA-Z0-9-]+(?:\s+(?:[A-Z][a-zA-Z0-9-]+|\d{1,4})){0,3}|[A-Z]{2,6})\b",
        blob)
    stop = {"The", "This", "That", "By", "If", "Given", "It", "A", "An", "In",
            "On", "No", "Not", "And", "Or", "But", "For", "MISS", "HIT", "OPEN",
            "TRUE", "FALSE", "Both", "Each", "Every", "Any", "One", "Two"}
    counts = collections.Counter(
        c.strip() for c in cand
        if c.strip() and c.strip() not in stop and c.strip().lower() not in watched)
    return [(n, c) for n, c in counts.most_common(12) if c >= 2]


def by_entity(rows: list) -> dict:
    """Group graded rows per entity. Per-entity is the whole point: a model can
    be right about one actor and wrong about another for the same premise, and
    that difference is the most informative thing in the record."""
    out = collections.defaultdict(lambda: {"hit": [], "miss": [], "open": []})
    for r in rows:
        ent = r.get("entity") or "(unattributed)"
        st = str(r.get("status", "open")).lower()
        bucket = "hit" if st in HIT else "miss" if st in MISS else "open"
        out[ent][bucket].append(r)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--ledger", help="override the ledger path (for fixtures)")
    a = ap.parse_args()

    rows = load_rows(a.model, a.ledger)
    if not rows:
        raise SystemExit(f"  no ledger rows for {a.model}")

    groups = by_entity(rows)
    graded = sum(len(g["hit"]) + len(g["miss"]) for g in groups.values())

    print(f"\n  {a.model}: {len(rows)} rows, {graded} graded across "
          f"{len(groups)} entities\n")

    if not graded:
        print("  Nothing graded yet, so there is nothing to refit AGAINST.")
        print("  A v2 proposed now would be fitted to expectations rather than")
        print("  to outcomes, which is the failure this suite exists to avoid.")
        return

    lines = [f"# {a.model} — v2 proposal", "",
             "**Generated from graded outcomes. Nothing here is applied.**", "",
             "Every revised premise below is a REFIT: fitted to outcomes that",
             "have already happened, and therefore carrying no predictive",
             "credit. Each ships at `confidence: low`, marked",
             "`REFITTED, NOT YET ESTABLISHED`, and earns a tier only on its",
             "next graded claims.", "",
             "## Per-entity record", ""]

    retire_flags = []
    for ent, g in sorted(groups.items()):
        h, m, o = len(g["hit"]), len(g["miss"]), len(g["open"])
        verdict = ("holds" if h and not m else
                   "FAILED here" if m and not h else
                   "mixed" if h and m else "untested")
        lines.append(f"### {ent} — {h} hit / {m} miss / {o} open — **{verdict}**")
        lines.append("")
        for r in g["miss"]:
            lines.append(f"- MISS: {str(r.get('claim',''))[:150]}")
            if r.get("what_happened"):
                lines.append(f"  - what happened: {str(r['what_happened'])[:150]}")
        for r in g["hit"]:
            lines.append(f"- HIT: {str(r.get('claim',''))[:150]}")
        lines.append("")
        if m and not h:
            retire_flags.append(ent)

    # What the record named that this model never watched.
    fresh = unwatched_names(a.model, rows)
    lines += ["## New entities the record named", ""]
    if fresh:
        lines += ["The graded rows keep naming these, and this model watches",
                  "none of them:", ""]
        lines += [f"- **{n}** — {c} mentions" for n, c in fresh]
        lines += ["",
                  "A v2 must either watch them or say why not. Refitting tends",
                  "to NARROW a model toward the entities it already got right,",
                  "which reads as improvement and is the opposite — widening is",
                  "the correction.", ""]
    else:
        lines += ["Nothing recurring that is not already watched. Either the",
                  "model's entity set covers its own evidence, or the record is",
                  "too small to tell — with few graded rows, assume the latter.",
                  ""]

    lines += ["## What a v2 must do", "",
              "1. **Keep what explains the hits.** A revision that fixes a miss",
              "   by breaking a hit is not an improvement, and the per-entity",
              "   split above is what makes that checkable.",
              "2. **State which entity each premise now covers.** A premise that",
              "   silently narrows to the entities it got right is refitting",
              "   dressed as precision.",
              "3. **Leave v1 intact.** v1 keeps its record. This is an append.", ""]

    if retire_flags:
        lines += ["## Deletion clause check — RAISED", "",
                  "These entities produced misses and no hits: "
                  + ", ".join(f"`{e}`" for e in retire_flags) + ".", "",
                  "Before writing a v2, answer the question the deletion clause",
                  "asks: did a PARAMETER fail, or did the MECHANISM? If the",
                  "mechanism failed, this model retires and is replaced. Refitting",
                  "a dead mechanism is how a model becomes unfalsifiable by",
                  "patching, and the deletion clause outranks this proposal.", ""]
    else:
        lines += ["## Deletion clause check — not raised", "",
                  "No entity shows misses without hits.", ""]

    out = MODELS_DIR / a.model / "V2_PROPOSAL.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote {out.name} — a proposal. Nothing was applied.")
    if retire_flags:
        print(f"  DELETION CLAUSE RAISED for: {', '.join(retire_flags)}")


if __name__ == "__main__":
    main()
