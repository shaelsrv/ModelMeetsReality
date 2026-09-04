"""Starter models — go from "I have an opinion" to a working instrument in one command.

The catalogue lives in starters/README.md for reading; this turns a choice into
files. Each starter ships with premises already written in plain language and a
first claim already shaped, so the user edits specifics rather than facing a
blank MODEL.md.

  python -m suites.starter --list
  python -m suites.starter --new B1                 # scaffold "My Own Predictions"
  python -m suites.starter --new I2 --slug my-org   # choose the repo name
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.fleet import ROOT, MODELS_DIR  # noqa: E402

# tier, slug, title, the question a normal person already asks, premise, what
# would prove it wrong, and the shape of the first claim.
STARTERS = {
 "B1": ("basic", "my-predictions", "My Own Predictions",
        "I think this is going to happen — am I right?",
        "I have beliefs about what happens next, and I can tell which are good only "
        "by writing them down before the outcome instead of remembering afterwards.",
        "If my hit rate over ten dated claims is no better than guessing, my sense of "
        "what is 'obvious' is not tracking reality.",
        "Something I believe about the next 90 days that a friend could score without "
        "asking me what I meant."),
 "B2": ("basic", "prices-i-notice", "The Prices I Notice",
        "Is this actually getting more expensive, or does it just feel that way?",
        "My sense of prices comes from a few salient purchases, not from the actual "
        "trend, so it drifts in predictable directions.",
        "If my direction calls on five tracked items are right less than half the time, "
        "my price intuitions are noise.",
        "By <date>, <thing> will cost more than <amount>."),
 "B3": ("basic", "keep-being-wrong", "The Thing I Keep Being Wrong About",
        "Where does my judgment keep failing?",
        "I have a recurring blind spot — one class of thing I systematically "
        "misjudge in the same direction every time.",
        "If my next three predictions in this class are accurate, the blind spot is "
        "imagined and this model retires.",
        "The next specific instance, with a date and a way to score it."),
 "B4": ("basic", "what-friends-care-about", "What My Friends Will Care About",
        "What will people be talking about next month?",
        "Whether something spreads depends on how it fits people's lives, not on how "
        "interesting or important it is.",
        "If topics I judge 'interesting but unrelatable' spread as often as ones I "
        "judge relatable, the mechanism is wrong.",
        "By <date>, at least three people I know will mention <topic> unprompted."),
 "I1": ("intermediate", "where-money-comes-from", "Where The Money Comes From",
        "Who pays for this, and what happens when they stop?",
        "An organisation's behaviour is shaped more by who funds it than by what it "
        "says it values; funding changes show up in behaviour before announcements.",
        "If a major funding change passes with no behavioural change inside two "
        "quarters, funding is not the driver here.",
        "A specific consequence of a specific funding change, dated."),
 "I2": ("intermediate", "who-actually-decides", "Who Actually Decides",
        "Who really makes this call?",
        "The person named as decision-maker and the person who actually decides are "
        "often different; the real one is identifiable by what they need to protect.",
        "If outcomes consistently match the formal decision-maker's stated preference "
        "over my identified actual one, the model is wrong.",
        "What the next decision will be, and by whom."),
 "I3": ("intermediate", "what-they-cannot-say", "What They Cannot Say",
        "What is the thing nobody here is allowed to mention?",
        "Organisations act under constraints they cannot state publicly, so behaviour "
        "predicted from the unstated constraint beats behaviour predicted from the "
        "announcement.",
        "If the stated reasons predict actions at least as well as the constraint "
        "does, there is no hidden constraint worth modelling.",
        "An action the stated reasons do not predict but the unstated constraint does."),
 "I4": ("intermediate", "bill-coming-due", "The Bill Coming Due",
        "What maintenance is being skipped, and when does it bite?",
        "Deferred upkeep accumulates invisibly and then fails suddenly; the deferral "
        "is observable long before the failure.",
        "If tracked deferrals run years past my predicted windows without failing, the "
        "timing mechanism has no predictive content even if the direction is right.",
        "The specific failure and its rough window."),
 "I5": ("intermediate", "same-story-two-sides", "Same Story, Two Sides",
        "Why do both sides think they are obviously right?",
        "Disputes are won by which framing neutral parties adopt when retelling, not "
        "by which side is more correct.",
        "If the losing framing's vocabulary is the one neutral sources use, "
        "framing-adoption is not what decides disputes.",
        "Which vocabulary neutral people use in three months."),
 "A1": ("advanced", "am-i-calibrated", "Am I Calibrated?",
        "When I say 70%, am I right 70% of the time?",
        "My confidence is miscalibrated in a stable direction, which means it can be "
        "measured and corrected rather than merely regretted.",
        "If my stated confidence already matches my hit rate within a few points, "
        "there is nothing to correct.",
        "A prediction about my own hit rate across my next ten claims."),
 "A2": ("advanced", "right-wrong-reason", "Right For The Wrong Reason",
        "Did my reasoning work, or did I get lucky?",
        "A hit only counts if the reason I gave actually operated; hits and lucky hits "
        "are indistinguishable from the inside.",
        "If nearly all my hits turn out earned, the distinction is not worth tracking "
        "and this retires.",
        "What fraction of my next ten hits will be earned rather than lucky."),
 "A3": ("advanced", "boring-explanation", "The Boring Explanation",
        "What if it is just incompetence, timing, or luck?",
        "Boring mechanisms — nobody was in charge, the timing was coincidence, someone "
        "was tired — explain more outcomes than strategic ones.",
        "If my mechanism-rich explanations beat the boring account on matched cases, "
        "the boring prior is too strong.",
        "One of my own explanations, with the boring version bet against it."),
 "A4": ("advanced", "not-watching", "What I Am Not Watching",
        "The thing that decides this — am I even looking at it?",
        "Whatever is watched gets managed, so surprises arrive from the unwatched "
        "part of a situation.",
        "If resolutions keep arriving from things I was already monitoring, the "
        "blind-spot mechanism is not real.",
        "The resolution arrives from something on my unwatched list."),
 "A5": ("advanced", "what-changed-my-mind", "What Changed My Mind",
        "What did I believe a year ago, and what moved me?",
        "Belief change is mostly invisible in retrospect because the new belief feels "
        "like it was always held.",
        "If my recorded past beliefs match what I remember believing, memory is "
        "reliable here and the model is unnecessary.",
        "Which current belief I will abandon first."),
}

TMPL = """# {title} — (v1)

**The question:** {question}

**The kind:** {kind}. Started from the {tier} catalogue; edit freely — the
specifics should be yours, not the template's.

## Premises

**P1 — {premise}**

*(Add your own P2 when you notice a second thing this model assumes. A premise
you cannot state is one you cannot check.)*

## Falsifiable consequences (v1)

1. **{falsifier}**

## Deletion clause

If the consequence above fails and I cannot state a better one, this model
retires rather than being quietly reinterpreted to survive.

## First claim

Shape: {claim_shape}

Register it with a date and a way to score it — a claim without both is a
feeling. Use the cockpit's + button, or:

    python -m suites.starter --claim {slug}

## Epistemic status

v1, nothing graded yet. Everything here is a candidate until reality settles it.
"""


def scaffold(code: str, slug_override: str | None) -> None:
    if code not in STARTERS:
        raise SystemExit(f"unknown starter '{code}' — try --list")
    tier, slug, title, question, premise, falsifier, claim_shape = STARTERS[code]
    slug = slug_override or slug
    kind = ("a forecaster" if tier != "advanced" else
            "a model that reads your own record")
    rdir = MODELS_DIR / slug
    if rdir.exists():
        raise SystemExit(f"{rdir} already exists — pick another --slug")
    (rdir / "predict").mkdir(parents=True)
    (rdir / "MODEL.md").write_text(
        TMPL.format(title=title, question=question, kind=kind, tier=tier,
                    premise=premise, falsifier=falsifier,
                    claim_shape=claim_shape, slug=slug), encoding="utf-8")
    (rdir / "predict" / "ledger.json").write_text('{"predictions": []}', encoding="utf-8")

    f = ROOT / "fleet.json"
    cfg = json.load(f.open(encoding="utf-8")) if f.exists() else {"models": []}
    if slug not in cfg.setdefault("models", []):
        cfg["models"].append(slug)
        f.write_text(json.dumps(cfg, indent=1), encoding="utf-8")

    level = 1 if tier == "advanced" else 0
    pdir = ROOT / "map" / "projections"
    for pf in sorted(pdir.glob("*.json")) if pdir.exists() else []:
        proj = json.load(pf.open(encoding="utf-8"))
        proj.setdefault("assignments", {})[slug] = {
            "aspects": ["science-epistemics"] if tier == "advanced" else ["institutions"],
            "e_span": [8, 10], "kind": "forecaster", "level": level}
        pf.write_text(json.dumps(proj, ensure_ascii=False, indent=1), encoding="utf-8")
    # Deliberately NO `git init` here. Models under an instance's models/ dir
    # belong to the instance's own repo; initialising a repo per model makes them
    # nested repos the parent cannot stage ("does not have a commit checked out").
    # new_model.py does not do it either — this keeps the two scaffolders consistent.

    print(f"[{code}] {title}")
    print(f"  -> {rdir}")
    print(f"  question : {question}")
    print(f"  first claim shape: {claim_shape}")
    print("\n  next: open MODEL.md, make the specifics yours, then register the claim.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Scaffold a starter model.")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--new", metavar="CODE")
    ap.add_argument("--slug")
    a = ap.parse_args()
    if a.new:
        scaffold(a.new.upper(), a.slug)
        return
    cur = None
    for code, (tier, slug, title, q, *_rest) in STARTERS.items():
        if tier != cur:
            cur = tier
            print(f"\n{tier.upper()}")
        print(f"  {code}  {title:<34} {q}")
    print("\n  start with: B1, B3, then I2")
    print("  scaffold:   python -m suites.starter --new B1")


if __name__ == "__main__":
    main()
