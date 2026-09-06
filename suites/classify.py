"""Classifier runner — apply the classifier meta-models to every fleet prediction.

The two classifier repos (my-model, my-model) define WHAT to annotate
(MODEL.md carries the schema and the falsifiable bets); this suite is the shared HOW:
sweep all fleet ledgers, annotate every claim lacking an annotation, store to
<classifier>/annotations/annotations.jsonl keyed by the SAME content key the trajectory
store uses — so annotations join graded outcomes for free, and the classifiers' bets
(hinge-crossing Brier gap, power-legitimacy horizon interaction) become testable the
moment enough joined rows exist.

Idempotent (skips annotated), parallel (4 workers), cheap-tier model by default
(classification is extraction-shaped -- LEARNINGS 3). Runs in the weekly loop.

  python -m suites.classify --classifier my-model
  python -m suites.classify --classifier my-model
  python -m suites.classify --all
  python -m suites.classify --join-report        # annotation x outcome slices
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import sys
from collections import defaultdict
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

from harness.fleet import MODEL_REPOS  # fleet.json registry
from harness.fleet import CLASSIFIERS

E_PROMPT = """You are a structural classifier. Apply the schema below to ONE prediction. Classify only
what the claim itself involves; do not forecast.

SCHEMA (E0-E14 emergence ladder; E0-E8 substrate floors: physics->chemistry->biology->minds;
E9-E14 coordination floors: attention/memes(E9) -> institutions(E10) -> economy(E11) ->
states(E12) -> epistemes(E13) -> civilizational(E14); E8/E9 is the hinge):
- entities: every distinct entity the claim involves, each with e_level (En) and role
  (actor | object | instrument | venue | measure). Place by OPERATING level; decompose compound
  entities first.
- relationships: pairs with type (depends-on | controls | measures | composes |
  installs-stakes-in | competes-with) and cross_level true/false.
- signature: levels_spanned (int), crosses_hinge (any relationship linking E<=8 to E>=9),
  max_level ("En"), coordination_only (all entities E9+).

PREDICTION: {claim}
(made by instrument: {model}; domain: {domain})

Return ONLY JSON:
{"entities":[{"name":"...","e_level":"E11","role":"actor"}],
"relationships":[{"a":"...","b":"...","type":"...","cross_level":true}],
"signature":{"levels_spanned":0,"crosses_hinge":false,"max_level":"E12","coordination_only":false}}"""

LEG_PROMPT = """You are a power/legitimacy classifier. For ONE prediction, identify who holds POWER over
the outcome and who holds LEGITIMACY over it — they may differ, and the gap is the point. Classify
from publicly documented structure; do not forecast the outcome.

- power_holder: the entity whose choices most move this outcome. power_sources subset of
  [coercive-capacity, capital, legal-authority, agenda-control, network-position,
  information-asymmetry, operational-control]. why: one line.
  demonstrated_recently: has this power been exercised/demonstrated in the recent past?
- legitimacy_holder: the entity with the recognized RIGHT over this outcome (may equal power
  holder). legitimacy_sources subset of [electoral-mandate, legal-constitutional, traditional,
  expertise, performance-track-record, charismatic, institutional-embedding, procedural].
  backing_institutions: named institutions that would defend the claim. past_work: what earned
  record, if any, the legitimacy rests on. why: one line.
- alignment: same_entity true/false; gap none|partial|split; gap_note.
- durability: legitimacy_renewal (how maintained); lapse_risk low|med|high.

PREDICTION: {claim}
(made by instrument: {model}; domain: {domain})

Return ONLY JSON:
{"power_holder":{"entity":"...","power_sources":["..."],"why":"...","demonstrated_recently":true},
"legitimacy_holder":{"entity":"...","legitimacy_sources":["..."],"backing_institutions":["..."],
"past_work":"...","why":"..."},
"alignment":{"same_entity":true,"gap":"none","gap_note":""},
"durability":{"legitimacy_renewal":"...","lapse_risk":"low"}}"""

PROMPTS = {"my-model": E_PROMPT, "my-model": LEG_PROMPT}


def _key(source, repo, claim, resolve_by):
    return hashlib.sha256(f"{source}|{repo}|{claim}|{resolve_by}".encode()).hexdigest()[:16]


def all_claims():
    out = []
    for repo in MODEL_REPOS:
        for rel in ("predict/ledger.json", "predict/live_ledger.json",
                    "signals/signal_ledger.json"):
            p = TOOLS / repo / rel
            if not p.exists():
                continue
            d = json.load(p.open(encoding="utf-8"))
            for r in (d.get("predictions", d) if isinstance(d, dict) else d):
                claim = (r.get("claim") or "")[:200]
                if not claim:
                    continue
                out.append({"key": _key("live", repo, claim, r.get("resolve_by", "")),
                            "model": repo, "claim": claim,
                            "domain": r.get("entity", r.get("mechanism", ""))[:60],
                            "status": r.get("status", "open")})
    return out


def annotate(classifier: str, model: str, limit: int) -> None:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    adir = TOOLS / classifier / "annotations"
    adir.mkdir(parents=True, exist_ok=True)
    afile = adir / "annotations.jsonl"
    done = set()
    if afile.exists():
        done = {json.loads(l)["key"] for l in afile.read_text(encoding="utf-8").splitlines()
                if l.strip()}
    claims = [c for c in all_claims() if c["key"] not in done]
    if limit:
        claims = claims[:limit]
    print(f"[{classifier}] annotating {len(claims)} claims ({len(done)} done) · {model}")
    prompt = PROMPTS[classifier]

    def one(c):
        p = (prompt.replace("{claim}", c["claim"]).replace("{model}", c["model"])
             .replace("{domain}", c["domain"]))
        r = chat(model, [{"role": "user", "content": p}], temperature=0.1, max_tokens=1400)
        return c, (parse_json(r.text) if not r.error else None)

    n_ok = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = [ex.submit(one, c) for c in claims]
        with afile.open("a", encoding="utf-8") as f:
            for fut in as_completed(futs):
                c, d = fut.result()
                if not d:
                    print(f"  ! {c['claim'][:56]}")
                    continue
                row = {"key": c["key"], "model": c["model"], "claim": c["claim"],
                       "annotated": datetime.date.today().isoformat(),
                       "annotation": d}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                n_ok += 1
                if classifier == "my-model":
                    sig = d.get("signature", {})
                    print(f"  E:{sig.get('max_level','?'):>4} span={sig.get('levels_spanned','?')} "
                          f"hinge={'Y' if sig.get('crosses_hinge') else 'n'} {c['claim'][:52]}")
                else:
                    al = d.get("alignment", {})
                    print(f"  gap={al.get('gap','?'):>7} "
                          f"pw={d.get('power_holder',{}).get('entity','?')[:24]:<26}"
                          f"{c['claim'][:44]}")
    print(f"[{classifier}] +{n_ok} annotations")


def join_report() -> None:
    """Slice graded outcomes by annotation signatures — the classifiers' bets, checked."""
    traj = ROOT / "trajectory" / "trajectory.jsonl"
    graded = {}
    if traj.exists():
        for l in traj.read_text(encoding="utf-8").splitlines():
            r = json.loads(l)
            if r.get("brier") is not None and r.get("source") == "live":
                graded[r["key"]] = r
    L = [f"# Classifier joins — annotation x outcome",
         f"Updated {datetime.date.today().isoformat()} · {len(graded)} graded live rows "
         f"available for joining", ""]
    for cl in CLASSIFIERS:
        afile = TOOLS / cl / "annotations" / "annotations.jsonl"
        if not afile.exists():
            L += [f"## {cl}", "(no annotations yet)", ""]
            continue
        anns = [json.loads(l) for l in afile.read_text(encoding="utf-8").splitlines() if l.strip()]
        joined = [(a, graded[a["key"]]) for a in anns if a["key"] in graded]
        L += [f"## {cl}: {len(anns)} annotations, {len(joined)} joined to graded outcomes"]
        if cl == "my-model":
            buckets = defaultdict(list)
            for a, g in joined:
                sig = a["annotation"].get("signature", {})
                buckets["hinge-crossing" if sig.get("crosses_hinge")
                        else "same-side"].append(g["brier"])
            for b, vs in sorted(buckets.items()):
                L.append(f"- {b}: n={len(vs)} mean Brier {sum(vs)/len(vs):.3f}")
        else:
            buckets = defaultdict(list)
            for a, g in joined:
                gap = a["annotation"].get("alignment", {}).get("gap", "?")
                buckets[gap].append(g["brier"])
            for b, vs in sorted(buckets.items()):
                L.append(f"- gap={b}: n={len(vs)} mean Brier {sum(vs)/len(vs):.3f}")
        L.append("")
    out = ROOT / "trajectory" / "CLASSIFIER_JOINS.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))
    print(f"-> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run classifier meta-models over fleet predictions.")
    ap.add_argument("--classifier", choices=CLASSIFIERS)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--join-report", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="classification is extraction-shaped; STRONG-cheap tier")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.join_report:
        join_report()
        return
    if not os.environ.get("OPENROUTER_API_KEY"):
        if os.environ.get("LLM_BACKEND") != "claude-code":
            raise SystemExit("OPENROUTER_API_KEY not set (or set LLM_BACKEND=claude-code)")
    targets = CLASSIFIERS if a.all or not a.classifier else [a.classifier]
    for t in targets:
        annotate(t, a.model, a.limit)


if __name__ == "__main__":
    main()
