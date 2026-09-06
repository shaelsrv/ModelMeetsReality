"""Hunch candidate generator — stochastic exploration of the fleet's un-visited intersections.

Implements hunch-generator/MODEL.md: draw a random (E-level x time-horizon x domain x
2-3 fleet models), cross the models' mechanisms at that intersection, and generate hunch
CANDIDATES. Candidates are QUARANTINED in hunch-tracker/candidates/ — they are NOT
hunches until the operator promotes one (P2: machine and human calibration never mix).
Every draw is seeded and logged so a batch is reproducible.

Two kinds of draw: 'hunch' crosses 2-3 random fleet models at a random intersection;
'model-seed' hunts for a GAP the whole fleet misses there — a promoted model-seed
that warms under scanning graduates into a NEW sister model, not just a confirmed
intuition.

  python -m suites.hunch_gen --generate --n 3 [--mode hunch|model-seed|both]
  python -m suites.hunch_gen --generate --seed 42
  python -m suites.hunch_gen --list
  python -m suites.hunch_gen --promote <candidate-id>
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
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



def _fleet_repos():
    """Model repos for THIS instance, from fleet.json — never a hardcoded list."""
    try:
        import json as _j
        cfg = _j.load((Path(__file__).resolve().parents[1] / "fleet.json").open(encoding="utf-8"))
        return list(cfg.get("models", [])) + list(cfg.get("classifiers", []))
    except Exception:
        return []

TOOLS = _models_dir(ROOT)
CDIR = TOOLS / "hunch-tracker" / "candidates"
HDIR = TOOLS / "hunch-tracker" / "hunches"

FLEET = _fleet_repos()

E_LEVELS = ["E4 biochemistry", "E6 organisms", "E7 social animals", "E8 individual minds",
            "E9 attention/memes", "E10 institutions", "E11 economy", "E12 states",
            "E13 epistemes", "E14 civilizational"]
HORIZONS = ["weeks", "months", "1-2 years", "5-10 years", "a generation"]
DOMAINS = ["media & entertainment", "labor & professions", "education & credentialing",
           "religion & ritual", "cities & housing", "friendship & family",
           "science & research practice", "law & enforcement", "logistics & supply",
           "health & medicine", "sport & competition", "language & translation",
           "art & authorship", "energy & climate response", "finance & credit",
           "warfare & security", "food & agriculture", "aging & demographics"]

GENERATE = """You are a hunch generator inside a family of falsifiable structural models. Your job:
produce 1-2 PRE-THEORETICAL HUNCHES that fall out of crossing the given models' mechanisms at a
random, probably un-visited intersection. A hunch is a felt directional guess — early, statable,
concrete enough to imply observable signals — NOT a formal prediction and NOT a restatement of
any input model's existing claims.

THE DRAW (explore exactly this intersection):
- Emergence level: {elevel}
- Time horizon: {horizon}
- Domain: {domain}

MODELS TO CROSS (their core mechanisms, from their own docs):
{models}

Quality bar (reject your own drafts that fail it):
- Non-obvious to a smart generalist; a reasonable skeptic might bet against it.
- Genuinely uses the intersection: the level, the horizon, AND the domain shape the guess.
- Emerges from the CROSSING of the models, not from any single one alone.
- Implies 2-3 concrete observables someone could scan for.
- Stated in one or two plain sentences, first person optional, hedged like a hunch
  ("I suspect...", "feels like...") — not academic prose.

Return ONLY JSON:
{"candidates":[{"hunch":"the hunch, 1-2 plain sentences",
"why_this_intersection":"one line: how level x horizon x domain x models produced it",
"implied_observables":["...","..."],
"skeptic_bet":"one line: what a skeptic would bet instead"}]}"""

MODEL_SEED = """You are a model-seed generator inside a family of falsifiable structural models. Your job:
find a MISSING MODEL — a mechanism or phenomenon at the given intersection that NONE of the fleet's
existing models covers, and state the hunch that a dedicated model there would have real predictive
content. This is a hunch about a GAP: if it warms under scanning, it graduates into a new sister
model, not just a confirmed intuition.

THE DRAW (look for the gap exactly here):
- Emergence level: {elevel}
- Time horizon: {horizon}
- Domain: {domain}

THE EXISTING FLEET (mechanisms already covered — your seed must NOT be reducible to these; name
which existing model comes closest and why it still misses the phenomenon):
{models}

Quality bar:
- Names a real recurring mechanism (not a topic): something that happens the same way across
  instances and could anchor premises + falsifiable consequences.
- Not reducible to any listed model or an obvious combination of two.
- Implies 2-3 concrete observables that would show the mechanism operating.
- The seed should feel like the fleet's other models did at birth: one strong structural bet.

Return ONLY JSON:
{"candidates":[{"hunch":"the gap-hunch, 1-2 plain sentences",
"proposed_model_name":"short-kebab-name for the would-be sister model",
"core_mechanism":"one line: the recurring mechanism the new model would formalize",
"nearest_existing":"which fleet model comes closest, and the one line it misses",
"implied_observables":["...","..."],
"skeptic_bet":"one line: what a skeptic would bet instead"}]}"""


def _mechanism(repo: str) -> str:
    p = TOOLS / repo / "MODEL.md"
    if not p.exists():
        return f"{repo}: (no MODEL.md)"
    text = p.read_text(encoding="utf-8", errors="replace")
    prem = re.split(r"\n## ", text)
    body = next((s for s in prem if s.lower().startswith("premise")), text)
    return f"### {repo}\n" + body[:1600]


def cmd_generate(n: int, seed: int | None, model: str, mode: str) -> None:
    CDIR.mkdir(parents=True, exist_ok=True)
    if seed is None:
        seed = random.SystemRandom().randrange(10**6)
    rng = random.Random(seed)
    today = datetime.date.today().isoformat()
    print(f"[gen] seed={seed} · {n} draws · mode={mode} · {model}")
    for i in range(n):
        kind = mode if mode != "both" else ("model-seed" if rng.random() < 0.4 else "hunch")
        if kind == "model-seed":
            # a gap hunt reads the WHOLE fleet as the covered ground, not a random pair
            draw = {"kind": kind, "elevel": rng.choice(E_LEVELS),
                    "horizon": rng.choice(HORIZONS), "domain": rng.choice(DOMAINS),
                    "models": FLEET}
            tmpl, temp = MODEL_SEED, 0.9
        else:
            draw = {"kind": kind, "elevel": rng.choice(E_LEVELS),
                    "horizon": rng.choice(HORIZONS), "domain": rng.choice(DOMAINS),
                    "models": rng.sample(FLEET, rng.choice([2, 3]))}
            tmpl, temp = GENERATE, 0.8
        mechs = "\n\n".join(_mechanism(m) for m in draw["models"])
        p = (tmpl.replace("{elevel}", draw["elevel"])
             .replace("{horizon}", draw["horizon"]).replace("{domain}", draw["domain"])
             .replace("{models}", mechs))
        r = chat(model, [{"role": "user", "content": p}], temperature=temp, max_tokens=1800)
        d = parse_json(r.text) if not r.error else None
        if not d or not d.get("candidates"):
            print(f"  draw {i+1} [{kind}: {draw['elevel'].split()[0]} x {draw['horizon']} x "
                  f"{draw['domain']}]: generation failed ({r.error or 'unparseable'})")
            continue
        for j, c in enumerate(d["candidates"]):
            cid = f"gen-{today}-s{seed}-{i+1}{chr(97+j)}"
            row = {"id": cid, "generated": today, "source": "generator", "kind": kind,
                   "draw": {**draw, "seed": seed}, **c, "promoted": False}
            (CDIR / f"{cid}.json").write_text(
                json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
            lens = "fleet-gap" if kind == "model-seed" else "+".join(draw["models"])
            print(f"  [{cid}] {kind} · {draw['elevel'].split()[0]} x {draw['horizon']} x "
                  f"{draw['domain']} x {lens}")
            if kind == "model-seed":
                print(f"    seed: {c.get('proposed_model_name','?')} — {c.get('core_mechanism','')}")
            print(f"    {c.get('hunch','')}")
            print(f"    skeptic: {c.get('skeptic_bet','')[:100]}")


def cmd_list() -> None:
    if not CDIR.exists():
        print("(no candidates)")
        return
    for f in sorted(CDIR.glob("*.json")):
        c = json.load(f.open(encoding="utf-8"))
        flag = "PROMOTED" if c.get("promoted") else "candidate"
        d = c.get("draw", {})
        print(f"  [{flag:>9}] {c['id']} · {d.get('elevel','?').split()[0]} x "
              f"{d.get('horizon','?')} x {d.get('domain','?')}")
        print(f"      {c.get('hunch','')[:110]}")


def cmd_promote(cid: str, model: str) -> None:
    f = CDIR / f"{cid}.json"
    if not f.exists():
        raise SystemExit(f"no candidate {cid}")
    c = json.load(f.open(encoding="utf-8"))
    if c.get("promoted"):
        raise SystemExit(f"{cid} already promoted")
    from suites.hunch_track import cmd_add
    if c.get("kind") == "model-seed" and c.get("proposed_model_name"):
        hid = f"seed-{c['proposed_model_name'][:40]}"
    else:
        hid = f"gen-{re.sub(r'[^a-z0-9]+', '-', c['hunch'].lower()).strip('-')[:40]}"
    cmd_add(hid, c["hunch"], model)
    # stamp machine provenance onto the registered hunch — the calibration quarantine (P2)
    hf = HDIR / f"{hid}.json"
    h = json.load(hf.open(encoding="utf-8"))
    h["source"] = "generator"
    h["kind"] = c.get("kind", "hunch")
    if c.get("kind") == "model-seed":
        h["graduation_path"] = (f"new sister model '{c.get('proposed_model_name','')}' — "
                                f"mechanism: {c.get('core_mechanism','')}")
    h["provenance"] = {"candidate_id": cid, "draw": c.get("draw", {}),
                       "promoted_by_operator": datetime.date.today().isoformat()}
    hf.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")
    c["promoted"] = True
    c["promoted_as"] = hid
    f.write_text(json.dumps(c, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"promoted {cid} -> hunch '{hid}' (source=generator, quarantined calibration)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate hunch candidates by random exploration.")
    ap.add_argument("--generate", action="store_true")
    ap.add_argument("--mode", choices=["hunch", "model-seed", "both"], default="both")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--promote", metavar="ID")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="generation lands nothing in ledgers by itself, but candidate "
                         "quality decides operator time — STRONG tier")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.list:
        cmd_list(); return
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    if a.generate:
        cmd_generate(a.n, a.seed, a.model, a.mode)
    if a.promote:
        cmd_promote(a.promote, a.model)


if __name__ == "__main__":
    main()
