"""Substrate maps + emergent-pattern libraries per sister model.

The method (2026-08-23): each model's dynamics run on SUBSTRATES (the underlying stocks,
fields, and mediums). Combinations of substrate conditions have historically produced
EMERGENT PATTERNS — recurring macro-behaviors with datable instances. If current conditions
match a known pattern's preconditions, a prediction there is *working from memory*
(pattern-recall); if the substrate combination has no historical instance, the prediction is
a *novel-regime* inference. The two modes should — testably — calibrate differently.

Per repo this writes substrate/patterns.json:
  {"substrates":[{name, description, condition_axes}],
   "patterns":[{id, name, instances:[{case, period}], preconditions, signature, course}]}

sync_ledger.py then uses each instrument's library to tag every public prediction with a
precedent (pattern + historical instances + match strength) or "novel" — rendered on the
site and split-scored at grading.

  python suites/substrate_map.py                # all seven models
  python suites/substrate_map.py --repo my-model
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.openrouter import chat
from harness.actors import parse_json

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
from harness.fleet import MODEL_REPOS as REPOS

PROMPT = """You are analyzing an original theoretical model to extract its SUBSTRATE STRUCTURE and
its EMERGENT-PATTERN LIBRARY.

1. SUBSTRATES — the underlying stocks/fields/mediums the model's dynamics actually run on (not
   its claims — the things whose STATES its claims are about). For each: name, one-line
   description, and 2-4 condition axes (the state variables worth tracking, e.g. "scarcity vs
   abundance", "concentrated vs distributed").

2. EMERGENT-PATTERN LIBRARY — 6-10 macro-patterns that have HISTORICALLY emerged from specific
   combinations of these substrate conditions. Real history only, specific and datable. For each:
   - id (short slug), name (the pattern, plainly named)
   - instances: 2-4 dated historical cases where it emerged
   - preconditions: the substrate-condition combination that preceded it (stated in terms of the
     substrates above)
   - signature: the observable early markers that it is emerging again
   - course: how it typically ran (duration, resolution)
   Prefer patterns relevant to near-term forecasting with this model. If an important substrate
   combination has NO known historical instance, list it under "uncharted" — these are the novel
   regimes where the model must extrapolate rather than recall.

THE MODEL:
{model}

Return ONLY JSON:
{"substrates":[{"name":"...","description":"...","condition_axes":["..."]}],
"patterns":[{"id":"...","name":"...","instances":[{"case":"...","period":"..."}],
"preconditions":"...","signature":"...","course":"..."}],
"uncharted":[{"combination":"...","why_no_precedent":"..."}]}"""


def map_repo(repo):
    path = os.path.join(TOOLS, repo, "MODEL.md")
    if not os.path.exists(path):
        print(f"  [{repo}] no MODEL.md, skipped"); return
    with open(path, encoding="utf-8") as f:
        model_text = f.read()[:13000]
    print(f"  [{repo}] mapping substrates + patterns…", flush=True)
    r = chat("openai/o3", [{"role": "user", "content": PROMPT.replace("{model}", model_text)}],
             temperature=0.3, max_tokens=6000)
    d = parse_json(r.text) if not r.error else None
    if not d:
        r = chat("openai/o3", [{"role": "user", "content": PROMPT.replace("{model}", model_text)}],
                 temperature=0.2, max_tokens=8000)
        d = parse_json(r.text) if not r.error else None
    if not d or not d.get("patterns"):
        print(f"    ! failed: {r.error or 'unparseable'}"); return
    outdir = os.path.join(TOOLS, repo, "substrate")
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, "patterns.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print(f"    → {len(d.get('substrates', []))} substrates · {len(d['patterns'])} patterns · "
          f"{len(d.get('uncharted', []))} uncharted combos")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    a = ap.parse_args()
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("[note] no key"); return
    for repo in ([a.repo] if a.repo else REPOS):
        map_repo(repo)


if __name__ == "__main__":
    main()
