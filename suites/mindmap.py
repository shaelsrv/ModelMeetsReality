"""Entity mindmap v2 — membership + co-occurrence.

v1 was wrong in a way worth recording: each entity's "region" was its 40 nearest
fragments in embedding space, so every node hit the cap, regions overlapped, and
36 of 36 possible pairs linked. The strongest edges were alias pairs (FIFA-
an officeholder and their institution) — the same entity twice, not an insight.

v2 changes three things:
  MEMBERSHIP  — a fragment belongs to an entity if it MENTIONS it (alias match) or
                is semantically close AND above a strict bar. No fixed count: an
                entity with thin evidence gets a small region, which is information.
  CO-OCCURRENCE — an edge means fragments where BOTH entities appear. That is the
                association a mind actually forms. Weight is Jaccard overlap,
                lifted where co-mentions are numerous (not just proportionally high).
  HIERARCHY   — `part_of` in the registry nests officeholders under institutions,
                so officeholder/institution is structure, not the map's top finding.

Semantic similarity still contributes, but only as a SECONDARY signal on pairs
that already co-occur, so it sharpens real links instead of inventing them.

  python -m suites.mindmap --build
  python -m suites.mindmap --show
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

from suites.memory_index import load_indexes, embed, cosine  # noqa: E402

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
OUT = EDIR / "mindmap.json"

SEM_BAR = 0.42        # strict: semantic membership without a mention must be strong
MIN_CO = 2            # an edge needs at least this many co-mentioning fragments
# officeholder -> institution: declared, so alias pairs become hierarchy not edges
PART_OF = {}  # officeholder -> institution, per instance


def registry() -> dict:
    f = EDIR / "entities.json"
    return json.load(f.open(encoding="utf-8")) if f.exists() else {}


def _alias_re(aliases: list[str]):
    parts = [re.escape(a.strip()) for a in aliases if len(a.strip()) >= 3]
    if not parts:
        return None
    return re.compile(r"(?<![A-Za-z])(" + "|".join(parts) + r")(?![A-Za-z])", re.I)


def ambiguity_report(reg: dict, rows: list) -> list:
    """Which aliases fire most often INSIDE another entity's documents.

    'Congress' taught this lesson: it is FIFA's own body as well as the US one,
    and it silently inflated three edges. An alias that matches mostly where
    another entity dominates is a false-positive generator; surface it rather
    than let it distort the graph unnoticed.
    """
    pats = {s: _alias_re(e["aliases"]) for s, e in reg.items()}
    flags = []
    for s, e in reg.items():
        for alias in e["aliases"]:
            a_re = _alias_re([alias])
            if not a_re:
                continue
            hits = [r for r in rows if a_re.search(r.get("text", ""))]
            if len(hits) < 4:
                continue
            for other, opat in pats.items():
                if other == s or not opat:
                    continue
                inside = sum(1 for r in hits if opat.search(r.get("text", "")))
                if inside / len(hits) >= 0.6:
                    flags.append({"entity": s, "alias": alias, "hits": len(hits),
                                  "mostly_inside": other,
                                  "share": round(inside / len(hits), 2)})
    return flags


def members(reg: dict, rows: list) -> dict:
    """Which fragments belong to each entity, and why. Mention beats similarity."""
    pats = {s: _alias_re(e["aliases"]) for s, e in reg.items()}
    cues = {s: f"{e['name']}: {', '.join(e['aliases'][:8])}" for s, e in reg.items()}
    cvec = dict(zip(cues.keys(), embed(list(cues.values()))))
    out = {s: {"mention": set(), "semantic": set()} for s in reg}
    for i, r in enumerate(rows):
        text = r.get("text", "")
        for s, pat in pats.items():
            if pat and pat.search(text):
                out[s]["mention"].add(i)
        for s in reg:
            if i in out[s]["mention"]:
                continue
            if cosine(cvec[s], r["vec"]) >= SEM_BAR:
                out[s]["semantic"].add(i)
    return out


def build() -> dict:
    reg = registry()
    if not reg:
        raise SystemExit("no entities registered — run suites.entities --build first")
    rows = load_indexes()
    if not rows:
        raise SystemExit("no memory index — run suites.memory_index --build first")

    mem = members(reg, rows)
    nodes = []
    for s, e in reg.items():
        m, sem = mem[s]["mention"], mem[s]["semantic"]
        idx = m | sem
        nodes.append({
            "id": s, "name": e["name"], "kind": e["kind"],
            "part_of": PART_OF.get(s),
            "fragments": len(idx), "by_mention": len(m), "by_similarity": len(sem),
            "repos": sorted({rows[i]["repo"] for i in idx}),
            "kinds": sorted({rows[i]["kind"] for i in idx})[:5],
        })

    edges = []
    slugs = list(reg.keys())
    for i, a in enumerate(slugs):
        A = mem[a]["mention"] | mem[a]["semantic"]
        for b in slugs[i + 1:]:
            if PART_OF.get(a) == b or PART_OF.get(b) == a:
                continue                      # hierarchy, not an edge
            B = mem[b]["mention"] | mem[b]["semantic"]
            both = A & B
            if len(both) < MIN_CO:
                continue
            union = len(A | B) or 1
            jac = len(both) / union
            # co-mention count matters as well as proportion: 20 shared fragments
            # is a stronger claim than 2, even at the same Jaccard
            weight = jac * (1 + min(len(both), 30) / 30)
            hard = len(mem[a]["mention"] & mem[b]["mention"])
            edges.append({
                "a": a, "b": b, "weight": round(weight, 3),
                "co_fragments": len(both), "co_mentions": hard,
                "jaccard": round(jac, 3),
                "shared_repos": sorted({rows[i2]["repo"] for i2 in both})[:6],
                "why": (f"{len(both)} fragments involve both"
                        + (f" ({hard} name both explicitly)" if hard else
                           " (semantic membership only — weaker)")),
            })
    edges.sort(key=lambda e: -e["weight"])

    flags = ambiguity_report(reg, rows)
    out = {"built": datetime.date.today().isoformat(), "version": 2,
           "nodes": nodes, "edges": edges, "ambiguous_aliases": flags,
           "method": ("membership = alias mention OR similarity >= "
                      f"{SEM_BAR}; edges = co-occurrence (min {MIN_CO} shared "
                      "fragments), weighted by Jaccard x co-mention volume; "
                      "part_of pairs excluded as hierarchy"),
           "note": ("Edges describe how THIS FLEET's artifacts co-locate entities — "
                    "not verified real-world relationships. A strong edge is a "
                    "hypothesis about our own coverage, not a finding about the world.")}
    EDIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="Entity mindmap (membership + co-occurrence).")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    d = json.load(OUT.open(encoding="utf-8")) if (a.show and OUT.exists()) else build()
    poss = len(d["nodes"]) * (len(d["nodes"]) - 1) // 2
    print(f"[mindmap v{d.get('version',2)}] {len(d['nodes'])} nodes · "
          f"{len(d['edges'])} edges of {poss} possible")
    print("\n  nodes (fragments = mentions + semantic):")
    for n in sorted(d["nodes"], key=lambda x: -x["fragments"]):
        par = f" (part of {n['part_of']})" if n.get("part_of") else ""
        print(f"  {n['name']:<24}{par:<18} {n['fragments']:>3} = "
              f"{n['by_mention']:>3}m + {n['by_similarity']:>3}s · {len(n['repos'])} repos")
    print("\n  strongest links:")
    for e in d["edges"][:10]:
        print(f"  {e['weight']:.3f}  {e['a']:<20} — {e['b']:<20} {e['why']}")
    if d.get("ambiguous_aliases"):
        print("\n  [ambiguous aliases — these fire mostly inside another entity's docs]")
        for f in d["ambiguous_aliases"]:
            print(f"    '{f['alias']}' ({f['entity']}): {f['share']:.0%} of its "
                  f"{f['hits']} hits are in {f['mostly_inside']} documents")


if __name__ == "__main__":
    main()
