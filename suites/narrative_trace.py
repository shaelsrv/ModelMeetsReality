"""Narrative tracer — decompose the narrative competition around an event.

Implements narrative-model/MODEL.md: sides are found by STAKES (P1), coalitions are
part of the weave (P2), victory is vocabulary adoption (P3), the winner mechanism is
resonance x credibility-fit x channel-match (P4), and the cycle has staged clocks (P5).

  python -m suites.narrative_trace --event "the FIFA presidency controversy" --slug fifa-presidency
  python -m suites.narrative_trace --predict --slug fifa-presidency
  python -m suites.narrative_trace --postmortem --event "..." --slug brexit-referendum
  python -m suites.narrative_trace --list
"""
from __future__ import annotations

import argparse
import datetime
import json
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
REPO = ROOT.parent / "narrative-model"
TDIR = REPO / "traces"
LEDGER = REPO / "predict" / "ledger.json"

TRACE = """You have LIVE WEB ACCESS. Today is {today}. You are a narrative tracer: decompose the
NARRATIVE COMPETITION around one event. An event is raw; a narrative is the event plus a causal
story, a role assignment, and an omission set. Report only weavings that actually exist in
coverage you can find — cite outlets/actors and dates; do not invent sides.

THE EVENT: {event}

For EACH side weaving the event (identify sides by STAKES — whose installed interests the weave
protects — not by stated positions):
- side: who they are; stakes: what they protect/gain.
- weave: causal_story (why it happened, per them) | roles (hero/villain/victim) |
  temporal_frame (crisis|continuity|cycle) | foregrounded (which facts ARE the event, per them) |
  omission_set (what the weave needs the audience not to ask).
- coalition: amplifiers (who repeats it), validators (who lends credibility), beneficiaries
  (who gains if it wins, incl. silent ones).
- modes: media channels actually used (broadcast, print, social platforms, influencers,
  official statements, leaks, memes) with any evidence of emphasis.
- credibility_source: official-authority | expertise | insider-testimony | raw-footage |
  statistics | victim-standing | none-visible.

Then the WHOLE-CYCLE read:
- distinct_weavings: how many genuinely distinct narratives exist (merge restatements).
- stage: seeding | amplification | contestation | consolidation | decay — with the dated
  evidence for the staging.
- vocabulary_watch: for each side, 2-4 marker TERMS whose adoption by neutral outlets would
  signal that side's weave winning (the P3 observable — concrete, checkable phrases).
- current_read: which side's vocabulary is neutral coverage using TODAY, with examples.

Return ONLY JSON:
{"event":"...","sides":[{"side":"...","stakes":"...","weave":{"causal_story":"...","roles":"...",
"temporal_frame":"...","foregrounded":"...","omission_set":"..."},"coalition":{"amplifiers":["..."],
"validators":["..."],"beneficiaries":["..."]},"modes":["..."],"credibility_source":"...",
"marker_terms":["..."]}],
"distinct_weavings":0,"stage":"...","stage_evidence":"dated evidence",
"current_read":"whose vocabulary neutral coverage uses today, with examples",
"honest_note":"weakest link in this trace"}"""

PREDICT = """You are making a PRE-CONSOLIDATION WINNER CALL on a narrative competition, using ONLY the
P4 mechanism: resonance (whose weave rhymes with mass audiences' lived slot structures) x
credibility-fit (does each side's credibility source match what its target audience already
trusts) x channel-match (does the weave travel natively where that audience is). You may NOT
use poll leads or current vocabulary adoption as inputs — the call must come from structure, so
that grading it tests the mechanism.

THE TRACE (produced {trace_date}, stage: {stage}):
{trace}

Score each side 0-1 on resonance, credibility_fit, channel_match (one line of mechanism each);
name the predicted winner; state the vocabulary-adoption resolution test (which marker terms in
neutral outlets by when); set resolve_by ~{horizon}.

Return ONLY JSON:
{"scores":[{"side":"...","resonance":0.0,"credibility_fit":0.0,"channel_match":0.0,
"mechanism":"one line per factor"}],
"predicted_winner":"...","confidence":0.0,
"claim":"one sentence: which side's weave becomes the default retelling",
"resolution_criteria":"the vocabulary-adoption test, concrete and checkable",
"resolve_by":"YYYY-MM-DD","reasoning_trace":"3-5 lines: the P4 arithmetic in words"}"""

POSTMORTEM = """You have LIVE WEB ACCESS. Today is {today}. Run a narrative-cycle POSTMORTEM on a
SETTLED narrative competition — one where the default retelling has consolidated. Ground every
judgment in checkable coverage.

THE SETTLED EVENT/CYCLE: {event}

Determine:
- winner: which side's weave became the default retelling; the vocabulary-adoption evidence
  (whose terms neutral sources use now).
- why_won: decompose per the fit mechanism — resonance (what audience slot structure it rhymed
  with), credibility_fit (source vs audience trust), channel_match, plus simplicity (did it
  survive retelling hops intact).
- why_lost: the losing side's named failure — right-story-wrong-messenger |
  wrong-channel | too-complex-to-retell | late-stage-contest-with-seeding-tactics |
  credibility-mismatch | omission-set-exposed | other (name it).
- avoid_list: 2-4 transferable DON'Ts extracted from the losing side, stated generally.
- stage_dates: rough dates for seeding/amplification/contestation/consolidation.
- spend_note: if the losing side had more reach/budget, say so — that is the P4
  fit-beats-spend evidence.

Return ONLY JSON:
{"winner":"...","vocabulary_evidence":"...","why_won":{"resonance":"...","credibility_fit":"...",
"channel_match":"...","simplicity":"..."},"why_lost":{"side":"...","failure":"...","detail":"..."},
"avoid_list":["..."],"stage_dates":"...","spend_note":"...","honest_note":"weakest link"}"""


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def _write_md(slug: str, d: dict, kind: str) -> Path:
    L = [f"# Narrative trace — {d.get('event', slug)}",
         f"{kind} · {datetime.date.today().isoformat()} · status: CANDIDATE reading "
         f"(MODEL.md consequence 1 ungraded)", ""]
    for s in d.get("sides", []):
        w, c = s.get("weave", {}), s.get("coalition", {})
        L += [f"## Side: {s.get('side','?')}",
              f"- stakes: {s.get('stakes','')}",
              f"- causal story: {w.get('causal_story','')}",
              f"- roles: {w.get('roles','')} · frame: {w.get('temporal_frame','')}",
              f"- foregrounded: {w.get('foregrounded','')}",
              f"- omission set: {w.get('omission_set','')}",
              f"- amplifiers: {', '.join(c.get('amplifiers', []))}",
              f"- validators: {', '.join(c.get('validators', []))}",
              f"- beneficiaries: {', '.join(c.get('beneficiaries', []))}",
              f"- modes: {', '.join(s.get('modes', []))} · credibility: "
              f"{s.get('credibility_source','')}",
              f"- marker terms (P3 watch): {', '.join(s.get('marker_terms', []))}", ""]
    L += [f"**Distinct weavings:** {d.get('distinct_weavings','?')} · **stage:** "
          f"{d.get('stage','?')} ({d.get('stage_evidence','')})",
          f"**Current vocabulary read:** {d.get('current_read','')}", "",
          f"_Weakest link: {d.get('honest_note','')}_"]
    out = TDIR / f"{slug}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out


def cmd_trace(event: str, slug: str, model: str) -> None:
    TDIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    p = TRACE.replace("{today}", today).replace("{event}", event)
    r = chat(model + ":online", [{"role": "user", "content": p}],
             temperature=0.3, max_tokens=4000)
    d = parse_json(r.text) if not r.error else None
    if not d or not d.get("sides"):
        raise SystemExit(f"trace failed: {r.error or 'unparseable'}")
    d["event"], d["traced"] = event, today
    (TDIR / f"{slug}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    out = _write_md(slug, d, "live trace")
    print(f"[{slug}] {len(d['sides'])} sides · {d.get('distinct_weavings','?')} weavings · "
          f"stage {d.get('stage','?')}")
    for s in d["sides"]:
        print(f"  - {s.get('side','?')[:44]:<46} cred={s.get('credibility_source','?'):<18}"
              f"terms: {', '.join(s.get('marker_terms', [])[:2])}")
    print(f"  read: {d.get('current_read','')[:110]}")
    print(f"-> {out}")


def cmd_predict(slug: str, model: str, horizon: str) -> None:
    tf = TDIR / f"{slug}.json"
    if not tf.exists():
        raise SystemExit(f"no trace {slug} — run --event first")
    t = json.load(tf.open(encoding="utf-8"))
    if t.get("stage") in ("consolidation", "decay"):
        raise SystemExit(f"stage is {t['stage']} — P5: pre-consolidation calls only "
                         f"(use --postmortem instead)")
    p = (PREDICT.replace("{trace_date}", t.get("traced", "?"))
         .replace("{stage}", t.get("stage", "?"))
         .replace("{trace}", json.dumps(t, ensure_ascii=False)[:8000])
         .replace("{horizon}", horizon))
    r = chat(model, [{"role": "user", "content": p}], temperature=0.3, max_tokens=2000)
    d = parse_json(r.text) if not r.error else None
    if not d or not d.get("claim"):
        raise SystemExit(f"predict failed: {r.error or 'unparseable'}")
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    led = json.load(LEDGER.open(encoding="utf-8")) if LEDGER.exists() else {"predictions": []}
    led["predictions"].append({
        "made_on": datetime.date.today().isoformat(), "slug": slug,
        "entity": t.get("event", slug), "claim": d["claim"],
        "resolution_criteria": d.get("resolution_criteria", ""),
        "confidence": d.get("confidence"), "resolve_by": d.get("resolve_by", ""),
        "mechanism": d.get("reasoning_trace", ""), "scores": d.get("scores", []),
        "predicted_winner": d.get("predicted_winner", ""), "status": "open"})
    json.dump(led, LEDGER.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[{slug}] WINNER CALL: {d.get('predicted_winner','?')} "
          f"(conf {d.get('confidence','?')}, resolve_by {d.get('resolve_by','?')})")
    for s in d.get("scores", []):
        print(f"  {s.get('side','?')[:40]:<42} res={s.get('resonance','?')} "
              f"cred={s.get('credibility_fit','?')} chan={s.get('channel_match','?')}")
    print(f"  test: {d.get('resolution_criteria','')[:120]}")
    print(f"-> {LEDGER}")


def cmd_postmortem(event: str, slug: str, model: str) -> None:
    TDIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    p = POSTMORTEM.replace("{today}", today).replace("{event}", event)
    r = chat(model + ":online", [{"role": "user", "content": p}],
             temperature=0.3, max_tokens=3000)
    d = parse_json(r.text) if not r.error else None
    if not d or not d.get("winner"):
        raise SystemExit(f"postmortem failed: {r.error or 'unparseable'}")
    d["event"], d["run"] = event, today
    (TDIR / f"{slug}.postmortem.json").write_text(
        json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    ww, wl = d.get("why_won", {}), d.get("why_lost", {})
    lessons = REPO / "LESSONS.md"
    entry = [f"## {today} — {event}",
             f"- winner: {d['winner']} · vocabulary: {d.get('vocabulary_evidence','')[:160]}",
             f"- won on: resonance: {ww.get('resonance','')[:120]} | cred-fit: "
             f"{ww.get('credibility_fit','')[:120]} | channel: {ww.get('channel_match','')[:100]}"
             f" | simplicity: {ww.get('simplicity','')[:100]}",
             f"- lost ({wl.get('side','?')}): {wl.get('failure','?')} — {wl.get('detail','')[:160]}",
             f"- spend note: {d.get('spend_note','')[:140]}"]
    entry += [f"- AVOID: {a}" for a in d.get("avoid_list", [])] + [""]
    old = lessons.read_text(encoding="utf-8") if lessons.exists() else \
        "# Narrative lessons — settled-cycle postmortems (newest first)\n\n"
    head, _, rest = old.partition("\n\n")
    lessons.write_text(head + "\n\n" + "\n".join(entry) + rest, encoding="utf-8")
    print(f"[{slug}] winner: {d['winner']}")
    print(f"  lost: {wl.get('side','?')} — {wl.get('failure','?')}")
    for a in d.get("avoid_list", []):
        print(f"  AVOID: {a}")
    print(f"-> {lessons}")


def cmd_list() -> None:
    if TDIR.exists():
        for f in sorted(TDIR.glob("*.json")):
            d = json.load(f.open(encoding="utf-8"))
            kind = "postmortem" if f.name.endswith(".postmortem.json") else \
                f"trace/{d.get('stage','?')}"
            print(f"  [{kind:>18}] {f.stem.replace('.postmortem','')} — "
                  f"{d.get('event','')[:70]}")
    if LEDGER.exists():
        for p in json.load(LEDGER.open(encoding="utf-8"))["predictions"]:
            print(f"  [{p['status']:>18}] CALL {p.get('slug','')} -> "
                  f"{p.get('predicted_winner','')[:50]} (by {p.get('resolve_by','')})")


def main() -> None:
    ap = argparse.ArgumentParser(description="Trace narrative competitions around events.")
    ap.add_argument("--event")
    ap.add_argument("--slug", default="")
    ap.add_argument("--predict", action="store_true")
    ap.add_argument("--postmortem", action="store_true")
    ap.add_argument("--horizon", default="60-90 days out")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="traces land in the repo and calls land in a graded ledger — STRONG tier")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.list:
        cmd_list(); return
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    if a.postmortem:
        if not a.event:
            raise SystemExit("--postmortem needs --event")
        cmd_postmortem(a.event, a.slug or slugify(a.event), a.model)
    elif a.predict:
        if not a.slug:
            raise SystemExit("--predict needs --slug of an existing trace")
        cmd_predict(a.slug, a.model, a.horizon)
    elif a.event:
        cmd_trace(a.event, a.slug or slugify(a.event), a.model)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
