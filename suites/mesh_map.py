"""Mesh mapping — after each analysis round, map the observed reality as a Mesh.

The mesh instrument doesn't just predict; its theory IS a cartography (nodes = stable
configurations, edges = typed structural-necessity claims). This task closes that loop:
after every predict/assess round, the round's observations, model reads, and verdicts
are compiled into a persistent dependency map of the watched domains —
`mesh/map/map.json` (the graph) + `mesh/map/MAP.md` (human-readable, with a mermaid
render).

The map obeys the theory's own edge-construction methodology (MODEL.md / mesh theory
§3.4): every edge carries a TYPE (foundation | enabling | legitimacy | sustaining), an
EVIDENCE tier (formal | empirical | historical | analytical | conjectural), and a
STRAIN state (none | building | acute). Conjectural edges are permitted but flagged —
they can never support a ρ claim. Nodes carry a state (stable | strained | hollowing |
tipping-window) tied to the failure taxonomy.

This maps the INSTRUMENT'S REGION — the watched domains as observed, round by round —
not the full E0–E14 cosmology. Each run is a delta: the LLM sees the current map plus
only the new rounds, proposes additions/updates with provenance, and the tool merges
(dedup by node id and by (from,to,type)). The map is therefore an accumulating,
revisable artifact whose every element traces to a round.

Wired via watch.json `"post_analysis": "mesh_map"` — model_watch runs it after every
predict/assess for the repo, and the grading loop inherits that automatically.

  python -m suites.mesh_map --repo mesh              # map rounds not yet mapped
  python -m suites.mesh_map --repo mesh --all        # remap from scratch (rebuild)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
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
TOOLS = ROOT.parent

EDGE_TYPES = {"foundation", "enabling", "legitimacy", "sustaining"}
EVIDENCE = {"formal", "empirical", "historical", "analytical", "conjectural"}
NODE_STATES = {"stable", "strained", "hollowing", "tipping-window"}
STRAIN = {"none", "building", "acute"}

MAP_PROMPT = """You are the cartographer for a dependency-graph instrument. Its theory: nodes are
STABLE CONFIGURATIONS (self-reinforcing arrangements), edges are STRUCTURAL-NECESSITY claims
("B cannot persist without A" — weaker than causation, testable by removal). Your job: from the
new analysis rounds below, propose a DELTA to the existing map.

RULES (the theory's own discipline — violations make the map worthless):
- Every edge MUST have: type (foundation=hard coupling | enabling=softer, alternatives exist |
  legitimacy=belief-mediated, nonlinear | sustaining=mutual reinforcement loop), evidence tier
  (formal | empirical | historical | analytical | conjectural), direction (A supports B), and a
  one-line note. Mark conjectural honestly — it is allowed, flagged, and never load-bearing.
- Enabling edges MUST name the alternative path in the note (that is what makes them enabling).
- Nodes are configurations, not events or categories: "the search-referral traffic economy" is a
  node; "Google's August update" is evidence, not a node.
- Node state from the failure taxonomy: stable | strained (dependency under visible load) |
  hollowing (mechanism degrading under green metrics) | tipping-window (near a basin boundary).
- Reuse existing node ids wherever the configuration is the same thing. Prefer updating a
  node's state/notes over minting a near-duplicate.
- Only map what the round data supports. An empty delta is a valid answer.

CURRENT MAP (ids, names, states; edges as from->to type/strain):
{current_map}

NEW ROUNDS (observations, model reads, claims, verdicts):
{rounds}

Return ONLY JSON:
{"nodes":[{"id":"kebab-slug","name":"...","entity":"watch-entity-id","state":"stable|strained|hollowing|tipping-window","note":"..."}],
"edges":[{"from":"node-id","to":"node-id","type":"foundation|enabling|legitimacy|sustaining","evidence":"formal|empirical|historical|analytical|conjectural","strain":"none|building|acute","note":"..."}],
"state_updates":[{"id":"existing-node-id","state":"...","note":"why it changed"}]}"""


def load_map(mdir: Path) -> dict:
    f = mdir / "map.json"
    if f.exists():
        return json.load(f.open(encoding="utf-8"))
    return {"updated": "", "rounds_mapped": [], "nodes": {}, "edges": []}


def map_summary(m: dict) -> str:
    if not m["nodes"]:
        return "(empty map)"
    lines = [f"- {nid} \"{n['name']}\" [{n['state']}] ({n.get('entity','')})"
             for nid, n in m["nodes"].items()]
    lines += [f"- {e['from']} -> {e['to']} {e['type']}/{e.get('strain','none')}"
              for e in m["edges"]]
    return "\n".join(lines)[:6000]


def rounds_text(led: dict, which: list[int]) -> str:
    out = []
    for p in led["predictions"]:
        if p.get("round") not in which:
            continue
        out.append(json.dumps({k: p.get(k) for k in
                               ("entity", "round", "observed", "model_read", "claim",
                                "status", "what_happened") if p.get(k)},
                              ensure_ascii=False))
    return "\n".join(out)[:16000]


def apply_delta(m: dict, d: dict, rounds: list[int], today: str) -> tuple[int, int, int]:
    n_nodes = n_edges = n_updates = 0
    for n in d.get("nodes", []):
        nid = n.get("id", "").strip()
        if not nid or n.get("state") not in NODE_STATES:
            continue
        if nid in m["nodes"]:
            m["nodes"][nid]["state"] = n["state"]
            m["nodes"][nid]["note"] = n.get("note", m["nodes"][nid].get("note", ""))
            m["nodes"][nid]["last_updated"] = today
        else:
            m["nodes"][nid] = {"name": n.get("name", nid), "entity": n.get("entity", ""),
                               "state": n["state"], "note": n.get("note", ""),
                               "first_seen": f"round {min(rounds)}", "last_updated": today}
            n_nodes += 1
    known = {(e["from"], e["to"], e["type"]) for e in m["edges"]}
    for e in d.get("edges", []):
        if (e.get("type") not in EDGE_TYPES or e.get("evidence") not in EVIDENCE
                or e.get("from") not in m["nodes"] or e.get("to") not in m["nodes"]):
            continue
        key = (e["from"], e["to"], e["type"])
        if key in known:
            for ex in m["edges"]:
                if (ex["from"], ex["to"], ex["type"]) == key:
                    ex["strain"] = e.get("strain", ex.get("strain", "none"))
            continue
        m["edges"].append({"from": e["from"], "to": e["to"], "type": e["type"],
                           "evidence": e["evidence"], "strain": e.get("strain", "none"),
                           "note": e.get("note", ""), "added": f"round {min(rounds)} / {today}"})
        known.add(key)
        n_edges += 1
    for u in d.get("state_updates", []):
        nid = u.get("id")
        if nid in m["nodes"] and u.get("state") in NODE_STATES:
            m["nodes"][nid]["state"] = u["state"]
            m["nodes"][nid]["note"] = u.get("note", m["nodes"][nid].get("note", ""))
            m["nodes"][nid]["last_updated"] = today
            n_updates += 1
    return n_nodes, n_edges, n_updates


GLYPH = {"foundation": "==>", "enabling": "-->", "legitimacy": "~~>", "sustaining": "<->"}


def render(m: dict, mdir: Path, repo: str) -> None:
    lines = [f"# The observed Mesh — {repo} instrument region",
             f"Updated {m['updated']} · rounds mapped: {m['rounds_mapped']} · "
             f"{len(m['nodes'])} nodes · {len(m['edges'])} edges",
             "",
             "Edge glyphs: `==>` foundation · `-->` enabling · `~~>` legitimacy · `<->` sustaining.",
             "Conjectural edges are marked `(conj)` and are never load-bearing.", ""]
    by_entity: dict[str, list[str]] = {}
    for nid, n in m["nodes"].items():
        by_entity.setdefault(n.get("entity") or "cross-domain", []).append(nid)
    for ent, nids in sorted(by_entity.items()):
        lines.append(f"## {ent}")
        for nid in sorted(nids):
            n = m["nodes"][nid]
            lines.append(f"- **{n['name']}** [`{n['state']}`] — {n.get('note','')}")
        lines.append("")
    lines.append("## Edges")
    for e in sorted(m["edges"], key=lambda x: (x["from"], x["to"])):
        conj = " (conj)" if e["evidence"] == "conjectural" else ""
        strain = f" ⚠{e['strain']}" if e.get("strain") not in (None, "none") else ""
        lines.append(f"- `{e['from']}` {GLYPH[e['type']]} `{e['to']}` "
                     f"[{e['type']}/{e['evidence']}{conj}]{strain} — {e.get('note','')}")
    lines += ["", "## Diagram", "", "```mermaid", "graph LR"]
    for nid, n in m["nodes"].items():
        label = n["name"][:40].replace('"', "'")
        mark = {"stable": "", "strained": " ⚠", "hollowing": " 🕳", "tipping-window": " ⚡"}[n["state"]]
        lines.append(f'  {nid.replace("-","_")}["{label}{mark}"]')
    arrow = {"foundation": "==>", "enabling": "-->", "legitimacy": "-.->", "sustaining": "<-->"}
    for e in m["edges"]:
        lines.append(f'  {e["from"].replace("-","_")} {arrow[e["type"]]} {e["to"].replace("-","_")}')
    lines += ["```", ""]
    (mdir / "MAP.md").write_text("\n".join(lines), encoding="utf-8")


def run(repo: str, model: str, remap_all: bool) -> None:
    rdir = TOOLS / repo
    led = json.load((rdir / "predict" / "ledger.json").open(encoding="utf-8"))
    mdir = rdir / "map"
    mdir.mkdir(exist_ok=True)
    m = load_map(mdir)
    if remap_all:
        m = {"updated": "", "rounds_mapped": [], "nodes": {}, "edges": []}
    all_rounds = sorted({p.get("round", 0) for p in led["predictions"]})
    todo = [r for r in all_rounds if r not in m["rounds_mapped"]]
    if not todo:
        print(f"[{repo}] map current ({len(m['nodes'])} nodes); no unmapped rounds")
        return
    today = datetime.date.today().isoformat()
    print(f"[{repo}] mapping rounds {todo} onto {len(m['nodes'])}-node map…")
    prompt = (MAP_PROMPT.replace("{current_map}", map_summary(m))
              .replace("{rounds}", rounds_text(led, todo)))
    # lands in the dataset -> STRONG tier; extraction-shaped -> sonnet (LEARNINGS 3)
    r = chat(model, [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=4000)
    d = parse_json(r.text) if not r.error else None
    if d is None:
        print(f"  ! mapping failed: {r.error or 'unparseable'} -- map unchanged, rounds stay unmapped")
        return
    nn, ne, nu = apply_delta(m, d, todo, today)
    m["rounds_mapped"] = sorted(set(m["rounds_mapped"]) | set(todo))
    m.setdefault("history", [])
    for rd in todo:
        m["history"].append({"label": f"round {rd}", "date": today})
    m["updated"] = today
    json.dump(m, (mdir / "map.json").open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
    render(m, mdir, repo)
    from suites.mesh_viz import write_html
    write_html(m, mdir, repo)
    print(f"  +{nn} nodes, +{ne} edges, {nu} state updates -> "
          f"{len(m['nodes'])} nodes / {len(m['edges'])} edges · MAP.md + map.html rendered")


DEEPEN_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. You are deepening an observed Mesh —
a dependency map (nodes = stable configurations, edges = typed structural-necessity claims:
"B cannot persist without A"). The map below was built from an instrument's analysis rounds; it is
shallow. Your job: for the region around the nodes below, add the structurally important
dependencies the rounds did not surface — upstream supports, downstream dependents, cross-domain
couplings, and the ASSUMED SUBSTRATES (background conditions every node takes for granted — the
theory says these are where the most dangerous fragilities concentrate, precisely because they are
not usually drawn; draw them here as nodes with note prefix "substrate assumption:").

DISCIPLINE (violations make the map worthless):
- Edge types: foundation (hard: B breaks with A) | enabling (softer: alternatives exist — the note
  MUST name the alternative path) | legitimacy (belief-mediated, nonlinear) | sustaining (mutual
  loop: add BOTH directions).
- Evidence tiers: formal | empirical | historical | analytical | conjectural. Deepening mostly
  produces analytical and conjectural — mark them honestly; conjectural is allowed and flagged.
  Use the web to upgrade to empirical where a checkable source exists (cite it in the note).
- Direction: from supporter to dependent. Check each edge: does A hold B up, or the reverse?
- Nodes are configurations, not events, categories, or organizations-as-such.
- Add AT MOST {cap} new nodes. Depth beats breadth: prefer completing the structure around
  existing strained/tipping nodes over opening new territory.

CURRENT MAP:
{current_map}

Return ONLY JSON (same schema as always):
{"nodes":[{"id":"kebab-slug","name":"...","entity":"watch-entity-id or cross-domain",
"state":"stable|strained|hollowing|tipping-window","note":"..."}],
"edges":[{"from":"...","to":"...","type":"...","evidence":"...","strain":"none|building|acute","note":"..."}],
"state_updates":[{"id":"...","state":"...","note":"..."}]}"""


def deepen(repo: str, model: str, cap: int) -> None:
    """Grow the map beyond what rounds directly observed: upstream/downstream structure,
    cross-domain couplings, and assumed substrates — web-grounded, evidence-tiered.
    Provenance marks every element as deepen-pass output, not round observation."""
    rdir = TOOLS / repo
    mdir = rdir / "map"
    m = load_map(mdir)
    if not m["nodes"]:
        raise SystemExit("map is empty -- run the round mapper first")
    today = datetime.date.today().isoformat()
    passno = m.get("deepen_passes", 0) + 1
    print(f"[{repo}] deepen pass {passno} on {len(m['nodes'])} nodes / {len(m['edges'])} edges…")
    prompt = (DEEPEN_PROMPT.replace("{today}", today).replace("{cap}", str(cap))
              .replace("{current_map}", map_summary(m)))
    r = chat(model + ":online", [{"role": "user", "content": prompt}],
             temperature=0.3, max_tokens=4000)
    d = parse_json(r.text) if not r.error else None
    if d is None:
        print(f"  ! deepening failed: {r.error or 'unparseable'} -- map unchanged")
        return
    marker = [f"deepen-{passno}"]
    nn, ne, nu = apply_delta(m, d, marker if False else [0], today)  # rounds label below
    # re-stamp provenance: apply_delta labels with "round 0"; deepen output is not a round
    for nid, n in m["nodes"].items():
        if n.get("first_seen") == "round 0":
            n["first_seen"] = f"deepen pass {passno}"
    for e in m["edges"]:
        if e.get("added", "").startswith("round 0"):
            e["added"] = f"deepen pass {passno} / {today}"
    m["deepen_passes"] = passno
    m.setdefault("history", []).append({"label": f"deepen pass {passno}", "date": today})
    m["updated"] = today
    json.dump(m, (mdir / "map.json").open("w", encoding="utf-8"), ensure_ascii=False, indent=1)
    render(m, mdir, repo)
    from suites.mesh_viz import write_html
    write_html(m, mdir, repo)
    print(f"  +{nn} nodes, +{ne} edges, {nu} state updates -> "
          f"{len(m['nodes'])} nodes / {len(m['edges'])} edges · MAP.md + map.html rendered")


def main() -> None:
    ap = argparse.ArgumentParser(description="Map observed reality as a Mesh after analysis rounds.")
    ap.add_argument("--repo", default="mesh")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    ap.add_argument("--all", action="store_true", help="rebuild the map from every round")
    ap.add_argument("--deepen", action="store_true",
                    help="web-grounded expansion pass: upstream/downstream + assumed substrates")
    ap.add_argument("--cap", type=int, default=8, help="max new nodes per deepen pass")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY"):
        if os.environ.get("LLM_BACKEND") != "claude-code":
            raise SystemExit("OPENROUTER_API_KEY not set (or set LLM_BACKEND=claude-code)")
    if a.deepen:
        deepen(a.repo, a.model, a.cap)
    else:
        run(a.repo, a.model, a.all)


if __name__ == "__main__":
    main()
