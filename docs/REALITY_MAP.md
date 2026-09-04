# The Reality Map — combining models into one map of the universe

The premise: no single person can model reality, but many people each modeling an
ASPECT — with shared coordinates, shared discipline, and graded evidence — can
combine into the most complete map anyone has. This document defines the
coordinates, the contribution unit, the validation tiers, and the federation
protocol. The local Map tab renders one instance's slice; the commons renders
everyone's.

## Coordinates (shared by every contributor)

- **Vertical axis: the emergence ladder E0–E14** — physics → chemistry → biology →
  minds (E8) → attention/memes (E9) → institutions → economy → states → epistemes
  → civilizational. Every model declares its E-SPAN: the floors its mechanism
  actually operates on.
- **Horizontal axis: aspects** — a small controlled vocabulary of domains
  (matter/energy · life · individual minds · attention/media · institutions ·
  economy/markets · states/geopolitics · science/epistemics · technology/tools ·
  culture/narrative · infrastructure/logistics · civilization/long-term). A model
  claims 1–3 aspects.
- A model's MAP REGION = aspects × E-span. Overlaps are welcome (competing models
  of one region are the engine of progress); EMPTY regions are the map's product —
  each gap is a standing invitation.

## The contribution unit: the mapcard

A mapcard is the SHAREABLE derivative of a model — no private data, no ledger
contents, no reasoning:

```json
{"model": "slug", "instance": "anonymous-or-named", "kind": "forecaster",
 "aspects": ["institutions"], "e_span": [10, 12],
 "mechanism": "one-line mechanism statement",
 "consequences": ["one-line falsifiable consequence", "..."],
 "record": {"open": 12, "graded": 9, "supported": 3, "refuted": 1,
            "mean_brier": 0.21, "attribution_share": 0.07},
 "updated": "YYYY-MM-DD", "license": "CC-BY-4.0"}
```

The record block is COUNTS AND SCORES ONLY — enough for the map to color the
region by evidence, never enough to leak claims. `suites/reality_map.py --export
--repo <model>` produces one.

## Validation tiers (how the map colors a region)

1. **declared** — a mapcard exists; the region is claimed. (outline)
2. **registered** — the model has open, dated, criteria-bearing claims. (hatched)
3. **graded** — claims have resolved; Brier vs baseline exists. (filled, intensity
   by record)
4. **attributed** — independent outcome-attribution has picked this mechanism as
   reality's driver. (the strongest color the map gives)
5. **refuted** — the model honored a deletion clause; the region shows the
   TOMBSTONE, permanently. Dead models stay on the map: knowing a mechanism does
   NOT operate in a region is map content of the highest value.

## Federation (the community layer)

- Each instance runs private; contribution = pushing MAPCARDS ONLY to a public
  commons repo (git PRs at first — the review is schema + license, never quality
  gatekeeping; bad models die by grading, not by moderation).
- The commons aggregates cards into one combined map; the renderer is the same
  one the local Map tab uses, pointed at more cards.
- Credit: every card carries its instance name; the map IS the attribution.
  License CC-BY-4.0 (family convention). Reading is never gated (commons
  doctrine).
- Disagreement is data: two cards claiming one region with opposite graded
  records is the map working, not a conflict to resolve.
- Ships with T3 (the template gains `--export` + a CONTRIBUTING pointer); the
  commons repo itself launches with the template so day-one adopters have
  somewhere to send cards.

## What the local map already shows (the honest state)

Rendering our own 40+ cards makes the point the vision rests on: everything below
E8 is EMPTY — no physics, no chemistry, no biology, no neuroscience. One
instance, even a busy one, covers a corridor (E8–E14, heavy on institutions/
attention/states). The gaps are not a failure; they are the argument for the
commons, drawn as a picture.

## The mapping model is itself a model (added after the obvious question)

The coordinates above are not the architecture — they are `em-ladder.v1`, one
PROJECTION among possible many, stored in `map/projections/` with the same
discipline as any model:

- **Intrinsic vs projected:** a mapcard's mechanism and record are projection-
  independent; its coordinates are per-projection (`coords: {"em-ladder.v1":
  {...}, "your-better-scheme.v1": {...}}`). Replacing the ontology never touches
  a card.
- **Adequacy criteria (how a projection is graded):** operability (blind coders
  place a new model at kappa >= 0.5), discrimination (cards spread, not clump),
  joint-carving (map-adjacent models share attribution cross-hits more than
  distant ones — proximity predicts mechanism-sharing, or the axes are
  decoration), gap fertility (its gaps provoke models; inert gaps count against).
  em-ladder.v1's own adequacy line currently reads: "none yet — the incumbent
  holds by default, not by evidence."
- **Succession rule:** challengers are ADDED, never edited in; beat the incumbent
  on >=2 adequacy criteria over the same cards and the default rendering
  switches. Retired projections are kept forever so historical cards stay
  interpretable. Contributors can therefore contribute PROJECTIONS, not just
  models — a physicist's scale-based axes can compete with the emergence ladder
  on measured adequacy, and the commons renders any projection over the same
  cards.
