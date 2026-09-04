"""Sensing map — abstraction-cycle cartography of a watched domain.

The mesh gets a dependency map (mesh_map); this is the same move with the OTHER imported
methodology: the my-model model's abstraction cycle (absorption -> anomaly ->
abstraction), applied per the user's ask to the AI domain via my-model's rounds. After
each analysis round, the round's observations compile into a map of the domain's
FRAMEWORKS — the reigning stable framings — each placed in its cycle phase with its
constraint stack, observed patches, accumulated anomalies, and candidate new names.

Map units (from the my-model methodology):
  * framework: a reigning framing (e.g. "capability progress = benchmark scores"), with
    phase: absorption (holding comfortably) | anomaly (contradictions accumulating) |
    patching (visible methodology revisions / definitional stretches) | naming-contest
    (successor vocabulary competing) | reorganized (a new framework has stabilized)
  * constraint stack per framework: which layers hold it in place (instruments,
    vocabulary, institutions, funding, careers) and which are cracking
  * patches: countable absorption events (the patch-before-crack signature)
  * anomalies: what the current framing cannot hold, and whether each arrived by
    amplitude (signal too big) or resolution (sharper instruments)
  * name_candidates: successor vocabulary observed in the wild
  * sensing_bias: what this domain's own instruments structurally cannot see

ISOLATION NOTE: this map is OPERATOR-SIDE cartography, like the collision registry.
It borrows the my-model MODEL.md as its lens over another instrument's rounds
because the user asked for exactly that cross-application — but the map is never fed
back into any instrument's prediction prompts. Models stay blind to each other; the
operator does not have to be.

Wired via watch.json {"post_analysis": "sensing_map"}. Writes <repo>/map/sensing_map.json
+ SENSING_MAP.md.

  python -m suites.sensing_map --repo my-model
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

PHASES = {"absorption", "anomaly", "patching", "naming-contest", "reorganized"}
LAYERS = ("instruments", "vocabulary", "institutions", "funding", "careers")

MAP_PROMPT = """You are the cartographer for an abstraction-cycle instrument. Its methodology (the
my-model model): domains are organized by reigning FRAMEWORKS held in place by a constraint
stack (instruments, vocabulary, institutions, funding, careers). Contradictions are ABSORBED via
visible patches until anomaly pressure — arriving by amplitude (signal too big) or resolution
(sharper instruments) — cracks multiple layers, and a NAMING step stabilizes a successor. The
domain's own sensing surface is survival-biased: it grows vocabulary for internal threats faster
than for externalities it causes.

From the new analysis rounds below, propose a DELTA to the existing map of the watched domain.

RULES:
- A framework is a reigning FRAMING ("capability progress = benchmark scores"), not a technology,
  company, or event. Events are evidence: they land as patches, anomalies, or name_candidates.
- Phase must be earned by the evidence in the rounds: absorption | anomaly | patching |
  naming-contest | reorganized. Do not advance a phase without an observed patch, anomaly, or
  naming event to point to.
- Every patch/anomaly entry needs a one-line concrete referent (what happened, roughly when).
  Anomalies must state their arrival channel: amplitude or resolution.
- cracking: which constraint-stack layers show cracks (subset of instruments, vocabulary,
  institutions, funding, careers), only if evidenced.
- sensing_bias: name what this domain's instruments structurally cannot see — one or two sharp
  entries, not a list of everything.
- Reuse existing framework ids; prefer updating phase/patches over minting near-duplicates.
- Only map what the rounds support. An empty delta is a valid answer.

CURRENT MAP:
{current_map}

NEW ROUNDS (observations, model reads, claims, verdicts):
{rounds}

Return ONLY JSON:
{"frameworks":[{"id":"kebab-slug","name":"...","entity":"watch-entity-id","phase":"...",
"cracking":["instruments"],"patches":[{"what":"...","when":"..."}],
"anomalies":[{"what":"...","channel":"amplitude|resolution","when":"..."}],
"name_candidates":["..."],"note":"..."}],
"sensing_bias":[{"blind_spot":"...","why_structural":"..."}]}"""


def load_map(mdir: Path) -> dict:
    f = mdir / "sensing_map.json"
    if f.exists():
        return json.load(f.open(encoding="utf-8"))
    return {"updated": "", "rounds_mapped": [], "frameworks": {}, "sensing_bias": []}


def map_summary(m: dict) -> str:
    if not m["frameworks"]:
        return "(empty map)"
    out = []
    for fid, f in m["frameworks"].items():
        out.append(f"- {fid} \"{f['name']}\" [{f['phase']}] patches:{len(f.get('patches',[]))} "
                   f"anomalies:{len(f.get('anomalies',[]))} cracking:{f.get('cracking',[])}")
    return "\n".join(out)[:5000]


def rounds_text(led: dict, which: list[int]) -> str:
    out = []
    for p in led["predictions"]:
        if p.get("round") not in which:
            continue
        out.append(json.dumps({k: p.get(k) for k in
                               ("entity", "round", "observed", "model_read", "claim",
                                "status", "what_happened") if p.get(k)}, ensure_ascii=False))
    return "\n".join(out)[:16000]


def apply_delta(m: dict, d: dict, rounds: list[int], today: str) -> tuple[int, int]:
    n_new = n_upd = 0
    for f in d.get("frameworks", []):
        fid = (f.get("id") or "").strip()
        if not fid or f.get("phase") not in PHASES:
            continue
        entry = m["frameworks"].get(fid)
        if entry is None:
            entry = {"name": f.get("name", fid), "entity": f.get("entity", ""),
                     "phase": f["phase"], "cracking": [], "patches": [], "anomalies": [],
                     "name_candidates": [], "note": "", "phase_history": [],
                     "first_seen": f"round {min(rounds)}"}
            m["frameworks"][fid] = entry
            n_new += 1
        else:
            n_upd += 1
        if entry["phase"] != f["phase"]:
            entry["phase_history"].append({"from": entry["phase"], "to": f["phase"], "on": today})
            entry["phase"] = f["phase"]
        entry["cracking"] = sorted(set(entry.get("cracking", []))
                                   | {c for c in f.get("cracking", []) if c in LAYERS})
        seen_p = {p.get("what") for p in entry["patches"]}
        entry["patches"] += [p for p in f.get("patches", []) if p.get("what") not in seen_p]
        seen_a = {a.get("what") for a in entry["anomalies"]}
        entry["anomalies"] += [a for a in f.get("anomalies", []) if a.get("what") not in seen_a]
        entry["name_candidates"] = sorted(set(entry.get("name_candidates", []))
                                          | set(f.get("name_candidates", [])))
        if f.get("note"):
            entry["note"] = f["note"]
        entry["last_updated"] = today
    seen_b = {b.get("blind_spot") for b in m["sensing_bias"]}
    m["sensing_bias"] += [b for b in d.get("sensing_bias", [])
                          if b.get("blind_spot") and b["blind_spot"] not in seen_b]
    return n_new, n_upd


PHASE_GLYPH = {"absorption": "🟢", "anomaly": "🟡", "patching": "🟠",
               "naming-contest": "🔴", "reorganized": "🔵"}


def render(m: dict, mdir: Path, repo: str) -> None:
    lines = [f"# The sensing map — {repo} watched domain, abstraction-cycle state",
             f"Updated {m['updated']} · rounds mapped: {m['rounds_mapped']} · "
             f"{len(m['frameworks'])} frameworks",
             "",
             "Phases: 🟢 absorption · 🟡 anomaly accumulating · 🟠 patching · "
             "🔴 naming-contest · 🔵 reorganized. The patch-before-crack count is the "
             "leading indicator.", ""]
    by_entity: dict[str, list[str]] = {}
    for fid, f in m["frameworks"].items():
        by_entity.setdefault(f.get("entity") or "cross-domain", []).append(fid)
    for ent, fids in sorted(by_entity.items()):
        lines.append(f"## {ent}")
        for fid in sorted(fids):
            f = m["frameworks"][fid]
            lines.append(f"### {PHASE_GLYPH[f['phase']]} {f['name']}  `{f['phase']}`")
            if f.get("note"):
                lines.append(f"{f['note']}")
            if f.get("cracking"):
                lines.append(f"- **Cracking layers:** {', '.join(f['cracking'])}")
            for p in f.get("patches", []):
                lines.append(f"- patch: {p.get('what','')} ({p.get('when','')})")
            for a in f.get("anomalies", []):
                lines.append(f"- anomaly [{a.get('channel','?')}]: {a.get('what','')} ({a.get('when','')})")
            if f.get("name_candidates"):
                lines.append(f"- name candidates: {', '.join(f['name_candidates'])}")
            for h in f.get("phase_history", []):
                lines.append(f"- phase shift: {h['from']} → {h['to']} ({h['on']})")
            lines.append("")
    if m["sensing_bias"]:
        lines.append("## What this domain's instruments cannot see")
        for b in m["sensing_bias"]:
            lines.append(f"- **{b['blind_spot']}** — {b.get('why_structural','')}")
        lines.append("")
    (mdir / "SENSING_MAP.md").write_text("\n".join(lines), encoding="utf-8")


def run(repo: str, model: str, remap_all: bool) -> None:
    rdir = TOOLS / repo
    led = json.load((rdir / "predict" / "ledger.json").open(encoding="utf-8"))
    mdir = rdir / "map"
    mdir.mkdir(exist_ok=True)
    m = load_map(mdir)
    if remap_all:
        m = {"updated": "", "rounds_mapped": [], "frameworks": {}, "sensing_bias": []}
    all_rounds = sorted({p.get("round", 0) for p in led["predictions"]})
    todo = [r for r in all_rounds if r not in m["rounds_mapped"]]
    if not todo:
        print(f"[{repo}] sensing map current ({len(m['frameworks'])} frameworks); no unmapped rounds")
        return
    today = datetime.date.today().isoformat()
    print(f"[{repo}] sensing-mapping rounds {todo}…")
    prompt = (MAP_PROMPT.replace("{current_map}", map_summary(m))
              .replace("{rounds}", rounds_text(led, todo)))
    r = chat(model, [{"role": "user", "content": prompt}], temperature=0.2, max_tokens=4000)
    d = parse_json(r.text) if not r.error else None
    if d is None:
        print(f"  ! mapping failed: {r.error or 'unparseable'} -- map unchanged")
        return
    nn, nu = apply_delta(m, d, todo, today)
    m["rounds_mapped"] = sorted(set(m["rounds_mapped"]) | set(todo))
    m.setdefault("history", [])
    for rd in todo:
        m["history"].append({"label": f"round {rd}", "date": today})
    m["updated"] = today
    json.dump(m, (mdir / "sensing_map.json").open("w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    render(m, mdir, repo)
    from suites.sensing_viz import write_html
    write_html(m, mdir, repo)
    print(f"  +{nn} frameworks, {nu} updated -> {len(m['frameworks'])} total · "
          f"map/SENSING_MAP.md rendered")


DEEPEN_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. You are deepening a sensing map — an
abstraction-cycle cartography of a domain. Its methodology (the my-model model): domains are
organized by reigning FRAMEWORKS held in place by a constraint stack (instruments, vocabulary,
institutions, funding, careers); contradictions are absorbed via visible patches until anomaly
pressure (amplitude = signal too big, or resolution = sharper instruments) cracks multiple layers,
and a NAMING step stabilizes a successor. Sensing surfaces are survival-biased: a field grows
vocabulary for internal threats faster than for externalities it causes.

The map below covers only what analysis rounds happened to observe. Your job: EXPLORE the aspects
listed and map the reigning frameworks there — 2-3 per aspect, at most {cap} total new frameworks.

ASPECTS TO EXPLORE: {aspects}

RULES:
- A framework is a reigning FRAMING (a sentence someone in the field would treat as obvious), not a
  technology, company, or event. Name it as the framing: "X = Y".
- Use the web: every phase assignment must rest on 1-3 CONCRETE, DATED referents recorded as
  patches (absorption events: methodology revisions, definitional stretches, "adjusted" metrics),
  anomalies (what the framing cannot hold — mark channel: amplitude | resolution), or
  name_candidates (successor vocabulary actually observed in the wild, not invented by you).
- Phases: absorption | anomaly | patching | naming-contest | reorganized. Do not dramatize: most
  reigning frameworks are in absorption, and saying so is valuable. A framework in "patching" needs
  observable patches listed.
- cracking: constraint-stack layers (instruments, vocabulary, institutions, funding, careers) only
  where evidenced.
- sensing_bias: for the explored aspects, 1-2 sharp entries on what the field's own instruments
  structurally cannot see (survival bias: named threats are internal; unnamed ones are caused
  externalities).
- entity: use the aspect slug you were given for new frameworks.
- Reuse existing framework ids if an aspect's framing is already mapped; prefer enriching it.

CURRENT MAP:
{current_map}

Return ONLY JSON (same schema):
{"frameworks":[{"id":"kebab-slug","name":"...","entity":"aspect-slug","phase":"...",
"cracking":["..."],"patches":[{"what":"...","when":"..."}],
"anomalies":[{"what":"...","channel":"amplitude|resolution","when":"..."}],
"name_candidates":["..."],"note":"..."}],
"sensing_bias":[{"blind_spot":"...","why_structural":"..."}]}"""


def deepen(repo: str, model: str, aspects: str, cap: int) -> None:
    """Explore aspects of the domain the rounds did not cover: web-grounded framework
    mapping, phase assignments earned by dated referents."""
    rdir = TOOLS / repo
    mdir = rdir / "map"
    m = load_map(mdir)
    today = datetime.date.today().isoformat()
    passno = m.get("deepen_passes", 0) + 1
    print(f"[{repo}] sensing deepen pass {passno}: {aspects}")
    prompt = (DEEPEN_PROMPT.replace("{today}", today).replace("{cap}", str(cap))
              .replace("{aspects}", aspects).replace("{current_map}", map_summary(m)))
    r = chat(model + ":online", [{"role": "user", "content": prompt}],
             temperature=0.3, max_tokens=4000)
    d = parse_json(r.text) if not r.error else None
    if d is None:
        print(f"  ! deepening failed: {r.error or 'unparseable'} -- map unchanged")
        return
    nn, nu = apply_delta(m, d, [0], today)
    for f in m["frameworks"].values():
        if f.get("first_seen") == "round 0":
            f["first_seen"] = f"deepen pass {passno}"
    m["deepen_passes"] = passno
    m.setdefault("history", []).append(
        {"label": f"deepen pass {passno}", "date": today, "aspects": aspects})
    m["updated"] = today
    json.dump(m, (mdir / "sensing_map.json").open("w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    render(m, mdir, repo)
    from suites.sensing_viz import write_html
    write_html(m, mdir, repo)
    print(f"  +{nn} frameworks, {nu} enriched -> {len(m['frameworks'])} total")


def main() -> None:
    ap = argparse.ArgumentParser(description="Abstraction-cycle cartography from analysis rounds.")
    ap.add_argument("--repo", default="my-model")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--deepen", metavar="ASPECTS",
                    help="comma-separated aspects to explore (web-grounded expansion pass)")
    ap.add_argument("--cap", type=int, default=8, help="max new frameworks per deepen pass")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    if not os.environ.get("OPENROUTER_API_KEY"):
        if os.environ.get("LLM_BACKEND") != "claude-code":
            raise SystemExit("OPENROUTER_API_KEY not set (or set LLM_BACKEND=claude-code)")
    if a.deepen:
        deepen(a.repo, a.model, a.deepen, a.cap)
    else:
        run(a.repo, a.model, a.all)


if __name__ == "__main__":
    main()
