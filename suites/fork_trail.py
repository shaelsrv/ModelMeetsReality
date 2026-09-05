"""Fork provenance — did anyone TAKE this model and work on it?

A fork is not a popularity count. It is an event with a trail: who forked, when
their account was created, and — the part that matters — whether the fork ever
**diverged** from the parent. A fork that never diverged is a bookmark. A fork
with commits of its own is somebody doing something with the model.

That distinction is why this exists at all, and it came from an operator
argument that overturned part of a rule these models had written: forks carry
inspectable provenance in a way a star count cannot.

## What this is NOT, and the reasoning is load-bearing

**Never a rank, a sort key, a size, a colour, or a "top" label.** A fork count
is still a platform-observable number, and the objection that sank stars applies
undiminished here: whichever number occupies the display slot becomes the
vocabulary outsiders repeat. This is card metadata — a fact about the repo, like
its licence.

**Never a quality signal.** A diverged fork says someone worked on the model. It
says nothing about whether the model is right. Only grading says that.

**The filter is deliberately NOT a published threshold.** The adversary lens made
the sharpest point: a published heuristic ("we count diverged forks from accounts
over one year old with N followers") is a spec sheet. Buy aged accounts,
follow-farm them, script a trivial commit. So this reports **observations**, not
a pass/fail score — no threshold to optimise against, because there is no gate.

**Nobody currently owns re-auditing it.** The legitimacy lens found the gap that
survived every challenge: detectability is not a stable property, it decays as
adversaries adapt, and R1 names no standing institution to notice. That gap is
recorded here rather than papered over. It is the reason this reports rather than
judges.

    python -m suites.fork_trail --repo shaelsrv/gravity-wells
    python -m suites.fork_trail --repo owner/name --json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _gh(path: str):
    try:
        r = subprocess.run(["gh", "api", path], capture_output=True,
                           text=True, timeout=90)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        return json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def trail(repo: str, limit: int = 30, deep: bool = False) -> dict:
    """Fork provenance for owner/name. Observations only — no score, no gate."""
    forks = _gh(f"repos/{repo}/forks?per_page={limit}")
    if forks is None:
        return {"repo": repo, "error": "could not read forks (private, "
                                       "missing, or rate-limited)"}
    out = {"repo": repo, "forks": len(forks), "diverged": 0, "bookmarks": 0,
           "detail": []}
    for f in forks:
        owner = (f.get("owner") or {}).get("login", "?")
        created, pushed = f.get("created_at", ""), f.get("pushed_at", "")
        # The tell: a fork whose latest push postdates its creation has commits
        # of its own. GitHub copies the parent's pushed_at at fork time, so
        # equal timestamps mean nothing was ever added.
        diverged = bool(created and pushed and pushed > created)
        row = {"owner": owner, "created": created[:10], "diverged": diverged}
        if deep:
            # Account context, reported as facts and never thresholded here.
            u = _gh(f"users/{owner}") or {}
            row["account_created"] = (u.get("created_at") or "")[:10]
            row["public_repos"] = u.get("public_repos")
            row["followers"] = u.get("followers")
        out["detail"].append(row)
        out["diverged" if diverged else "bookmarks"] += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Fork provenance for a model repo.")
    ap.add_argument("--repo", required=True, help="owner/name")
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--deep", action="store_true",
                    help="also fetch each forker's account facts")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    d = trail(a.repo, a.limit, a.deep)
    if a.json:
        print(json.dumps(d, indent=1))
        return
    if d.get("error"):
        print(f"  {d['repo']}: {d['error']}")
        return
    print(f"  {d['repo']}: {d['forks']} fork(s) — "
          f"{d['diverged']} diverged, {d['bookmarks']} bookmark(s)")
    for r in d["detail"]:
        extra = ""
        if "account_created" in r:
            extra = (f"  acct={r['account_created']} "
                     f"repos={r['public_repos']} followers={r['followers']}")
        print(f"      {'worked' if r['diverged'] else 'bookmark':<9} "
              f"{r['owner'][:28]:<28} forked {r['created']}{extra}")
    print("\n  A diverged fork means someone TOOK this model and worked on it.")
    print("  It is not a quality signal and is never a rank. Only grading")
    print("  says whether a model is right.")


if __name__ == "__main__":
    main()
