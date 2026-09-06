"""Calibration reweighter — learn each model's confidence curve; no LLM anywhere.

Recovers predicted probabilities from graded binary rows (p = 1-sqrt(brier) if hit,
sqrt(brier) if miss; partials skipped), bins them, and measures observed hit rate
per bin. The correction table maps stated -> observed; the bet (MODEL.md c.1) is
that reweighted Brier beats raw within two windows.

  python -m suites.calibrate            # build curves + report
"""
from __future__ import annotations

import datetime
import json
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
OUT = TOOLS / "calibration-reweighter"

BINS = [(0.0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.01)]


def rows():
    tf = ROOT / "trajectory" / "trajectory.jsonl"
    if not tf.exists():
        return []
    out = []
    for l in tf.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        b = r.get("brier")
        o = r.get("outcome", r.get("status"))
        if b is None:
            continue
        if o in (1, 1.0, "1", "hit", True):
            p, y = 1 - b ** 0.5, 1
        elif o in (0, 0.0, "0", "miss", False):
            p, y = b ** 0.5, 0
        else:
            continue  # partials: p unrecoverable from brier alone
        out.append({"model": r.get("model", "?"), "p": round(p, 4), "y": y})
    return out


def curve(rs):
    c = []
    for lo, hi in BINS:
        sel = [r for r in rs if lo <= r["p"] < hi]
        if not sel:
            c.append({"bin": [lo, min(hi, 1.0)], "n": 0, "stated": None, "observed": None})
            continue
        c.append({"bin": [lo, min(hi, 1.0)], "n": len(sel),
                  "stated": round(sum(r["p"] for r in sel) / len(sel), 3),
                  "observed": round(sum(r["y"] for r in sel) / len(sel), 3)})
    return c


def reweight(p, c):
    for entry in c:
        lo, hi = entry["bin"]
        if lo <= p < hi and entry["observed"] is not None and entry["n"] >= 5:
            return entry["observed"]
    return p


def main():
    rs = rows()
    if not rs:
        print("no graded binary rows yet")
        return
    by_model = defaultdict(list)
    for r in rs:
        by_model[r["model"]].append(r)
    fleet_curve = curve(rs)
    curves = {"_fleet": fleet_curve}
    L = [f"# Calibration curves", f"Built {datetime.date.today().isoformat()} · "
         f"{len(rs)} graded binary rows (partials excluded)", "",
         "| scope | n | raw Brier | reweighted | verdict |", "|---|---|---|---|---|"]

    def briers(sel, c):
        raw = sum((r["p"] - r["y"]) ** 2 for r in sel) / len(sel)
        rw = sum((reweight(r["p"], c) - r["y"]) ** 2 for r in sel) / len(sel)
        return raw, rw

    raw, rw = briers(rs, fleet_curve)
    L.append(f"| fleet | {len(rs)} | {raw:.3f} | {rw:.3f} | "
             f"{'reweighted' if rw < raw else 'raw'} wins |")
    for m, sel in sorted(by_model.items(), key=lambda kv: -len(kv[1])):
        c = curve(sel) if len(sel) >= 10 else fleet_curve
        curves[m] = {"curve": c, "borrowed": len(sel) < 10}
        raw, rw = briers(sel, c)
        L.append(f"| {m}{' (borrowed curve)' if len(sel) < 10 else ''} | {len(sel)} | "
                 f"{raw:.3f} | {rw:.3f} | {'reweighted' if rw < raw else 'raw'} wins |")
    L += ["", "## Reliability (fleet)",
          "| stated | observed | n |", "|---|---|---|"]
    for e in fleet_curve:
        if e["n"]:
            L.append(f"| {e['stated']} | {e['observed']} | {e['n']} |")
    L += ["", "In-sample reweighting wins by construction; the REGISTERED bet is "
             "out-of-sample: curves frozen now, judged on the October cohort "
             "(MODEL.md consequence 1)."]
    OUT.mkdir(exist_ok=True)
    (OUT / "curves.json").write_text(json.dumps(
        {"built": datetime.date.today().isoformat(), "curves": curves},
        ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "CURVES.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
