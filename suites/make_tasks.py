"""Generate TASKS.md — recurring prompts that run a model on a schedule.

USE.md gets a model running in one conversation. This is the other half: the
model running *over time*, in whatever scheduled-task feature the reader's
assistant provides (ChatGPT Tasks, Claude's scheduling, or a calendar reminder
and a paste).

A model that only answers when asked is a reference book. A model that reports
on a schedule is an instrument — and the difference matters most for exactly the
kinds here that are about change: trackers, timers, forecasters.

## The discipline is copied from the local runner, not invented

`model_watch.py` runs these models locally as OBSERVE → MODEL READ → PREDICT,
and the scheduled prompts carry the same shape. A task that produced softer
output than the local runner would quietly train the reader to expect less of
the model than it demands of itself. Specifically, every generated task keeps:

  * **observe first, with dates and sources** — no reasoning from memory
  * **contradictions are the valuable output** — a task that only ever confirms
    the model is a horoscope with a schedule
  * **falsifiable, dated predictions** — an unresolvable claim is not a claim
  * **a quality bar** — no base-rate-certain events; a good prediction is one a
    smart skeptic might bet against
  * **a recency guard** — search surfaces old stories that read as current; the
    citizen-copilot tasks learned this the hard way and say so explicitly

## Self-contained, always

Each task must run with no project files, no memory of prior chats, and no
output from another task. A scheduled prompt that depends on context the
scheduler does not carry will fail silently weeks later, reporting confidently
from nothing.

    python -m suites.make_tasks --model window-timer --author shaelsrv
    python -m suites.make_tasks --all --author shaelsrv
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.fleet import ROOT, MODELS_DIR  # noqa: E402

# What a recurring run of each kind should actually DO, and how often. A
# forecaster on a daily schedule produces noise; a tracker on a quarterly one
# misses the thing it exists to catch.
KIND_TASKS = {
    "forecaster": [
        ("Standing forecast", "weekly",
         "make 1-2 dated, falsifiable predictions from what changed this week"),
        ("Resolution check", "monthly",
         "check predictions whose date has passed and grade them honestly"),
    ],
    "tracker": [
        ("Movement watch", "weekly",
         "report whether the thing being tracked moved, and past which threshold"),
        ("Resolution check", "monthly", "grade any threshold calls that resolved"),
    ],
    "timer": [
        ("Window read", "weekly",
         "say whether the window is opening, open, or closing — and what would change that"),
    ],
    "classifier": [
        ("New cases", "weekly",
         "find new cases in the domain and classify them by this model's categories"),
    ],
    "tracer": [
        ("Chain check", "monthly",
         "take one recent outcome and trace it back through the mechanism"),
    ],
    "finder": [
        ("Candidate sweep", "weekly",
         "surface new instances of the pattern, with why each fits"),
    ],
    "generator": [
        ("Draw", "weekly", "produce new candidates from the mechanism"),
    ],
    "attributor": [
        ("Cause review", "monthly",
         "take a recent outcome and weigh the competing explanations"),
    ],
    "adversary": [
        ("Counter-case", "weekly",
         "attack the strongest current consensus in this domain"),
    ],
    "mirror": [
        ("Reflection", "monthly",
         "review the period's reasoning and reflect its shape back"),
    ],
}

COMMON_RULES = """- OBSERVE FIRST. Search for what actually happened. Cite 2-4 concrete items
  with dates and sources. Do not reason from memory.
- RECENCY GUARD. Date-stamp every item and include only what falls in the
  window. Search surfaces older stories that look current — if an item is older
  or undated, drop it or label it clearly. Never present old news as new.
- READ IT THROUGH THIS MODEL ONLY. If the mechanism has little grip on what you
  found, say so plainly rather than stretching it. A stretched reading is how a
  model becomes a horoscope.
- CONTRADICTIONS ARE THE VALUABLE OUTPUT. If the observations cut against the
  model, lead with that. A report that only ever confirms is not measuring
  anything.
- SEPARATE what the model says from what you are guessing. Label the guesses.
- NO CERTAINTY IT HAS NOT EARNED. This model's public record is counts of claims
  made and graded — not a score, and not evidence it is right."""


def _one_line(s, cap: int) -> str:
    """Flatten and cap a short author-controlled field.

    A custom task's name and description are written into a prompt a stranger
    pastes into their assistant, so they must not carry structure: collapsing
    whitespace kills multi-line payloads and fake-heading tricks, and the cap
    kills the rest.
    """
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    s = s.replace("<<<", "").replace(">>>", "").replace("```", "")
    return s if len(s) <= cap else s[:cap].rstrip() + "…"


def _section(md: str, heading: str) -> str:
    m = re.search(rf"^##\s*{heading}.*?$(.*?)(?=^##\s|\Z)", md, re.I | re.M | re.S)
    return (m.group(1).strip() if m else "")


def build(slug: str, author: str) -> tuple[str, list]:
    repo = MODELS_DIR / slug
    mm = repo / "MODEL.md"
    if not mm.exists():
        raise SystemExit(f"no MODEL.md at {repo}")
    md = mm.read_text(encoding="utf-8", errors="replace")
    warn = []

    card = {}
    cf = repo / "model.json"
    if cf.exists():
        try:
            card = json.load(cf.open(encoding="utf-8"))
        except (OSError, ValueError):
            pass

    title = card.get("title") or slug.replace("-", " ").title()
    kind = card.get("kind") or "forecaster"
    mech = _one_line(card.get("mechanism"), 240)
    title = _one_line(title, 80)
    repo_url = card.get("repo") or f"https://github.com/{author}/{slug}"
    # A model may CHOOSE its tasks rather than inherit them from its kind.
    # tasks.json in the repo is that choice, and it lives in the repo (not in
    # the cockpit) so the selection travels with a Garden submission or an
    # import, the same way tags.json does.
    #
    # Absent tasks.json, output is byte-identical to the kind default. That is a
    # hard requirement, not a nicety: publish_model regenerates TASKS.md on
    # every publish, so any drift here would churn every repo that never opted
    # in — and a user's dragged selection would die silently on the next push,
    # which is worse than having no picker at all.
    tasks = None
    sel_file = repo / "tasks.json"
    if sel_file.exists():
        try:
            sel = json.load(sel_file.open(encoding="utf-8"))
        except (OSError, ValueError):
            sel = {}
            warn.append("tasks.json is unreadable; fell back to the kind default")
        chosen = []
        by_id = {f"{k}:{t[0]}": t for k, v in KIND_TASKS.items() for t in v}
        for tid in sel.get("selected", []):
            if tid in by_id:
                chosen.append(by_id[tid])
            else:
                warn.append(f"unknown task template '{tid}' — skipped")
        for c in sel.get("custom", []):
            # Custom tasks are a (name, cadence, does) triple, never freeform
            # prompt text. The generator wraps them in the same STEP 1/2/3 and
            # COMMON_RULES scaffold, so a task added through the UI carries the
            # same discipline as a built-in one. A freeform prompt box would be
            # the one hole in that.
            #
            # Sanitised HERE, not only at the cockpit endpoint. An IMPORTED
            # repo brings its own tasks.json, publish_model regenerates from
            # it, and neither path touches /api/runs — so a check that lived
            # only in the endpoint would be bypassed by exactly the case that
            # matters: a stranger's model.
            nm = _one_line(c.get("name"), 60)
            ds = _one_line(c.get("does"), 200)
            cd = _one_line(c.get("cadence"), 20) or "weekly"
            if nm and ds:
                chosen.append((nm, cd, ds))
            elif c.get("name") or c.get("does"):
                warn.append("a custom task was dropped: name or description "
                            "was empty after sanitising")
        if chosen:
            tasks = chosen
        elif sel:
            warn.append("tasks.json selected nothing usable; used the kind default")

    if tasks is None:
        tasks = KIND_TASKS.get(kind, KIND_TASKS["forecaster"])
        if kind not in KIND_TASKS:
            warn.append(f"kind '{kind}' has no task template; used forecaster's")

    consequences = _section(md, "Falsifiable consequences")
    if not consequences:
        warn.append("no falsifiable consequences — scheduled runs will have "
                    "nothing to hold their own claims against")

    # "over the last week period" is what naive suffix-stripping produces; say
    # the window in words a person would use.
    WINDOW = {"weekly": "7 days", "monthly": "30 days",
              "quarterly": "90 days", "daily": "24 hours"}

    blocks = []
    for i, (name, cadence, does) in enumerate(tasks, 1):
        window = WINDOW.get(cadence, cadence)
        blocks.append(f"""### Task {i} — {name}

**Answers:** {does}
**Suggested cadence:** {cadence}

```text
You are running the model "{title}" ({repo_url}) as a standing instrument.
Its mechanism: {mech}

You have web access. Today's date is whatever today is — do not assume.

STEP 1 — OBSERVE. Search for what has actually happened in [SUBJECT] over the
last {window}. Cite 2-4 concrete items with dates and sources.

STEP 2 — MODEL READ. Which of this model's mechanisms do those observations
engage, and what does the model infer? If the observations CONTRADICT the model,
say so plainly and lead with it.

STEP 3 — {name.upper()}. {does[0].upper() + does[1:]}. Each claim must name what
observable settles it and by what date. QUALITY BAR: nothing base-rate-certain —
a good claim is one a smart skeptic might bet against.

Rules:
{COMMON_RULES}

Keep it under 400 words. Open with the content, not a title or a preamble.
```

Replace `[SUBJECT]` with what you want watched before saving the task.
""")

    doc = f"""# Scheduled tasks for {title}

USE.md gets this model running in one conversation. These run it **over time**.

A model that only answers when asked is a reference book. On a schedule it is an
instrument — which matters most for the kinds that are about change.

## How to install these

**If your assistant supports scheduled tasks** (ChatGPT Tasks, Claude
scheduling): create a task, paste one prompt block below, set the cadence, edit
`[SUBJECT]` to what you want watched.

**If it does not:** these work pasted by hand. Put a recurring reminder in your
calendar and paste the block when it fires. Nothing here depends on files,
memory, or a previous run — that is deliberate. A scheduled prompt that relies
on context the scheduler does not carry will fail silently weeks later, still
reporting confidently from nothing.

**Approval:** an assistant should show you the exact task name, schedule and
prompt before creating anything, and wait. If it creates recurring tasks without
asking, stop — that is not how this is meant to work.

---

{chr(10).join(blocks)}
---

## What these will not do

They will not tell you the model is right. Each run states what would falsify
its own claims, and a run that finds the model contradicted is doing its job.

They will not act for you, send anything anywhere, or persist beyond the
assistant you paste them into.

Source: {repo_url} · [Model Garden](https://modelmeetsreality.xyz/modelgarden/)
"""
    return doc, warn


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate TASKS.md for model repos.")
    ap.add_argument("--model")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--author", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    slugs = []
    if a.all:
        cfg = json.load((ROOT / "fleet.json").open(encoding="utf-8"))
        slugs = sorted(set(cfg.get("models", []) + cfg.get("classifiers", [])))
    elif a.model:
        slugs = [a.model]
    else:
        ap.print_help()
        return

    n = 0
    for s in slugs:
        if not (MODELS_DIR / s / "MODEL.md").exists():
            continue
        doc, warn = build(s, a.author)
        n += 1
        ntasks = doc.count("### Task ")
        print(f"  {s:<26} {ntasks} task(s), {len(doc)} chars"
              + (f"  ({len(warn)} warning)" if warn else ""))
        for w in warn:
            print(f"      - {w}")
        if not a.dry_run:
            (MODELS_DIR / s / "TASKS.md").write_text(doc, encoding="utf-8")
    print(f"\n  {'(dry run) ' if a.dry_run else ''}{n} TASKS.md written")


if __name__ == "__main__":
    main()
