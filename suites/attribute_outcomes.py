"""Outcome attributor — code which registered mechanism actually drove each graded outcome.

Implements attribution-model/MODEL.md: the whole registry (fleet + canon) is a
hypothesis menu (P1, with NONE mandatory); the claim's own model gets no privilege
(P2 — earned = attribution matches authorship; CROSS-HIT = someone else's mechanism
drove your hit); the scoreboard settles internal-vs-external (P3).

  python -m suites.attribute_outcomes --run [--limit 20]
  python -m suites.attribute_outcomes --scoreboard
"""
from __future__ import annotations

import argparse
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

from harness.openrouter import chat  # noqa: E402
from harness.actors import parse_json  # noqa: E402

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
AFILE = TOOLS / "attribution-model" / "attributions" / "attributions.jsonl"

# The mechanism menu — one line per registered model. Static v1 (revisit if a
# MODEL.md's core mechanism changes); canon lines mirror canon/models/ cards.
MENU = {}  # instance mechanism one-liners: {"model-slug": "its mechanism"}
CANON = set()  # canon control slugs, if this instance runs any

PROMPT = """You are an outcome attributor. A prediction has been GRADED — the outcome is known. Your
job: decide which mechanism from the menu below ACTUALLY DROVE the outcome. The model that made
the claim gets NO privilege — judge only from what happened. If no menu mechanism genuinely
explains it, answer "none" (mandatory honesty — forced attribution corrupts the scoreboard).

THE CLAIM ({verdict}): {claim}
MADE BY (authorship, for the record only — do NOT favor it): {author}
WHAT ACTUALLY HAPPENED: {what}

THE MECHANISM MENU:
{menu}

Rules: primary driver = the single mechanism whose operation best explains the OUTCOME (not the
claim's wording). A MISS also has a driver — what mechanism produced the reality that falsified
the claim? Secondary is optional. Shares sum to <= 1.0; leftover = unexplained.

Return ONLY JSON:
{"primary":"menu-key or none","primary_share":0.0,
"secondary":"menu-key or none","secondary_share":0.0,
"why":"2-3 lines: the mechanism's operation, visible in what happened",
"confidence":0.0}"""


def graded_rows():
    """All graded rows: trajectory store (has what-happened via postmortems) + ledgers."""
    rows = []
    traj = ROOT / "trajectory" / "trajectory.jsonl"
    pms = {}
    pmf = ROOT / "trajectory" / "postmortems.jsonl"
    if pmf.exists():
        for l in pmf.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                pms[r.get("key")] = r
    if traj.exists():
        for l in traj.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if r.get("brier") is None:
                continue
            pm = pms.get(r.get("key"), {})
            rows.append({"key": r["key"], "author": r.get("model", "?"),
                         "claim": r.get("claim", ""), "verdict": r.get("outcome", r.get("status", "?")),
                         "what": pm.get("what_happened", pm.get("analysis", ""))[:800]})
    return rows


def cmd_run(model: str, limit: int) -> None:
    AFILE.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if AFILE.exists():
        done = {json.loads(l)["key"] for l in AFILE.read_text(encoding="utf-8").splitlines()
                if l.strip()}
    todo = [r for r in graded_rows() if r["key"] not in done and r["claim"]]
    if limit:
        todo = todo[:limit]
    menu = "\n".join(f"- {k}: {v}" for k, v in MENU.items()) + "\n- none: no menu mechanism explains this outcome"
    print(f"[attribute] {len(todo)} graded rows to code ({len(done)} done)")
    with AFILE.open("a", encoding="utf-8") as f:
        for r in todo:
            p = (PROMPT.replace("{verdict}", str(r["verdict"])).replace("{claim}", r["claim"][:400])
                 .replace("{author}", r["author"]).replace("{what}", r["what"] or "(no narrative; judge from claim + verdict)")
                 .replace("{menu}", menu))
            resp = chat(model, [{"role": "user", "content": p}], temperature=0.2, max_tokens=900)
            d = parse_json(resp.text) if not resp.error else None
            if not d or "primary" not in d:
                print(f"  ! {r['claim'][:60]}")
                continue
            row = {"key": r["key"], "author": r["author"], "verdict": r["verdict"],
                   "claim": r["claim"][:200], "coded": datetime.date.today().isoformat(), **d}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            cross = (d["primary"] not in ("none", r["author"]) and r["verdict"] in ("hit", 1.0, "1"))
            print(f"  {d['primary'][:24]:<26} {'CROSS-HIT ' if cross else ''}"
                  f"({d.get('primary_share','?')}) {r['claim'][:52]}")


def cmd_scoreboard() -> None:
    if not AFILE.exists():
        print("(no attributions yet)")
        return
    rows = [json.loads(l) for l in AFILE.read_text(encoding="utf-8").splitlines() if l.strip()]
    share = defaultdict(float)
    n_primary = defaultdict(int)
    cross_hits = []
    earned_like = 0
    for r in rows:
        p = r.get("primary", "none")
        # a "none" verdict means the WHOLE outcome went unexplained — full share,
        # else zero-share nones make "Unexplained: 0%" a lie over mostly-none data
        share[p] += 1.0 if p == "none" else float(r.get("primary_share", 0) or 0)
        n_primary[p] += 1
        s = r.get("secondary")
        if s and s != "none":
            share[s] += float(r.get("secondary_share", 0) or 0)
        if p == r.get("author"):
            earned_like += 1
        elif p != "none" and str(r.get("verdict")) in ("hit", "1", "1.0", "partial", "0.5"):
            cross_hits.append(r)
    total = sum(share.values()) or 1
    int_tot = sum(v for k, v in share.items() if k in MENU and k not in CANON)
    can_tot = sum(v for k, v in share.items() if k in CANON)
    non_tot = share.get("none", 0)
    L = [f"# Attribution scoreboard — which mechanisms does reality use?",
         f"Updated {datetime.date.today().isoformat()} · {len(rows)} graded outcomes coded", "",
         f"**Internal (family) mechanisms: {int_tot/total:.0%} · Canon (external): "
         f"{can_tot/total:.0%} · Unexplained: {non_tot/total:.0%}**", "",
         "| mechanism | kind | n primary | share |", "|---|---|---|---|"]
    for k, v in sorted(share.items(), key=lambda kv: -kv[1]):
        kind = "canon" if k in CANON else ("—" if k == "none" else "family")
        L.append(f"| {k} | {kind} | {n_primary.get(k,0)} | {v/total:.1%} |")
    L += ["", f"Authorship-matched (earned-like): {earned_like}/{len(rows)} · "
              f"CROSS-HITS (right claim, someone else's mechanism): {len(cross_hits)}"]
    for c in cross_hits[:8]:
        L.append(f"- {c['author']} claimed it; {c['primary']} drove it — {c['claim'][:80]}")
    out = TOOLS / "attribution-model" / "SCOREBOARD.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"-> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Attribute graded outcomes to mechanisms.")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--scoreboard", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="attribution decides scores — STRONG tier")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.scoreboard and not a.run:
        cmd_scoreboard(); return
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    if a.run:
        cmd_run(a.model, a.limit)
    if a.scoreboard:
        cmd_scoreboard()


if __name__ == "__main__":
    main()
