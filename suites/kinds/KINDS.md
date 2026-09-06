# The eleven kinds, and what falsifies each

A kind is not a label. It is a **commitment about what would prove the model
wrong**, and that commitment changes the premise shape, the watch frame, and the
question the agentic pass asks.

Before this file, `kind` was a string in `model.json` that nothing in the code
read. These packs make it load-bearing.

## Tiers, stated honestly

**PROVEN** — a discipline worked out against real instances in this system.
**DESIGNED** — the falsifier question is stated but no instance has been built,
so the pack ships with the open question rather than a confident answer. Same
seeded-vs-established honesty the instance index enforces.

| kind | tier | the falsifier |
|---|---|---|
| forecaster | PROVEN | a dated expectation that does not occur by its date |
| decision-model | PROVEN | a future choice, in the named situation, that breaks the stated ordering |
| tracker | PROVEN | the leading indicator stops leading — the lag it claims does not hold |
| classifier | PROVEN | a case it sorted one way behaves like the other class |
| adversary | PROVEN | the belief it attacks survives the specific test it named |
| tracer | DESIGNED | the chain runs in a different order than claimed, or skips a named link |
| timer | DESIGNED | the phase it names does not arrive in the window it names |
| attributor | DESIGNED | the outcome is better explained by a cause it excluded |
| finder | DESIGNED | it fails to surface an instance that later proves to have been findable |
| generator | DESIGNED | **open question.** What proves a generator wrong? A generator that only produces plausible output is unfalsifiable. Candidate: it must state what it will NOT generate, and be wrong when that appears. |
| mirror | DESIGNED | **open question.** A model of the modeller. Candidate: it predicts a specific revision the author will make, and the author does not make it. |

Two kinds ship with the question open rather than a fabricated answer. That is
the honest state, and inventing a discipline to fill a table cell would be worse
than the gap.

## Premise shapes

**forecaster** — `By <date>, <observable> will <state>.`
Falsifier is the date arriving with the observable in another state.

**decision-model** — `Given <recurring situation>, <actor> chooses <A> over <B>.
Revealed by: <2+ completed decisions>. Violated by: <a future choice>.`
Never psychology: "X is loyal" admits no future observation that settles it.

**tracker** — `In <domain>, <signal A> moves before <signal B> by <lag>.`
Falsifier is B moving first, or the lag failing.

**classifier** — `Cases with <feature> belong to <class 1>, not <class 2>,
because <mechanism>.` Falsifier is a sorted case behaving like the other class.

**adversary** — `<Common belief> is wrong because <mechanism>. It would survive
if <specific observation>.` Its job is to be refutable by the thing it attacks.

## What the agentic pass asks, per kind

Every kind runs the same machinery — `model_watch --predict` and `--assess`,
web-grounded, citation-validated. What changes is the **question**:

- **forecaster** — "what do you expect, by when, and what would settle it?"
- **decision-model** — "has any COMPLETED, ANNOUNCED decision since this model
  was written conformed to or violated the ordering? Ignore stated intentions:
  the model's whole claim is that actions reveal what statements conceal."
- **tracker** — "did the leading signal move first this period, and by how much?"
- **classifier** — "did any case sorted by this model behave like the other class?"
- **adversary** — "did the belief under attack survive its named test?"

That framing is the pack's real content. The engine is shared; the question is
not.
