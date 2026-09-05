"""Import a shared model repo — the contribution unit of this system.

A model repo is already self-contained (MODEL.md + ledgers + artifacts), so
sharing one is just copying a directory. What a naive copy gets WRONG is
provenance: the origin's claims land in your ledger and are counted as yours,
its embeddings were computed elsewhere, and it carries no coordinates for your
map. This import fixes all three.

What is kept:
  · MODEL.md — the theory, which is the actual thing being shared
  · supporting artifacts (cases, traces, notes) — the reasoning behind it

What is quarantined, never silently adopted:
  · CLAIMS — the origin's predictions are moved to imported/ and are NOT part of
    your record. Their record is theirs; you have not predicted anything yet.
  · index.jsonl — embeddings computed against another corpus; rebuilt locally.

  python -m suites.import_model ../shared/pressure-model
  python -m suites.import_model ./downloaded-model --slug their-pressure --keep-claims
  python -m suites.import_model --inspect ../shared/pressure-model
"""
from __future__ import annotations

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.fleet import ROOT, MODELS_DIR  # noqa: E402

LEDGERS = ("predict/ledger.json", "predict/live_ledger.json",
           "signals/signal_ledger.json")
# computed against the origin's corpus — meaningless here, rebuilt on demand
LOCAL_ONLY = ("index.jsonl",)


def inspect(src: Path) -> dict:
    mm = src / "MODEL.md"
    info = {"path": str(src), "has_model_md": mm.exists(),
            "claims": 0, "graded": 0, "files": 0, "bytes": 0,
            "carries_index": (src / "index.jsonl").exists(), "kind": "", "level": None}
    for rel in LEDGERS:
        f = src / rel
        if not f.exists():
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = d.get("predictions", d) if isinstance(d, dict) else d
        info["claims"] += len(rows)
        info["graded"] += sum(1 for r in rows if r.get("status", "open") != "open")
    for f in src.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            info["files"] += 1
            info["bytes"] += f.stat().st_size
    if mm.exists():
        head = mm.read_text(encoding="utf-8", errors="replace")[:1500]
        for line in head.splitlines():
            if "**The kind:**" in line:
                info["kind"] = line.split("**The kind:**")[-1].strip()[:70]
    return info


def do_import(src: Path, slug: str | None, keep_claims: bool,
              aspects: str, span: str, level: int) -> None:
    if not (src / "MODEL.md").exists():
        raise SystemExit(f"{src} has no MODEL.md — not a model repo")
    slug = slug or src.name
    dst = MODELS_DIR / slug
    if dst.exists():
        raise SystemExit(f"{dst} already exists — pass --slug to rename")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", "__pycache__"))

    # 1. embeddings from another corpus are not yours
    dropped = []
    for name in LOCAL_ONLY:
        f = dst / name
        if f.exists():
            f.unlink()
            dropped.append(name)

    # 2. the origin's claims are quarantined, not adopted
    moved = 0
    if not keep_claims:
        q = dst / "imported"
        for rel in LEDGERS:
            f = dst / rel
            if not f.exists():
                continue
            try:
                d = json.load(f.open(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows = d.get("predictions", d) if isinstance(d, dict) else d
            if not rows:
                continue
            q.mkdir(exist_ok=True)
            (q / Path(rel).name).write_text(
                json.dumps({"note": ("Claims made by the ORIGIN instance. Kept for "
                                     "reference; they are not part of this instance's "
                                     "record and are not graded here."),
                            "imported_from": str(src), "imported_on":
                                datetime.date.today().isoformat(),
                            "predictions": rows}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            moved += len(rows)
            # leave a real, empty ledger in place
            f.write_text('{"predictions": []}', encoding="utf-8")

    # 3. provenance, so the model never pretends to be locally grown
    (dst / "IMPORTED.md").write_text(
        f"""# Imported model

Source: `{src}`
Imported: {datetime.date.today().isoformat()}
Claims quarantined: {moved} (see `imported/`) — not part of this instance's record.

The theory in MODEL.md is the shared thing. Its track record is not transferable:
a model's record belongs to the instance that made the predictions. To find out
whether this model works *for you*, register your own claims from it.

If you amend MODEL.md, note it here — a shared model that diverges silently
becomes a different model wearing the same name.
""", encoding="utf-8")

    # 4. register locally
    f = ROOT / "fleet.json"
    cfg = json.load(f.open(encoding="utf-8")) if f.exists() else {"models": []}
    if slug not in cfg.setdefault("models", []):
        cfg["models"].append(slug)
        f.write_text(json.dumps(cfg, indent=1), encoding="utf-8")

    pdir = ROOT / "map" / "projections"
    mapped = []
    for pf in sorted(pdir.glob("*.json")) if pdir.exists() else []:
        proj = json.load(pf.open(encoding="utf-8"))
        if slug in proj.get("assignments", {}):
            continue
        try:
            lo, hi = (int(x) for x in span.split(","))
        except ValueError:
            lo, hi = 9, 13
        proj.setdefault("assignments", {})[slug] = {
            "aspects": [s.strip() for s in aspects.split(",") if s.strip()],
            "e_span": [lo, hi], "kind": "forecaster", "level": level}
        pf.write_text(json.dumps(proj, ensure_ascii=False, indent=1), encoding="utf-8")
        mapped.append(pf.stem)

    print(f"imported {slug}")
    print(f"  -> {dst}")
    if moved:
        print(f"  {moved} origin claim(s) quarantined in imported/ — NOT your record")
    if dropped:
        print(f"  dropped {', '.join(dropped)} (rebuild: python -m suites.memory_index --build)")
    print(f"  registered in fleet.json" + (f"; mapped in {', '.join(mapped)}" if mapped else ""))
    print("\n  next: read MODEL.md, then register YOUR first claim from it.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Import a shared model repo.")
    ap.add_argument("source", nargs="?")
    ap.add_argument("--inspect", metavar="PATH")
    ap.add_argument("--slug")
    ap.add_argument("--keep-claims", action="store_true",
                    help="adopt the origin's claims as your own (rarely correct)")
    ap.add_argument("--aspects", default="science-epistemics")
    ap.add_argument("--e-span", default="9,13")
    ap.add_argument("--level", type=int, default=0)
    a = ap.parse_args()

    if a.inspect:
        i = inspect(Path(a.inspect))
        print(f"{i['path']}")
        print(f"  model document : {'yes' if i['has_model_md'] else 'NO — not importable'}")
        print(f"  kind           : {i['kind'] or '(unstated)'}")
        print(f"  claims         : {i['claims']} ({i['graded']} graded) — would be quarantined")
        print(f"  carries index  : {'yes — will be dropped' if i['carries_index'] else 'no'}")
        print(f"  size           : {i['files']} files, {i['bytes']//1024} KB")
        return
    if not a.source:
        ap.print_help()
        return
    do_import(Path(a.source), a.slug, a.keep_claims, a.aspects, a.e_span, a.level)


if __name__ == "__main__":
    main()
