"""Prove a claim's criteria were frozen before its outcome — from git history.

This is the second provenance tier, made reachable without a resolver, without
the operator, and without anyone's judgment.

`self-graded` means the author counted their own rows. `criteria-frozen` means
something stronger and checkable: **the claim and its resolution criteria were
committed before the resolve date**, so the author could not have known the
outcome when they wrote the test. Git's commit history is the evidence. Nobody
has to be trusted for it, and nobody has to be paid to check it.

What this does NOT do — deliberately:

  It does not say the claim is TRUE. A frozen claim can still be graded by its
  author, and a dishonest author can still mark it however they like. Freezing
  proves the TEST was fixed in advance, not that the VERDICT is right. That is
  the whole distance between tier two and tier three, and pretending otherwise
  would be the fraud this system exists to detect.

Why it matters anyway: a claim whose criteria were written after the fact is
unfalsifiable in practice, however honest its author. Freezing is the cheapest
real thing a registry can verify about someone else's model.

    python -m suites.freeze_check --model my-predictions
    python -m suites.freeze_check --all
    python -m suites.freeze_check --repo ../some-clone --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.fleet import ROOT, MODELS_DIR  # noqa: E402

LEDGERS = ("predict/ledger.json", "predict/live_ledger.json",
           "signals/signal_ledger.json")


def _git(args: list, cwd: Path) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                           text=True, timeout=60)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _first_commit_date(repo: Path, rel: str) -> str | None:
    """When this file first appeared. The earliest date its claims can be from.

    `--follow` so a renamed ledger keeps its history: a rename is not a reset,
    and treating it as one would silently un-freeze every claim in the file.
    """
    out = _git(["log", "--follow", "--reverse", "--format=%ad", "--date=short",
                "--", rel], repo)
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return lines[0] if lines else None


def _rows(repo: Path, rel: str) -> list:
    f = repo / rel
    if not f.exists():
        return []
    try:
        d = json.load(f.open(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = d.get("predictions", d) if isinstance(d, dict) else d
    return [r for r in rows if isinstance(r, dict)]


def check(repo: Path) -> dict:
    """Per-claim freeze status for one model repo."""
    if not (repo / ".git").exists() and not _git(["rev-parse", "--git-dir"], repo):
        return {"repo": repo.name, "error": "not a git repo — freezing is "
                                            "unprovable without commit history"}

    claims, frozen, unfrozen, unprovable = [], 0, 0, 0
    for rel in LEDGERS:
        rows = _rows(repo, rel)
        if not rows:
            continue
        first = _first_commit_date(repo, rel)
        for r in rows:
            cid = r.get("id") or (r.get("claim") or "")[:40]
            resolve_by = r.get("resolve_by")
            has_criteria = bool(r.get("resolution_criteria") or r.get("criteria"))

            if not first:
                status, why = "unprovable", "file has no commit history"
            elif not resolve_by:
                status, why = "unprovable", "claim has no resolve_by date"
            elif not has_criteria:
                # Criteria are the test. A dated claim with no criteria has
                # nothing to freeze — it can be reinterpreted at resolution.
                status, why = "unfrozen", "no resolution criteria to freeze"
            elif first < resolve_by:
                status, why = "frozen", f"committed {first}, resolves {resolve_by}"
            else:
                status, why = ("unfrozen",
                               f"first committed {first}, on/after its own "
                               f"resolve date {resolve_by} — the outcome could "
                               f"already have been known")
            claims.append({"id": cid, "status": status, "why": why,
                           "resolve_by": resolve_by, "ledger": rel})
            frozen += status == "frozen"
            unfrozen += status == "unfrozen"
            unprovable += status == "unprovable"

    n = len(claims)
    # The TIER is a property of the whole card, so it is the weakest link: one
    # unfrozen claim means the record as a whole is not criteria-frozen. A tier
    # that averaged would let an author bury a back-dated claim in a pile of
    # good ones.
    tier = "self-graded"
    if n and frozen == n:
        tier = "criteria-frozen"
    return {"repo": repo.name, "n": n, "frozen": frozen, "unfrozen": unfrozen,
            "unprovable": unprovable, "tier": tier, "claims": claims}


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Prove claims were committed before their resolve date.")
    ap.add_argument("--model")
    ap.add_argument("--repo", help="path to any model repo (e.g. a clone)")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="list every claim")
    a = ap.parse_args()

    repos = []
    if a.repo:
        repos = [Path(a.repo)]
    elif a.all:
        cfg = json.load((ROOT / "fleet.json").open(encoding="utf-8"))
        repos = [MODELS_DIR / s
                 for s in sorted(set(cfg.get("models", []) + cfg.get("classifiers", [])))]
    elif a.model:
        repos = [MODELS_DIR / a.model]
    else:
        ap.print_help()
        return

    out = []
    for repo in repos:
        if not repo.exists():
            continue
        out.append(check(repo))

    if a.json:
        print(json.dumps(out, indent=1))
        return

    for d in out:
        if d.get("error"):
            print(f"  {d['repo']:<26} {d['error']}")
            continue
        print(f"  {d['repo']:<26} {d['tier']:<16} "
              f"{d['frozen']}/{d['n']} frozen"
              + (f", {d['unfrozen']} unfrozen" if d["unfrozen"] else "")
              + (f", {d['unprovable']} unprovable" if d["unprovable"] else ""))
        if a.verbose:
            for c in d["claims"]:
                print(f"      [{c['status']:<10}] {c['id'][:46]:<46} {c['why']}")

    elig = sum(1 for d in out if d.get("tier") == "criteria-frozen")
    print(f"\n  {elig} of {len(out)} repo(s) qualify for criteria-frozen.")
    print("  Frozen means the TEST was fixed before the outcome — not that the")
    print("  verdict is right. Only independent resolution shows that.")


if __name__ == "__main__":
    main()
