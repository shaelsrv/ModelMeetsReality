"""Worldview modeling — a person's model of the world, built, consistency-checked,
classifier-mapped, and extrapolation-tested.

The Patel exercise completed: where model_import turns an analyst's CLAIMS into graded
ledgers, this models the WORLDVIEW behind them — then tests whether our model of their
model is any good by extrapolating it into domains they have not addressed and grading
the extrapolations.

Per analyst (from a multi-video transcript corpus, dated banners):

  1. WORLDVIEW.md — their model, written like a family MODEL.md: premises with
     confidence tiers, causal mechanisms, POWER-DYNAMICS REASONING (how they attribute
     agency and force), domains covered, signature vocabulary.
  2. CONSISTENCY.md — the historical-consistency audit across dated pieces: the stable
     core, drifts (dated), outright contradictions, and a consistency grade. A worldview
     that shifts silently is a different object from one that updates openly.
  3. CLASSIFIER_MAP.md — the two classifier meta-models applied to the PERSON:
     which E0–E14 floors their reasoning operates on (and their characteristic
     cross-level moves / hinge behavior), and their implicit legitimacy model — which
     power/legitimacy sources they credit, which they are blind to.
  4. extrapolations ledger — falsifiable predictions in domains the analyst has NOT
     covered, elicited from WORLDVIEW.md as the lens. LABELING IS MANDATORY: these are
     OUR MODEL OF THEIR MODEL, never attributable to the person. Grading them tests the
     worldview model: if extrapolations grade like the analyst's own claims grade, the
     model captured something real; if they diverge, our model of them is wrong — a
     falsifiable claim about a model of a mind, which is the point.

  python -m suites.worldview --build my-model --speaker "my-model" --inbox inbox/my-model
  python -m suites.worldview --extrapolate my-model --domain "AI datacenter buildout"
  python -m suites.worldview --status my-model
"""
from __future__ import annotations

import argparse
import datetime
import glob
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
WDIR = ROOT / "povs" / "worldviews"

WORLDVIEW_PROMPT = """You are modeling a person's WORLDVIEW from their own words — the model of the
world that generates their statements. Source: dated transcripts below, all by {speaker}.

Write their worldview as a rigorous model document with these sections:
1. DOMAIN & STANCE — what they model, from what position, with what incentives.
2. PREMISES — their load-bearing beliefs as numbered premises, each with a confidence tier as
   THEY hold it (asserted-bedrock / working-assumption / speculative) and 1-2 verbatim-ish
   supporting references (video + date).
3. MECHANISMS — the causal machines they reason with (e.g. "demography drives X via Y"), stated
   as mechanisms, with where they apply them.
4. POWER-DYNAMICS REASONING — how they attribute power and agency: who can act in their world,
   through what levers, what makes actors strong/weak, how they think coercion/legitimacy/
   capability interact. Quote their characteristic moves.
5. DOMAINS COVERED vs NOT — what their corpus addresses; what visibly adjacent domains it never
   touches (candidates for extrapolation).
6. SIGNATURE VOCABULARY — their coined or characteristic terms and what work each does.

Faithful, not flattering: preserve their confidence tiers, note where they hedge vs assert.

TRANSCRIPTS:
{corpus}

Return the model document as plain markdown (no JSON)."""

CONSISTENCY_PROMPT = """You are auditing the HISTORICAL CONSISTENCY of one person's worldview across
their dated statements. Source: the dated transcripts below, all by {speaker}.

Report:
1. STABLE CORE — premises/mechanisms held constant across all pieces (with dates spanning).
2. DRIFTS — positions that shifted over time: from what, to what, dated, and whether the shift
   was acknowledged (open updating) or silent.
3. CONTRADICTIONS — statements in tension with each other (quote both sides, dated). Judge
   strictly: rhetorical emphasis differences are not contradictions; incompatible predictions or
   incompatible mechanisms are.
4. CONSISTENCY GRADE — one of: rigid (never updates) | coherent-updating (changes openly with
   reasons) | drifting (changes silently) | contradictory (holds incompatibles simultaneously),
   with a one-paragraph justification.

TRANSCRIPTS:
{corpus}

Return plain markdown."""

CLASSIFY_PROMPT = """Two classifier lenses applied to a PERSON's reasoning style, based on their
worldview model below.

LENS 1 — E-LEVEL MAP (E0-E14 ladder: E0-E8 substrate floors physics->chemistry->biology->minds;
E9-E14 coordination floors: attention/memes(E9), institutions(E10), economy(E11), states(E12),
epistemes(E13), civilizational(E14); E8/E9 is the hinge):
- Which floors does their reasoning natively operate on? (primary, secondary)
- Their characteristic cross-level moves (e.g. "argues from E3-geography to E12-state behavior")
- Hinge behavior: do they cross the substrate/coordination seam, and how carefully?
- Floors they never touch — the structural blind spots.

LENS 2 — LEGITIMACY MAP:
- Which POWER sources do they credit as real? (coercive-capacity, capital, legal-authority,
  agenda-control, network-position, information-asymmetry, operational-control)
- Which LEGITIMACY sources do they treat as mattering? (electoral, legal-constitutional,
  traditional, expertise, performance-track-record, charismatic, institutional-embedding,
  procedural)
- How do they handle power-legitimacy GAPS — do they even distinguish the two?
- Their implicit theory of why actors obey/comply — and what that theory cannot see.

WORLDVIEW MODEL:
{worldview}

Return plain markdown with the two lens sections."""

EXTRAP_PROMPT = """You are running a MODEL OF A PERSON'S WORLDVIEW as a forecasting instrument in a
domain the person has NOT publicly addressed. You are not predicting what they would say; you are
running their model's mechanisms on new terrain.

=== THE WORLDVIEW MODEL (of {speaker}, as constructed by us) ===
{worldview}
=== END MODEL ===

DOMAIN (not covered in their corpus): {domain}
Today is {today}.

Apply THEIR premises and mechanisms — especially their power-dynamics reasoning — to this domain.
Produce exactly 3 falsifiable SHORT-TERM predictions resolving by {resolve_by}: concrete
observables, checkable by search on that date, each with the mechanism OF THEIRS that drives it.
QUALITY BAR: a smart skeptic could bet against each. If their model genuinely cannot reach this
domain, say so for that slot instead of forcing it.

Return ONLY JSON:
{"reachable":true,"predictions":[{"claim":"...","resolution_criteria":"...",
"confidence":0.0,"their_mechanism":"which of their mechanisms drives this"}],
"unreachable_note":""}"""


def _corpus(inbox: Path, cap: int = 60000) -> str:
    parts = []
    for t in sorted(inbox.glob("transcript_*.txt")):
        vid = t.stem.replace("transcript_", "")
        src = inbox / f"source_{vid}.json"
        meta = json.load(src.open(encoding="utf-8")) if src.exists() else {}
        head = (f"===== VIDEO {meta.get('published','?')} :: "
                f"{meta.get('title', vid)[:80]} =====")
        parts.append(head + "\n" + t.read_text(encoding="utf-8"))
    corpus = "\n\n".join(parts)
    if len(corpus) > cap:
        # proportional trim per piece, keeping every dated banner
        ratio = cap / len(corpus)
        parts = [p[:max(2000, int(len(p) * ratio))] for p in parts]
        corpus = "\n\n".join(parts)
    return corpus


def cmd_build(slug: str, speaker: str, inbox: str, model: str) -> None:
    out = WDIR / slug
    out.mkdir(parents=True, exist_ok=True)
    corpus = _corpus(ROOT / inbox)
    print(f"[worldview:{slug}] corpus {len(corpus):,} chars — building ({model})…")
    steps = [
        ("WORLDVIEW.md", WORLDVIEW_PROMPT.replace("{speaker}", speaker)
         .replace("{corpus}", corpus), 7000),
        ("CONSISTENCY.md", CONSISTENCY_PROMPT.replace("{speaker}", speaker)
         .replace("{corpus}", corpus), 5000),
    ]
    for fname, prompt, mt in steps:
        r = chat(model, [{"role": "user", "content": prompt}], temperature=0.3, max_tokens=mt)
        if r.error or not r.text.strip():
            raise SystemExit(f"{fname} failed: {r.error or 'empty'}")
        (out / fname).write_text(r.text, encoding="utf-8")
        print(f"  -> {fname} ({len(r.text):,} chars)")
    wv = (out / "WORLDVIEW.md").read_text(encoding="utf-8")
    r = chat(model, [{"role": "user", "content":
                      CLASSIFY_PROMPT.replace("{worldview}", wv[:20000])}],
             temperature=0.2, max_tokens=4000)
    if not r.error and r.text.strip():
        (out / "CLASSIFIER_MAP.md").write_text(r.text, encoding="utf-8")
        print(f"  -> CLASSIFIER_MAP.md ({len(r.text):,} chars)")
    meta = {"slug": slug, "speaker": speaker, "built": datetime.date.today().isoformat(),
            "inbox": inbox, "corpus_chars": len(corpus), "built_with": model}
    (out / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(f"[worldview:{slug}] built.")


def cmd_extrapolate(slug: str, domain: str, model: str, horizon: int) -> None:
    out = WDIR / slug
    wv = (out / "WORLDVIEW.md").read_text(encoding="utf-8")
    meta = json.load((out / "meta.json").open(encoding="utf-8"))
    today = datetime.date.today().isoformat()
    resolve_by = (datetime.date.today() + datetime.timedelta(days=horizon)).isoformat()
    p = (EXTRAP_PROMPT.replace("{speaker}", meta["speaker"])
         .replace("{worldview}", wv[:16000]).replace("{domain}", domain)
         .replace("{today}", today).replace("{resolve_by}", resolve_by))
    r = chat(model + ":online", [{"role": "user", "content": p}],
             temperature=0.3, max_tokens=2200)
    d = parse_json(r.text) if not r.error else None
    if not d:
        raise SystemExit(f"extrapolation failed: {r.error or 'unparseable'}")
    lpath = out / "extrapolations.json"
    led = (json.load(lpath.open(encoding="utf-8")) if lpath.exists()
           else {"predictions": [], "learnings": [], "rounds": 0,
                 "LABEL": "OUR model of {}'s worldview, extrapolated — NOT their claims"
                 .format(meta["speaker"])})
    led["rounds"] += 1
    if not d.get("reachable", True):
        print(f"  model-of-{slug} judges domain unreachable: {d.get('unreachable_note','')[:120]}")
    for pred in d.get("predictions", []):
        led["predictions"].append({
            "entity": f"extrap:{re.sub(r'[^a-z0-9]+', '-', domain.lower())[:40]}",
            "name": f"[model-of-{meta['speaker']}] {domain}"[:90],
            "made_on": today, "resolve_by": resolve_by, "round": led["rounds"],
            "status": "open", "claim": pred.get("claim", "")[:250],
            "resolution_criteria": pred.get("resolution_criteria", ""),
            "confidence": pred.get("confidence"),
            "mechanism": "extrapolated: " + pred.get("their_mechanism", "")[:180]})
        print(f"  [{pred.get('confidence','?')}] {pred.get('claim','')[:85]}")
    json.dump(led, lpath.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"  -> {lpath.relative_to(ROOT)} ({len(led['predictions'])} extrapolations)")


def cmd_status(slug: str) -> None:
    out = WDIR / slug
    for f in ("WORLDVIEW.md", "CONSISTENCY.md", "CLASSIFIER_MAP.md", "extrapolations.json"):
        p = out / f
        print(f"  {'✓' if p.exists() else '·'} {f}"
              + (f" ({p.stat().st_size:,}B)" if p.exists() else ""))


def main() -> None:
    ap = argparse.ArgumentParser(description="Model a person's worldview; test it by extrapolation.")
    ap.add_argument("--build", metavar="SLUG")
    ap.add_argument("--speaker", default="")
    ap.add_argument("--inbox", default="")
    ap.add_argument("--extrapolate", metavar="SLUG")
    ap.add_argument("--domain", default="")
    ap.add_argument("--status", metavar="SLUG")
    ap.add_argument("--model", default="openai/gpt-5",
                    help="worldview synthesis is judgment-shaped -> reasoning model")
    ap.add_argument("--horizon", type=int, default=45)
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    if a.status:
        cmd_status(a.status)
        return
    if not os.environ.get("OPENROUTER_API_KEY"):
        raise SystemExit("OPENROUTER_API_KEY not set")
    if a.build:
        if not (a.speaker and a.inbox):
            raise SystemExit("--build needs --speaker and --inbox")
        cmd_build(a.build, a.speaker, a.inbox, a.model)
    if a.extrapolate:
        if not a.domain:
            raise SystemExit("--extrapolate needs --domain")
        cmd_extrapolate(a.extrapolate, a.domain, a.model, a.horizon)


if __name__ == "__main__":
    main()
