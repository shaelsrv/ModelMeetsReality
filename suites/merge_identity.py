"""Cross-source identity for imported analysts — proposed by LLM, confirmed by a human.

The problem (imports/README "Not built yet"): "my-model" (video) and "my-model"
(newsletter) are one source recorded as two analysts, and "Compute capacity ramp via
infra buildout" vs "GW-scale training via multi-campus buildouts" are plausibly one
mechanism. Until merged, the legitimacy table implies independent track records where
there is one.

The design is NON-DESTRUCTIVE: ledger files are never rewritten. The merge lives in
`imports/identity.json` as an alias map, applied at REPORT time by grade_claims — so a
merge is reversible by editing one file, and the raw record of who-said-what-where stays
intact.

`imports/identity.json`:
  {"analysts":  {"my-model": "my-model"},              # alias -> canonical
   "mechanisms": {"<analyst>|<alias mechanism>": "<canonical mechanism>"}}
Mechanism keys are canonical-analyst-scoped ("my-model|Compute capacity ramp ...")
so two analysts' same-named mechanisms never collide.

DISCIPLINE — who may write what:
  * ANALYST merges are identity facts, checkable against the world (my-model is
    my-model's founder). `--propose` includes them; applying them is uncontroversial.
  * MECHANISM merges CHANGE HOW TRACK RECORDS AGGREGATE. They are written to
    `imports/identity_proposal.json` and NEVER auto-applied — a human moves a proposal
    into identity.json to confirm it. The whole framework is built on "criteria before
    outcome"; merging two mechanisms after seeing their scores is the same contamination
    in aggregation form, so the confirmation step is load-bearing, not politeness.

  python -m suites.merge_identity --propose      # LLM proposal -> identity_proposal.json
  python -m suites.merge_identity --show         # current confirmed map + its effect
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
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
IDENTITY = ROOT / "imports" / "identity.json"
PROPOSAL = ROOT / "imports" / "identity_proposal.json"


def load_identity() -> dict:
    if IDENTITY.exists():
        return json.load(IDENTITY.open(encoding="utf-8"))
    return {"analysts": {}, "mechanisms": {}}


def canonical(analyst: str, mechanism: str, ident: dict) -> tuple[str, str]:
    """Map (analyst, mechanism) through the confirmed alias map. Used by grade_claims."""
    a = ident.get("analysts", {}).get(analyst, analyst)
    m = ident.get("mechanisms", {}).get(f"{a}|{mechanism}", mechanism)
    return a, m


def _models_inventory() -> list[dict]:
    """One row per (analyst, mechanism) across all import ledgers, with enough context
    for an identity judgment: claim count, topics, and a few sample claims."""
    inv = defaultdict(lambda: {"n": 0, "samples": [], "sources": set()})
    for f in sorted(glob.glob(str(ROOT / "imports" / "*.claims.jsonl"))):
        if Path(f).stem.endswith("-unclustered.claims"):
            continue
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            key = (r.get("analyst", "?"), r.get("mechanism") or Path(f).stem)
            e = inv[key]
            e["n"] += 1
            e["sources"].add(r.get("source_title") or r.get("source_url") or "?")
            if len(e["samples"]) < 3:
                e["samples"].append(r.get("claim", "")[:120])
    return [{"analyst": a, "mechanism": m, "n_claims": e["n"],
             "sources": sorted(e["sources"])[:3], "samples": e["samples"]}
            for (a, m), e in sorted(inv.items())]


PROPOSE_PROMPT = """Below is an inventory of imported forecasting models, one per
(analyst, mechanism). Some entries are the SAME identity recorded twice:

1. ANALYST duplicates — the same person/publication under two names (a person and the
   outlet they write, a channel name vs a byline). Only merge when the identity is a
   checkable public fact you are confident of, and say why.
2. MECHANISM duplicates — the same causal machine split by phrasing, WITHIN one
   (post-analyst-merge) analyst. Merge only if the two mechanisms' claims would resolve
   on the SAME observables — not merely the same topic area. Two mechanisms about "AI
   compute" that bet on different observables (capex dollars vs datacenter gigawatts)
   are DIFFERENT machines; keeping them separate is the entire point of the split.
   Be conservative: a wrong merge corrupts two track records at once.

INVENTORY:
{inventory}

Return ONLY JSON:
{"analysts":[{"alias":"...","canonical":"...","why":"the public fact that makes them one identity"}],
"mechanisms":[{"analyst":"<canonical analyst>","alias":"...","canonical":"...",
"why":"why these resolve on the same observables","confidence":"high|medium|low"}]}
Empty lists are valid answers."""


def cmd_propose(model: str) -> None:
    inv = _models_inventory()
    if not inv:
        raise SystemExit("no import ledgers found")
    r = chat(model, [{"role": "user", "content":
                      PROPOSE_PROMPT.replace("{inventory}", json.dumps(inv, indent=1))}],
             temperature=0.2, max_tokens=3000)
    d = parse_json(r.text) if not r.error else None
    if not d:
        raise SystemExit(f"proposal failed: {r.error or 'unparseable'}")
    PROPOSAL.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"proposal -> {PROPOSAL}\n")
    for a in d.get("analysts", []):
        print(f"  ANALYST   {a['alias']}  ->  {a['canonical']}   ({a.get('why','')})")
    for m in d.get("mechanisms", []):
        print(f"  MECHANISM [{m.get('confidence','?'):6s}] ({m.get('analyst','?')}) "
              f"{m['alias']}  ->  {m['canonical']}\n"
              f"            {m.get('why','')}")
    print("\nTo confirm: move entries into imports/identity.json "
          '({"analysts": {alias: canonical}, "mechanisms": {"<analyst>|<alias>": canonical}}).'
          "\nMechanism merges are never auto-applied.")


def cmd_show() -> None:
    ident = load_identity()
    print(f"confirmed identity map ({IDENTITY.name}):")
    print(json.dumps(ident, indent=2, ensure_ascii=False))
    merged = defaultdict(int)
    for row in _models_inventory():
        a, m = canonical(row["analyst"], row["mechanism"], ident)
        merged[(a, m)] += row["n_claims"]
    print(f"\neffect: {len(merged)} models after merge")
    for (a, m), n in sorted(merged.items()):
        print(f"  {a:<16} {m[:55]:<56} {n:>3} claims")


def main() -> None:
    ap = argparse.ArgumentParser(description="Cross-source identity for imported analysts.")
    ap.add_argument("--propose", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--model", default="openai/gpt-5")
    a = ap.parse_args()
    if a.propose:
        from suites.grade_claims import _load_env
        _load_env()
        if not os.environ.get("OPENROUTER_API_KEY"):
            if os.environ.get("LLM_BACKEND") != "claude-code":
                raise SystemExit("OPENROUTER_API_KEY not set (or set LLM_BACKEND=claude-code)")
        cmd_propose(a.model)
    else:
        cmd_show()


if __name__ == "__main__":
    main()
