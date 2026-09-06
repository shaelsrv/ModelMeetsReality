"""Reality map — build this instance's mapcards; export shareable cards.

Implements docs/REALITY_MAP.md: every model gets a mapcard (aspects x E-span +
mechanism + record COUNTS ONLY). The cockpit Map tab renders map/mapcards.json;
--export produces the community-shareable card for one model (no private data).

  python -m suites.reality_map --build
  python -m suites.reality_map --export --repo my-model
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from suites.attribute_outcomes import MENU  # noqa: E402

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
MDIR = ROOT / "map"

ASPECTS = ["matter-energy", "life", "individual-minds", "attention-media",
           "institutions", "economy-markets", "states-geopolitics",
           "science-epistemics", "technology-tools", "culture-narrative",
           "infrastructure-logistics", "civilization-longterm"]

# aspects + E-span per model. Hand-coded v1 (transparent, editable); future:
# derive spans from classifier annotations once enough claims are annotated.
REGIONS = {}  # legacy fallback; coordinates now live in map/projections/


def _record(name: str) -> dict:
    """Counts and scores only — never claim contents."""
    rec = {"open": 0, "graded": 0, "supported": 0, "refuted": 0,
           "mean_brier": None, "attribution_share": 0}
    repo = TOOLS / name
    ledger_repo = repo if repo.exists() else TOOLS / "canon"
    rels = (["predict/ledger.json", "predict/live_ledger.json", "signals/signal_ledger.json"]
            if repo.exists() else ["predict/ledger.json"])
    for rel in rels:
        p = ledger_repo / rel
        if not p.exists():
            continue
        try:
            d = json.load(p.open(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for r in (d.get("predictions", d) if isinstance(d, dict) else d):
            if not repo.exists() and r.get("entity") != name:
                continue  # canon shared ledger: rows tagged by card slug
            if r.get("status", "open") == "open":
                rec["open"] += 1
            else:
                rec["graded"] += 1
                if r.get("status") in ("hit", "partial"):
                    rec["supported"] += 1
    # refutations: honored deletion/trial refutations noted in MODEL.md amendments
    mm = (repo / "MODEL.md") if repo.exists() else (TOOLS / "canon" / "models" / f"{name}.md")
    if mm.exists():
        t = mm.read_text(encoding="utf-8", errors="replace").lower()
        rec["refuted"] = t.count("refuted")
    briers = []
    tf = ROOT / "trajectory" / "trajectory.jsonl"
    if tf.exists():
        for l in tf.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            row = json.loads(l)
            if row.get("model") == name and row.get("brier") is not None:
                briers.append(row["brier"])
    if briers:
        rec["mean_brier"] = round(sum(briers) / len(briers), 3)
    att = TOOLS / "attribution-model" / "attributions" / "attributions.jsonl"
    if att.exists():
        n = 0
        for l in att.read_text(encoding="utf-8").splitlines():
            if l.strip() and json.loads(l).get("primary") == name:
                n += 1
        rec["attribution_share"] = n
    return rec


def tier(rec: dict) -> str:
    if rec["attribution_share"]:
        return "attributed"
    if rec["graded"]:
        return "graded"
    if rec["open"]:
        return "registered"
    return "declared"


def projections() -> list[dict]:
    """All registered projections — the mapping models themselves, versioned."""
    pdir = MDIR / "projections"
    out = []
    if pdir.exists():
        for f in sorted(pdir.glob("*.json")):
            out.append(json.load(f.open(encoding="utf-8")))
    return out


def build(projection_id: str | None = None) -> dict:
    """Build the map UNDER one projection. Intrinsic cards (mechanism, record) are
    projection-independent; coordinates come from the projection's assignments —
    so a better mapping model can replace this one without touching any card."""
    MDIR.mkdir(exist_ok=True)
    projs = projections()
    if not projs:
        raise SystemExit("no projections registered in map/projections/")
    proj = next((p for p in projs if p["id"] == projection_id), None) if projection_id \
        else next((p for p in projs if p.get("status") == "incumbent"), projs[0])
    aspects = proj["axes"]["horizontal"]["values"]
    n_floors = len(proj["axes"]["vertical"]["values"])
    on_disk = {d.name for d in TOOLS.iterdir()
               if d.is_dir() and (d / "MODEL.md").exists()}
    # canon cards live inside the canon repo rather than as sibling repos
    canon_cards = {f.stem for f in (TOOLS / "canon" / "models").glob("*.md")} \
        if (TOOLS / "canon" / "models").exists() else set()

    cards, phantom = [], []
    for name, asg in proj["assignments"].items():
        # An assignment whose repo was deleted would otherwise be drawn as a real
        # card with an empty record — a model that does not exist, counted as
        # covering map territory. Report it instead of quietly inflating coverage.
        if name not in on_disk and name not in canon_cards:
            phantom.append(name)
            continue
        rec = _record(name)
        cards.append({"model": name, "instance": "this-instance", "kind": asg["kind"],
                      "aspects": asg["aspects"], "e_span": asg["e_span"],
                      "level": asg.get("level", 0),
                      "mechanism": MENU.get(name, "")[:160],
                      "record": rec, "tier": tier(rec),
                      "updated": datetime.date.today().isoformat()})

    # A model absent from the projection is invisible to the map, the mindmap and
    # sleep — which is how seven repos silently went unmapped. Report them rather
    # than let coverage quietly under-count.
    unmapped = sorted(on_disk - set(proj["assignments"]))
    covered = set()
    for c in cards:
        for a in c["aspects"]:
            for e in range(c["e_span"][0], c["e_span"][1] + 1):
                covered.add((a, e))
    total = len(aspects) * n_floors
    out = {"built": datetime.date.today().isoformat(), "unmapped": unmapped,
           "phantom": phantom,
           "projection": {"id": proj["id"], "version": proj["version"],
                          "status": proj.get("status", "?"), "title": proj.get("title", ""),
                          "adequacy_graded": proj.get("adequacy", {}).get("graded", ""),
                          "available": [{"id": p["id"], "version": p["version"],
                                         "status": p.get("status")} for p in projs]},
           "aspects": aspects, "cards": cards,
           "coverage": {"cells_covered": len(covered), "cells_total": total,
                        "empty_floors": [f"E{e}" for e in range(n_floors)
                                         if not any((a, e) in covered for a in aspects)],
                        "empty_aspects": [a for a in aspects
                                          if not any((a, e) in covered
                                                     for e in range(n_floors))]}}
    (MDIR / "mapcards.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser(description="Build/export the instance's reality mapcards.")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--projection", help="projection id (default: the incumbent)")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--repo")
    a = ap.parse_args()
    if a.export:
        projs = projections()
        coords = {}
        kind = None
        for p in projs:
            asg = p.get("assignments", {}).get(a.repo or "")
            if asg:
                coords[f"{p['id']}.v{p['version']}"] = {"aspects": asg["aspects"],
                                                        "e_span": asg["e_span"]}
                kind = asg["kind"]
        if not coords:
            raise SystemExit("--export needs --repo assigned in at least one projection")
        card = {"model": a.repo, "instance": "ANONYMIZE-OR-NAME-ME", "kind": kind,
                "coords": coords,  # per-projection: a better mapping model just adds a key
                "mechanism": MENU.get(a.repo, ""),
                "record": _record(a.repo),
                "updated": datetime.date.today().isoformat(), "license": "CC-BY-4.0"}
        print(json.dumps(card, ensure_ascii=False, indent=1))
        return
    out = build(a.projection)
    cov = out["coverage"]
    pj = out["projection"]
    print(f"[map] projection {pj['id']}.v{pj['version']} ({pj['status']}) · "
          f"{len(out['cards'])} cards · {cov['cells_covered']}/{cov['cells_total']} "
          f"cells covered")
    print(f"  empty floors: {', '.join(cov['empty_floors']) or 'none'}")
    if out.get("phantom"):
        print(f"  [!] {len(out['phantom'])} assignment(s) point at models that no longer "
              f"exist — remove from the projection: {', '.join(out['phantom'])}")
    if out.get("unmapped"):
        print(f"  [!] {len(out['unmapped'])} model(s) NOT on the map — add them to the "
              f"projection: {', '.join(out['unmapped'])}")
    print(f"  empty aspects: {', '.join(cov['empty_aspects']) or 'none'}")


if __name__ == "__main__":
    main()
