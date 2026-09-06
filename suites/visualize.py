"""Generate a visual synthesis of the analysis this instance has already done.

Reads the STRUCTURED artifacts -- the claim ledgers, the model graph, the event
history, the fleet index -- and asks the configured model to lay them out as a
spec. A deterministic renderer turns that spec into one self-contained HTML file.

    python -m suites.visualize --view claims
    python -m suites.visualize --view mindmap --title "F1 2026"
    python -m suites.visualize --list

THREE RULES, EACH LOAD-BEARING

1. THE MODEL EMITS A SPEC, NEVER HTML. Model output is data, not markup: letting
   it write HTML/JS would put generated text into the DOM of a page the operator
   opens. It is also why a spec beats a one-shot render -- specs re-render when
   the renderer improves.

2. EVERY NODE CARRIES A SOURCE REF, OR IT IS DROPPED. A ref is a claim id, event
   id or model slug that EXISTS in the artifacts. This is validate_citations
   applied to internal references instead of URLs, and for the same reason: a
   confident synthesis that cannot be traced back is the failure mode of every
   "summarize my notes" tool.

3. THE LEDGER'S OWN VOCABULARY SURVIVES. A claim that is `void` renders as void;
   a `miss` renders as a miss; a candidate is never promoted to a finding. The
   discipline the analysis was written under does not get flattened by the thing
   that visualises it.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
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
WORK = ROOT.parent
OUT = WORK / "visuals"

VIEWS = {
    "claims": "the claim record — what is open, graded, void, and how confident",
    "mindmap": "how the models and their subjects relate",
    "gaps": "what the analysis says is missing or unresolved",
}

PROMPT = """You are laying out a visual synthesis of analysis that has ALREADY been done.
You are not adding conclusions. You are arranging what exists so a reader can see it.

VIEW: {view} — {view_desc}

THE SOURCE MATERIAL
{sources}

RULES THAT DECIDE WHETHER YOUR OUTPUT IS USABLE

1. EVERY node and callout MUST carry a "ref" that appears VERBATIM in the source
   material above — a claim id, an event id, or a model slug. A node whose ref
   does not appear in the sources is DROPPED before rendering, so an unreferenced
   node is wasted output, not a bonus.

2. USE THE RECORD'S OWN WORDS. If the ledger says a claim is `void`, it is void.
   If a verdict is `miss`, it is a miss. Never write "finding" where the source
   says "candidate". Never round a confidence up. Never resolve something the
   record leaves open.

3. SAY WHAT IS THIN. If the material is a small sample, or carries a stated bias,
   put that in a callout rather than presenting the arrangement as solid.

Return ONLY JSON:
{{"title":"short title for this view",
  "summary":"2-3 lines: what a reader is looking at, including its limits",
  "sections":[{{"heading":"...","nodes":[
     {{"label":"short","detail":"one line","ref":"<id from the sources>","tone":"neutral|good|bad|void"}}
  ]}}],
  "callouts":[{{"text":"something the reader should not miss","ref":"<id>"}}]}}"""


def gather() -> tuple[str, set]:
    """Structured artifacts only. Prose analysis is deliberately NOT fed in: it
    is already someone's synthesis, and summarising a summary is how caveats get
    lost."""
    lines, refs = [], set()

    try:
        fleet = json.loads((ROOT / "fleet.json").read_text(encoding="utf-8"))["models"]
    except Exception:
        fleet = []
    if fleet:
        lines.append("MODELS IN THIS INSTANCE")
        for slug in fleet:
            md = WORK / slug / "MODEL.md"
            kind = "?"
            if md.exists():
                import re
                m = re.search(r"\*\*The kind:\*\*\s*(\S+)",
                              md.read_text(encoding="utf-8", errors="replace"))
                if m:
                    kind = m.group(1)
            lines.append(f"  {slug} · kind={kind}")
            refs.add(slug)
        lines.append("")

    n_claims = 0
    for slug in fleet:
        p = WORK / slug / "predict" / "ledger.json"
        if not p.exists():
            continue
        try:
            preds = json.loads(p.read_text(encoding="utf-8")).get("predictions", [])
        except ValueError:
            continue
        for c in preds:
            cid = c.get("id") or f"{slug}#{n_claims}"
            refs.add(str(cid))
            st = c.get("status", "open")
            v = f" verdict={c['verdict']}" if c.get("verdict") else ""
            lines.append(f"CLAIM {cid} · {slug} · {st}{v} · conf={c.get('confidence')} "
                         f"· by {c.get('resolve_by')} · {str(c.get('claim',''))[:150]}")
            n_claims += 1
    if n_claims:
        lines.insert(len(lines) - n_claims, "CLAIMS")
        lines.append("")

    g = ROOT / "map" / "model_graph.json"
    if g.exists():
        try:
            gd = json.loads(g.read_text(encoding="utf-8"))
            lines.append(f"MODEL GRAPH: {len(gd.get('nodes',[]))} models, "
                         f"{len(gd.get('edges',[]))} connected pairs")
            for e in gd.get("edges", [])[:20]:
                lines.append(f"  {e['a']} — {e['b']} · {e.get('kinds')}")
            lines.append("")
        except ValueError:
            pass

    for tl in sorted(WORK.glob("*/timeline.json")):
        try:
            td = json.loads(tl.read_text(encoding="utf-8"))
        except ValueError:
            continue
        evs = td.get("timeline", [])
        lines.append(f"EVENT HISTORY ({tl.parent.name}): {len(evs)} events")
        if td.get("note"):
            lines.append(f"  STATED BIAS: {td['note'][:300]}")
        for e in evs[:25]:
            refs.add(str(e.get("id")))
            lines.append(f"  {e.get('id')} · {e.get('date')} · {str(e.get('item',''))[:120]}")
        lines.append("")
        break

    return "\n".join(lines), refs


def validate(spec: dict, refs: set) -> tuple[dict, list]:
    """Drop every node whose ref is not real. Returns (clean spec, dropped)."""
    dropped = []
    for sec in spec.get("sections", []):
        keep = []
        for n in sec.get("nodes", []):
            r = str(n.get("ref", ""))
            if r and any(r in x or x in r for x in refs):
                keep.append(n)
            else:
                dropped.append(f"{sec.get('heading','?')}: {n.get('label','?')} (ref={r!r})")
        sec["nodes"] = keep
    keep = []
    for c in spec.get("callouts", []):
        r = str(c.get("ref", ""))
        if r and any(r in x or x in r for x in refs):
            keep.append(c)
        else:
            dropped.append(f"callout: {str(c.get('text',''))[:40]} (ref={r!r})")
    spec["callouts"] = keep
    spec["sections"] = [s for s in spec.get("sections", []) if s.get("nodes")]
    return spec, dropped


TONE = {"good": "#3fb950", "bad": "#e08050", "void": "#7c7b75", "neutral": "#8b8b8b"}


def render(spec: dict, meta: dict) -> str:
    """Spec -> one self-contained HTML file. Deterministic; no model output
    reaches the DOM as markup."""
    def esc(s):
        return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    secs = []
    for s in spec.get("sections", []):
        cards = "".join(
            f'<div class="n" style="border-left-color:{TONE.get(n.get("tone"),TONE["neutral"])}">'
            f'<b>{esc(n.get("label"))}</b><p>{esc(n.get("detail"))}</p>'
            f'<code>{esc(n.get("ref"))}</code></div>'
            for n in s.get("nodes", []))
        secs.append(f'<h2>{esc(s.get("heading"))}</h2><div class="g">{cards}</div>')
    calls = "".join(f'<div class="c">{esc(c.get("text"))}<code>{esc(c.get("ref"))}</code></div>'
                    for c in spec.get("callouts", []))
    dropped = meta.get("dropped") or []
    drop_html = ""
    if dropped:
        items = "".join(f"<li>{esc(d)}</li>" for d in dropped[:8])
        drop_html = (f'<div class="drop"><b>{len(dropped)} node(s) dropped</b> — their '
                     f'source reference did not exist in the record. Listed rather than '
                     f'silently removed.<ul>{items}</ul></div>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(spec.get('title','Visual synthesis'))}</title><style>
*{{box-sizing:border-box}}body{{background:#0b0b0d;color:#f1efe8;margin:0;padding:2rem;
font:16px/1.6 system-ui,sans-serif}}main{{max-width:1100px;margin:0 auto}}
h1{{font-size:1.9rem;letter-spacing:-.02em;margin:0 0 .4rem}}
.sum{{color:#a9a79f;max-width:60ch;margin:0 0 2rem}}
h2{{font-size:.78rem;letter-spacing:.18em;text-transform:uppercase;color:#7c7b75;
margin:2.4rem 0 .9rem;border-bottom:1px solid #242428;padding-bottom:.4rem}}
.g{{display:grid;gap:.7rem;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr))}}
.n{{background:#141417;border:1px solid #242428;border-left:3px solid;border-radius:8px;
padding:.8rem 1rem}}.n b{{font-size:.95rem}}.n p{{margin:.3rem 0 .5rem;font-size:.87rem;color:#a9a79f}}
code{{font:11px ui-monospace,monospace;color:#7c7b75}}
.c{{background:#141417;border-left:3px solid #b8ff3c;padding:.8rem 1rem;border-radius:8px;
margin:.6rem 0;font-size:.92rem}}
.drop{{margin-top:2.5rem;padding:.9rem 1.1rem;border:1px dashed #3a3a3f;border-radius:8px;
color:#7c7b75;font-size:.85rem}}.drop ul{{margin:.5rem 0 0;padding-left:1.1rem}}
.foot{{margin-top:3rem;padding-top:1rem;border-top:1px solid #242428;color:#7c7b75;font-size:.8rem}}
</style></head><body><main>
<h1>{esc(spec.get('title','Visual synthesis'))}</h1>
<p class="sum">{esc(spec.get('summary'))}</p>
{"".join(secs)}
{'<h2>Do not miss</h2>' + calls if calls else ''}
{drop_html}
<div class="foot">Generated {esc(meta.get('at'))} from this instance's own record.
Every card carries the source reference it was built from; anything unreferenced was
dropped. This is an arrangement of existing analysis, not new analysis.</div>
</main></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--view", choices=sorted(VIEWS), default="claims")
    ap.add_argument("--title")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    OUT.mkdir(exist_ok=True)
    if a.list:
        for f in sorted(OUT.glob("*.html")):
            print(f"  {f.name}")
        return

    from suites.grade_claims import _load_env
    _load_env()

    sources, refs = gather()
    if not refs:
        raise SystemExit("nothing to visualise yet — this instance has no models or claims")
    print(f"  {len(refs)} referenceable items in the record")

    p = (PROMPT.replace("{view}", a.view).replace("{view_desc}", VIEWS[a.view])
         .replace("{sources}", sources[:14000]))
    r = chat(a.model, [{"role": "user", "content": p}], temperature=0.3, max_tokens=2600)
    spec = parse_json(r.text) if not r.error else None
    if not spec:
        raise SystemExit(f"generation failed: {r.error or 'unparseable'}")
    if a.title:
        spec["title"] = a.title

    spec, dropped = validate(spec, refs)
    if dropped:
        print(f"  {len(dropped)} node(s) dropped for unverifiable refs:")
        for d in dropped[:5]:
            print(f"    - {d}")
    n = sum(len(s.get("nodes", [])) for s in spec.get("sections", []))
    meta = {"at": date.today().isoformat(), "dropped": dropped}
    f = OUT / f"{a.view}-{date.today().isoformat()}.html"
    f.write_text(render(spec, meta), encoding="utf-8")
    (OUT / f"{a.view}-{date.today().isoformat()}.json").write_text(
        json.dumps({"spec": spec, "meta": meta}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    print(f"  {n} node(s) kept -> {f}")


if __name__ == "__main__":
    main()
