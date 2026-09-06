"""Model graph — how many ways is the world being seen, and where do those views connect.

Every brainstorm synthesis already answers this per-event: which mechanisms CONVERGE,
where they are in TENSION (and what observable would settle it), and what CROSSED
insights emerge only from combining two. That structure was computed once per run and
then thrown away. This assembles it into one graph.

Two projections, because they answer different questions:

  per-issue   — for ONE event: which lenses had grip, where they split, what decides it.
                "How many aspects is the world seeing here, and who disagrees with whom?"
  cross-issue — across ALL runs: which pairs recur, which mechanisms bridge domains.
                "Which views connect, in general?"

    python -m suites.model_graph                 # cross-issue map -> map/model_graph.json
    python -m suites.model_graph --issue <bid>   # one event's structure
    python -m suites.model_graph --pair a,b      # every insight two models produced together

Edges carry PROVENANCE — run id and the actual insight text — because the value here is
clicking through to what was said, not admiring a topology.

WEIGHTING: edges are weighted by RATE (times linked / times co-rostered), never raw count.
Raw counts measure which models happened to be passed to --models together, so an
unnormalized graph shows you your own selection habits and calls it affinity.

STATUS: candidate instrument. It summarises a handful of runs; a recurring pair is a
hypothesis about mechanism affinity, not a finding, and tension deciders are proto-claims
that must go through the normal seal path (dedup + date gate) rather than being registered
from here.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from suites.attribute_outcomes import MENU  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BDIR = ROOT / "brainstorms"
OUT = ROOT / "map" / "model_graph.json"

# A run whose evidence was discredited must not feed the map, for the same reason
# register_brainstorm refuses to seal it. "partial" is a checkpoint: real lens work,
# but no synthesis yet, so there are no edges to take.
SKIP_STATUS = {"superseded", "void", "discarded", "partial", "queued"}

KNOWN = set(MENU)

# The challenge panel runs on EVERY brainstorm rather than being rostered, so it
# co-occurs with everything by construction. Leaving it in ranked the adversary
# above every real pair — an artifact of it always being present, not affinity.
# Its verdicts still matter; they are just not edges in a mechanism map.
from suites.brainstorm import PANEL_EXCLUDE as PANEL  # noqa: E402  (single source)


def _known_povs() -> set:
    d = ROOT / "povs"
    return {p.stem for p in d.glob("*.md")} if d.exists() else set()


def _sister_models() -> set:
    """Any sibling directory holding a MODEL.md is a real model. MENU lists only the
    mechanisms wired into attribution, so resolving against it alone silently dropped
    legitimacy-classifier, hunch-generator and audience-model — models that genuinely
    participated in these brainstorms."""
    out = set()
    tools = ROOT.parent
    if tools.exists():
        for d in tools.iterdir():
            try:
                if d.is_dir() and (d / "MODEL.md").exists():
                    out.add(d.name)
            except OSError:
                continue
    canon = tools / "canon" / "models"
    if canon.exists():
        out |= {p.stem for p in canon.glob("*.md")}
    return out


def _split(raw) -> list:
    """Model names arrive dirty. Synthesis writes '["a + b"]', '["a/b/c"]', and prose
    like 'DA panel'. Splitting on separators and matching against the known roster is
    what stops junk nodes: an unparsed 'attention-substrate + pressure-model' would
    otherwise become a third node that is neither."""
    names = []
    for tok in (raw or []):
        for part in str(tok).replace("+", ",").replace("/", ",").split(","):
            part = part.strip().strip("`'\"").lower()
            if part:
                names.append(part)
    return names


def _resolve(names: list, roster: set, unknown: Counter) -> list:
    out = []
    for n in names:
        if n in roster:
            out.append(n)
        else:
            # panel voices are real participants but not models; drop quietly
            if not any(k in n for k in ("adversary", "devil", "librarian", "base-rate",
                                        "occam", "simplicity", "panel", "ensemble",
                                        "synthesis", "null")):
                unknown[n] += 1
    return sorted(set(out))


def load(include_partial: bool = False) -> tuple[list, Counter]:
    """Return (runs, unknown-name counter). Each run: id, models rostered, edges."""
    roster = (KNOWN | _known_povs() | _sister_models()) - PANEL
    unknown: Counter = Counter()
    runs = []
    for f in sorted(BDIR.glob("*.json")):
        if f.name == "ledger.json":
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        status = d.get("status")
        if status in SKIP_STATUS and not (include_partial and status == "partial"):
            continue
        syn = d.get("synthesis") or {}
        if not syn:
            continue
        rostered = _resolve(_split(d.get("models") or []), roster, Counter())
        edges = []
        for c in syn.get("convergences", []):
            ms = _resolve(_split(c.get("models")), roster, unknown)
            for a, b in combinations(ms, 2):
                edges.append({"a": a, "b": b, "kind": "converge",
                              "why": str(c.get("point", ""))[:400]})
        for t in syn.get("tensions", []):
            ms = _resolve(_split(t.get("models")), roster, unknown)
            for a, b in combinations(ms, 2):
                edges.append({"a": a, "b": b, "kind": "tension",
                              "why": str(t.get("sides", ""))[:400],
                              "decider": str(t.get("decider", ""))[:400]})
        for c in syn.get("crossed", []):
            ms = _resolve(_split(c.get("pair")), roster, unknown)
            for a, b in combinations(ms, 2):
                edges.append({"a": a, "b": b, "kind": "crossed",
                              "why": str(c.get("insight", ""))[:400]})
        runs.append({"id": d.get("id") or f.stem, "at": d.get("at", ""),
                     "researched": bool(d.get("researched")),
                     "models": rostered, "edges": edges,
                     "load_bearing": (syn.get("load_bearing") or {}).get("model", ""),
                     "event": str(d.get("event", ""))[:200]})
    return runs, unknown


def build(runs: list) -> dict:
    co = Counter()          # times two models were rostered together
    linked = defaultdict(list)
    for r in runs:
        for a, b in combinations(sorted(set(r["models"])), 2):
            co[(a, b)] += 1
        for e in r["edges"]:
            key = tuple(sorted((e["a"], e["b"])))
            if key[0] == key[1]:
                continue
            linked[key].append({**e, "run": r["id"]})

    edges = []
    for key, items in linked.items():
        runs_linked = len({i["run"] for i in items})
        opportunities = co.get(key, 0)
        if not opportunities:
            # Linked without ever being rostered together means the name resolution
            # is off, not that affinity is perfect. Skip rather than score it 1.00.
            continue
        kinds = Counter(i["kind"] for i in items)
        edges.append({
            "a": key[0], "b": key[1],
            # Rate, not count: in how many of the runs where BOTH were rostered did
            # they produce structure. Counted once per run — a pair that converged
            # and also crossed in one run must not score 2.0 and stop being a rate.
            "weight": round(runs_linked / opportunities, 3),
            "links": len(items), "runs_linked": runs_linked,
            "co_rostered": co.get(key, 0),
            "kinds": dict(kinds),
            "why": [{"run": i["run"], "kind": i["kind"], "text": i["why"],
                     **({"decider": i["decider"]} if i.get("decider") else {})}
                    for i in items],
        })
    # A 1.00 from a single shared run is not evidence of affinity; sort by
    # weight but surface how many runs it rests on so thin edges are visible.
    edges.sort(key=lambda e: (-e["weight"], -e["runs_linked"], -e["links"]))

    deg = Counter()
    for e in edges:
        deg[e["a"]] += e["links"]
        deg[e["b"]] += e["links"]
    appear = Counter()
    for r in runs:
        for m in set(r["models"]):
            appear[m] += 1
    nodes = [{"id": m, "runs": appear[m], "links": deg.get(m, 0),
              "kind": "pov" if m in _known_povs() and m not in KNOWN else "mechanism",
              "mechanism": MENU.get(m, "")[:120]}
             for m in sorted(appear)]
    return {"spec": "model-graph-v1", "runs": len(runs),
            "nodes": nodes, "edges": edges}


def issue(bid: str) -> None:
    runs, _ = load(include_partial=True)
    r = next((x for x in runs if x["id"] == bid), None)
    if not r:
        raise SystemExit(f"no run with synthesis: {bid}")
    print(f"# {r['id']}  ({r['at']}{', researched' if r['researched'] else ''})")
    print(f"  {len(r['models'])} lenses rostered · load-bearing: {r['load_bearing'] or '?'}")
    for kind in ("converge", "tension", "crossed"):
        es = [e for e in r["edges"] if e["kind"] == kind]
        if not es:
            continue
        print(f"\n## {kind} ({len(es)})")
        for e in es[:12]:
            print(f"  {e['a']} — {e['b']}")
            print(f"    {e['why'][:200]}")
            if e.get("decider"):
                print(f"    DECIDER: {e['decider'][:170]}")


def pair(a: str, b: str) -> None:
    runs, _ = load()
    key = tuple(sorted((a.strip().lower(), b.strip().lower())))
    hits = [(r["id"], e) for r in runs for e in r["edges"]
            if tuple(sorted((e["a"], e["b"]))) == key]
    if not hits:
        raise SystemExit(f"no recorded link between {key[0]} and {key[1]}")
    print(f"# {key[0]} × {key[1]} — {len(hits)} link(s)")
    for rid, e in hits:
        print(f"\n[{e['kind']}] {rid}")
        print(f"  {e['why']}")
        if e.get("decider"):
            print(f"  DECIDER: {e['decider']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--issue", help="show one event's structure by brainstorm id")
    ap.add_argument("--pair", help="two model names, comma-separated")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    if a.issue:
        return issue(a.issue)
    if a.pair:
        p = [x for x in a.pair.split(",") if x.strip()]
        if len(p) != 2:
            raise SystemExit("--pair takes exactly two model names")
        return pair(*p)

    runs, unknown = load()
    g = build(runs)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{g['runs']} runs · {len(g['nodes'])} models · {len(g['edges'])} connected pairs"
          f"  -> {OUT.relative_to(ROOT)}")
    if unknown:
        # Named, not swallowed: an unparsed name is a silently missing edge.
        print(f"  unresolved names ({sum(unknown.values())}): "
              f"{', '.join(n for n, _ in unknown.most_common(6))}")
    print(f"\n  strongest connections (rate = linked / co-rostered):")
    for e in g["edges"][:a.top]:
        kinds = "+".join(f"{k}:{v}" for k, v in e["kinds"].items())
        print(f"   {e['weight']:.2f}  {e['a']} — {e['b']}"
              f"   ({e['runs_linked']}/{e['co_rostered']} runs, {e['links']} links · {kinds})")


if __name__ == "__main__":
    main()
