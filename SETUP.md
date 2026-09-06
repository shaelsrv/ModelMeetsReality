# Setup — from one copy to a fleet of models (and models of models)

The pattern: ONE copy of this repo becomes your **main** — the engine that runs
everything. Models are NOT edits to the main; each model is its own sibling repo the
main scaffolds, registers, and grades. One engine, many models, one shared record.

```
your-workspace/
  my-copilot/        <- MAIN: the engine (this repo, renamed). Suites + harness + fleet.json
  power-shifts/      <- a model (sibling repo, scaffolded by the main)
  my-industry/       <- another model
  my-own-modeling/   <- a META model (its subject: the two models above)
```

## 1. Copy the repo → make it your main

```bash
cp -r copilot-template my-copilot        # or: git clone <template-url> my-copilot
cd my-copilot
git config --global --add safe.directory "$PWD"          # if git says "dubious ownership"
git init && git add -A && git commit -m "main instance"   # version your engine from day one
cp .env.example .env
```

Your main is private infrastructure. Keeping it (and every model repo) **self-hosted,
local and private** is the recommended default — honesty is easiest where being wrong
costs nothing socially, and your theories about your own world belong on your own
machine. The friction is real; you will thank yourself for doing it. Publishing
anything is a separate, later decision.

## 2. Set it up in a harness (pick one, mix freely)

The LLM layer is pluggable via `LLM_BACKEND` in `.env`:

- **Claude Code / compatible assistant (no API key).** Set `LLM_BACKEND=claude-code`.
  Calls shell out to the `claude` CLI in print mode and bill the subscription you
  already pay for (Pro/Max weekly limits). Web-grounded steps (`:online`) use the
  CLI's WebSearch. This is the cheapest full setup.
- **Metered key.** Set `OPENROUTER_API_KEY`. One key, many models.
- **Fully local & private.** Point `OPENROUTER_BASE` at any OpenAI-compatible
  endpoint: Ollama (`http://localhost:11434/v1`), LM Studio, vLLM. Your theories,
  claims, and misses never leave your machine.

Then schedule the weekly loop in the same harness (Claude Code scheduled task, cron,
or Windows Task Scheduler):

```bash
python -m suites.grading_loop        # everything due, one pass; missing key = loud error
```

## 3. Spawn model repos from the main

Never write models inside the main. Scaffold siblings:

```bash
python -m suites.new_model power-shifts --title "Power Shifts" --domain "how authority moves in my industry"
```

This creates `../power-shifts/` (MODEL.md + watch.json + ledger skeletons) and
registers it in `fleet.json` — the single registry every suite reads. `git init` each
model repo too: the trajectory store reads your MODEL.md git history to attribute
results per model VERSION ("did v2 beat v1" becomes a query).

Write the MODEL.md the way you'd finally admit the theory to yourself: premises with
honest confidence tiers, FALSIFIABLE consequences, and a deletion clause you commit
to honoring. Then let it live:

```bash
python -m suites.model_watch --repo power-shifts --predict   # register dated claims
python -m suites.model_watch --repo power-shifts --assess    # grade what's due
python -m suites.trajectory                                  # the longitudinal record
python -m suites.postmortem --run                            # earned vs lucky, per hit
```

Repeat step 3 for every theory you carry. The fleet grows sideways; the main stays
clean.

## 4. Go meta — test the thinking of your thinking

A model's subject can be ANY theory — including your other models, and including
your modeling itself. The harness doesn't distinguish; the ledgers work at every
level. The ladder, concretely:

- **Level 0:** a model of the world (`power-shifts` predicts events).
- **Level 1:** a model of your models. Scaffold `my-own-modeling` and give it
  premises about level 0: "my confidence calibrates worse in domain X than Y",
  "my models' misses cluster on de-escalation", "my v2 revisions beat my v1s".
  Its evidence is your own trajectory store and postmortems — data you already
  accumulate; its claims are graded by the same weekly loop.
- **Level 2 and up:** a model of your revision process ("when a model of mine dies,
  my replacement overcorrects"), graded against the level-1 record. And so on —
  each level is falsifiable against the ledgers of the level below, so the
  recursion stays honest instead of becoming philosophy.

Two ready-made meta-suites help at level 1: `suites/classify.py` (annotate every
claim's structural signature, then check which signatures you're actually good at)
and `suites/hindsight_audit.py` (would your model have seen X coming — audited
against criteria, not memory).

The stop rule, so recursion serves you instead of consuming you: only add a level
when the level below has GRADED rows for it to explain. A meta-model over an empty
ledger is procrastination with extra steps.

## 5. New worlds = new instances (optional)

For a genuinely separate domain (work vs personal, or another person's worldview),
copy the template again into a second MAIN with its own fleet, rather than mixing
fleets in one registry. Instances share nothing; that isolation is a feature.
