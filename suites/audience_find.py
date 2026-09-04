"""Audience finder — request -> situation dynamics -> resonant demographics, ranked.

Implements the audience-model (sister repo audience-model/MODEL.md): the resonance
premise says attention follows STRUCTURAL RHYME between a situation's dynamics and an
audience's lived pressure structure, not topic. Three steps, one report:

  1. SIGNATURE — classify the request into 1-3 dominant dynamics from the registered
     taxonomy, plus the invited stance (who the viewer gets to be).
  2. SEGMENTS — generate candidate audience segments as LIVED-DYNAMICS bundles
     (position, gatekept-vs-gatekeeping, precarity, status trajectory, verification
     burden) whose lives rhyme with the signature.
  3. RANK — relevance = affinity x reachability x attention budget, each segment with
     its mechanism (WHY it rhymes), its venues, and its anti-segments (who will bounce).

Every output is a candidate (MODEL.md consequence 2 is untested); reports say so.

  python -m suites.audience_find --request "a public ledger of sealed predictions graded against reality"
  python -m suites.audience_find --file ../copilot-template/README.md
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
ADIR = ROOT / "audience"

TAXONOMY = ("underdog-vs-incumbent | gatekeeper-defection | exposed-hypocrisy | "
            "threshold-tipping | quiet-competence-vindicated | betrayal-of-trust | "
            "coalition-of-the-excluded | decay-of-giants | earned-vs-conferred | "
            "escape-exit | stealth-then-reveal | the-bill-comes-due | david-tooling | "
            "verification-crisis")

PROMPT = """You are an audience finder running the resonance model: attention follows STRUCTURAL
RHYME between a situation's dynamics and an audience's lived pressure structure — never mere topic
overlap. Topic-matching is the baseline you must beat; do not produce it.

THE REQUEST (the thing seeking its audience):
{request}

STEP 1 — SIGNATURE. Classify the request's 1-3 dominant situation dynamics from this taxonomy
(no inventions): {taxonomy}. Then name the INVITED STANCE: who does the request invite the
audience to be (the underdog, the judge, the insider, the vindicated, the survivor, the builder)?

STEP 2 — SEGMENTS. Generate 5-7 audience segments defined as LIVED-DYNAMICS bundles, not
demographics-as-usual: position (career stage / institutional role), gatekept vs gatekeeping,
precarity level, status trajectory (rising / blocked / defending), verification burden (how often
they must prove things to skeptics). For each: WHY their lived dynamics rhyme with the signature
(the mechanism, one or two sentences — this is the whole product; generic "they'd find it
interesting" is failure).

STEP 2b — PARALLEL LIKES. For each segment, list parallel_likes: 3-5 OTHER specific things
(creators, books, franchises, games, communities, genres) this segment demonstrably gravitates
to — the parallel-affinity fingerprint. These must share the segment's DYNAMICS, not the
request's topic; they are how you actually find and recognize the segment in the wild.

STEP 3 — RANK by relevance = affinity (strength of rhyme) x reachability (do they congregate
somewhere addressable — name the venues) x attention budget (saturated segments resonate but
cannot attend). Also name 1-2 ANTI-SEGMENTS: who superficially looks like the audience by topic
but will bounce, and why the dynamics predict it.

Return ONLY JSON:
{"signature":{"dynamics":["..."],"stance":"...","read":"2 sentences on what the request IS, dynamically"},
"segments":[{"name":"short handle","bundle":"position/gatekeeping/precarity/trajectory/verification in one line",
"rhyme":"the mechanism","parallel_likes":["..."],"affinity":0.0,"reachability":0.0,"attention_budget":"low|medium|high",
"venues":["..."],"relevance":0.0}],
"anti_segments":[{"name":"...","why_bounce":"..."}],
"honest_note":"one line on the weakest link in this particular analysis"}"""


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def run(request: str, label: str, model: str) -> None:
    ADIR.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    p = PROMPT.replace("{request}", request[:6000]).replace("{taxonomy}", TAXONOMY)
    r = chat(model, [{"role": "user", "content": p}], temperature=0.4, max_tokens=3500)
    d = parse_json(r.text) if not r.error else None
    if not d or not d.get("segments"):
        raise SystemExit(f"audience find failed: {r.error or 'unparseable'}")
    slug = slugify(label)
    d["request_label"] = label
    d["generated"] = today
    d["status"] = "CANDIDATE — the dynamics-beat-topic bet (MODEL.md c.2) is untested"
    (ADIR / f"{slug}.json").write_text(json.dumps(d, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    sig = d.get("signature", {})
    L = [f"# Audience map — {label}", f"Generated {today} · status: CANDIDATE "
         f"(resonance bet untested — hypothesis-generation, not authority)", "",
         f"**Signature:** {' + '.join(sig.get('dynamics', []))} · invited stance: "
         f"**{sig.get('stance','?')}**", f"{sig.get('read','')}", "", "## Ranked segments"]
    for s in sorted(d["segments"], key=lambda x: -float(x.get("relevance", 0))):
        L += [f"### {s.get('relevance',0):.2f} · {s['name']}",
              f"- bundle: {s.get('bundle','')}",
              f"- rhyme: {s.get('rhyme','')}",
              f"- parallel likes: {', '.join(s.get('parallel_likes', []))}",
              f"- venues: {', '.join(s.get('venues', []))} · attention: "
              f"{s.get('attention_budget','?')} · affinity {s.get('affinity','?')} · "
              f"reach {s.get('reachability','?')}", ""]
    L += ["## Anti-segments (topic-matched, dynamics-mismatched)"]
    for a in d.get("anti_segments", []):
        L.append(f"- **{a.get('name','')}** — {a.get('why_bounce','')}")
    L += ["", f"_Weakest link: {d.get('honest_note','')}_"]
    (ADIR / f"{slug}.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:6]))
    for s in sorted(d["segments"], key=lambda x: -float(x.get("relevance", 0)))[:5]:
        print(f"  {s.get('relevance',0):.2f}  {s['name']} — {s.get('rhyme','')[:80]}")
    print(f"-> audience/{slug}.md")


def main() -> None:
    ap = argparse.ArgumentParser(description="Find the resonant audience for a request.")
    ap.add_argument("--request")
    ap.add_argument("--file", help="analyze a file's content as the request")
    ap.add_argument("--label", default="")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    if a.file:
        text = Path(a.file).read_text(encoding="utf-8", errors="replace")
        run(text, a.label or Path(a.file).stem, a.model)
    elif a.request:
        run(a.request, a.label or a.request[:50], a.model)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
