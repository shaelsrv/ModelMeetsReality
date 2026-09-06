"""Mapcard validator — the automated half of commons moderation.

Implements docs/CONTRIBUTING.md checks 1, 2 and 4. It never judges whether a
model is GOOD; bad models die by grading. It checks only the things grading
cannot catch:

  1. SCHEMA      — does the card parse, and does the repo behind it have a real
                   MODEL.md (premises, a falsifiable consequence, a deletion
                   clause)? A model with no falsifier is not wrong, it is
                   unfalsifiable, and it cannot be coloured on a validation map.
  2. PAYLOAD     — does the repo carry executable code? Imports never run it,
                   but a reader might, so the card must say so.
  4. RECORD      — does the card's claimed record match the repo's own ledgers?
                   Cards are checkable against the repos that produced them, and
                   a mismatch is the one form of fraud unique to this system.

Check 3 (privacy / named private individuals) is deliberately NOT automated —
telling a public officeholder from a private person is a judgment call, and a
regex that tried would produce false accusations. It is flagged for a human.

  python -m suites.validate_card card.json
  python -m suites.validate_card card.json --repo ../their-model
  python -m suites.validate_card --self --repo my-model
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

from harness.fleet import MODELS_DIR  # noqa: E402

REQUIRED = ("model", "aspects", "mechanism", "record")
EXEC_SUFFIXES = {".py", ".sh", ".bat", ".ps1", ".js", ".exe", ".cmd"}
LEDGERS = ("predict/ledger.json", "predict/live_ledger.json",
           "signals/signal_ledger.json")


def check_schema(card: dict) -> list:
    out = []
    for k in REQUIRED:
        if k not in card:
            out.append(("FAIL", "schema", f"card is missing required field '{k}'"))
    if "coords" not in card and "e_span" not in card:
        out.append(("FAIL", "schema", "card has no coordinates (coords or e_span)"))
    rec = card.get("record") or {}
    for k in ("open", "graded"):
        if k in rec and not isinstance(rec[k], int):
            out.append(("FAIL", "schema", f"record.{k} must be a count, got {rec[k]!r}"))
    for leaky in ("claims", "claim_text", "predictions", "reasoning"):
        if leaky in card:
            out.append(("FAIL", "privacy",
                        f"card carries '{leaky}' — cards are counts only, never content"))
    ok, why = _licence_check(card.get("license", ""))
    if not ok:
        # FAIL, not WARN. The Garden refuses to list a card that fails this, so a
        # WARN here would let an author pass locally and be silently rejected at
        # build — spec-vs-tooling drift, which is the thing this file exists to
        # catch rather than create.
        out.append(("FAIL", "licence", why))
    return out


# Mirrors model-garden/build/licenses.py. Duplicated because that lives in a
# different repo and this suite must run standalone in a stranger's checkout;
# if you change one, change both. The Garden's copy is authoritative.
_LICENCE_OK = {
    "CC-BY-4.0", "CC-BY-SA-4.0", "CC0-1.0", "MIT", "APACHE-2.0",
    "BSD-3-CLAUSE", "BSD-2-CLAUSE", "GPL-3.0", "GPL-2.0", "AGPL-3.0",
    "LGPL-3.0", "UNLICENSE",
}


def _licence_norm(value: str) -> str:
    import re
    s = (value or "").strip().upper()
    s = re.sub(r"^LICEN[CS]ED UNDER\s+", "", s)
    s = re.sub(r"\s+LICEN[CS]E$", "", s).strip()
    s = re.sub(r"[\s_]+", "-", s)
    s = s.replace("CREATIVE-COMMONS", "CC").replace("--", "-").strip("-")
    s = re.sub(r"^APACHE-?2(\.0)?$", "APACHE-2.0", s)
    s = re.sub(r"^(A?GPL|LGPL)-?([23])(\.0)?(-OR-LATER|\+)?$", r"-.0", s)
    s = re.sub(r"^CC-?BY-?4(\.0)?$", "CC-BY-4.0", s)
    s = re.sub(r"^CC-?BY-?SA-?4(\.0)?$", "CC-BY-SA-4.0", s)
    s = re.sub(r"^CC-?0(-1\.0)?$", "CC0-1.0", s)
    s = re.sub(r"^BSD-?([23])(-CLAUSE)?$", r"BSD--CLAUSE", s)
    return s


def _licence_check(value: str):
    import re
    if not (value or "").strip():
        return False, ("no license field — the Garden cannot list a model whose "
                       "readers do not know if they may use, clone or fork it")
    key = _licence_norm(value)
    if key in _LICENCE_OK:
        return True, ""
    if re.search(r"\bN[CD]\b|NONCOMMERCIAL|NODERIV", key):
        return False, (f"licence '{value}' restricts commercial use or derivatives; "
                       f"the Garden's fork-and-import mechanics require both")
    return False, (f"licence '{value}' is not listable. It must permit redistribution "
                   f"AND derivatives: {', '.join(sorted(_LICENCE_OK))}")


def check_model_doc(repo: Path) -> list:
    out = []
    mm = repo / "MODEL.md"
    if not mm.exists():
        return [("FAIL", "schema", "repo has no MODEL.md — not a model")]
    t = mm.read_text(encoding="utf-8", errors="replace").lower()
    if "premise" not in t:
        out.append(("FAIL", "schema", "MODEL.md states no premises"))
    if not re.search(r"falsifiab|consequence|fails if|would count against", t):
        out.append(("FAIL", "schema",
                    "MODEL.md names no falsifiable consequence — the model cannot lose, "
                    "so it cannot be graded or coloured on the map"))
    if "deletion clause" not in t and "retires" not in t:
        out.append(("WARN", "schema",
                    "no deletion clause — nothing says when this model should be retired"))
    return out


def check_payload(repo: Path) -> list:
    execs = [f for f in repo.rglob("*")
             if f.is_file() and f.suffix.lower() in EXEC_SUFFIXES
             and ".git" not in f.parts]
    if not execs:
        return []
    names = ", ".join(str(f.relative_to(repo)) for f in execs[:4])
    more = f" (+{len(execs)-4} more)" if len(execs) > 4 else ""
    return [("FLAG", "payload",
             f"{len(execs)} executable file(s): {names}{more}. Import never runs them, "
             f"but the card must disclose this so readers are not surprised.")]


def check_record(card: dict, repo: Path) -> list:
    """The fraud check unique to this system: does the claimed record hold up?"""
    claimed = card.get("record") or {}
    actual = {"open": 0, "graded": 0}
    for rel in LEDGERS:
        f = repo / rel
        if not f.exists():
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for r in (d.get("predictions", d) if isinstance(d, dict) else d):
            if r.get("status", "open") == "open":
                actual["open"] += 1
            else:
                actual["graded"] += 1
    out = []
    for k in ("open", "graded"):
        if k in claimed and isinstance(claimed[k], int) and claimed[k] != actual[k]:
            sev = "FAIL" if claimed[k] > actual[k] else "WARN"
            why = ("claims more than the repo supports" if claimed[k] > actual[k]
                   else "under-reports; repo has more")
            out.append((sev, "record",
                        f"record.{k}={claimed[k]} but repo has {actual[k]} — {why}"))
    if claimed.get("graded", 0) > 0 and actual["graded"] == 0:
        out.append(("FAIL", "record",
                    "card advertises a graded record the repo cannot evidence"))
    return out


def validate(card: dict, repo: Path | None) -> list:
    findings = check_schema(card)
    if repo and repo.exists():
        findings += check_model_doc(repo)
        findings += check_payload(repo)
        findings += check_record(card, repo)
    else:
        findings.append(("WARN", "scope",
                         "no repo given — schema checked, record and payload unverified"))
    findings.append(("HUMAN", "privacy",
                     "a person must confirm this model is not about a named private "
                     "individual; public roles are fine, private people are not"))
    return findings


def main() -> None:
    ap = argparse.ArgumentParser(description="Validate a mapcard for the commons.")
    ap.add_argument("card", nargs="?")
    ap.add_argument("--repo")
    ap.add_argument("--self", dest="selfcheck", action="store_true",
                    help="validate one of this instance's own models before publishing")
    a = ap.parse_args()

    if a.selfcheck:
        if not a.repo:
            raise SystemExit("--self needs --repo <model-slug>")
        repo = MODELS_DIR / a.repo
        from suites.reality_map import _record, projections
        coords = {}
        for p in projections():
            asg = p.get("assignments", {}).get(a.repo)
            if asg:
                coords[f"{p['id']}.v{p['version']}"] = {
                    "aspects": asg["aspects"], "e_span": asg["e_span"]}
        card = {"model": a.repo, "instance": "this-instance",
                "aspects": next(iter(coords.values()), {}).get("aspects", []),
                "coords": coords, "mechanism": "(fill in before publishing)",
                "record": _record(a.repo), "license": "CC-BY-4.0"}
    else:
        if not a.card:
            ap.print_help()
            return
        card = json.load(Path(a.card).open(encoding="utf-8"))
        repo = Path(a.repo) if a.repo else None

    findings = validate(card, repo if not a.selfcheck else repo)
    order = {"FAIL": 0, "FLAG": 1, "WARN": 2, "HUMAN": 3}
    findings.sort(key=lambda f: order.get(f[0], 9))
    fails = sum(1 for s, _c, _m in findings if s == "FAIL")

    print(f"card: {card.get('model', '(unnamed)')}")
    for sev, cat, msg in findings:
        print(f"  {sev:<6} [{cat}] {msg}")
    print()
    if fails:
        print(f"  VERDICT: not listable — {fails} blocking issue(s).")
        print("  None of these is about whether the model is any good. Fix the defect")
        print("  and resubmit; models are only ever delisted for schema, record")
        print("  misreporting, privacy, or licence.")
    else:
        print("  VERDICT: listable, pending the human privacy check above.")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
