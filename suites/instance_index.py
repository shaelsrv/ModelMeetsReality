"""Generate INDEX.md — one map of everything in this instance.

An instance grows sideways by design: one model per theory, each its own sibling
repo. That is the right shape and it produces a directory listing nobody can
read. After thirty models there is no way to see what exists, which are real and
which are still scaffolds, or what has actually been graded.

GENERATED, never hand-written. Counts in a hand-maintained index rot — this
project has already shipped one stale hand-typed number to a live page. Every
figure here is read from the ledgers at build time.

    python -m suites.instance_index
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT.parent
OUT = WORK / "INDEX.md"


def model_row(slug: str) -> dict:
    d = WORK / slug
    md = d / "MODEL.md"
    row = {"slug": slug, "kind": "?", "open": 0, "graded": 0, "verdicts": Counter(),
           "seeded": False, "premises": 0}
    if md.exists():
        t = md.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"\*\*The kind:\*\*\s*(\S+)", t)
        if m:
            row["kind"] = m.group(1)
        # "SEEDED, NOT YET ESTABLISHED" marks a premise with the situation named
        # but no cited decisions behind it. That distinction is the honest half of
        # this index: a seeded model is a question, not a claim about the world.
        row["seeded"] = "SEEDED, NOT YET ESTABLISHED" in t
        row["premises"] = len(re.findall(r"\*\*P\d+ —", t))
    led = d / "predict" / "ledger.json"
    if led.exists():
        try:
            preds = json.loads(led.read_text(encoding="utf-8")).get("predictions", [])
        except ValueError:
            preds = []
        for c in preds:
            if c.get("status") == "graded":
                row["graded"] += 1
                row["verdicts"][c.get("verdict") or "?"] += 1
            else:
                row["open"] += 1
    return row


def build() -> None:
    try:
        fleet = json.loads((ROOT / "fleet.json").read_text(encoding="utf-8"))["models"]
    except Exception:
        fleet = []
    rows = [model_row(s) for s in fleet]
    by_kind: dict = {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)

    n_open = sum(r["open"] for r in rows)
    n_graded = sum(r["graded"] for r in rows)
    n_seeded = sum(1 for r in rows if r["seeded"])
    verdicts = Counter()
    for r in rows:
        verdicts.update(r["verdicts"])

    L = ["# This instance", "",
         f"**{len(rows)} models · {n_open} open claims · {n_graded} graded**"
         + (f" ({', '.join(f'{v} {k}' for k, v in verdicts.items())})" if verdicts else ""),
         ""]
    if n_seeded:
        L += [f"{n_seeded} of {len(rows)} models are **seeded** — the decision situation is "
              "named but no completed decisions are cited behind the premise yet. A seeded "
              "model is a question, not a claim about the world.", ""]

    for kind in sorted(by_kind):
        group = sorted(by_kind[kind], key=lambda r: r["slug"])
        L += [f"## {kind} ({len(group)})", "",
              "| model | premises | open | graded | |", "|---|---|---|---|---|"]
        for r in group:
            v = " ".join(f"{k}:{n}" for k, n in r["verdicts"].items())
            flag = "seeded" if r["seeded"] else ""
            L.append(f"| `{r['slug']}` | {r['premises']} | {r['open']} | "
                     f"{r['graded']} {v} | {flag} |")
        L.append("")

    # Corpora and documents that are not models but are part of the instance.
    extras = []
    for d in sorted(WORK.iterdir()):
        if not d.is_dir() or d.name in fleet or d.name.startswith(".") or d == ROOT:
            continue
        n = len(list(d.glob("*.json"))) + len(list(d.glob("*.md")))
        if n:
            extras.append((d.name, n))
    if extras:
        L += ["## Corpora and other directories", ""]
        for name, n in extras:
            L.append(f"- `{name}/` — {n} file(s)")
        L.append("")

    docs = sorted(p.name for p in WORK.glob("*.md") if p.name != "INDEX.md")
    if docs:
        L += ["## Documents", ""] + [f"- `{d}`" for d in docs] + [""]

    L += ["## Commands that work from here", "",
          "```bash",
          "cd " + ROOT.name + "                              # the engine",
          "python -m suites.event_history --build      # rebuild the event history",
          "python -m suites.instance_index             # rebuild this file",
          "python -m suites.model_watch --repo <slug> --predict   # register claims",
          "python -m suites.model_watch --repo <slug> --assess    # grade what is due",
          "python -m suites.compat_check               # all three install levels",
          "COCKPIT_PORT=8790 python -m ui.server       # the cockpit",
          "```", "",
          "_Generated by `suites.instance_index`. Every count is read from the "
          "ledgers at build time — do not edit by hand._"]

    OUT.write_text("\n".join(L), encoding="utf-8")
    print(f"  {len(rows)} models, {n_open} open, {n_graded} graded -> {OUT}")
    if n_seeded:
        print(f"  {n_seeded} seeded (premise named, no cited decisions yet)")


if __name__ == "__main__":
    build()
