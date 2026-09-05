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
