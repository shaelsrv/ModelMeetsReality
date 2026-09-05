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

# --- What may land on YOUR DISK from a stranger's repo -------------------
#
# Importing used to be `copytree(ignore=[".git", "__pycache__"])`, which is a
# block-list: everything not named was copied. Demonstrated consequences of
# that, from a constructed hostile repo — every one of these landed:
#
#   setup.py              runs on `pip install .`
#   run.sh                runs if anyone executes it
#   model.pkl             arbitrary code on unpickle
#   .vscode/tasks.json    with runOn:folderOpen, executes when the folder is
#                         OPENED IN THE EDITOR — no user action beyond that
#   .git-hooks/pre-commit runs on commit
#   notes.md.exe          double-extension, looks like a document
#   .env                  read by tooling, and a place to hide values
#
# A model is a THEORY. It is markdown, a card, a licence and a ledger. Nothing
# in that list needs to execute, so the copy is now an ALLOW-LIST: an extension
# not named here does not reach the disk at all. A block-list fails open on
# whatever the attacker thought of that we did not.
SAFE_SUFFIX = {".md", ".json", ".jsonl", ".txt", ".yaml", ".yml", ".csv"}
SAFE_NAMES = {"LICENSE", "LICENSE-CODE", "LICENSE-CONTENT", "NOTICE",
              "CITATION.cff", ".gitignore", ".gitattributes"}
# Directories that carry execution semantics regardless of what is inside them.
UNSAFE_DIRS = {".git", ".github", ".vscode", ".idea", ".devcontainer",
               ".git-hooks", "__pycache__", "node_modules", ".venv", "venv",
               "bin", "scripts"}


def _safe_copy(src: Path, dst: Path) -> list:
    """Copy a model repo, allow-list only. Returns what was refused."""
    refused = []
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if any(part in UNSAFE_DIRS for part in rel.parts):
            if p.is_file():
                refused.append(str(rel))
            continue
        if not p.is_file():
            continue
        # A double extension ("notes.md.exe") passes a naive suffix check on the
        # wrong half, so the WHOLE name is checked for an executable segment.
        parts = p.name.lower().split(".")
        if len(parts) > 2 and any(f".{s}" not in SAFE_SUFFIX for s in parts[1:-1]):
            refused.append(str(rel))
            continue
        if p.name in SAFE_NAMES or p.suffix.lower() in SAFE_SUFFIX:
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
        else:
            refused.append(str(rel))
    dst.mkdir(parents=True, exist_ok=True)
    return refused


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
    refused = _safe_copy(src, dst)
    if refused:
        # Never silent. A model that shipped executables is telling you
        # something about itself, and the person importing should see it.
        print(f"  !! refused {len(refused)} file(s) — a model is markdown, a "
              f"card, a licence and a ledger; nothing in it needs to execute:")
        for r in refused[:12]:
            print(f"       {r}")
        if len(refused) > 12:
            print(f"       … and {len(refused) - 12} more")

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
        # What would actually reach the disk. Two threat surfaces, not one:
        # prose aimed at the reader's ASSISTANT, and files aimed at their
        # MACHINE. This is the second.
        _p = Path(a.inspect)
        exec_like = []
        for f in sorted(_p.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(_p)
            if any(part in UNSAFE_DIRS for part in rel.parts) and ".git" not in rel.parts[:1]:
                exec_like.append(str(rel))
            elif not (f.name in SAFE_NAMES or f.suffix.lower() in SAFE_SUFFIX):
                exec_like.append(str(rel))
        if exec_like:
            print(f"  executable/other: {len(exec_like)} file(s) that will NOT "
                  f"be copied:")
            for r in exec_like[:8]:
                print(f"       {r}")
            if len(exec_like) > 8:
                print(f"       … and {len(exec_like) - 8} more")
            print("     A model is a theory. Files that can run are refused at "
                  "import — but their")
            print("     presence tells you something about this repo.")
        else:
            print("  executable      : none — only documents, cards and ledgers")
        # A stranger's model is exactly the case the injection tripwire exists
        # for, and inspect is where a person decides whether to trust the repo
        # at all — so it is reported here, before import.
        try:
            from suites.legitimacy_audit import audit as _la
            inj = [f for f in _la(Path(a.inspect), Path(a.inspect).name)
                   if f[1] == "INJECTION"]
        except Exception:
            inj = []
        if inj:
            print(f"  !! {len(inj)} injection tripwire(s):")
            for sev, _k, detail in inj:
                print(f"       {sev:<5} {detail}")
            print("     These files are meant to be pasted into an assistant, so "
                  "prose can BE an instruction.")
            print("     Read them yourself before importing.")
        else:
            print("  injection scan : nothing tripped — but this catches lazy "
                  "attacks only; read it yourself")
        return
    if not a.source:
        ap.print_help()
        return
    do_import(Path(a.source), a.slug, a.keep_claims, a.aspects, a.e_span, a.level)


if __name__ == "__main__":
    main()
