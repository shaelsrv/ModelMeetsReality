"""Model tags — what a browser needs to decide, computed where possible.

Some tags already emerged from the machinery: level, kind, aspects, e_span,
tier. They answer "what is this". They do not answer the questions someone
actually has in front of a list of models:

    Can I use this?  Is it any good?  Does it fit my situation?
    How long until I know?  What does it need?  Is it still alive?

DERIVED tags are computed from the repo and cannot be gamed by wishful
self-description — a model is "proven" only if its own graded record says so,
"stale" only if its git history says so. DECLARED tags are the author's, because
no machine can read intent: scope, inputs, and sensitivity.

    python -m suites.tags --model my-model
    python -m suites.tags --all
    python -m suites.tags --set my-model --scope personal --inputs none
"""
from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
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

# Author-declared. A machine cannot infer these, so they are asked for, and the
# card shows them as claims by the author rather than as measurements.
SCOPE = ["personal", "team", "organisation", "local", "national", "global"]
INPUTS = ["none", "own-records", "public-web", "paid-data", "specialist-access"]
SENSITIVITY = ["neutral", "contested", "sensitive"]
EFFORT = ["minutes", "hours", "ongoing"]


def _ledger_rows(repo: Path):
    for rel in LEDGERS:
        f = repo / rel
        if not f.exists():
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in (d.get("predictions", d) if isinstance(d, dict) else d):
            yield r


def derive(repo: Path) -> dict:
    """Tags computed from the repo. Not assertable by the author."""
    rows = list(_ledger_rows(repo))
    graded = [r for r in rows if r.get("status", "open") not in ("open", "?")]
    hits = [r for r in graded if r.get("status") in ("hit", "partial")]
    out = {}

    # --- "how far along is it?" — HOW MUCH has resolved, never how well.
    #
    # This used to emit a quality verdict ("proven"/"mixed"/"failing") plus a
    # hit_rate, both computed by collapsing every claim the model holds into one
    # number regardless of domain or of who resolved it. That is a blended score
    # with no holder: it merges a claim nobody checked with one an outside party
    # resolved, and a reader cannot undo the merge. See earned-standing P1.
    #
    # A quality signal may be displayed only per (domain, provenance) and only
    # where claims were independently resolved — which no repo supports yet. So
    # what is emitted here is a STAGE, which says how much evidence exists
    # without ruling on it.
    if not graded:
        out["evidence"] = "untested"
    elif len(graded) < 5:
        out["evidence"] = "early"
    else:
        out["evidence"] = "graded"
    out["graded_n"] = len(graded)
    out["hits_n"] = len(hits)   # a count, not a rate — rates blend, counts do not

    # --- "how long until I know?" — from the actual claim horizons
    spans = []
    for r in rows:
        made, due = r.get("made_on"), r.get("resolve_by")
        if made and due and len(made) == 10 and len(due) == 10:
            try:
                spans.append((datetime.date.fromisoformat(due)
                              - datetime.date.fromisoformat(made)).days)
            except ValueError:
                pass
    if spans:
        med = sorted(spans)[len(spans) // 2]
        out["horizon"] = ("days" if med <= 14 else "weeks" if med <= 60 else
                          "months" if med <= 400 else "years")
        out["median_days"] = med

    # --- "is it still alive?" — git history, not a status field
    try:
        r = subprocess.run(["git", "log", "-1", "--format=%ad", "--date=short"],
                           cwd=repo, capture_output=True, text=True, timeout=10)
        last = (r.stdout or "").strip()
        if last:
            age = (datetime.date.today() - datetime.date.fromisoformat(last)).days
            out["activity"] = ("active" if age <= 45 else
                               "quiet" if age <= 180 else "dormant")
            out["last_touched"] = last
    except Exception:
        pass

    # --- "has it been honest?" — did it actually retire or amend something?
    #
    # Naive keyword matching gets this exactly backwards: "struck" and "retires"
    # appear in every well-written DELETION CLAUSE, describing the condition
    # under which the model would retire. Matching those tagged a healthy model
    # as self-retired for having a good clause. Look for dated events instead —
    # an amendment or retirement records WHEN it happened.
    mm = repo / "MODEL.md"
    if mm.exists():
        t = mm.read_text(encoding="utf-8", errors="replace")
        low = t.lower()
        # a real event is dated: "Amendment 2026-09-04", "Retired 2026-08-12"
        import re as _re
        events = _re.findall(r"(amendment|amended|retired|struck)\s*[:\-—(]?\s*"
                             r"(\d{4}-\d{2}-\d{2})", low)
        if any(e[0] in ("retired", "struck") for e in events):
            out["honesty"] = "self-retired"
        elif events:
            out["honesty"] = "amended"
        if "deletion clause" not in low and "retires to notation" not in low:
            out["risk"] = "no-deletion-clause"
    return out


def declared(repo: Path) -> dict:
    f = repo / "tags.json"
    return json.load(f.open(encoding="utf-8")) if f.exists() else {}


def tags_for(slug: str) -> dict:
    repo = MODELS_DIR / slug
    if not (repo / "MODEL.md").exists():
        raise SystemExit(f"no model at {repo}")
    d = derive(repo)
    a = declared(repo)
    return {"model": slug, "derived": d, "declared": a,
            "missing_declared": [k for k in ("scope", "inputs", "sensitivity", "effort")
                                 if k not in a]}


def render(t: dict) -> str:
    d, a = t["derived"], t["declared"]
    chips = []
    if d.get("evidence"):
        n = d.get("graded_n", 0)
        chips.append(f"{d['evidence']}" + (f" ({n} graded)" if n else ""))
    for k in ("horizon", "activity", "honesty", "risk"):
        if d.get(k):
            chips.append(str(d[k]))
    for k in ("scope", "inputs", "sensitivity", "effort"):
        if a.get(k):
            chips.append(f"{a[k]}")
    return " · ".join(chips) if chips else "(no tags yet)"


def main() -> None:
    ap = argparse.ArgumentParser(description="Model tags for browsing and sharing.")
    ap.add_argument("--model")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--set", dest="setslug")
    for k, choices in (("scope", SCOPE), ("inputs", INPUTS),
                       ("sensitivity", SENSITIVITY), ("effort", EFFORT)):
        ap.add_argument(f"--{k}", choices=choices)
    a = ap.parse_args()

    if a.setslug:
        repo = MODELS_DIR / a.setslug
        if not (repo / "MODEL.md").exists():
            raise SystemExit(f"no model at {repo}")
        cur = declared(repo)
        for k in ("scope", "inputs", "sensitivity", "effort"):
            v = getattr(a, k)
            if v:
                cur[k] = v
        (repo / "tags.json").write_text(json.dumps(cur, indent=1), encoding="utf-8")
        print(f"{a.setslug}: declared tags -> {cur}")
        return

    if a.all:
        cfg = json.load((ROOT / "fleet.json").open(encoding="utf-8"))
        slugs = cfg.get("models", []) + cfg.get("classifiers", [])
        for s in slugs:
            if not (MODELS_DIR / s / "MODEL.md").exists():
                continue
            t = tags_for(s)
            print(f"  {s:<24} {render(t)}")
            if t["missing_declared"]:
                print(f"  {'':<24} needs: {', '.join(t['missing_declared'])}")
        return

    if a.model:
        t = tags_for(a.model)
        print(json.dumps(t, indent=1))
        print("\n  " + render(t))
        if t["missing_declared"]:
            print(f"\n  Author must declare: {', '.join(t['missing_declared'])}")
            print(f"  e.g. python -m suites.tags --set {a.model} --scope personal "
                  f"--inputs none --sensitivity neutral --effort minutes")
        return
    ap.print_help()


if __name__ == "__main__":
    main()
