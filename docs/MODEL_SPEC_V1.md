# Model Repo Format — v1

The shareable unit is a git repository. This is the contract: a repo that meets
it can be listed in the Garden, imported by anyone, and rendered on a map
alongside models it has never met.

Versioned deliberately. v1 is what we converged on by building; it will be wrong
in places, and v2 will fix those in the open rather than by silent drift.

---

## Required

    MODEL.md          the theory — the actual thing being shared
    model.json        machine-readable card (schema below)
    LICENSE           anything permitting redistribution; CC-BY-4.0 suggested

## Strongly recommended

    USE.md            how to RUN the model once, in ChatGPT / Claude / Gemini
    TASKS.md          how to run it on a SCHEDULE (or pasted from a reminder)

MODEL.md is the theory; USE.md is how someone without Python, a local model, or
any tooling actually uses it. A reader pastes one line —
`https://github.com/<owner>/<model>  Help me use this` — and the assistant reads
the repo and becomes the model.

Generate both:

    python -m suites.make_use   --model <slug> --author <handle>
    python -m suites.make_tasks --model <slug> --author <handle>

`publish_model` regenerates them automatically, and `legitimacy_audit` flags a
repo missing either — so the convention holds without anyone remembering it.
Both are derived from MODEL.md, which means a stale copy advertises a model that
no longer matches its own instructions.
Verified working in a live ChatGPT session: the assistant explained itself,
flagged the model's own low-confidence premise unprompted, labelled its guesses,
and produced a dated falsifiable prediction rather than a summary.

USE.md must follow **Review → Explain → Confirm → Apply**: explain what the
model is, say what it will and will not do, and ask before proceeding. A pasted
instruction block is shaped exactly like a prompt-injection attempt — the only
honest difference is that this one expects to be examined and refused. A model
whose USE.md demands obedience is indistinguishable from an attack.

### MODEL.md must contain

    # <Name> — <one line> (v1)

    **The kind:** one of the kinds below
    **The domain:** what it models, in a sentence

    ## Premises
    **P1 — <claim>.** ...          one or more, each stateable and load-bearing

    ## Falsifiable consequences (v1)
    1. **<observable>** ...        at least one; what would count AGAINST it

    ## Deletion clause
    <when this model should be retired>

    ## Epistemic status
    <what is bet vs what is floor; what is graded so far>

A model with no falsifiable consequence is not listable. Not because it is
wrong — because it cannot be wrong, and the Garden's colours mean validation.

### model.json

```json
{
  "spec": "v1",
  "model": "gravity-wells",
  "title": "Gravity Wells",
  "author": "github-username",
  "repo": "https://github.com/username/gravity-wells",
  "license": "CC-BY-4.0",
  "kind": "forecaster",
  "level": 0,
  "aspects": ["matter-energy"],
  "e_span": [0, 2],
  "mechanism": "one line: what this model says drives outcomes",
  "declared": {
    "scope": "global",
    "inputs": "public-web",
    "sensitivity": "neutral",
    "effort": "hours"
  },
  "record": { "open": 1, "graded": 0 }
}
```

`record` carries **counts only** — never claim text, never reasoning. Cards are
advertisements; repos hold the substance.

## Optional, and conventional

    predict/ledger.json     your claims (open + graded)
    imported/               claims inherited from a model you imported
    IMPORTED.md             provenance, if this is derived from someone else's
    tags.json               your declared tags
    cases/ traces/ notes/   the reasoning behind the theory

## Vocabulary

**kind** — forecaster · classifier · tracer · finder · tracker · generator ·
attributor · adversary · mirror · timer

**level** — 0 models the world · 1 models models · 2 models the modelling process

**aspects** — matter-energy · life · individual-minds · attention-media ·
institutions · economy-markets · states-geopolitics · science-epistemics ·
technology-tools · culture-narrative · infrastructure-logistics ·
civilization-longterm

**e_span** — `[low, high]` over E0–E14, the floors the mechanism operates on

## Validating before you submit

    python -m suites.validate_card model.json --repo .

Checks schema, whether the record matches your own ledgers, whether the repo
carries executable files (disclosed, not blocked), and licence. It does not
judge whether your model is any good — that is what grading is for.

## What the Garden does not check

Plausibility, novelty, writing quality, or whether your model contradicts a
popular one. Two models claiming the same region with opposite records is the
system working. **Refuted models stay listed** — a mechanism shown not to
operate somewhere is a finding, and its tombstone is worth more than silence.
