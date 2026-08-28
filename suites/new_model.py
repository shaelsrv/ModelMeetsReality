"""Scaffold a new sister model: MODEL.md + watch.json skeletons + fleet registration.

  python -m suites.new_model my-model --title "My Model" --domain "what it models"
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.fleet import ROOT

MODEL_TMPL = """# {title} — (v1)

**The domain:** {domain}

## Premises

**P1 — .** (State each load-bearing claim with an honest confidence tier.)

## Falsifiable consequences (v1)

1. **:** a concrete observable that would count against the model.

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
    a = ap.parse_args()
    rdir = ROOT.parent / a.slug
    rdir.mkdir(exist_ok=True)
    (rdir / "MODEL.md").write_text(
        MODEL_TMPL.format(title=a.title or a.slug, domain=a.domain), encoding="utf-8")
    (rdir / "watch.json").write_text(json.dumps(WATCH_TMPL, indent=1), encoding="utf-8")
    f = ROOT / "fleet.json"
    cfg = json.load(f.open(encoding="utf-8"))
    if a.slug not in cfg["models"]:
        cfg["models"].append(a.slug)
        f.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    print(f"scaffolded ../{a.slug}/ and registered in fleet.json")
    print("next: edit MODEL.md + watch.json, then:")
    print(f"  python -m suites.model_watch --repo {a.slug} --predict")

if __name__ == "__main__":
    main()
