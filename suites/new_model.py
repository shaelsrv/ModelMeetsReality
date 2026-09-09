"""Scaffold a new sister model: MODEL.md + watch.json skeletons + fleet registration.

  python -m suites.new_model my-model --title "My Model" --domain "what it models"
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json

from harness.fleet import ROOT, MODELS_DIR

KINDS_DIR = Path(__file__).resolve().parent / "kinds"


def _read_packs(f: Path) -> dict:
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("packs", {})
    except ValueError:
        return {}


def load_pack(kind: str) -> dict:
    """The discipline for this kind: premise shape, falsifier, and the question
    the agentic pass asks.

    Before this, `kind` was a string in model.json that nothing read -- a
    classifier scaffolded identically to a forecaster, and the difference that
    actually matters (what would prove it wrong) was left to the author to
    remember. The engine is shared; the discipline is not.

    THE ELEVEN ARE A STARTING SET, NOT A TAXONOMY. `my_kinds.json` (gitignored,
    yours, never overwritten by an engine update) is read first and wins on a
    name collision, so you can add a kind the eleven do not cover -- or sharpen
    one of theirs -- without editing a shipped file. A kind you invent is a
    claim about what would falsify a whole CLASS of model; writing one is the
    same discipline as writing a model, one level up.
    """
    return (_read_packs(KINDS_DIR / "my_kinds.json").get(kind)
            or _read_packs(KINDS_DIR / "packs.json").get(kind)
            or {})


MODEL_TMPL = """# {title} — (v1)

**The kind:** {kind}
**The domain:** {domain}

## Premises

{premise_help}

**P1 — .** (State each load-bearing claim with an honest confidence tier.)

## Falsifiable consequences (v1)

{falsifier_help}

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
    pack = load_pack(a.kind)
    # An unknown kind is allowed -- the eleven are a starting set. But it must not
    # scaffold SILENTLY, which is what happened before: you got a model with a
    # label, no premise shape, no falsifier and an empty agentic frame, and
    # nothing said so. Say it, and say how to fix it.
    if not pack:
        known = sorted(set(_read_packs(KINDS_DIR / "packs.json"))
                       | set(_read_packs(KINDS_DIR / "my_kinds.json")))
        print(f"  NOTE: '{a.kind}' has no discipline pack, so this model scaffolds")
        print( "        without a premise shape, a falsifier, or an agentic frame.")
        print( "        Known kinds: " + ", ".join(known))
        print(f"        To define '{a.kind}' as a real kind, add it to")
        print( "        suites/kinds/my_kinds.json -- see suites/kinds/KINDS.md")
        print( "        ('Creating your own kind'). Then re-run this command.")
    _nl = chr(10)
    _premise = (pack.get("premise_shape")
                and ("*Shape for a " + a.kind + ":* `" + pack["premise_shape"] + "`"
                     + ((_nl * 2 + "*Banned:* " + pack["banned"]) if pack.get("banned") else ""))
                or "(State each load-bearing claim with an honest confidence tier.)")
    _fals = (pack.get("falsifier")
             and ("*What falsifies a " + a.kind + ":* " + pack["falsifier"]
                  + ((_nl * 2 + "> **" + pack["warning"] + "**") if pack.get("warning") else ""))
             or "")
    (rdir / "MODEL.md").write_text(
        MODEL_TMPL.format(title=a.title or a.slug, domain=a.domain, kind=a.kind,
                          premise_help=_premise, falsifier_help=_fals),
        encoding="utf-8")
    watch = dict(WATCH_TMPL)
    if pack.get("predict_frame"):
        # The frame is what makes the agentic pass KIND-AWARE: a decision-model
        # is told to ignore stated intentions, a forecaster to demand a date.
        watch["frame"] = pack["predict_frame"]
    if pack.get("assess_frame"):
        watch["assess_frame"] = pack["assess_frame"]
    watch["kind"] = a.kind
    (rdir / "watch.json").write_text(json.dumps(watch, indent=1), encoding="utf-8")
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

    # A model people cannot RUN is a paper. USE.md and TASKS.md are generated
    # from MODEL.md, so they are written after the theory is, not now — but the
    # scaffold says so rather than leaving the author to discover the convention
    # by reading someone else's repo.
    print("\nnext:")
    print("  1. write MODEL.md — premises, falsifiable consequences, deletion clause")
    print("  2. python -m suites.make_card  --model {0} --author <handle>".format(a.slug))
    print("  3. python -m suites.make_use   --model {0} --author <handle>"
          "   # one-prompt install".format(a.slug))
    print("  4. python -m suites.make_tasks --model {0} --author <handle>"
          "   # scheduled runs".format(a.slug))
    print("  5. python -m suites.legitimacy_audit --model {0}"
          "        # catches what is missing".format(a.slug))
    print(f"\n  then: python -m suites.model_watch --repo {a.slug} --predict")

if __name__ == "__main__":
    main()
