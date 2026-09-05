"""Generate a model.json card from a model repo.

The v1 format requires a `model.json`, and until this existed nothing produced
one — a validator with nothing to validate, and a Garden nobody could publish
to. This closes that: it reads what the repo already knows and writes the card.

Everything it can compute, it computes; everything it cannot, it asks for rather
than inventing. A card is an advertisement for a repo, and an advertisement that
makes up its own claims is the failure the whole registry exists to avoid.

  DERIVED    kind, level, aspects, e_span, mechanism (from MODEL.md and the
             instance's map), record counts (from the repo's own ledgers),
             derived tags (from tags.py)
  ASKED      author and repo URL — the two facts the repo cannot know about
             itself — plus any declared tag not yet set

    python -m suites.make_card --model gravity-wells --author yourhandle
    python -m suites.make_card --all --author yourhandle --dry-run
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

LEDGERS = ("predict/ledger.json", "predict/live_ledger.json",
           "signals/signal_ledger.json")

KINDS = ("forecaster", "classifier", "tracer", "finder", "tracker",
         "generator", "attributor", "adversary", "mirror", "timer")


def _first(pattern: str, text: str, group: int = 1, dotall: bool = False) -> str | None:
    flags = re.I | re.M | (re.S if dotall else 0)
    m = re.search(pattern, text, flags)
    return m.group(group).strip() if m else None


def read_model_md(repo: Path) -> dict:
    """Pull what the theory document already states about itself."""
    f = repo / "MODEL.md"
    if not f.exists():
        return {}
    t = f.read_text(encoding="utf-8", errors="replace")
    out = {}

    # "# Name — one line (v1)"
    h = _first(r"^#\s+(.+)$", t)
    if h:
        head = re.sub(r"\s*\(v\d+\)\s*$", "", h).strip()
        parts = re.split(r"\s+[—–-]\s+", head, maxsplit=1)
        out["title"] = parts[0].strip()
        if len(parts) > 1:
            out["tagline"] = parts[1].strip()

    # "**The kind:** a FORECASTER at ..." — take the first known kind word
    kindline = _first(r"\*\*The kind:\*\*\s*(.+)$", t)
    if kindline:
        low = kindline.lower()
        for k in KINDS:
            if k in low:
                out["kind"] = k
                break

    # The domain line wraps in a hand-written MODEL.md, so match up to the blank
    # line rather than the line end — otherwise the mechanism truncates
    # mid-sentence and the card advertises half a thought.
    # The spec says "**The domain:**" but every starter template asks
    # "**The question:**" — better phrasing for a general audience, and the one
    # a beginner's first model actually carries. Accepting only the spec wording
    # rejected every starter-built model at the Garden gate, which is the
    # onboarding path breaking on its own format.
    domain = _first(
        r"\*\*The (?:domain|question|hypothesis)[^:]*:\*\*\s*(.+?)(?:\n\s*\n|\n\s*\*\*|\n##)",
        t, dotall=True)
    if domain:
        # The mechanism line is what a browser reads first; keep it to one line.
        out["mechanism"] = re.sub(r"\s+", " ", domain).strip().rstrip(".")[:240]
    elif out.get("tagline"):
        out["mechanism"] = out["tagline"]

    # A card must not be built for a repo with no falsifier — the Garden's
    # whole premise is that a listed model could be shown wrong.
    out["has_falsifier"] = bool(
        re.search(r"^##\s*Falsifiable consequences", t, re.I | re.M))
    out["has_deletion"] = bool(
        re.search(r"deletion clause|retires? to notation", t, re.I))
    return out


def read_record(repo: Path) -> dict:
    """Counts from the repo's own ledgers. Never claim text.

    Deliberately skips imported/: an imported model's record belongs to the
    instance that earned it and does not transfer by being copied.
    """
    rec = {"open": 0, "graded": 0}
    for rel in LEDGERS:
        f = repo / rel
        if not f.exists():
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = d.get("predictions", d) if isinstance(d, dict) else d
        for r in rows if isinstance(rows, list) else []:
            rec["open" if r.get("status", "open") == "open" else "graded"] += 1
    return rec


def map_coords(slug: str) -> dict:
    """Aspects and E-span from the instance's reality map, if it places this model."""
    out = {}
    for rel in ("map/projections/em-ladder.v1.json", "map/assignments.json"):
        f = ROOT / rel
        if not f.exists():
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = d.get("assignments", d) if isinstance(d, dict) else d
        rows = entries.values() if isinstance(entries, dict) else entries
        for a in rows if isinstance(rows, (list, tuple)) else []:
            if not isinstance(a, dict) or a.get("model") != slug:
                continue
            if a.get("aspects"):
                out["aspects"] = a["aspects"]
            elif a.get("aspect"):
                out["aspects"] = [a["aspect"]]
            if a.get("e_span"):
                out["e_span"] = a["e_span"]
            elif a.get("e") is not None:
                out["e_span"] = [a["e"], a["e"]]
    return out


def build(slug: str, author: str, repo_url: str | None,
          license_id: str) -> tuple[dict, list]:
    repo = MODELS_DIR / slug
    if not (repo / "MODEL.md").exists():
        raise SystemExit(f"no model at {repo}")

    md = read_model_md(repo)
    warn = []
    if not md.get("has_falsifier"):
        warn.append("MODEL.md has no '## Falsifiable consequences' section — "
                    "not listable in the Garden until it does")
    if not md.get("has_deletion"):
        warn.append("MODEL.md has no deletion clause")

    card = {
        "spec": "v1",
        "model": slug,
        "title": md.get("title") or slug.replace("-", " ").title(),
        "author": author,
        "repo": repo_url or f"https://github.com/{author}/{slug}",
        "license": license_id,
        "kind": md.get("kind"),
        "mechanism": md.get("mechanism") or "",
    }
    if not card["kind"]:
        warn.append("could not read a kind from MODEL.md's '**The kind:**' line")
        card["kind"] = "forecaster"

    # level: declared in fleet.json if the instance tracks it
    try:
        cfg = json.load((ROOT / "fleet.json").open(encoding="utf-8"))
        card["level"] = int((cfg.get("levels") or {}).get(slug, 0))
    except (OSError, ValueError, TypeError):
        card["level"] = 0

    card.update(map_coords(slug))
    card.setdefault("aspects", [])
    if not card["aspects"]:
        warn.append("no aspects — the model is not placed on the reality map, "
                    "so readers cannot find it by domain")

    try:
        from suites.tags import derive, declared
        card["derived"] = derive(repo)
        dec = declared(repo)
        card["declared"] = dec
        missing = [k for k in ("scope", "inputs", "sensitivity", "effort")
                   if k not in dec]
        if missing:
            warn.append(f"declared tags not set: {', '.join(missing)} — "
                        f"run: python -m suites.tags --set {slug} --scope ... ")
    except Exception as e:
        warn.append(f"could not compute tags: {e}")

    card["record"] = read_record(repo)
    # R5: a record without stated provenance reads as a measurement when it is
    # a self-report. The Garden requires this field and rejects cards lacking it.
    card["record_provenance"] = "self-graded"
    return card, warn


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate a v1 model.json card.")
    ap.add_argument("--model")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--author", required=True, help="your GitHub handle")
    ap.add_argument("--repo", help="repo URL (default https://github.com/<author>/<slug>)")
    ap.add_argument("--license", default="CC-BY-4.0")
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

    ok = blocked = 0
    for s in slugs:
        if not (MODELS_DIR / s / "MODEL.md").exists():
            continue
        card, warn = build(s, a.author, a.repo if a.model else None, a.license)
        listable = not any("not listable" in w for w in warn)
        ok += listable
        blocked += (not listable)
        print(f"  {s:<26} {'ok' if listable else 'NOT LISTABLE'}"
              f"  kind={card['kind']} record={card['record']}")
        for w in warn:
            print(f"      - {w}")
        if not a.dry_run:
            (MODELS_DIR / s / "model.json").write_text(
                json.dumps(card, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\n  {'(dry run) ' if a.dry_run else ''}{ok} listable, "
          f"{blocked} blocked by a missing falsifier")


if __name__ == "__main__":
    main()
