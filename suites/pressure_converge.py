"""Pressure convergence — resultant-vector analysis of an office/arena, with a full
REASONING TRACE attached to every prediction.

The synthesis of four family mechanisms, made computable:
  * pressure model — magnitude = severity x credibility; phi-repair boosts, decay cuts;
    dilemma -> delay absorbs unresolved tension when nothing forces the clock
  * threshold (Sangama) — >=3 INDEPENDENT cross-domain pressures aligned on one outcome
    = convergence, the strongest directional signal; vectors sharing >50% of their
    source structure are ONE vector (the independence test)
  * mesh P8 (structural law) — total magnitude drives P(some transition) regardless of
    alignment; alignment determines destination confidence; high-tension resolutions
    arrive from the unmonitored dimension
  * loop dominance (feedback-loops paper) — fast pressures dominate short horizons,
    slow ones long horizons: the outcome distribution is horizon-dependent

TWO-STAGE BY DESIGN: an LLM extracts the pressure-vector table (judgment: sources,
directions, magnitudes, evidence — fed by the pressure_watch dynamics log where one
exists); then PLAIN CODE computes independence dedup, convergence counts, the resultant,
the tension index, and the two-horizon outcome distribution. The probability is
arithmetic over an auditable table, not an LLM's gut number — so when a prediction
misses, the post-mortem can point at the exact vector whose weight was wrong.

Artifacts per run: my-model/converge/<slug>.json (the complete reasoning trace)
+ <slug>.md (readable) + a ledger claim whose mechanism cites the trace. This is the
template for reasoning-traced predictions generally.

  python -m suites.pressure_converge --target "Chair of the my-model" \
      --question "September 2026 my-model rate decision"
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
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
from harness.fleet import DECISION_REPO
RDIR = TOOLS / (DECISION_REPO or "decision-model")

SEVERITY = {"low": 1.0, "med": 2.0, "high": 3.0}
TS_FACTOR = {"short": {"fast": 1.0, "medium": 0.6, "slow": 0.3},
             "long": {"fast": 0.3, "medium": 0.8, "slow": 1.0}}
TOTAL_BANDS = [(2.0, "low"), (5.0, "moderate"), (8.0, "high"), (99.0, "saturated")]

VECTOR_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. You are extracting a PRESSURE-VECTOR
TABLE for a resultant-vector analysis. Institutional analysis of a public office/arena — publicly
documented stakes only, never anyone's inner life.

TARGET: {target}
QUESTION (the decision/outcome space): {question}

RECENT MONITORED DYNAMICS (from the standing pressure monitor; use and extend via the web):
{dynamics}

Extract EVERY significant pressure currently bearing on the target with respect to the question.
For each vector:
- id: v1, v2, ...
- source_form: who/what installs it (a named market, statute, party, electorate, press, foreign
  power, allied institution, military, technology constraint)
- domain: market | state-legal | party-political | electorate | press | foreign | institutional |
  military | technological
- pushes_toward: which OUTCOME it pushes (use short outcome labels; be consistent)
- severity: low | med | high  (what is lost/gained if defied/obeyed)
- credibility: 0.0-1.0 — has the consequence been DEMONSTRATED recently (phi-repair events raise
  it; lapsed/undemonstrated threats lower it). Cite the demonstration or its absence.
- timescale: fast (days-weeks) | medium (months) | slow (years)
- evidence: one dated line
- overlaps: list of other vector ids sharing >50% of their source structure with this one
  (same underlying coalition/balance-sheet/command chain counted twice is a double-count)

Then:
- outcomes: MUTUALLY EXCLUSIVE resolutions of the question — concrete decisions/actions one of
  which will actually happen (not desiderata, themes, or qualities), PLUS "delay/no-change"
  always. Every vector's pushes_toward MUST be one of these outcome labels.
- forcing_deadline: true/false — is there a date by which a decision is structurally forced
  (a scheduled meeting/vote/expiry)? Name it if true.
- unmonitored_dimensions: 1-2 dimensions orthogonal to the pressures above where a resolving
  surprise could arrive (the analytical blind spot).
- novel_regime: true if this pressure combination has no clear historical precedent.

Return ONLY JSON:
{"vectors":[{"id":"v1","source_form":"...","domain":"...","pushes_toward":"...",
"severity":"low|med|high","credibility":0.0,"timescale":"fast|medium|slow",
"evidence":"...","overlaps":[]}],
"outcomes":["...","delay/no-change"],
"forcing_deadline":false,"deadline":"YYYY-MM-DD or empty",
"unmonitored_dimensions":["..."],"novel_regime":false}"""


def dedup(vectors: list[dict]) -> tuple[list[dict], list[str]]:
    """Independence test: union overlapping vectors; keep the max-weight representative.
    Returns (kept, notes)."""
    parent = {v["id"]: v["id"] for v in vectors}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    byid = {v["id"]: v for v in vectors}
    for v in vectors:
        for o in v.get("overlaps", []):
            if o in byid:
                union(v["id"], o)
    groups: dict[str, list[dict]] = {}
    for v in vectors:
        groups.setdefault(find(v["id"]), []).append(v)
    kept, notes = [], []
    for root, grp in groups.items():
        if len(grp) == 1:
            kept.append(grp[0])
        else:
            best = max(grp, key=lambda v: SEVERITY.get(v.get("severity"), 1)
                       * float(v.get("credibility", 0.5)))
            kept.append(best)
            notes.append(f"merged {[v['id'] for v in grp]} -> {best['id']} "
                         f"(shared source structure; counted once)")
    return kept, notes


def compute(d: dict) -> dict:
    vectors = d.get("vectors", [])
    kept, dedup_notes = dedup(vectors)
    outcomes = [o for o in d.get("outcomes", []) if o]
    if "delay/no-change" not in outcomes:
        outcomes.append("delay/no-change")
    trace = {"dedup_notes": dedup_notes, "horizons": {}}
    total_raw = sum(SEVERITY.get(v.get("severity"), 1) * float(v.get("credibility", 0.5))
                    for v in kept)
    band = next(b for cap, b in TOTAL_BANDS if total_raw < cap)
    for horizon in ("short", "long"):
        scores = {o: 0.0 for o in outcomes}
        steps = []
        for v in kept:
            w = (SEVERITY.get(v.get("severity"), 1)
                 * float(v.get("credibility", 0.5))
                 * TS_FACTOR[horizon].get(v.get("timescale"), 0.6))
            o = v.get("pushes_toward", "")
            tgt = o if o in scores else ("delay/no-change" if "delay" in o.lower() else o)
            if tgt not in scores:
                scores[tgt] = 0.0
                outcomes.append(tgt)
            scores[tgt] += w
            steps.append(f"{v['id']} {v['source_form'][:30]} -> '{tgt}': "
                         f"{SEVERITY.get(v.get('severity'),1):.0f}sev x "
                         f"{float(v.get('credibility',0.5)):.2f}cred x "
                         f"{TS_FACTOR[horizon].get(v.get('timescale'),0.6):.1f}ts = {w:.2f}")
        active = {o: s for o, s in scores.items() if o != "delay/no-change"}
        tot_active = sum(active.values()) or 1e-9
        top_o, top_s = max(active.items(), key=lambda kv: kv[1]) if active else ("?", 0)
        tension = 1.0 - top_s / tot_active
        # dilemma -> delay: unresolved tension mass flows to delay unless a deadline forces
        delay_bonus = tension * tot_active * (0.3 if d.get("forcing_deadline") else 1.0) * 0.5
        scores["delay/no-change"] += delay_bonus
        steps.append(f"tension={tension:.2f}; delay absorbs {delay_bonus:.2f} "
                     f"({'deadline forces -> x0.3' if d.get('forcing_deadline') else 'no forcing deadline'})")
        total = sum(scores.values()) or 1e-9
        dist = {o: round(s / total, 3) for o, s in sorted(scores.items(), key=lambda kv: -kv[1])}
        # convergence: independent domains aligned per outcome
        conv = {}
        for o in active:
            doms = {v.get("domain") for v in kept if v.get("pushes_toward") == o}
            conv[o] = len(doms)
        trace["horizons"][horizon] = {
            "steps": steps, "scores": {k: round(v, 3) for k, v in scores.items()},
            "tension_index": round(tension, 3), "distribution": dist,
            "convergence_domains": conv,
            "converged": [o for o, n in conv.items() if n >= 3]}
    trace["total_pressure"] = round(total_raw, 2)
    trace["pressure_band"] = band
    trace["structural_law_note"] = (
        f"total pressure {band} ({total_raw:.1f}): P(some transition) "
        + ("high regardless of destination confidence"
           if band in ("high", "saturated") else "moderate/low")
        + f"; resolving surprises likely from: {', '.join(d.get('unmonitored_dimensions', []))}")
    return trace


def render_md(target, question, d, trace, out_md: Path) -> None:
    L = [f"# Convergence trace — {target}", f"**Question:** {question}",
         f"Generated {datetime.date.today().isoformat()} · "
         f"total pressure **{trace['pressure_band']}** ({trace['total_pressure']}) · "
         f"novel regime: {d.get('novel_regime')}", "",
         "## Pressure vectors (post-dedup input to the arithmetic)"]
    kept_ids = {s.split()[0] for h in trace["horizons"].values() for s in h["steps"]
                if s and s[0] == "v"}
    for v in d["vectors"]:
        mark = "" if v["id"] in kept_ids else " *(merged away)*"
        L.append(f"- **{v['id']}** [{v['domain']}] {v['source_form']} → *{v['pushes_toward']}* · "
                 f"{v['severity']}/{v.get('credibility')}cred/{v.get('timescale')}{mark} — "
                 f"{v.get('evidence','')}")
    for n in trace["dedup_notes"]:
        L.append(f"- ⚖ {n}")
    for h in ("short", "long"):
        t = trace["horizons"][h]
        L += ["", f"## {h.capitalize()} horizon", "```"]
        L += t["steps"]
        L += ["```", f"tension index: {t['tension_index']}",
              "**Distribution:** " + " · ".join(f"{o} **{p:.0%}**"
                                                for o, p in t["distribution"].items()),
              ("**CONVERGED** (≥3 independent domains): " + ", ".join(t["converged"]))
              if t["converged"] else "_no ≥3-domain convergence — directional confidence capped_"]
    L += ["", f"## Structural-law note", trace["structural_law_note"],
          "", f"Unmonitored dimensions (butterfly watch): "
          + "; ".join(d.get("unmonitored_dimensions", []))]
    out_md.write_text("\n".join(L), encoding="utf-8")


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def run(target: str, question: str, model: str, horizon_days: int) -> None:
    today = datetime.date.today().isoformat()
    # feed the monitor's logged dynamics for this office, if any
    dyn = []
    lf = RDIR / "dynamics" / "log.jsonl"
    if lf.exists():
        for line in lf.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if target.lower() in r.get("office", "").lower():
                dyn.append(f"[{r.get('monitored')}] {r.get('kind')}: {r.get('what')} "
                           f"({r.get('installer_or_actor','')})")
    p = (VECTOR_PROMPT.replace("{today}", today).replace("{target}", target)
         .replace("{question}", question)
         .replace("{dynamics}", "\n".join(dyn[-15:]) or "(none logged)"))
    print(f"[converge] {target} :: {question}")
    d = None
    for _ in range(3):
        r = chat(model + ":online", [{"role": "user", "content": p}],
                 temperature=0.2, max_tokens=4000)
        d = parse_json(r.text) if not r.error else None
        if d and d.get("vectors"):
            break
        d = None
    if not d:
        raise SystemExit(f"vector extraction failed: {r.error or 'unparseable'}")

    trace = compute(d)
    cdir = RDIR / "converge"
    cdir.mkdir(exist_ok=True)
    slug = slugify(question)
    full = {"target": target, "question": question, "generated": today,
            "extracted_by": model, "input": d, "trace": trace}
    (cdir / f"{slug}.json").write_text(json.dumps(full, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    render_md(target, question, d, trace, cdir / f"{slug}.md")

    sh = trace["horizons"]["short"]
    top, p_top = next(iter(sh["distribution"].items()))
    print(f"  vectors: {len(d['vectors'])} ({len(trace['dedup_notes'])} merges) · "
          f"pressure {trace['pressure_band']} ({trace['total_pressure']}) · "
          f"tension {sh['tension_index']}")
    for o, pp in sh["distribution"].items():
        c = sh["convergence_domains"].get(o, 0)
        print(f"    {pp:.0%}  {o}" + (f"  [CONVERGED: {c} domains]" if o in sh["converged"] else
                                      (f"  ({c} domains)" if c else "")))
    print(f"  -> converge/{slug}.json + .md (full reasoning trace)")

    # ledger claim with the trace as its mechanism
    resolve_by = (d.get("deadline") or
                  (datetime.date.today() + datetime.timedelta(days=horizon_days)).isoformat())
    lpath = RDIR / "predict" / "ledger.json"
    led = json.load(lpath.open(encoding="utf-8"))
    led["rounds"] = led.get("rounds", 0) + 1
    led["predictions"].append({
        "entity": f"converge:{slug}"[:80], "name": f"{target} — {question}"[:90],
        "made_on": today, "resolve_by": resolve_by, "round": led["rounds"],
        "status": "open",
        "claim": f"Outcome of '{question}': {top}"[:250],
        "resolution_criteria": f"The observable decision/outcome by {resolve_by}; "
                               f"'{top}' as defined in the trace's outcome set",
        "confidence": p_top,
        "mechanism": f"pressure-convergence resultant: tension {sh['tension_index']}, "
                     f"pressure {trace['pressure_band']}, converged={sh['converged']}; "
                     f"full reasoning trace at converge/{slug}.json",
        "trace": f"converge/{slug}.json"})
    json.dump(led, lpath.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"  -> ledger claim appended (p={p_top} '{top}', by {resolve_by})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Resultant-vector pressure convergence with reasoning trace.")
    ap.add_argument("--target", required=True, help="office or arena")
    ap.add_argument("--question", required=True, help="the decision/outcome space")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    ap.add_argument("--horizon", type=int, default=45)
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY"):
        if os.environ.get("LLM_BACKEND") != "claude-code":
            raise SystemExit("OPENROUTER_API_KEY not set (or set LLM_BACKEND=claude-code)")
    run(a.target, a.question, a.model, a.horizon)


if __name__ == "__main__":
    main()
