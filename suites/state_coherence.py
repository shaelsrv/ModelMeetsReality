"""Do a model's predicted entity states hang together, or contradict each other?

A model makes several predictions about the same entity. Nothing currently checks
that they are mutually consistent -- a model can predict "no re-measurement is
published" and "the new measurement stays below 25%" about the same entity in the
same round, and both go into the ledger unremarked.

That is not a small bookkeeping problem. Two predictions about one entity that
cannot both be true mean the model has no single view of that entity, and
whichever one grades as a hit will look like the model was right.

WHAT THIS CHECKS, and what it deliberately does not.

  CROSS-ENTITY DRIFT   The same entity predicted into different states by
                       different rounds or repos. Reported, because a model
                       whose own view of an entity moves without a stated
                       reason is drifting rather than updating.

  STATE-SPACE OVERLAP  Two predictions on one entity whose possible_states
                       lists share wording. Sharing a state space means the
                       predictions are about the same question, so their
                       predicted states must be compatible.

  MISPLACED SUBJECT    A predicted state that names a DIFFERENT entity than the
                       row is filed under -- the failure seen live, where a
                       prediction filed under an oversight-posture entity
                       predicted a protocol outcome.

It does NOT judge whether a prediction is right. Nothing here touches outcomes;
this runs before any grading, on the internal consistency of the round.

  python -m suites.state_coherence --model ai-oversight-lag
  python -m suites.state_coherence --all
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

from harness.fleet import MODELS_DIR, ROOT


def toks(t: str) -> set:
    return {w for w in re.findall(r"[a-z]{4,}", (t or "").lower())}


def load(model: str) -> tuple:
    lf = MODELS_DIR / model / "predict" / "ledger.json"
    wf = MODELS_DIR / model / "watch.json"
    rows = []
    if lf.exists():
        d = json.loads(lf.read_text(encoding="utf-8"))
        rows = d.get("predictions", d if isinstance(d, list) else [])
    ents = {}
    if wf.exists():
        try:
            for e in json.loads(wf.read_text(encoding="utf-8")).get("entities", []):
                ents[e.get("id")] = e.get("name", "")
        except ValueError:
            pass
    return rows, ents


def check(model: str) -> list:
    rows, ents = load(model)
    if not rows:
        return [("skip", f"{model}: no ledger rows")]

    findings = []
    by_ent = collections.defaultdict(list)
    for r in rows:
        by_ent[r.get("entity", "(none)")].append(r)

    for ent, rs in sorted(by_ent.items()):
        # 1. Same entity, overlapping state space, incompatible calls.
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                a, b = rs[i], rs[j]
                sa = toks(" ".join(a.get("possible_states") or []))
                sb = toks(" ".join(b.get("possible_states") or []))
                if not sa or not sb:
                    continue
                overlap = len(sa & sb) / len(sa | sb)
                if overlap < 0.25:
                    continue
                pa, pb = a.get("predicted_state", ""), b.get("predicted_state", "")
                if toks(pa) and toks(pb) and not (toks(pa) & toks(pb)):
                    findings.append((
                        "overlap",
                        f"{ent}: two predictions share {overlap:.0%} of their state "
                        f"space but call different states\n"
                        f"      A: {pa[:78]}\n      B: {pb[:78]}"))

        # 2. A row whose SUBJECT is a different watched entity.
        #
        # Read the claim, not just the predicted state. A state often elides its
        # subject ("no new guarantee announced by any of the three") while the
        # claim names it outright ("no major agent interoperability protocol
        # (A2A, MCP, or ACP) will announce..."). Checking the state alone missed
        # a real misfiling on the first live round.
        for r in rs:
            ps = toks(r.get("predicted_state", "")) | toks(r.get("claim", ""))
            if not ps:
                continue
            own = toks(ent) | toks(ents.get(ent, ""))
            # Tokens shared by several watched entities ("agent", "ai") identify
            # nobody -- comparing on them made a real misfiling invisible,
            # because the misfiled claim contained its host entity's generic
            # half. Score only on tokens that DISTINGUISH one entity.
            shared = set()
            for e1, n1 in ents.items():
                for e2, n2 in ents.items():
                    if e1 < e2:
                        shared |= (toks(e1) | toks(n1)) & (toks(e2) | toks(n2))
            owndist = own - shared
            for other, oname in ents.items():
                if other == ent:
                    continue
                on = (toks(other) | toks(oname)) - shared
                if not on:
                    continue
                hits_other, hits_own = ps & on, ps & owndist
                if hits_other and not hits_own:
                    findings.append((
                        "misfiled",
                        f"{ent}: this row is about '{other}'\n"
                        f"      {str(r.get('claim',''))[:78]}"))
                    break
                # Names both. Not a clean misfiling -- but a row reading as two
                # entities at once cannot be graded against one of them without
                # a choice nobody recorded, so it is reported rather than
                # resolved. Forcing a verdict here would be the detector
                # inventing the answer.
                if hits_other and hits_own:
                    findings.append((
                        "ambiguous",
                        f"{ent}: also reads as '{other}' "
                        f"(shares {', '.join(sorted(hits_other))})\n"
                        f"      {str(r.get('claim',''))[:78]}"))
                    break
    return findings


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    if a.all:
        cfg = json.loads((ROOT / "fleet.json").read_text(encoding="utf-8"))
        models = cfg.get("models", [])
    elif a.model:
        models = [a.model]
    else:
        raise SystemExit("  --model <slug> or --all")

    total = 0
    for m in models:
        fs = check(m)
        real = [f for f in fs if f[0] != "skip"]
        total += len(real)
        if not fs:
            print(f"  {m:26s} coherent")
        elif not real:
            print(f"  {m:26s} {fs[0][1].split(': ',1)[1]}")
        else:
            print(f"  {m:26s} {len(real)} finding(s)")
            for kind, msg in real:
                print(f"    [{kind}] {msg}")

    print(f"\n  {total} coherence finding(s) across {len(models)} model(s)")
    if total:
        print("  These are INTERNAL consistency problems, found before any")
        print("  grading. A model with contradictory predictions about one")
        print("  entity will score a hit whichever way the world goes.")


if __name__ == "__main__":
    main()
