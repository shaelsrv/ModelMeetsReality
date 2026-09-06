# Install test — clean instance, 10 models, host and Docker

**2026-09-06.** The template installed from scratch in an empty directory, ten
models scaffolded as separate git repos, each run through its own agentic web
search, then the same engine exercised in a container. Written down because four
of the five defects below only appear on a clean install — the working tree
hides them.

## Result

| | |
|---|---|
| Install per `SETUP.md` | works, after the fixes below |
| Models scaffolded | 10, each its own git repo, all registered in `fleet.json` |
| Models producing claims by own search | **9 / 10** |
| Dated claims registered | 18 (confidence 0.25–0.85, mean 0.62) |
| Compatibility levels passing | **3 / 3** (assistant, local, docker) |
| End-to-end to a listable card | yes — passes the Garden's licence gate |

The tenth was still mid-search when this was written; it had already failed and
been fixed once (see defect 4), so the honest number is 9 confirmed.

## What "its own reasoning" looked like

Each model reads its own `MODEL.md`, searches the live web through `:online`,
and writes claims that reference its own premises. It is genuinely per-model, not
one prompt with the domain swapped:

- **grid-load** cited NESO winter operational data against P3 (reinforcement
  lags peak growth). In the container it found Dutch heat-pump grid congestion
  with reinforcement deferred to 2035 — an unusually direct hit on that premise.
- **freight-rates** noticed that one of its own comparisons was *near-tautological*
  ("DAT linehaul is quoted ex-fuel by construction"), and said so instead of
  claiming support.
- **hiring-freeze** reported that the observations **do not test the model as
  designed**, because the freeze it found predated the window, and dropped its
  confidence to 0.4.
- **clinic-throughput** used medical-office-building occupancy (92.7%, completions
  down 26%) as evidence that estate rather than clinician-hours is the binding
  constraint — exactly its P1.

Self-criticism and calibration, not confirmation. That is the behaviour the
format is supposed to produce, and it survived a clean install.

## Five defects, all found by installing rather than assuming

**1. Five suites never loaded `.env`.** `model_watch`, `model_import`,
`substrate_map`, `review_untrusted`, `compat_check` all call `chat()` and none
called `_load_env()`. Following `SETUP.md` step 3 gave *"no key and no
claude-code backend"* while `.env` sat there correctly configured.
`grade_claims` has had the loader all along with a comment saying its absence
*"cost a debugging cycle"* — the fix existed and five callers never used it.

**2. The template's harness was 100 lines behind.** No `research` flag, no
citation capture, no `validate_citations`, no local-backend degradation. Found
by building the Docker image and importing a function that was not there. **The
container is built FROM this repo, so template drift is silently Docker drift.**

**3. `new_model` ships a placeholder entity, and nothing warns you.**
`watch.json` contains an entity literally named `"Example entity"`. On the
ten-model run, 2 models correctly refused to invent observations about a target
that does not exist — and **8 silently substituted a real entity of their own
choosing**. The improvising is the dangerous half: those claims look perfectly
fine and are about a target the author never picked. Now refused up front,
before a search is spent.

**4. A failed parse discarded the evidence.** `! unparseable` printed and the
response was thrown away — after paying minutes and money for it. The raw reply
is now written beside the ledger, and that is how defect 3 was actually
identified: the model had explained the problem clearly, in prose the parser
dropped on the floor.

**5. `git init` fails on this filesystem.** `fatal: detected dubious ownership`
on a fresh copy. Not a template bug, but every install on a non-ownership
filesystem hits it, and `SETUP.md` does not mention the one-line fix
(`git config --global --add safe.directory <path>`).

## Docker

Both tiers behave as documented.

- **`sandbox_import.sh`** (hardened: `--network=none`, no credential, no model)
  inspected a model repo offline, listed executable files, ran the injection
  scan, and wrote nothing without `--yes`.
- **`sandbox_agent.sh`** (weaker tier: network on, credential present) read a
  read-only mounted repo and correctly judged it a real falsifiable model rather
  than a stunt, reporting the injection scan alongside.
- **Full agentic loop in-container**: searched the web, returned **5 validated
  citations**, and `validate_citations` caught a fabricated URL mixed into the
  list. Harness parity with the host is now real rather than assumed.

## What is still not proven

- **Level 1 (paste into a live assistant) is `MANUAL`.** `compat_check` says so
  itself: *"a 'manual' row is not a pass… it is the level with the most users."*
  Not tested here.
- **Grading is untested.** Only `--predict` ran. `--assess` grades on the
  resolve date (2026-10-21) and nothing has resolved.
- **Local backends untested** — Ollama and LM Studio were not running, so those
  rows skipped rather than passed.
- One model's final run had not returned when this was written.

## Reproducing

```bash
cp -r copilot-template my-copilot && cd my-copilot
git config --global --add safe.directory "$PWD"   # see defect 5
git init && git add -A && git commit -m "main instance"
cp .env.example .env                              # set LLM_BACKEND
python -m suites.new_model my-model --title "..." --domain "..."
# then EDIT ../my-model/watch.json — the placeholder is refused (defect 3)
# and write real premises into MODEL.md; the scaffold is empty by design
python -m suites.model_watch --repo my-model --predict
python -m suites.make_use --model my-model --author you
python -m suites.make_tasks --model my-model --author you
python -m suites.tags --set my-model --scope national --inputs public-web \
    --sensitivity neutral --effort hours
python -m suites.make_card --model my-model --author you
```
