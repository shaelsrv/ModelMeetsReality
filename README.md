# Copilot Template — a model-research harness, clean

A reusable instance of the model-copilot pattern: build falsifiable models of anything,
run them as forecasting instruments against reality, grade them on schedule, and keep a
version-attributed trajectory of how each model performs. This template ships ALL the
machinery and NO data: instantiate it, add your own models, accumulate your own record.

## Instantiate

1. Copy this directory to a new name (your instance).
2. `cp .env.example .env` and set `OPENROUTER_API_KEY`.
3. Scaffold your first model:
   `python -m suites.new_model my-model --title "My Model" --domain "what it models"`
   (creates a sibling directory `../my-model/` with MODEL.md + watch.json skeletons and
   registers it in `fleet.json` — the single registry every suite reads).
4. Write the MODEL.md: premises with honest confidence tiers, and FALSIFIABLE
   consequences — a model that cannot lose is notation, not theory.

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
