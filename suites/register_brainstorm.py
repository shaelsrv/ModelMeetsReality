"""Seal a brainstorm's joint claims into the ledger.

A brainstorm that produces dated, falsifiable claims and leaves them in a
markdown file has not made a bet — it has written an essay. This pass moves
them into `brainstorms/ledger.json`, where the grading loop can find them and
where they can go against us.

Two properties matter and are enforced here:

  IMMUTABLE      a claim is sealed with its resolution criteria frozen at
                 registration. Re-running the registrar never rewrites an
                 existing row; it only adds ones not yet present. The whole
                 value of a ledger is that you cannot edit the bet after
                 seeing the world.
  ADVERSARY TOO  the devil's advocate's null claims register alongside the
                 ensemble's. If only the exciting claims are sealed, the
                 record measures enthusiasm, not calibration. Brainstorm
                 already merges them into joint_claims tagged
                 backed_by=devils-advocate; they are registered identically
                 and graded identically.

    python -m suites.register_brainstorm --id bs-garden-rules
    python -m suites.register_brainstorm --id bs-garden-rules --dry-run
    python -m suites.register_brainstorm --all
"""
from __future__ import annotations

import argparse
import hashlib
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

ROOT = Path(__file__).resolve().parents[1]
BDIR = ROOT / "brainstorms"
LEDGER = BDIR / "ledger.json"


def claim_id(bid: str, claim: str) -> str:
    """Stable id from the brainstorm and the claim text.

    Content-derived so re-registration is idempotent, and so that editing a
    claim's wording produces a NEW id rather than silently mutating a sealed
    bet — an edit is a new claim, which is the honest reading.
    """
    h = hashlib.sha256(f"{bid}|{claim}".encode("utf-8")).hexdigest()[:8]
    return f"{bid}-{h}"


def _load_ledger() -> list:
    if not LEDGER.exists():
        return []
    try:
        d = json.load(LEDGER.open(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return d.get("predictions", []) if isinstance(d, dict) else list(d)


def unverified_dates(bs: dict) -> list[str]:
    """Dates that appear in the CLAIMS but were never in the operator's ask.

    A sealed claim inherits whatever the event text asserted. If the event text
    stated a date the operator never gave — inferred by whoever wrote it — the
    lenses adopt it and it hardens into the ledger. That happened once: an
    Apple keynote was sealed as 'Sept 5' when the event was Sept 9, and two
    claims ended up measuring a window that mostly preceded the thing they were
    about. The event's own synthesis had already flagged the premise as
    unverified, and it was sealed anyway.

    This does not know which dates are true. It surfaces every date a claim
    asserts so a human confirms it before the claim hardens.
    """
    out = set()
    syn = bs.get("synthesis") or {}
    for jc in syn.get("joint_claims", []):
        text = f"{jc.get('claim','')} {jc.get('resolution_criteria','')}"
        for m in re.finditer(r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
                             r"[a-z]*\.?\s+\d{1,2})\b", text):
            out.add(m.group(1))
    return sorted(out)


def register(bid: str, dry: bool = False, confirm_dates: bool = False) -> dict:
    f = BDIR / f"{bid}.json"
    if not f.exists():
        raise SystemExit(f"no brainstorm at {f}")
    bs = json.load(f.open(encoding="utf-8"))

    # A run can be retired after the fact -- a bug found, its evidence discredited.
    # bs-mmr-research-pilot is the case this exists for: web search silently never
    # executed, so every "finding" was model recall and all nine cited URLs were
    # fabricated. Its synthesis and claims are still on disk and looked perfectly
    # sealable. Refuse rather than trust a comment nobody reads.
    if bs.get("status") in ("superseded", "void", "discarded"):
        raise SystemExit(
            "%s: run is marked '%s' -- refusing to seal.\n  %s"
            % (bid, bs["status"], str(bs.get("annotation") or "(no annotation)")[:400]))

    # A researched run whose citations failed validation is not evidence. Sealing a
    # claim on an invented URL is the exact laundering the validator prevents, so
    # the seal path checks it too rather than trusting the doc to be followed.
    if bs.get("researched"):
        bad = {n: len((v.get("research") or {}).get("_invented") or [])
               for n, v in (bs.get("lenses") or {}).items()}
        bad = {n: c for n, c in bad.items() if c}
        if bad:
            detail = ", ".join("%s(%d)" % (n, c) for n, c in sorted(bad.items()))
            print("  ! %s: %d invented citation(s) were dropped from: %s"
                  % (bid, sum(bad.values()), detail))
            print("    Those lenses' URLs must NOT be used as date-gate primary sources.")

    syn = bs.get("synthesis") or {}
    claims = syn.get("joint_claims", [])

    dates = unverified_dates(bs)
    if dates and not (confirm_dates or dry):
        raise SystemExit(
            f"{bid}: claims assert calendar dates: {', '.join(dates)}\n"
            f"  Confirm each against a primary source before sealing — a wrong\n"
            f"  date hardens into the ledger and can make a measurement window\n"
            f"  miss the event it is about.\n"
            f"  Re-run with --confirm-dates once checked (or --dry-run to preview).")
    if not claims:
        return {"brainstorm": bid, "added": 0, "skipped": 0, "note": "no joint claims"}

    rows = _load_ledger()
    have = {r.get("id") for r in rows if r.get("id")}
    # Older rows predate ids; match them on claim text so a re-run does not
    # duplicate a bet that was registered by hand.
    have_text = {(r.get("claim") or "").strip() for r in rows}

    added, skipped = [], 0
    for jc in claims:
        text = (jc.get("claim") or "").strip()
        if not text:
            continue
        cid = claim_id(bid, text)
        if cid in have or text in have_text:
            skipped += 1
            continue
        backed = jc.get("backed_by", [])
        row = {
            "id": cid,
            "made_on": bs.get("at"),
            "entity": bid,
            "claim": text,
            "resolution_criteria": jc.get("resolution_criteria", ""),
            "confidence": jc.get("confidence"),
            "resolve_by": jc.get("resolve_by"),
            "mechanism": "brainstorm ensemble claim; backed by "
                         + (", ".join(backed) if backed else "unattributed"),
            # The adversary's bets are marked so a later report can show the
            # ensemble's record and the null's record separately. If the nulls
            # beat the lenses, that is the finding.
            "side": "null" if backed == ["devils-advocate"] else "ensemble",
            "status": "open",
        }
        added.append(row)

    if added and not dry:
        rows.extend(added)
        LEDGER.write_text(
            json.dumps({"predictions": rows}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    return {"brainstorm": bid, "added": len(added), "skipped": skipped,
            "rows": added}


def main() -> None:
    ap = argparse.ArgumentParser(description="Seal brainstorm joint claims into the ledger.")
    ap.add_argument("--id")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--confirm-dates", action="store_true",
                    help="you have checked every date the claims assert")
    a = ap.parse_args()

    ids = []
    if a.all:
        ids = [f.stem for f in sorted(BDIR.glob("*.json"))
               if f.name not in ("ledger.json",) and not f.name.endswith(".queued.json")]
    elif a.id:
        ids = [a.id]
    else:
        ap.print_help()
        return

    tot_a = tot_s = 0
    for bid in ids:
        try:
            r = register(bid, dry=a.dry_run, confirm_dates=a.confirm_dates)
        except SystemExit as e:
            print(f"  {bid}: {e}")
            continue
        tot_a += r["added"]
        tot_s += r["skipped"]
        if r["added"] or r["skipped"]:
            print(f"  {bid}: +{r['added']} sealed, {r['skipped']} already present")
        for row in r.get("rows", []):
            print(f"      [{row['side']:<8}] {row['id']}  by {row['resolve_by']}  "
                  f"c={row['confidence']}  {row['claim'][:70]}")
    print(f"\n  {'(dry run) ' if a.dry_run else ''}"
          f"{tot_a} claims sealed, {tot_s} already in ledger -> {LEDGER}")


if __name__ == "__main__":
    main()
