"""Scaffold a new sister model: MODEL.md + watch.json skeletons + fleet registration.

  python -m suites.new_model my-model --title "My Model" --domain "what it models"
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.fleet import ROOT, MODELS_DIR

MODEL_TMPL = """# {title} — (v1)

**The kind:** {kind}
**The domain:** {domain}

## Premises

**P1 — .** (State each load-bearing claim with an honest confidence tier.)

## Falsifiable consequences (v1)

1. **:** a concrete observable that would count against the model.

## Deletion clause

(When should this model be retired? State the conditions under which you would
stop believing it — if consequence 1 fails twice, if the mechanism turns out to
restate something simpler. A model that cannot say what would end it is not
falsifiable, and the format requires this.)

## Watch domains (v1)

Entities in `watch.json`; predictions land in `predict/ledger.json`.

## Epistemic status

v1. All claims candidates until graded.
"""

WATCH_TMPL = {"model_file": "MODEL.md", "ledger": "predict/ledger.json",
  "frame": "One-paragraph description of this instrument for the prediction prompt.",
  "default_model": "openai/gpt-4o",
  "entities": [{"id": "example", "name": "Example entity",
                "watch": "what to observe about it"}]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--title", default="")
    ap.add_argument("--domain", default="")
    ap.add_argument("--level", type=int, default=0,
                    help="0 = models the world · 1 = models the fleet's models · "
                         "2 = models the modelling process. Consolidation runs "
                         "bottom-up and never compresses what a live higher level reads.")
    ap.add_argument("--aspects", default="science-epistemics",
                    help="comma-separated aspects for the reality map")
    ap.add_argument("--e-span", default="9,13", help="emergence floors, e.g. 9,13")
    ap.add_argument("--kind", default="forecaster")
    a = ap.parse_args()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    rdir = MODELS_DIR / a.slug
    rdir.mkdir(exist_ok=True)
    (rdir / "MODEL.md").write_text(
        MODEL_TMPL.format(title=a.title or a.slug, domain=a.domain, kind=a.kind),
        encoding="utf-8")
    (rdir / "watch.json").write_text(json.dumps(WATCH_TMPL, indent=1), encoding="utf-8")
    f = ROOT / "fleet.json"
    cfg = json.load(f.open(encoding="utf-8"))
    if a.slug not in cfg["models"]:
        cfg["models"].append(a.slug)
        f.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    # Register on the reality map too. A model absent from the projection is
    # invisible to the map, the mindmap and sleep's consolidation planner — which
    # is how seven repos silently went unmapped before this was automatic.
    pdir = ROOT / "map" / "projections"
    mapped = []
    if pdir.exists():
        for pf in sorted(pdir.glob("*.json")):
            proj = json.load(pf.open(encoding="utf-8"))
            if a.slug in proj.get("assignments", {}):
                continue
            try:
                lo, hi = (int(x) for x in a.e_span.split(","))
            except ValueError:
                lo, hi = 9, 13
            proj.setdefault("assignments", {})[a.slug] = {
                "aspects": [s.strip() for s in a.aspects.split(",") if s.strip()],
                "e_span": [lo, hi], "kind": a.kind, "level": a.level}
            pf.write_text(json.dumps(proj, ensure_ascii=False, indent=1), encoding="utf-8")
            mapped.append(pf.stem)

    print(f"scaffolded ../{a.slug}/ and registered in fleet.json")
    if mapped:
        print(f"  mapped at level {a.level} in: {', '.join(mapped)}")
    else:
        print("  [!] no projection found — add this model to the map manually")
    print("next: edit MODEL.md + watch.json, then:")
    print(f"  python -m suites.model_watch --repo {a.slug} --predict")

if __name__ == "__main__":
    main()
