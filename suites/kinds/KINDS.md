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

## Creating your own kind

**The eleven are a starting set, not a taxonomy.** They are the kinds that came
up first, and five of them earned their discipline against real models. Nothing
claims the list is complete — a domain you know well may need a kind nobody here
has written.

A kind is not a category or a topic. It is **a claim about what would falsify a
whole class of model**. If you cannot state the falsifier for the class, you have
a subject area, not a kind — write a model instead.

Define yours in `suites/kinds/my_kinds.json`. It is gitignored, read *before* the
shipped packs, and wins on a name collision — so an engine update never
overwrites it, and you can also sharpen one of the eleven without editing a
shipped file.

```json
{
  "packs": {
    "your-kind": {
      "tier": "designed",
      "one_line": "what this class of model does, in a few words",
      "premise_shape": "The sentence every premise of this kind fills in.",
      "falsifier": "what would show a model of this kind is wrong",
      "predict_frame": "What the agentic pass should look for. Be specific about what to IGNORE -- that is usually where the discipline lives.",
      "assess_frame": "What question settles a claim of this kind when its date arrives.",
      "banned": "optional -- the move that would make this kind unfalsifiable",
      "scope": "optional -- where this kind does and does not apply",
      "warning": "optional -- shown when the discipline is not yet proven"
    }
  }
}
```

Then use it like any other:

```bash
python -m suites.new_model my-model --kind your-kind --title "..." --domain "..."
```

An unknown kind still scaffolds — the engine will not stop you — but it prints a
notice and produces a model with no premise shape, no falsifier and an empty
agentic frame. That is a model with a label, not a kind.

**Three tests before you call it a kind:**

1. **The falsifier is about the class, not one model.** "Wrong when the leading
   signal stops leading" is a kind. "Wrong when interest rates fall" is a model.
2. **The ban is load-bearing.** Most good kinds forbid something tempting. The
   decision-model bans psychology, because "X is ruthless" admits no observation
   that settles it. What does yours refuse to let you say?
3. **`predict_frame` names what to ignore.** The instruction that makes a kind
   work is usually a *restriction* — ignore rumour, ignore stated intent, ignore
   the cases you sorted correctly.

Start with `tier: "designed"`. Promote to `"proven"` only after a real model of
that kind has been graded and the discipline survived contact — the same rule
the shipped eleven are held to, where six are still `designed` and two ship with
their falsifier question openly unresolved.
