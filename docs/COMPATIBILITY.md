# Every change must work at every level

There are three ways someone runs a model from this system, and they share
almost nothing. A change that works locally can be silently broken for the
largest audience, because that audience runs nothing you can watch.

Run `python -m suites.compat_check` before calling a change done. It is not a
checklist — a checklist would drift, the way this document would on its own.

---

## The three installation levels

### 1. ASSISTANT — no install at all

Someone pastes `USE.md` into ChatGPT, Claude, or Gemini. No Python, no clone, no
Docker. **The largest audience and the easiest to break without noticing**,
because nothing executes here to tell you it failed.

What must hold:

- every model ships `USE.md` and `TASKS.md`
- `USE.md` still **fences** the author's sections — if a regeneration ever drops
  the `QUOTED VERBATIM` markers, the paste-in path becomes injectable again and
  no local or docker test would catch it
- the prompt still behaves in a real assistant

The last one **cannot be automated**. `compat_check` reports it as `MANUAL`, not
as a pass. Verifying it means opening a session and pasting.

### 2. LOCAL — the suites on the host

Python, a clone, the cockpit. What must hold: the offline spine runs —
`import_model`, `legitimacy_audit`, `freeze_check`, `make_card`, `make_use`,
`make_tasks`. None of these needs a model or a network, and that property is
what makes level 3 possible.

### 3. DOCKER — sandboxes for untrusted content

Two images, deliberately unequal:

| | network | credential | model |
|---|---|---|---|
| `mmr-sandbox` | **none** | none | none |
| `mmr-agent` | on | one | one |

What must hold: both Dockerfiles present, both wrapper scripts valid **as
`bash` reads them** (see the line-endings trap below), and the import sandbox's
`--network=none` still genuinely blocking.

---

## The three model backends

Applies to levels 2 and 3.

| backend | credential | leaves the machine |
|---|---|---|
| **local** — Ollama, LM Studio | none | no |
| **openrouter** — hosted API | single-purpose key | yes |
| **claude-code** — the CLI | API key; `--bare` never reads OAuth or keychain | yes |

Local is listed first because it is strictly the strongest: nothing to leak,
nothing to intercept. A key is required **only** for a remote endpoint —
pointing `OPENROUTER_BASE` at localhost is itself the statement that no
credential is involved.

Three namespaces, and mixing them 404s rather than degrading:

- `claude-code` wants a bare family name (`sonnet`)
- OpenRouter wants a vendor slug (`anthropic/claude-sonnet-4`)
- a local server has **neither** — it serves whatever was pulled

So local endpoints are **asked** what they have via `/v1/models` rather than
guessed at.

---

## Traps this has actually hit

Each was found by running the checker, not by reading code:

**CRLF line endings.** Git's autocrlf rewrote `scripts/*.sh` to CRLF, which
makes bash fail with `syntax error near unexpected token $'in\r'` — and the same
file then breaks inside a Linux container, where these actually run.
`.gitattributes` pins `*.sh` and Dockerfiles to LF.

**Windows paths into Git Bash.** Three wrong forms, three different failures:
backslashes read as escapes (`scripts\x.sh` → `scriptsx.sh`), drive letters
unknown (`F:/...`), and even `/f/...` failing from a spawned shell while working
interactively. The checker runs `bash -n` from the script's own directory with a
bare filename.

**`localhost` inside a container** is the *container*, not your machine. The
wrappers rewrite it to the docker-host alias — otherwise a working local model
looks broken.

**A cloud model slug against a local server** is a 404, not a fallback.

---

## What a green run does not mean

`compat_check` reports `MANUAL` for the pasted-prompt path and `skip` for
anything not installed here. Neither is a pass:

- **`skip` means unverified**, not working. LM Studio is compatible by
  construction and has never been run here; Ollama has been tested against real
  GPU hardware. Those are different claims and the doc keeps them apart.
- **`MANUAL` means a human has to look.** The level with the most users is the
  one no test can reach.
