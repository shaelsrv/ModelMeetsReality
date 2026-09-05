"""Pre-publication audit: what in these repos would cost us credibility?

Not a quality review. A model may be wrong, unfinished, or unpopular and still
belong in public — that is the whole premise. This looks for the narrower set of
things that would damage the standing of the *project* if a stranger found them
after publication, in roughly the order a hostile reader would find them:

  SECRET      an API key, token or credential committed to a repo. Publishing
              one is unrecoverable — it is public the moment the repo flips, and
              rotating afterwards does not undo it.
  PRIVATE     a named private individual used as a subject. Public roles are
              fine; private people are not, and this is the one check the Garden
              reserves for a human, so here it only FLAGS for review.
  UNFALSIFIABLE  a listed model with no falsifiable consequence or no deletion
              clause. Not wrong — unfalsifiable, which is what the format
              exists to exclude. Listing one contradicts our own stated rule.
  BORROWED    an imported/ directory or another instance's claims inside a repo
              we are about to publish under our own name. Someone else's record
              republished as ours is the fraud this system is built to detect.
  EMPTY       a scaffold that was never written — placeholder text still in
              MODEL.md. Publishing template boilerplate as a "model" is the
              cheapest possible way to look unserious.
  OVERCLAIM   language asserting a finding, proof or discovery in a repo whose
              record shows nothing graded. The project's entire claim is that it
              distinguishes candidates from findings; a repo that ignores that
              distinction undermines it more than a wrong prediction would.

    python -m suites.legitimacy_audit
    python -m suites.legitimacy_audit --model gravity-wells
    python -m suites.legitimacy_audit --strict     # non-zero exit on any BLOCK
"""
from __future__ import annotations

import argparse
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

from harness.fleet import ROOT, MODELS_DIR  # noqa: E402

# Credential shapes. Deliberately narrow: a scanner that cries wolf gets muted,
# and a muted scanner is worse than none before an irreversible publication.
SECRET_PAT = [
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}"), "OpenAI-style key"),
    (re.compile(r"\bsk-or-v1-[A-Za-z0-9]{20,}"), "OpenRouter key"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key id"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"), "Google API key"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*"
                r"['\"][A-Za-z0-9/+_\-]{16,}['\"]"), "hardcoded credential"),
]

# Words that assert settled knowledge. The project's own discipline says these
# require a graded record behind them.
OVERCLAIM_PAT = re.compile(
    r"(?i)\b(we (?:have )?(?:proved|proven|discovered|established)"
    r"|this (?:proves|demonstrates conclusively|is a finding)"
    r"|conclusively (?:shows|proves)"
    r"|(?:the|our) finding(?:s)? (?:is|are|show)"
    r"|confirmed that)\b")

SCAFFOLD_PAT = [
    re.compile(r"\*\*P1 — \.\*\*"),
    re.compile(r"State each load-bearing claim with an honest confidence tier"),
    re.compile(r"a concrete observable that would count against the model"),
    re.compile(r"^\s*1\.\s*\*\*:\*\*", re.M),
]

TEXT_SUFFIX = {".md", ".json", ".jsonl", ".py", ".txt", ".yaml", ".yml",
               ".toml", ".js", ".sh", ".env", ".cfg", ".ini"}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "assets"}


def _text_files(repo: Path):
    for p in repo.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(repo).parts):
            continue
        if p.suffix.lower() in TEXT_SUFFIX:
            yield p


def audit(repo: Path, slug: str) -> list[tuple[str, str, str]]:
    """Return [(severity, kind, detail)]. BLOCK stops publication; FLAG needs eyes."""
    out = []
    mm = repo / "MODEL.md"
    md = mm.read_text(encoding="utf-8", errors="replace") if mm.exists() else ""

    # --- SECRET: the only unrecoverable one, so it is checked over every file.
    for f in _text_files(repo):
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat, what in SECRET_PAT:
            m = pat.search(t)
            if m:
                rel = f.relative_to(repo)
                out.append(("BLOCK", "SECRET",
                            f"{rel}: possible {what} — publishing this is "
                            f"unrecoverable; rotate and purge history"))
                break

    # --- BORROWED: someone else's earned record presented as ours.
    #
    # A quarantined import is the system WORKING, not a defect: imported/ beside
    # an IMPORTED.md that says whose record it is, and which publish_model
    # excludes from the export, is exactly the designed handling. What is
    # dangerous is the unlabelled case — foreign claims with no provenance note,
    # or foreign claims merged into this model's own ledger where they would be
    # counted as its record.
    imp = repo / "imported"
    if imp.exists():
        if not (repo / "IMPORTED.md").exists():
            out.append(("BLOCK", "BORROWED",
                        "imported/ present with no IMPORTED.md — foreign claims "
                        "with no provenance read as this model's own record"))
        else:
            # Same claim in both the quarantine and the live ledger means the
            # import leaked into our record, which is the fraud we detect.
            def _claims(p):
                try:
                    d = json.load(p.open(encoding="utf-8"))
                except (OSError, ValueError):
                    return set()
                rows = d.get("predictions", d) if isinstance(d, dict) else d
                return {(r.get("claim") or r.get("name") or "")[:80]
                        for r in rows if isinstance(r, dict)} - {""}
            quarantined = set()
            for f in imp.glob("*.json"):
                quarantined |= _claims(f)
            live = set()
            for rel in ("predict/ledger.json", "signals/signal_ledger.json"):
                if (repo / rel).exists():
                    live |= _claims(repo / rel)
            leaked = quarantined & live
            if leaked:
                out.append(("BLOCK", "BORROWED",
                            f"{len(leaked)} imported claim(s) also present in this "
                            f"model's own ledger — a foreign record counted as ours"))

    # --- UNFALSIFIABLE: contradicts the format we require of everyone else.
    if md:
        if not re.search(r"^##\s*Falsifiable consequences", md, re.I | re.M):
            out.append(("BLOCK", "UNFALSIFIABLE",
                        "no '## Falsifiable consequences' section"))
        if not re.search(r"deletion clause|retires? to notation", md, re.I):
            out.append(("BLOCK", "UNFALSIFIABLE", "no deletion clause"))
    else:
        out.append(("BLOCK", "UNFALSIFIABLE", "no MODEL.md at all"))

    # --- EMPTY: unwritten scaffold shipped as a model.
    for pat in SCAFFOLD_PAT:
        if pat.search(md):
            out.append(("BLOCK", "EMPTY",
                        "MODEL.md still contains scaffold placeholder text"))
            break

    # --- OVERCLAIM: asserted findings with nothing graded behind them.
    graded = 0
    for rel in ("predict/ledger.json", "predict/live_ledger.json",
                "signals/signal_ledger.json"):
        f = repo / rel
        if not f.exists():
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = d.get("predictions", d) if isinstance(d, dict) else d
        graded += sum(1 for r in rows if isinstance(r, dict)
                      and r.get("status", "open") not in ("open", "?"))
    # Every markdown in the repo, not just the root: exploration prose under
    # cases/, traces/ and explore/ is exactly what a hostile reader quotes, and
    # it is where confident language accumulates without anyone re-reading it.
    for f in sorted(repo.rglob("*.md")):
        if any(part in SKIP_DIRS for part in f.relative_to(repo).parts):
            continue
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = OVERCLAIM_PAT.search(t)
        if m and graded == 0:
            out.append(("FLAG", "OVERCLAIM",
                        f"{f.relative_to(repo)}: {m.group(0)!r} with 0 graded "
                        f"claims — candidate language is required until "
                        f"something resolves"))
            break

    # --- PRIVATE: never auto-decided. A regex that accused people would be
    # worse than the problem it looks for, so this only surfaces candidates.
    #
    # Two-capitalised-words is far too loose on its own: it fired on every
    # model's own TITLE ("Gravity Wells", "Window Timer") and on ordinary
    # sentence fragments, flagging all 16 repos and teaching the reader to skip
    # the whole category. A check nobody reads protects nobody. So a candidate
    # must look like a PERSON — introduced by a personal cue — and must not be
    # something this repo already names itself.
    self_words = set()
    for w in re.split(r"[^A-Za-z]+", slug):
        if w:
            self_words.add(w.lower())
    title = re.search(r"^#\s+(.+)$", md, re.M)
    if title:
        for w in re.split(r"[^A-Za-z]+", title.group(1)):
            if w:
                self_words.add(w.lower())

    PERSON_CUE = re.compile(
        r"(?:\b(?:by|from|per|according to|interview(?:ed)? with|"
        r"said|told|wrote|reported by|contacted|met|spoke to|"
        r"Mr\.?|Ms\.?|Mrs\.?|Dr\.?|Prof\.?)\s+)"
        r"([A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){1,2})")
    names = set()
    for f in list(repo.glob("*.md")):
        try:
            t = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in PERSON_CUE.finditer(t):
            cand = m.group(1)
            if all(w.lower() in self_words for w in cand.split()):
                continue
            names.add(cand)
    if names:
        out.append(("FLAG", "PRIVATE",
                    f"{len(names)} capitalised name-like phrases to eyeball: "
                    + ", ".join(sorted(names)[:6])
                    + ("…" if len(names) > 6 else "")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Pre-publication legitimacy audit.")
    ap.add_argument("--model")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()

    cfg = json.load((ROOT / "fleet.json").open(encoding="utf-8"))
    slugs = [a.model] if a.model else sorted(
        set(cfg.get("models", []) + cfg.get("classifiers", [])))

    blocks = flags = clean = 0
    for s in slugs:
        repo = MODELS_DIR / s
        if not repo.exists():
            continue
        found = audit(repo, s)
        b = [f for f in found if f[0] == "BLOCK"]
        fl = [f for f in found if f[0] == "FLAG"]
        blocks += len(b)
        flags += len(fl)
        if not found:
            clean += 1
            print(f"  {s:<26} clean")
            continue
        print(f"  {s:<26} {len(b)} block, {len(fl)} flag")
        for sev, kind, detail in found:
            print(f"      {sev:<5} [{kind}] {detail}")

    print(f"\n  {clean} clean · {blocks} BLOCK (must fix before publishing) · "
          f"{flags} FLAG (needs a human)")
    if blocks:
        print("  A BLOCK is not 'this model is bad'. It is 'publishing this "
              "specific thing would cost us standing we cannot buy back'.")
    if a.strict and blocks:
        sys.exit(1)


if __name__ == "__main__":
    main()
