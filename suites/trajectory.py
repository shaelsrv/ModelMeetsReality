"""Model trajectory store — every claim, every outcome, every model version, over time.

The longitudinal record the fleet was missing: an append-only store
(`trajectory/trajectory.jsonl`) where every evaluated claim lands as one row —

  {recorded, source, model, model_version, claim, domain, p, baseline_p, market_p,
   outcome, brier, made_on, resolve_by, key}

— plus `version_events.jsonl` (when each model's MODEL.md version changed, reconstructed
from git history), so accuracy can be sliced BY MODEL VERSION and the trajectory of each
theory (did v2 grade better than v1? did the revision after the backtest learning help?)
becomes a queryable fact instead of a story.

Sources swept by --collect (idempotent; dedup by content key):
  * instrument ledgers (all repos' predict/ + signals/ ledgers) — graded rows
  * my-model backtests (data/markets.jsonl) — with market + baseline arms
  * the market paper book (settled positions)
  * imported-analyst ledgers (graded claims; version = "archive")

VERSION ATTRIBUTION: each model's version timeline is read from `git log -- MODEL.md`
(first line's "(vX...)" per commit); a claim is attributed to the version current at its
made_on date. Version changes are themselves rows in version_events (the trajectory's
x-axis ticks).

Runs inside the weekly grading loop (cheap, no LLM). Report: TRAJECTORY.md.

  python -m suites.trajectory --collect
  python -m suites.trajectory --report
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]

def _models_dir(root):
    """Where THIS instance's model repos live.

    fleet.json may set models_dir to give the instance a private namespace;
    without it, models are siblings of the instance (the original layout).
    Two instances under one parent otherwise read each other's models.
    """
    try:
        import json as _json
        cfg = _json.load((root / "fleet.json").open(encoding="utf-8"))
        if cfg.get("models_dir"):
            return (root / cfg["models_dir"]).resolve()
    except Exception:
        pass
    return root.parent


TOOLS = _models_dir(ROOT)
TDIR = ROOT / "trajectory"
STORE = TDIR / "trajectory.jsonl"
VEVENTS = TDIR / "version_events.jsonl"

from harness.fleet import MODEL_REPOS  # fleet.json registry
GRADED = {"hit", "partial", "miss", "unresolvable"}
OUTCOME = {"hit": 1.0, "partial": 0.5, "miss": 0.0}


def _key(*parts) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:16]


def _version_of(text: str) -> str:
    m = re.search(r"\(v([\w.\-]+)\)", text.splitlines()[0] if text else "")
    return m.group(1) if m else "?"


def version_timeline(repo: str) -> list[tuple[str, str]]:
    """[(date, version)] ascending — from git history of MODEL.md."""
    rdir = TOOLS / repo
    try:
        log = subprocess.run(["git", "log", "--format=%ad %H", "--date=short",
                              "--reverse", "--", "MODEL.md"],
                             cwd=rdir, capture_output=True, text=True, timeout=60).stdout
    except Exception:
        return []
    out, last = [], None
    for line in log.strip().splitlines():
        date, commit = line.split()
        try:
            blob = subprocess.run(["git", "show", f"{commit}:MODEL.md"], cwd=rdir,
                                  capture_output=True, timeout=60,
                                  encoding="utf-8", errors="replace").stdout
        except Exception:
            continue
        v = _version_of(blob)
        if v != last:
            out.append((date, v))
            last = v
    return out


def version_at(timeline, made_on: str) -> str:
    v = timeline[0][1] if timeline else "?"
    for date, ver in timeline:
        if date <= (made_on or "9999"):
            v = ver
    return v


def load_keys() -> set:
    keys = set()
    for f in (STORE, VEVENTS):
        if f.exists():
            keys |= {json.loads(l)["key"] for l in f.read_text(encoding="utf-8").splitlines()
                     if l.strip()}
    return keys


def collect() -> None:
    TDIR.mkdir(exist_ok=True)
    seen = load_keys()
    today = datetime.date.today().isoformat()
    new_rows, new_events = [], []

    timelines = {}
    for repo in MODEL_REPOS:
        tl = version_timeline(repo)
        timelines[repo] = tl
        for date, ver in tl:
            k = _key("vevent", repo, ver)
            if k not in seen:
                new_events.append({"recorded": today, "model": repo, "version": ver,
                                   "date": date, "key": k})
                seen.add(k)

    def add(row):
        if row["key"] not in seen:
            row["recorded"] = today
            new_rows.append(row)
            seen.add(row["key"])

    # 1 — instrument ledgers (graded rows only)
    for repo in MODEL_REPOS:
        for rel in ("predict/ledger.json", "predict/live_ledger.json",
                    "signals/signal_ledger.json"):
            p = TOOLS / repo / rel
            if not p.exists():
                continue
            d = json.load(p.open(encoding="utf-8"))
            for r in (d.get("predictions", d) if isinstance(d, dict) else d):
                if r.get("status") not in GRADED:
                    continue
                o = OUTCOME.get(r["status"])
                pp = r.get("confidence")
                add({"source": "live", "model": repo,
                     "model_version": version_at(timelines[repo], r.get("made_on", "")),
                     "claim": (r.get("claim") or "")[:200],
                     "domain": r.get("entity", r.get("mechanism", ""))[:60],
                     "p": pp, "baseline_p": None, "market_p": None,
                     "outcome": o, "status": r["status"],
                     "brier": round((pp - o) ** 2, 4)
                     if isinstance(pp, (int, float)) and o is not None else None,
                     "made_on": r.get("made_on", ""), "resolve_by": r.get("resolve_by", ""),
                     "key": _key("live", repo, r.get("claim"), r.get("resolve_by"))})

    # 2 — polymarket backtests
    bm = TOOLS / "my-model" / "data" / "markets.jsonl"
    if bm.exists():
        for line in bm.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if "instrument_p" not in r or r.get("contaminated"):
                continue
            o = 1.0 if r["outcome_yes"] else 0.0
            repo = r["domain"]
            add({"source": "backtest", "model": repo,
                 "model_version": version_at(timelines.get(repo, []), r.get("lead_date", "")),
                 "claim": r["question"][:200], "domain": r["domain"],
                 "p": r["instrument_p"], "baseline_p": r.get("baseline_p"),
                 "market_p": r.get("market_p_at_lead"), "outcome": o,
                 "status": "hit" if (r["instrument_p"] > 0.5) == r["outcome_yes"] else "miss",
                 "brier": round((r["instrument_p"] - o) ** 2, 4),
                 "made_on": r.get("lead_date", ""), "resolve_by": r["end_date"],
                 "key": _key("backtest", r["slug"])})

    # 3 — market paper book (settled)
    book = ROOT / "predict_public" / "market_book.json"
    if book.exists():
        b = json.load(book.open(encoding="utf-8"))
        for pos in b.get("positions", []):
            if pos.get("status") != "settled":
                continue
            repo = pos.get("instrument_repo", "?")
            o = 1.0 if pos.get("outcome") == "YES" else 0.0
            add({"source": "market_book", "model": repo,
                 "model_version": version_at(timelines.get(repo, []), pos.get("elicited_on", "")),
                 "claim": pos.get("question", "")[:200], "domain": "market",
                 "p": pos.get("model_p"), "baseline_p": None,
                 "market_p": pos.get("best_ask"), "outcome": o,
                 "status": "hit" if (pos.get("model_p", 0.5) > 0.5) == (o == 1.0) else "miss",
                 "brier": round((pos.get("model_p", 0.5) - o) ** 2, 4),
                 "made_on": pos.get("elicited_on", ""), "resolve_by": pos.get("end_date", ""),
                 "pnl": pos.get("pnl_virtual"),
                 "key": _key("book", pos.get("slug"))})

    # 4 — imported analysts
    import glob as _g
    for f in _g.glob(str(ROOT / "imports" / "*.claims.jsonl")):
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("status") not in OUTCOME:
                continue
            o = OUTCOME[r["status"]]
            sp = r.get("speaker_p")
            add({"source": "imports", "model": r.get("analyst", "?"),
                 "model_version": "archive",
                 "claim": (r.get("claim") or "")[:200],
                 "domain": r.get("mechanism", "")[:60],
                 "p": sp, "baseline_p": None, "market_p": None, "outcome": o,
                 "status": r["status"],
                 "brier": round((sp - o) ** 2, 4) if isinstance(sp, (int, float)) else None,
                 "made_on": r.get("made_on", ""), "resolve_by": r.get("resolve_by", ""),
                 "key": _key("imports", r.get("id"))})

    with STORE.open("a", encoding="utf-8") as f:
        for r in new_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with VEVENTS.open("a", encoding="utf-8") as f:
        for e in new_events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    total = len(load_keys())
    print(f"[trajectory] +{len(new_rows)} rows, +{len(new_events)} version events "
          f"({total} keys total)")


def report() -> None:
    if not STORE.exists():
        print("empty store"); return
    rows = [json.loads(l) for l in STORE.read_text(encoding="utf-8").splitlines() if l.strip()]
    vev = ([json.loads(l) for l in VEVENTS.read_text(encoding="utf-8").splitlines() if l.strip()]
           if VEVENTS.exists() else [])
    scored = [r for r in rows if r.get("brier") is not None
              and r.get("status") != "unresolvable"]
    by_mv = defaultdict(list)
    for r in scored:
        by_mv[(r["model"], r["model_version"], r["source"])].append(r)
    L = ["# Model trajectories",
         f"Updated {datetime.date.today().isoformat()} · {len(rows)} rows · "
         f"{len(scored)} scored · {len(vev)} version events",
         "",
         "| model | version | source | n | mean Brier | hit-ish | vs baseline | vs market |",
         "|---|---|---|---|---|---|---|---|"]
    for (m, v, src), rs in sorted(by_mv.items()):
        n = len(rs)
        b = sum(r["brier"] for r in rs) / n
        hit = sum(1 for r in rs if r["status"] in ("hit",)) / n
        bl = [r for r in rs if isinstance(r.get("baseline_p"), (int, float))]
        mk = [r for r in rs if isinstance(r.get("market_p"), (int, float))]
        vb = (sum((r["baseline_p"] - r["outcome"]) ** 2 for r in bl) / len(bl)) if bl else None
        vm = (sum((r["market_p"] - r["outcome"]) ** 2 for r in mk) / len(mk)) if mk else None
        L.append(f"| {m} | {v} | {src} | {n} | {b:.3f} | {hit:.0%} | "
                 f"{'—' if vb is None else ('WINS' if b < vb else 'loses') + f' ({vb:.3f})'} | "
                 f"{'—' if vm is None else ('WINS' if b < vm else 'loses') + f' ({vm:.3f})'} |")
    L += ["", "## Version timelines", ""]
    by_model = defaultdict(list)
    for e in vev:
        by_model[e["model"]].append((e["date"], e["version"]))
    for m, tl in sorted(by_model.items()):
        L.append(f"- **{m}**: " + " → ".join(f"v{v} ({d})" for d, v in sorted(tl)))
    L += ["", "_Trajectory question this table exists to answer: does version N+1 grade "
          "better than version N on comparable claims? Slices accrue every collect._"]
    (TDIR / "TRAJECTORY.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:14]))
    print(f"-> trajectory/TRAJECTORY.md")


def main() -> None:
    ap = argparse.ArgumentParser(description="Longitudinal model-version trajectory store.")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    if a.collect:
        collect()
    if a.report:
        report()
    if not (a.collect or a.report):
        collect()
        report()


if __name__ == "__main__":
    main()
