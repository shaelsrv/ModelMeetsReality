"""Publish one model as a standalone git repo.

A model lives as a SUBDIRECTORY of its instance's repo — deliberately, since a
repo per model would make them nested repos the parent cannot stage. So
publishing is an export, not a push: the model's files are copied into a fresh
standalone repo, committed, and pushed to the author's account.

What is deliberately NOT exported:

  imported/     another model's claims, quarantined on import. They belong to
                the instance that earned them and do not transfer by being
                copied — re-publishing them would launder someone else's record.
  index.jsonl   the instance's private memory embeddings.
  .env, keys    never, under any circumstances.

The export is idempotent: re-running updates the existing repo rather than
creating a second one.

    python -m suites.publish_model --model gravity-wells --private
    python -m suites.publish_model --all --private --dry-run
    python -m suites.publish_model --all --private --owner shaelsrv
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.fleet import ROOT, MODELS_DIR  # noqa: E402

# Never leaves the instance. Anything not matched here is exported, so the list
# is about what is PRIVATE or NOT THEIRS, not about what is tidy.
EXCLUDE_DIRS = {"imported", "__pycache__", ".git", "node_modules", ".venv"}
EXCLUDE_FILES = {"index.jsonl", ".env", ".env.local", "credentials.json"}
EXCLUDE_SUFFIXES = {".pyc", ".key", ".pem"}


def _run(cmd: list, cwd: Path | None = None, check: bool = True):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])}… failed: "
                           f"{(r.stderr or r.stdout).strip()[:300]}")
    return r


def gh_repo_exists(owner: str, name: str) -> bool:
    r = _run(["gh", "repo", "view", f"{owner}/{name}", "--json", "name"],
             check=False)
    return r.returncode == 0


def stage(src: Path, dst: Path) -> int:
    """Copy the model's publishable files into a clean directory."""
    n = 0
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if p.is_dir():
            continue
        if p.name in EXCLUDE_FILES or p.suffix in EXCLUDE_SUFFIXES:
            continue
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        n += 1
    return n


def ensure_license(d: Path, model: str) -> None:
    """A repo nobody may reuse is not shareable. CC-BY matches the card default."""
    if (d / "LICENSE").exists():
        return
    (d / "LICENSE").write_text(
        f"Creative Commons Attribution 4.0 International (CC BY 4.0)\n\n"
        f"This model — its premises, claims and record — may be shared and\n"
        f"adapted for any purpose, including commercially, provided attribution\n"
        f"is given.\n\nFull text: https://creativecommons.org/licenses/by/4.0/\n",
        encoding="utf-8")


def publish(slug: str, owner: str, private: bool, dry: bool) -> dict:
    src = MODELS_DIR / slug
    if not (src / "MODEL.md").exists():
        return {"model": slug, "skipped": "no MODEL.md"}

    card_f = src / "model.json"
    if not card_f.exists():
        return {"model": slug, "skipped": "no model.json — run make_card first"}

    # Regenerate the runnable half before publishing. Both are DERIVED from
    # MODEL.md, so a repo that ships them stale is advertising a model that no
    # longer matches its own instructions — and a repo missing them entirely is
    # a paper rather than an instrument. Generating here means the convention
    # holds for every model without anyone remembering two extra commands.
    if not dry:
        for mod, fname in (("make_use", "USE.md"), ("make_tasks", "TASKS.md")):
            try:
                gen = __import__(f"suites.{mod}", fromlist=["build"])
                doc, _ = gen.build(slug, owner)
                (src / fname).write_text(doc, encoding="utf-8")
            except Exception as e:
                # Never block publication on this — a model with a stale USE.md
                # is still worth publishing, and the audit flags what is missing.
                print(f"      note: could not regenerate {fname} ({e})")

    # Compatibility gate. Publishing is where a model stops being ours and
    # starts being someone else's problem, so it is checked against every
    # installation level here — most importantly level 1, the reader with no
    # tooling who can only paste. Blocking, because a published model missing
    # USE.md or its fence is broken for the largest audience and nothing
    # downstream would notice.
    if not dry:
        try:
            from suites.compat_check import check_model
            bad = [f for f in check_model(src) if f["status"] == "FAIL"]
            if bad:
                return {"model": slug, "skipped": "compat: " + "; ".join(
                    f["check"].split(": ", 1)[-1] for f in bad)}
        except ImportError:
            pass

    # Publication is the irreversible step, so the legitimacy gate runs HERE
    # rather than only at launch. The other gates do not catch this: make_card
    # called unwritten scaffolds "listable" and validate_card passed them,
    # because both check for the falsifier HEADING and placeholder text sits
    # underneath it.
    try:
        from suites.legitimacy_audit import audit as _legit_audit
        blocks = [f for f in _legit_audit(src, slug) if f[0] == "BLOCK"]
        if blocks:
            return {"model": slug,
                    "skipped": "legitimacy audit: "
                               + "; ".join(f"{k} {d[:60]}" for _, k, d in blocks)}
    except ImportError:
        pass

    exists = gh_repo_exists(owner, slug)
    if dry:
        return {"model": slug, "would": "update" if exists else "create",
                "private": private, "url": f"https://github.com/{owner}/{slug}"}

    tmp = Path(tempfile.mkdtemp(prefix=f"pub-{slug}-"))
    try:
        work = tmp / slug
        work.mkdir()
        nfiles = stage(src, work)
        ensure_license(work, slug)

        _run(["git", "init", "-q", "-b", "main"], cwd=work)
        _run(["git", "add", "-A"], cwd=work)
        msg = (f"{slug}: publish v1 model repo\n\n"
               f"Premises, falsifiable consequences and deletion clause per the\n"
               f"v1 model format. Record counts are self-graded — the model's\n"
               f"own ledger, not an independent resolution.")
        _run(["git", "-c", "user.name=Sail",
              "-c", "user.email=claude@sailsrv.com",
              "commit", "-q", "-m", msg], cwd=work)

        if not exists:
            card = json.load(card_f.open(encoding="utf-8"))
            desc = (card.get("mechanism") or "")[:180]
            _run(["gh", "repo", "create", f"{owner}/{slug}",
                  "--private" if private else "--public",
                  "--description", desc or f"{slug} — a v1 falsifiable model",
                  "--source", str(work), "--push"], cwd=work)
        else:
            _run(["git", "remote", "add", "origin",
                  f"https://github.com/{owner}/{slug}.git"], cwd=work)
            _run(["git", "push", "-q", "--force", "origin", "main"], cwd=work)

        return {"model": slug, "action": "updated" if exists else "created",
                "files": nfiles, "private": private,
                "url": f"https://github.com/{owner}/{slug}"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> None:
    ap = argparse.ArgumentParser(description="Publish model(s) as standalone repos.")
    ap.add_argument("--model")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--owner", default="shaelsrv")
    ap.add_argument("--private", action="store_true", default=True)
    ap.add_argument("--public", dest="private", action="store_false")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    slugs = []
    if a.all:
        cfg = json.load((ROOT / "fleet.json").open(encoding="utf-8"))
        slugs = cfg.get("models", []) + cfg.get("classifiers", [])
    elif a.model:
        slugs = [a.model]
    else:
        ap.print_help()
        return

    done = 0
    for s in slugs:
        try:
            r = publish(s, a.owner, a.private, a.dry_run)
        except Exception as e:
            print(f"  {s:<26} ERROR {str(e)[:140]}")
            continue
        if r.get("skipped"):
            print(f"  {s:<26} skipped — {r['skipped']}")
            continue
        done += 1
        verb = r.get("would") or r.get("action")
        print(f"  {s:<26} {verb:<8} {'private' if r['private'] else 'PUBLIC'}  {r['url']}")
    print(f"\n  {'(dry run) ' if a.dry_run else ''}{done} model(s)")


if __name__ == "__main__":
    main()
