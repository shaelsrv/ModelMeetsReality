"""Stamp one starter repo per model kind, from the shared discipline packs.

WHY THESE ARE THIN. The engine -- harness, suites, docker, ledger format -- is
identical across all eleven kinds. Only the discipline differs. Eleven repos each
carrying a copy of the engine would be eleven copies to drift apart, and this
project has already paid for that: the shareable template shipped a harness 100
lines behind the one actually in use, and the cockpit lived only in a scratch
directory while a HANDOFF doc referenced it.

So each stamped repo carries its KIND (the discipline, the premise shape, the
falsifier, the agentic frames) and PINS the engine by commit rather than copying
it. One engine, eleven disciplines.

    python scripts/stamp_kind_repos.py --out ../kind-repos
    python scripts/stamp_kind_repos.py --out ../kind-repos --push
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "suites" / "kinds" / "packs.json"
ENGINE_URL = "https://github.com/shaelsrv/ModelMeetsReality"

GITATTRIBUTES = """# Shell scripts keep LF: they run in Linux containers.
*.sh text eol=lf
Dockerfile text eol=lf
*.Dockerfile text eol=lf
"""


def engine_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def readme(kind: str, pack: dict, commit: str) -> str:
    tier = pack.get("tier", "designed")
    warn = pack.get("warning")
    banned = pack.get("banned")
    scope = pack.get("scope")
    return f"""# {kind} — a Model Meets Reality starter

**{pack.get('one_line','')}**

A *model* here is not neural weights. It is a short document stating premises, a
mechanism, at least one falsifiable consequence with a date, and a deletion
clause naming when you would retire it. This repo is a starting point for one of
the eleven kinds.

## What makes this kind a kind

**Premise shape**

```
{pack.get('premise_shape','')}
```

**What would prove it wrong:** {pack.get('falsifier','')}

{'> **' + warn + '**' if warn else ''}
{'**Banned:** ' + banned if banned else ''}
{'**Scope:** ' + scope if scope else ''}

**Tier: {tier.upper()}** — {'a discipline worked out against real instances.' if tier == 'proven' else 'the falsifier question is stated; no instance has been built yet. Treat the discipline as a proposal, not a settled rule.'}

## Agentic reasoning

Models here are not static documents. The engine runs each one against live
sources on a schedule: it searches, reads what it finds, and writes dated claims
that later get graded. Every citation is validated against what the search
actually returned, so a fabricated source is dropped rather than recorded.

What the pass asks is specific to this kind:

> {pack.get('predict_frame','')}

And when a claim comes due:

> {pack.get('assess_frame','')}

## Start

```bash
git clone {ENGINE_URL} my-copilot   # the engine (anonymous clone, no gh CLI needed)
cd my-copilot
git config --global --add safe.directory "$PWD"   # if git says "dubious ownership"
git init && git add -A && git commit -m "main instance"
cp .env.example .env      # set OPENROUTER_API_KEY, or LLM_BACKEND=claude-code

python -m suites.new_model my-model --kind {kind} \\
    --title "My Model" --domain "what it models, in a sentence"

# then EDIT ../my-model/watch.json -- the scaffold placeholder is refused
# and write real premises into MODEL.md; the scaffold is empty by design
python -m suites.model_watch --repo my-model --predict
```

The engine refuses to run against the scaffold placeholder, on purpose: running
it as-is spends a web search and returns either nothing or claims about a target
you did not choose.

## Engine

Pinned to `{commit}` of [{ENGINE_URL.rsplit('/',1)[1]}]({ENGINE_URL}). The engine
is shared across all eleven kinds; only the discipline above differs. Update
deliberately rather than tracking latest.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="../kind-repos")
    ap.add_argument("--only", help="one kind, for testing")
    a = ap.parse_args()

    packs = json.loads(PACKS.read_text(encoding="utf-8"))["packs"]
    commit = engine_commit()
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=True)

    made = []
    for kind, pack in packs.items():
        if a.only and kind != a.only:
            continue
        d = out / f"mmr-{kind}"
        d.mkdir(exist_ok=True)
        (d / "README.md").write_text(readme(kind, pack, commit), encoding="utf-8")
        (d / "KIND.json").write_text(
            json.dumps({"kind": kind, "engine": ENGINE_URL, "engine_commit": commit,
                        **pack}, indent=1, ensure_ascii=False), encoding="utf-8")
        (d / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")
        for src in ("LICENSE",):
            if (ROOT / src).exists():
                (d / src).write_text((ROOT / src).read_text(encoding="utf-8"),
                                     encoding="utf-8")
        made.append((kind, pack.get("tier"), d))

    for kind, tier, d in made:
        print(f"  {kind:16s} {tier:8s} -> {d.name}")
    print(f"\n  {len(made)} kind repo(s) stamped, engine pinned to {commit}")


if __name__ == "__main__":
    main()
