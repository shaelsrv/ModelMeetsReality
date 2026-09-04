"""Brainstorm — study one event through 2+ models at once, then synthesize.

Stage 1 (parallel): each chosen model reads the event through ITS mechanism only —
what it notices that others structurally cannot, and one falsifiable expectation.
Stage 2: synthesis — convergences, tensions (who would be right under what),
crossed insights (what two mechanisms produce that neither does alone), and 1-3
JOINT candidate claims with criteria. Results land in brainstorms/<id>.{json,md}
and render in the cockpit's Brainstorm tab.

  python -m suites.brainstorm --event "..." --models my-model,my-other-model
  python -m suites.brainstorm --list
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.openrouter import chat  # noqa: E402
from harness.actors import parse_json  # noqa: E402
from suites.attribute_outcomes import MENU  # noqa: E402  (mechanism one-liners)

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT.parent
BDIR = ROOT / "brainstorms"

LENS = """You are ONE model in a multi-model brainstorm. Read the event through THIS model's
mechanism ONLY — resist general-purpose analysis; if the mechanism has little grip here, say so
(a weak-grip admission is more useful than a stretched reading).

YOUR MODEL: {name} — {mech}
MODEL DOCUMENT EXCERPT:
{doc}

THE EVENT:
{event}

Return ONLY JSON:
{"grip":"strong|moderate|weak","read":"3-5 lines: what THIS mechanism says is happening",
"unique":"1-2 lines: what this model notices that other lenses structurally cannot",
"expectation":{"claim":"one falsifiable expectation about how this develops","resolve_by":"YYYY-MM-DD",
"confidence":0.0}}"""

ADVERSARY = """You are the DEVIL'S ADVOCATE — the family's designated adversary. The lens reads
below are converging on something. Your mechanism is the COUNTER-CASE: the null is a model
(friction, base rates, mean reversion, selection effects in what gets covered), and consensus is
evidence of shared priors before it is evidence of truth.

THE EVENT:
{event}

THE LENS READS:
{lenses}

Produce:
- shared_prior: what prior do the converging lenses share (same salient article? same
  prediction-shaped hole? same training data?) that could explain convergence without truth.
- counter_case: the strongest 3-5 line argument that the exciting reading is wrong and the
  base rate holds.
- weakest_convergence: which specific emerging consensus is most likely groupthink, and why.
- null_claims: 1-2 registrable NULL claims (dated, with criteria) betting AGAINST the ensemble —
  you are graded like everyone else.

Return ONLY JSON:
{"shared_prior":"...","counter_case":"...","weakest_convergence":"...",
"null_claims":[{"claim":"...","resolution_criteria":"...","resolve_by":"YYYY-MM-DD","confidence":0.0}]}"""

LIBRARIAN = """You are the BASE-RATE LIBRARIAN — the outside view. Ignore the lens mechanisms
below entirely at first. Name the historical REFERENCE CLASS this event belongs to (class first,
THEN the rate, THEN the probability — class-shopping after the answer is the failure mode), and
forecast the ensemble's emerging expectations from base rates alone.

THE EVENT:
{event}

THE LENS READS (only to see what they expect — do not adopt their mechanisms):
{lenses}

Return ONLY JSON:
{"reference_class":"what class of past events this is, stated precisely",
"class_size":"rough n and where the instances come from",
"base_rate":"what fraction of the class went the way the lenses expect",
"outside_view":"2-3 lines: what the base rate alone predicts here",
"disagreement":"where the outside view and the lenses part ways, in one line"}"""

OCCAM = """You are the SIMPLICITY JUDGE (Occam). The lens reads below are mechanism-rich. Construct
the SIMPLEST SUFFICIENT explanation of this event — noise, logistics, incompetence, coincidence,
ordinary churn — using strictly fewer entities, intentions, and coordination steps than the
lenses require. Then bet.

THE EVENT:
{event}

THE LENS READS:
{lenses}

Return ONLY JSON:
{"boring_explanation":"3-4 lines: the simplest sufficient account",
"complexity_saved":"what entities/intentions/coordination the lenses assume that this drops",
"where_boring_loses":"the one observation that would force the exciting reading",
"bet":"one line: which reading you'd put money on and at what odds"}"""

SYNTH = """You are synthesizing a multi-model brainstorm of one event. The lens reads below each
used a single mechanism. Your job is the STRUCTURE BETWEEN them, not a summary.

THE EVENT:
{event}

LENS READS:
{lenses}

THE CHALLENGE PANEL (mandatory — you MUST answer each, not ignore them):
- DEVIL'S ADVOCATE: {adversary}
- BASE-RATE LIBRARIAN (outside view): {librarian}
- SIMPLICITY JUDGE (Occam): {occam}

Produce:
- convergences: where 2+ mechanisms independently point the same way (name the models).
- tensions: where mechanisms genuinely disagree — state each side and WHAT OBSERVABLE would
  decide who is right (tensions without deciders are just vibes).
- crossed: 1-2 insights that emerge only from COMBINING two mechanisms (name the pair) —
  something neither lens produced alone.
- joint_claims: 1-3 candidate claims the ensemble would register, each with resolution
  criteria and a date; mark which models back each.
- load_bearing: which single model matters most for THIS event, one line why.

Return ONLY JSON:
{"convergences":[{"models":["..."],"point":"..."}],
"tensions":[{"models":["..."],"sides":"A says X; B says Y","decider":"the observable that settles it"}],
"crossed":[{"pair":["..."],"insight":"..."}],
"joint_claims":[{"claim":"...","resolution_criteria":"...","resolve_by":"YYYY-MM-DD",
"confidence":0.0,"backed_by":["..."]}],
"load_bearing":{"model":"...","why":"..."},
"da_response":"3-6 lines: your answer to the PANEL — per challenger, what you concede (downgrade
the affected claim) and what you rebut, with the reason; an unanswered challenger is a defect",
"honest_note":"weakest link of this brainstorm"}"""


def _doc(name):
    p = TOOLS / name / "MODEL.md"
    if not p.exists():
        p = TOOLS / "canon" / "models" / f"{name}.md"
    return p.read_text(encoding="utf-8", errors="replace")[:2500] if p.exists() else "(no doc)"


def run(event: str, models: list[str], model_llm: str, bid: str | None) -> None:
    BDIR.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    bid = bid or f"bs-{today}-{len(list(BDIR.glob('*.json')))+1}"

    def lens(name):
        p = (LENS.replace("{name}", name)
             .replace("{mech}", MENU.get(name, "(mechanism per its MODEL.md)"))
             .replace("{doc}", _doc(name)).replace("{event}", event[:3000]))
        r = chat(model_llm, [{"role": "user", "content": p}], temperature=0.4, max_tokens=1200)
        d = parse_json(r.text) if not r.error else None
        return name, d

    with ThreadPoolExecutor(max_workers=4) as ex:
        reads = dict(ex.map(lens, models))
    reads = {k: v for k, v in reads.items() if v}
    if len(reads) < 2:
        raise SystemExit(f"only {len(reads)} lens read(s) succeeded — need 2+")
    lens_text = "\n\n".join(f"### {k} (grip: {v.get('grip','?')})\nread: {v.get('read','')}\n"
                            f"unique: {v.get('unique','')}\n"
                            f"expectation: {json.dumps(v.get('expectation',{}), ensure_ascii=False)}"
                            for k, v in reads.items())
    # mandatory challenge panel — adversary + outside view + Occam, never deselectable
    def challenge(tmpl):
        rr = chat(model_llm, [{"role": "user", "content":
                               tmpl.replace("{event}", event[:3000])
                               .replace("{lenses}", lens_text)}],
                  temperature=0.4, max_tokens=1400)
        return parse_json(rr.text) if not rr.error else None
    with ThreadPoolExecutor(max_workers=3) as ex:
        da, libr, occ = list(ex.map(challenge, [ADVERSARY, LIBRARIAN, OCCAM]))
    fail = "(pass failed — treat the convergences as unchallenged on this front and say so)"
    r = chat(model_llm, [{"role": "user", "content":
                          SYNTH.replace("{event}", event[:3000]).replace("{lenses}", lens_text)
                          .replace("{adversary}", json.dumps(da, ensure_ascii=False) if da else fail)
                          .replace("{librarian}", json.dumps(libr, ensure_ascii=False) if libr else fail)
                          .replace("{occam}", json.dumps(occ, ensure_ascii=False) if occ else fail)}],
             temperature=0.4, max_tokens=2400)
    syn = parse_json(r.text) if not r.error else None
    if not syn:
        raise SystemExit(f"synthesis failed: {r.error or 'unparseable'}")
    # adversary null claims are registrable alongside joint claims
    if da:
        for nc in da.get("null_claims", []):
            nc["backed_by"] = ["devils-advocate"]
            syn.setdefault("joint_claims", []).append(nc)
    out = {"id": bid, "at": today, "event": event[:1200], "models": models,
           "lenses": reads, "adversary": da, "librarian": libr, "occam": occ,
           "synthesis": syn, "status": "done"}
    (BDIR / f"{bid}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    L = [f"# Brainstorm {bid}", f"{today} · models: {', '.join(models)}", "",
         f"**Event:** {event[:400]}", "", "## Lens reads"]
    for k, v in reads.items():
        L += [f"### {k} (grip: {v.get('grip','?')})", v.get("read", ""),
              f"*unique:* {v.get('unique','')}",
              f"*expectation:* {v.get('expectation',{}).get('claim','')} "
              f"(by {v.get('expectation',{}).get('resolve_by','?')})", ""]
    L += ["## Synthesis"]
    for c in syn.get("convergences", []):
        L.append(f"- CONVERGE [{', '.join(c.get('models', []))}]: {c.get('point','')}")
    for t in syn.get("tensions", []):
        L.append(f"- TENSION [{', '.join(t.get('models', []))}]: {t.get('sides','')} "
                 f"→ decider: {t.get('decider','')}")
    for x in syn.get("crossed", []):
        L.append(f"- CROSSED [{' x '.join(x.get('pair', []))}]: {x.get('insight','')}")
    L.append("")
    for jc in syn.get("joint_claims", []):
        L.append(f"- JOINT CLAIM ({jc.get('confidence','?')}, by {jc.get('resolve_by','?')}, "
                 f"backed by {', '.join(jc.get('backed_by', []))}): {jc.get('claim','')}")
    L += ["", "## Challenge panel (mandatory)"]
    if da:
        L += [f"**Devil's advocate** — shared prior: {da.get('shared_prior','')} · "
              f"counter-case: {da.get('counter_case','')} · weakest convergence: "
              f"{da.get('weakest_convergence','')}"]
    if libr:
        L += [f"**Base-rate librarian** — class: {libr.get('reference_class','')} "
              f"(n: {libr.get('class_size','?')}; rate: {libr.get('base_rate','?')}) · "
              f"outside view: {libr.get('outside_view','')} · parts ways: "
              f"{libr.get('disagreement','')}"]
    if occ:
        L += [f"**Simplicity judge** — boring explanation: {occ.get('boring_explanation','')} · "
              f"where boring loses: {occ.get('where_boring_loses','')} · bet: {occ.get('bet','')}"]
    L += [f"*Synthesis answers the panel:* {syn.get('da_response','(unanswered — flag this)')}"]
    lb = syn.get("load_bearing", {})
    L += ["", f"**Load-bearing model:** {lb.get('model','?')} — {lb.get('why','')}",
          f"_Weakest link: {syn.get('honest_note','')}_"]
    (BDIR / f"{bid}.md").write_text("\n".join(L), encoding="utf-8")
    q = BDIR / f"{bid}.queued.json"
    if q.exists():
        q.unlink()  # live delivery: the UI's queued card flips to the result on next poll
    print("\n".join(L))
    print(f"-> brainstorms/{bid}.md")


def main():
    ap = argparse.ArgumentParser(description="Multi-model brainstorm of one event.")
    ap.add_argument("--event")
    ap.add_argument("--models", help="comma-separated, 2+ (fleet names or canon card slugs)")
    ap.add_argument("--id")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.list:
        for f in sorted(BDIR.glob("*.json")):
            d = json.load(f.open(encoding="utf-8"))
            print(f"  [{d['at']}] {d['id']} · {', '.join(d['models'])} — {d['event'][:60]}")
        return
    if not (a.event and a.models):
        raise SystemExit("--event and --models required (2+ comma-separated)")
    models = [m.strip() for m in a.models.split(",") if m.strip()]
    if len(models) < 2:
        raise SystemExit("need 2+ models — that is the whole point")
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    run(a.event, models, a.model, a.id)


if __name__ == "__main__":
    main()
