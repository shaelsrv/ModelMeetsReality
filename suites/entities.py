"""Entity dossiers — what the FLEET has understood about a company, market, or nation.

Inverts the organization of knowledge: instead of "what does model X say", this asks
"what do all models say about entity Y". Everything is EXTRACTED from artifacts the
fleet already produced — claims, brainstorm lenses, blindspot registrations,
attributions, narrative traces, studies — never from the LLM's parametric memory.
A dossier with no artifacts is an empty dossier, and says so.

  python -m suites.entities --build                  # all registered entities
  python -m suites.entities --add openai --aliases "OpenAI,GPT-6,Astra,Brockman"
  python -m suites.entities --show openai
  python -m suites.entities --synthesize openai      # LLM pass over EXTRACTED evidence only
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
EDIR = TOOLS / "entity-atlas"
REG = EDIR / "entities.json"

# seed registry: kind matters — a company, a market, and a nation are read differently
SEED = {}  # register entities with --add; none ship by default


def registry() -> dict:
    if REG.exists():
        return json.load(REG.open(encoding="utf-8"))
    EDIR.mkdir(parents=True, exist_ok=True)
    REG.write_text(json.dumps(SEED, ensure_ascii=False, indent=1), encoding="utf-8")
    return dict(SEED)


def _hits(text: str, aliases: list) -> bool:
    low = text.lower()
    return any(a.lower() in low for a in aliases)


def gather(slug: str, ent: dict) -> dict:
    """Pull every artifact in the family that mentions this entity. Extraction only."""
    al = ent["aliases"]
    ev = {"claims": [], "lenses": [], "registrations": [], "attributions": [],
          "traces": [], "studies": [], "postmortems": []}

    # 1. claims across every ledger in every repo
    for repo in sorted(p for p in TOOLS.iterdir() if p.is_dir()):
        for rel in ("predict/ledger.json", "predict/live_ledger.json",
                    "signals/signal_ledger.json", "brainstorms/ledger.json"):
            f = repo / rel
            if not f.exists():
                continue
            try:
                d = json.load(f.open(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for r in (d.get("predictions", d) if isinstance(d, dict) else d):
                blob = f"{r.get('claim','')} {r.get('entity','')} {r.get('mechanism','')}"
                if _hits(blob, al):
                    ev["claims"].append({
                        "model": repo.name, "status": r.get("status", "?"),
                        "resolve_by": r.get("resolve_by", ""),
                        "confidence": r.get("confidence"),
                        "claim": r.get("claim", "")[:300],
                        "what_happened": r.get("what_happened", "")[:200]})

    # 2. brainstorm lenses + syntheses
    bdir = ROOT / "brainstorms"
    if bdir.exists():
        for f in sorted(bdir.glob("*.json")):
            if f.name.endswith(".queued.json") or f.name == "ledger.json":
                continue
            d = json.load(f.open(encoding="utf-8"))
            if not _hits(d.get("event", ""), al):
                continue
            for m, lens in (d.get("lenses") or {}).items():
                ev["lenses"].append({"brainstorm": d["id"], "model": m,
                                     "grip": lens.get("grip", "?"),
                                     "read": lens.get("read", "")[:400],
                                     "unique": lens.get("unique", "")[:250]})
            syn = d.get("synthesis", {})
            for c in syn.get("crossed", []):
                ev["lenses"].append({"brainstorm": d["id"],
                                     "model": " x ".join(c.get("pair", [])),
                                     "grip": "crossed", "read": c.get("insight", "")[:400],
                                     "unique": ""})

    # 3. blindspot registrations
    rdir = TOOLS / "blindspot-model" / "registrations"
    if rdir.exists():
        for f in sorted(rdir.glob("*.json")):
            d = json.load(f.open(encoding="utf-8"))
            if not _hits(d.get("criticality", ""), al):
                continue
            ev["registrations"].append({
                "case": d.get("case"), "resolve_by": d.get("resolve_by"),
                "monitored": d.get("monitored_set", [])[:8],
                "blindspots": [b.get("dimension", "")[:120]
                               for b in d.get("blindspots", [])]})

    # 4. attributions (which mechanism drove outcomes involving this entity)
    af = TOOLS / "attribution-model" / "attributions" / "attributions.jsonl"
    if af.exists():
        for l in af.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if _hits(r.get("claim", ""), al):
                ev["attributions"].append({"primary": r.get("primary"),
                                           "share": r.get("primary_share"),
                                           "verdict": r.get("verdict"),
                                           "claim": r.get("claim", "")[:180]})

    # 5. narrative traces
    tdir = TOOLS / "narrative-model" / "traces"
    if tdir.exists():
        for f in sorted(tdir.glob("*.json")):
            d = json.load(f.open(encoding="utf-8"))
            if not _hits(d.get("event", ""), al):
                continue
            ev["traces"].append({"event": d.get("event", "")[:160],
                                 "stage": d.get("stage"),
                                 "sides": [s.get("side", "")[:80] for s in d.get("sides", [])],
                                 "read": d.get("current_read", "")[:250]})

    # 6. empirical studies
    for repo in sorted(p for p in TOOLS.iterdir() if p.is_dir()):
        sdir = repo / "studies"
        if not sdir.exists():
            continue
        for f in sorted(sdir.glob("*.registration.json")):
            d = json.load(f.open(encoding="utf-8"))
            if _hits(f"{d.get('h1','')} {d.get('unit','')} {d.get('sampling_frame','')}", al):
                ev["studies"].append({"id": d.get("id"), "h1": d.get("h1", "")[:200],
                                      "status": d.get("status"),
                                      "verdict": d.get("verdict", "")})

    # 7. postmortem lessons
    pf = ROOT / "trajectory" / "postmortems.jsonl"
    if pf.exists():
        for l in pf.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if _hits(r.get("claim", ""), al):
                ev["postmortems"].append({
                    "model": r.get("model"), "verdict": r.get("verdict", r.get("category", "")),
                    "lesson": (r.get("lesson") or r.get("why") or "")[:220]})
    return ev


def stats(ev: dict) -> dict:
    cl = ev["claims"]
    graded = [c for c in cl if c["status"] not in ("open", "?")]
    hits = [c for c in graded if c["status"] in ("hit", "partial")]
    models = sorted({c["model"] for c in cl} | {l["model"] for l in ev["lenses"]})
    return {"claims": len(cl), "open": len(cl) - len(graded), "graded": len(graded),
            "hits": len(hits), "models_touching": models,
            "lenses": len(ev["lenses"]), "registrations": len(ev["registrations"]),
            "attributions": len(ev["attributions"]), "traces": len(ev["traces"]),
            "studies": len(ev["studies"])}


def build(slug: str | None = None) -> list:
    reg = registry()
    EDIR.mkdir(parents=True, exist_ok=True)
    (EDIR / "dossiers").mkdir(exist_ok=True)
    out = []
    for s, ent in reg.items():
        if slug and s != slug:
            continue
        ev = gather(s, ent)
        st = stats(ev)
        doc = {"slug": s, "name": ent["name"], "kind": ent["kind"],
               "aliases": ent["aliases"], "built": datetime.date.today().isoformat(),
               "stats": st, "evidence": ev,
               "synthesis": _existing_synthesis(s)}
        (EDIR / "dossiers" / f"{s}.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        out.append(doc)
    return out


def _existing_synthesis(slug: str) -> dict:
    f = EDIR / "dossiers" / f"{slug}.json"
    if f.exists():
        try:
            return json.load(f.open(encoding="utf-8")).get("synthesis", {})
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


SYNTH = """You are writing the "what we have understood" section of an ENTITY DOSSIER. Everything you
say must come from the EXTRACTED EVIDENCE below — artifacts this research fleet actually produced.
Do NOT add general knowledge about this entity from your own training; if the evidence is thin,
the honest output is a thin dossier that says what is missing.

ENTITY: {name} ({kind})

EXTRACTED EVIDENCE (claims, lens reads, blindspot registrations, attributions, traces, studies):
{evidence}

Produce:
- understanding: 4-6 lines — what the fleet has actually learned about this entity's structure
  and behavior, each point traceable to the evidence above.
- mechanisms: which mechanisms have been shown (or attributed) to drive this entity's outcomes.
- open_questions: what the fleet has bet on but not yet resolved.
- blind_spots: what NO artifact covers — the parts of this entity nobody modeled.
- confidence: "thin" | "moderate" | "substantial" — and one line justifying it by evidence volume.

Return ONLY JSON:
{"understanding":["..."],"mechanisms":["..."],"open_questions":["..."],
"blind_spots":["..."],"confidence":"thin|moderate|substantial","confidence_why":"..."}"""


def synthesize(slug: str, model: str) -> None:
    from harness.openrouter import chat
    from harness.actors import parse_json
    f = EDIR / "dossiers" / f"{slug}.json"
    if not f.exists():
        build(slug)
    d = json.load(f.open(encoding="utf-8"))
    if not any(d["evidence"].values()):
        print(f"[{slug}] no artifacts mention this entity — nothing to synthesize")
        return
    ev_text = json.dumps(d["evidence"], ensure_ascii=False)[:14000]
    r = chat(model, [{"role": "user", "content":
                      SYNTH.replace("{name}", d["name"]).replace("{kind}", d["kind"])
                      .replace("{evidence}", ev_text)}],
             temperature=0.3, max_tokens=1800)
    syn = parse_json(r.text) if not r.error else None
    if not syn:
        raise SystemExit(f"synthesis failed: {r.error or 'unparseable'}")
    syn["synthesized_on"] = datetime.date.today().isoformat()
    d["synthesis"] = syn
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{slug}] {syn.get('confidence','?')} — {syn.get('confidence_why','')[:110]}")
    for u in syn.get("understanding", [])[:6]:
        print(f"  · {u[:150]}")
    if syn.get("blind_spots"):
        print(f"  BLIND: {'; '.join(b[:80] for b in syn['blind_spots'][:3])}")


def main():
    ap = argparse.ArgumentParser(description="Entity dossiers from fleet artifacts.")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--add")
    ap.add_argument("--name")
    ap.add_argument("--kind", default="company")
    ap.add_argument("--aliases", default="")
    ap.add_argument("--show")
    ap.add_argument("--synthesize")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    a = ap.parse_args()
    if a.add:
        reg = registry()
        slug = re.sub(r"[^a-z0-9-]+", "-", a.add.lower()).strip("-")
        reg[slug] = {"name": a.name or a.add, "kind": a.kind,
                     "aliases": [x.strip() for x in a.aliases.split(",") if x.strip()]
                     or [a.name or a.add]}
        REG.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"registered entity '{slug}' ({a.kind}) with {len(reg[slug]['aliases'])} aliases")
        build(slug)
        return
    if a.show:
        f = EDIR / "dossiers" / f"{a.show}.json"
        if not f.exists():
            build(a.show)
        d = json.load(f.open(encoding="utf-8"))
        st = d["stats"]
        print(f"# {d['name']} ({d['kind']}) — built {d['built']}")
        print(f"  {st['claims']} claims ({st['open']} open, {st['graded']} graded, "
              f"{st['hits']} hits) · {st['lenses']} lens reads · "
              f"{st['registrations']} blindspot regs · {st['attributions']} attributions · "
              f"{st['studies']} studies")
        print(f"  models touching: {', '.join(st['models_touching'][:12])}")
        syn = d.get("synthesis") or {}
        if syn:
            print(f"  confidence: {syn.get('confidence','?')}")
            for u in syn.get("understanding", [])[:5]:
                print(f"   · {u[:160]}")
        return
    if a.synthesize:
        from suites.grade_claims import _load_env
        _load_env()
        import os
        if not (os.environ.get("OPENROUTER_API_KEY")
                or os.environ.get("LLM_BACKEND") == "claude-code"):
            raise SystemExit("no key and no claude-code backend")
        synthesize(a.synthesize, a.model)
        return
    docs = build()
    print(f"[entities] {len(docs)} dossiers built")
    for d in sorted(docs, key=lambda x: -x["stats"]["claims"]):
        st = d["stats"]
        print(f"  {d['slug']:<22} {st['claims']:>3} claims · {st['lenses']:>2} lenses · "
              f"{st['attributions']:>2} attributions · {len(st['models_touching']):>2} models")


if __name__ == "__main__":
    main()
