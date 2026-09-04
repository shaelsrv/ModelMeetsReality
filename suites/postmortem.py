"""Postmortems — why correct, why wrong, what we missed, what we analyzed right.

The trajectory store records THAT a claim resolved; this records WHY. For every scored
trajectory row without one, an LLM postmortem (web-enabled — establishing what actually
drove the outcome needs sources) produces a structured verdict:

  * correctness: earned_hit | lucky_hit | near_miss | mechanism_miss | shared_miss
      - hits are interrogated as hard as misses: a hit whose stated mechanism did NOT
        drive the outcome is LUCKY, and lucky hits are trajectory poison if uncounted
  * analyzed_right: what the read got structurally correct (even in misses)
  * missed: the specific thing not seen or mis-weighted
  * miss_category: information (a knowable fact wasn't known) | mechanism (the causal
      read was wrong — the valuable kind, feeds revisions) | calibration (right
      direction, wrong magnitude) | criteria (resolution mismatch) | none
  * lesson: one transferable line, usable in future rounds

Stored append-only in trajectory/postmortems.jsonl (joined by the trajectory key).
Transferable lessons for INSTRUMENT rows are auto-appended to that repo's ledger
learnings (deduped), closing the loop: postmortem -> learnings -> next round's prompt.

Runs in the weekly loop after trajectory collection.

  python -m suites.postmortem --run [--limit N]
  python -m suites.postmortem --report
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from collections import Counter, defaultdict
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
TDIR = ROOT / "trajectory"
STORE = TDIR / "trajectory.jsonl"
PMS = TDIR / "postmortems.jsonl"

MODEL_REPOS = {"my-model", "my-model", "my-model", "my-model",
               "my-model", "my-model", "my-model", "my-model",
               "my-model", "my-model", "my-model", "my-model"}

PM_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. Post-mortem one resolved prediction.
Be adversarial toward the prediction in BOTH directions: a hit whose stated reasoning did not
actually drive the outcome is LUCKY, not earned — and must be labeled so.

MODEL: {model} (version {version})
CLAIM: {claim}
PROBABILITY GIVEN: {p}
REASONING AT PREDICTION TIME: {reasoning}
OUTCOME: {outcome_str}
KNOWN RESOLUTION CONTEXT: {context}

STEP 1 — establish (web if needed) what actually drove the outcome: the 1-3 causal facts.
STEP 2 — compare against the reasoning-at-prediction-time:
  - correctness: earned_hit (right, AND the stated mechanism was among the actual drivers) |
    lucky_hit (right, but the actual drivers were NOT the stated mechanism) |
    near_miss (wrong side of 0.5 but well-calibrated reasoning, outcome was genuinely close) |
    mechanism_miss (wrong because the causal read was wrong) |
    shared_miss (wrong, but for reasons nearly all informed observers also missed)
  - analyzed_right: what the read got structurally correct, even if the claim missed
  - missed: the ONE most important thing not seen or mis-weighted
  - miss_category: information | mechanism | calibration | criteria | none
STEP 3 — lesson: one transferable line a future round of this model could apply.

Return ONLY JSON:
{"drivers":["..."],"correctness":"...","analyzed_right":"...","missed":"...",
"miss_category":"information|mechanism|calibration|criteria|none","lesson":"..."}"""


def load_rows():
    if not STORE.exists():
        return []
    return [json.loads(l) for l in STORE.read_text(encoding="utf-8").splitlines() if l.strip()]


def load_pms():
    if not PMS.exists():
        return {}
    return {json.loads(l)["key"]: json.loads(l)
            for l in PMS.read_text(encoding="utf-8").splitlines() if l.strip()}


def _reasoning_for(row) -> tuple[str, str]:
    """(reasoning_at_prediction_time, resolution_context) recovered from source stores."""
    src = row["source"]
    if src == "backtest":
        f = TOOLS / "my-model" / "data" / "markets.jsonl"
        for line in f.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("question", "")[:200] == row["claim"]:
                return (r.get("model_read") or "(none recorded)",
                        f"market resolved {'YES' if r.get('outcome_yes') else 'NO'} "
                        f"on {r.get('end_date')}")
    if src == "live":
        for rel in ("predict/ledger.json", "predict/live_ledger.json",
                    "signals/signal_ledger.json"):
            p = TOOLS / row["model"] / rel
            if not p.exists():
                continue
            d = json.load(p.open(encoding="utf-8"))
            for r in (d.get("predictions", d) if isinstance(d, dict) else d):
                if (r.get("claim") or "")[:200] == row["claim"]:
                    return (r.get("model_read") or r.get("mechanism") or "(none)",
                            r.get("what_happened") or "")
    if src == "market_book":
        b = json.load((ROOT / "predict_public" / "market_book.json").open(encoding="utf-8"))
        for pos in b.get("positions", []):
            if (pos.get("question") or "")[:200] == row["claim"]:
                return (pos.get("model_read") or "(none)",
                        f"market outcome {pos.get('outcome')}")
    if src == "imports":
        return ("(analyst's claim; reasoning mostly paywalled/unavailable)",
                "")
    return ("(none recovered)", "")


def _run_one(row, model):
    reasoning, context = _reasoning_for(row)
    o = row.get("outcome")
    outcome_str = ("YES/happened" if o == 1.0 else "NO/did not happen" if o == 0.0
                   else f"partial ({o})") + f" — graded {row.get('status')}"
    p = (PM_PROMPT.replace("{today}", datetime.date.today().isoformat())
         .replace("{model}", row["model"]).replace("{version}", str(row["model_version"]))
         .replace("{claim}", row["claim"]).replace("{p}", str(row.get("p")))
         .replace("{reasoning}", reasoning[:800]).replace("{outcome_str}", outcome_str)
         .replace("{context}", context[:400]))
    r = chat(model + ":online", [{"role": "user", "content": p}],
             temperature=0.2, max_tokens=1600)
    return parse_json(r.text) if not r.error else None


def cmd_run(model: str, limit: int) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    rows = [r for r in load_rows() if r.get("brier") is not None]
    done = load_pms()
    todo = [r for r in rows if r["key"] not in done]
    if limit:
        todo = todo[:limit]
    print(f"[postmortem] {len(todo)} to analyze ({len(done)} done) · {model} · 4 workers")
    lessons_by_repo = defaultdict(list)
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(_run_one, r, model): r for r in todo}
        with PMS.open("a", encoding="utf-8") as f:
            for fut in as_completed(futs):
                row = futs[fut]
                d = fut.result()
                if not d or not d.get("correctness"):
                    print(f"  ! failed: {row['claim'][:60]}")
                    continue
                pm = {"key": row["key"], "model": row["model"],
                      "model_version": row["model_version"], "source": row["source"],
                      "analyzed": datetime.date.today().isoformat(),
                      "correctness": d["correctness"],
                      "drivers": d.get("drivers", [])[:3],
                      "analyzed_right": (d.get("analyzed_right") or "")[:300],
                      "missed": (d.get("missed") or "")[:300],
                      "miss_category": d.get("miss_category", "none"),
                      "lesson": (d.get("lesson") or "")[:250]}
                f.write(json.dumps(pm, ensure_ascii=False) + "\n")
                if (row["model"] in MODEL_REPOS and pm["lesson"]
                        and pm["correctness"] not in ("earned_hit",)):
                    lessons_by_repo[row["model"]].append(pm["lesson"])
                print(f"  {pm['correctness']:>14} [{pm['miss_category']:>11}] "
                      f"{row['claim'][:56]}")
    # feed lessons back to instrument ledgers (dedup, cap 5 per repo per run)
    for repo, lessons in lessons_by_repo.items():
        lpath = TOOLS / repo / "predict" / "ledger.json"
        if not lpath.exists():
            continue
        led = json.load(lpath.open(encoding="utf-8"))
        existing = {l.get("learning", "") for l in led.get("learnings", [])}
        added = 0
        for l in lessons:
            if l not in existing and added < 5:
                led.setdefault("learnings", []).append(
                    {"entity": "postmortem", "round": 0,
                     "assessed": datetime.date.today().isoformat(), "learning": l})
                added += 1
        if added:
            json.dump(led, lpath.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"  -> {repo}: {added} lesson(s) fed to learnings ledger")


def cmd_report() -> None:
    pms = list(load_pms().values())
    if not pms:
        print("no postmortems yet"); return
    L = ["# Postmortems — why correct, why wrong",
         f"Updated {datetime.date.today().isoformat()} · {len(pms)} analyzed", ""]
    by_mv = defaultdict(list)
    for p in pms:
        by_mv[(p["model"], p["model_version"])].append(p)
    L += ["| model | ver | n | earned | lucky | near-miss | mech-miss | shared | top miss-category |",
          "|---|---|---|---|---|---|---|---|---|"]
    for (m, v), ps in sorted(by_mv.items()):
        c = Counter(p["correctness"] for p in ps)
        mc = Counter(p["miss_category"] for p in ps if p["miss_category"] != "none")
        top = mc.most_common(1)[0][0] if mc else "—"
        L.append(f"| {m} | {v} | {len(ps)} | {c.get('earned_hit',0)} | "
                 f"{c.get('lucky_hit',0)} | {c.get('near_miss',0)} | "
                 f"{c.get('mechanism_miss',0)} | {c.get('shared_miss',0)} | {top} |")
    L += ["", "**Reading rule:** the honest hit-rate is EARNED hits only; lucky hits are "
          "trajectory poison. mechanism_miss counts are the revision queue.", "",
          "## Recurring lessons (by model)"]
    by_model_lessons = defaultdict(Counter)
    for p in pms:
        if p.get("lesson"):
            by_model_lessons[p["model"]][p["lesson"]] += 1
    for m, cnt in sorted(by_model_lessons.items()):
        L.append(f"### {m}")
        for lesson, n in cnt.most_common(5):
            L.append(f"- {'(x%d) ' % n if n > 1 else ''}{lesson}")
        L.append("")
    (TDIR / "POSTMORTEMS.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:16]))
    print("-> trajectory/POSTMORTEMS.md")


def main() -> None:
    ap = argparse.ArgumentParser(description="Why correct / why wrong, per graded claim.")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    if a.run:
        if not (os.environ.get("OPENROUTER_API_KEY")
                or os.environ.get("LLM_BACKEND") == "claude-code"):
            raise SystemExit("OPENROUTER_API_KEY not set (or set LLM_BACKEND=claude-code)")
        cmd_run(a.model, a.limit)
    if a.report or not a.run:
        cmd_report()


if __name__ == "__main__":
    main()
