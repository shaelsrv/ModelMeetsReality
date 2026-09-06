# ModelMeetsReality (MMR) — the engine

Build falsifiable models of anything, run them as instruments against reality, grade
them on a date you set in advance, and keep a version-attributed record of how each one
performs. This repo ships ALL the machinery and NO data: copy it, add your own models,
accumulate your own record.

A **model** here is not neural weights. It is a short document stating premises, a
mechanism, at least one falsifiable consequence with a date, and a deletion clause
naming when its author would retire it. The engine scaffolds those, runs them against
live sources, and grades them when the date arrives.

Runs three ways — pasted into an assistant with no install, as suites on your machine,
or in a container. See `docs/COMPATIBILITY.md`.

## Start here (five minutes)

1. Copy this directory to a new name — that copy is your instance.
2. `cp .env.example .env`. Then either set `OPENROUTER_API_KEY`, or set
   `LLM_BACKEND=claude-code` to use the `claude` CLI you already have. No API
   key is needed on that backend.
3. **Pick a starter model** — you do not need a theory of anything to begin:

       python -m suites.starter --list
       python -m suites.starter --new B1

   Fourteen starters in three tiers, each phrased as a question you already ask
   ("I think this is going to happen — am I right?"). See `starters/README.md`.
   If you take only three: **B1, B3, then I2**.
4. Open the new `MODEL.md`, make the specifics yours, and register your first
   claim with a date and a way to score it.
5. **Open the cockpit** to see everything in one place:

       python ui/server.py            # http://127.0.0.1:8787

   Home shows what is due and what changed; the **+** button (or `c`) registers
   a claim; Verdict answers "am I actually any good at this?"; search runs over
   everything the instance knows.

Writing a model from scratch instead: `python -m suites.new_model my-model
--title "My Model" --domain "what it models" --level 0`. It lands in this
instance's own `models/` directory when `fleet.json` sets `models_dir`, and is
registered on the map automatically.

Install nothing to start — the suites and cockpit are stdlib-only. See
`requirements.txt` for the two optional extras (local semantic search, YouTube
transcripts).

## The loop

- `python -m suites.model_watch --repo my-model --predict` — observe (web) + predict:
  falsifiable claims with resolution criteria and dates, into the model's ledger.
- `python -m suites.model_watch --repo my-model --assess` — grade due claims (web).
- `python -m suites.grading_loop` — everything due, across the whole fleet, one pass
  (schedule it weekly; a missing API key is fatal, never a silent no-op).
- `python -m suites.substrate_map --repo my-model` — the model's substrates and
  historical emergent patterns (precedented vs novel-regime predictions).
- `python -m suites.trajectory` — the longitudinal store: every graded claim, keyed by
  model VERSION (from your git history of MODEL.md), so "did v2 beat v1" is a query.
- `python -m suites.postmortem --run` — why correct / why wrong per graded claim;
  earned vs LUCKY hits split; lessons feed back into the model's next rounds.

## Modeling people (optional)

- `harness/ingest_youtube.py`, `ingest_substack.py`, `ingest_doc.py` — build corpora.
- `python -m suites.model_import` — extract an analyst's CLAIMS into graded ledgers,
  one parallel model per mechanism (a person is not one model).
- `python -m suites.worldview --build ...` — model a person's WORLDVIEW: premises at
  their confidence tiers, mechanisms, power-dynamics reasoning; consistency audit
  across dated pieces; then EXTRAPOLATE their model into domains they have not
  addressed and grade the extrapolations (labeled as your model of their model, never
  as their claims) — the validity test for a model of a mind.
- `python -m suites.gather_evidence` + `grade_claims` — evidence-gated grading with
  the unresolvable / insufficient / not-yet-looked distinction kept honest.


## Harness compatibility — run on what you already pay for

The LLM layer is pluggable (`LLM_BACKEND` env):

- `openrouter` (default) — one API key, many models. `OPENROUTER_BASE` accepts ANY
  OpenAI-compatible endpoint: Ollama (`http://localhost:11434/v1`), LM Studio, vLLM,
  OpenAI itself — so a local GPU or an existing OpenAI account works unchanged.
- `claude-code` — no API key at all: calls shell out to the `claude` CLI in print
  mode, billing your EXISTING Claude subscription (Pro/Max weekly limits). `:online`
  model suffixes map to the CLI's WebSearch tool. Set `LLM_BACKEND=claude-code` and
  every suite — watches, grading, classifiers, postmortems, worldviews — runs on the
  limits you already have. Non-Anthropic model slugs run as sonnet on this backend.

Mix freely: e.g. weekly loop on claude-code, big backtests on a metered key.

## Disciplines baked in

Pre-registration before grading; criteria before outcome; confidence is earned, never
conferred; contamination self-reports on backfills; append-only ledgers; errors must
never masquerade as low counts. Read the docstrings — the rules live in the code.
