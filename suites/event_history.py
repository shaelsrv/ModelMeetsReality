"""Assemble one event history from what the models observed.

Every decision model, when it ran, recorded the COMPLETED decisions it found —
each with a date, an item, and a source. Those sit scattered across 30 ledgers.
This merges them into one timeline that later passes can cite by id.

Two things make this more than a concatenation:

DATES ARE DIRTY. The models wrote what the sources said: "2026-09-04",
"stated ~23 July 2026 (Hungarian GP)", "announced late November 2025, in effect
for the 2026 season". Coercing those to a single ISO date would invent precision
the source did not have, so the raw string is kept and a sortable date is added
ALONGSIDE it, with `approx` set when the parse was inferred rather than read.

THE SAME EVENT APPEARS IN MANY LEDGERS. The Zandvoort swap order was observed by
the Wolff, Russell and Antonelli models independently. Merging them without
keeping the observer list would both double-count the event in any pattern pass
and throw away the corroboration — three models finding the same thing is
evidence, and it is exactly the signal a later emergence pass needs to weight by.

    python -m suites.event_history --build
    python -m suites.event_history --subject verstappen
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
FLEET = ROOT / "fleet.json"
WORK = ROOT.parent
OUT = WORK / "f1-events"

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}


def norm_date(raw: str) -> tuple[str | None, bool]:
    """(sortable ISO date, approx). None when nothing parseable is present.

    Deliberately conservative: a range returns its START, a month-only string
    returns the first of that month with approx=True. The raw string is always
    kept by the caller, so nothing is lost by this being cautious.
    """
    s = (raw or "").strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        # a range like "2026-09-04 to 2026-09-06" keeps its start
        return m.group(0), bool(re.search(r"\bto\b|–|—", s))
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}", True
    m = re.search(r"([A-Za-z]+)\s+(\d{4})", s)
    if m and m.group(1).lower() in MONTHS:
        return f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}-01", True
    return None, True


def _toks(s: str) -> set:
    return set(re.findall(r"[a-z]{4,}", (s or "").lower()))


def collect() -> list:
    """Every observation from every decision-model ledger, with its observer."""
    fleet = json.loads(FLEET.read_text(encoding="utf-8"))["models"]
    # This instance also holds 10 models from an earlier install test (grid-load,
    # water-infra, clinic-throughput...). Their observations are real but belong to
    # other domains, and mixing them into an F1 timeline would put municipal water
    # investment beside a Zandvoort pit call. Decision models are the F1 set.
    fleet = [s for s in fleet if s.endswith("-decisions")]
    raw = []
    for slug in fleet:
        p = WORK / slug / "predict" / "ledger.json"
        if not p.exists():
            continue
        try:
            led = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for pred in led.get("predictions", []):
            for o in (pred.get("observed") or []):
                if not isinstance(o, dict) or not o.get("item"):
                    continue
                iso, approx = norm_date(str(o.get("date", "")))
                raw.append({
                    "item": str(o["item"]).strip(),
                    "date_raw": str(o.get("date", "")).strip(),
                    "date": iso, "approx": approx,
                    "source": str(o.get("source", "")).strip(),
                    "observer": slug.replace("-decisions", ""),
                })
    return raw


def merge(raw: list, threshold: float = 0.42) -> list:
    """Collapse the same event seen by several models, keeping every observer.

    Match on token overlap AND date proximity: two different decisions about the
    same person in the same week can read similarly, so text alone would over-merge.
    """
    events = []
    for r in raw:
        rt = _toks(r["item"])
        hit = None
        for e in events:
            if r["date"] and e["date"] and r["date"] != e["date"]:
                # different dates: only merge when the wording is near-identical
                if len(rt & e["_toks"]) / max(1, len(rt | e["_toks"])) < 0.75:
                    continue
            j = len(rt & e["_toks"]) / max(1, len(rt | e["_toks"]))
            if j >= threshold:
                hit = e
                break
        if hit:
            if r["observer"] not in hit["observers"]:
                hit["observers"].append(r["observer"])
            if r["source"] and r["source"] not in hit["sources"]:
                hit["sources"].append(r["source"])
            # prefer the longest telling of the event
            if len(r["item"]) > len(hit["item"]):
                hit["item"] = r["item"]
            # prefer an exact date over an approximate one
            if r["date"] and (not hit["date"] or (hit["approx"] and not r["approx"])):
                hit["date"], hit["date_raw"], hit["approx"] = r["date"], r["date_raw"], r["approx"]
        else:
            events.append({**r, "observers": [r["observer"]],
                           "sources": [r["source"]] if r["source"] else [],
                           "_toks": rt})
    for e in events:
        e.pop("_toks", None)
        e.pop("observer", None)
    events.sort(key=lambda e: (e["date"] or "9999", e["item"][:40]))
    for i, e in enumerate(events, 1):
        e["id"] = f"ev{i:03d}"
    return events


def build() -> None:
    raw = collect()
    events = merge(raw)
    OUT.mkdir(exist_ok=True)

    multi = [e for e in events if len(e["observers"]) > 1]
    undated = [e for e in events if not e["date"]]
    payload = {
        "spec": "f1-event-history-v1",
        "note": ("Assembled from what the decision models observed while running. "
                 "CORPUS BIAS, stated up front: these events were found by 30 "
                 "premise-guided searches, so this is what those premises went "
                 "looking for — not a neutral season log. Any pattern mined from "
                 "it will partly re-discover the seeds."),
        "observations_collected": len(raw),
        "events": len(events),
        "corroborated": len(multi),
        "undated": len(undated),
        "timeline": events,
    }
    (OUT / "timeline.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")

    lines = ["# 2026 F1 event history", "",
             f"{len(events)} distinct events merged from {len(raw)} observations "
             f"across {len(set(r['observer'] for r in raw))} decision models. "
             f"{len(multi)} " + ("was" if len(multi)==1 else "were") + " seen independently by more than one model.", "",
             "**Corpus bias:** assembled from premise-guided searches, not a neutral "
             "season log. See timeline.json.", ""]
    for e in events:
        obs = ", ".join(e["observers"])
        d = e["date"] or "undated"
        star = " ·" + "*" * (len(e["observers"]) - 1) if len(e["observers"]) > 1 else ""
        lines.append(f"**{e['id']}** · {d}{'~' if e['approx'] else ''}{star} — {e['item']}")
        lines.append(f"    observed by: {obs}")
        if e["sources"]:
            lines.append(f"    source: {e['sources'][0][:120]}")
        lines.append("")
    (OUT / "EVENTS.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"  {len(raw)} observations -> {len(events)} distinct events")
    print(f"  {len(multi)} corroborated by 2+ models, {len(undated)} undated")
    top = Counter(o for e in events for o in e["observers"]).most_common(5)
    print("  most observant models: " + ", ".join(f"{k}({v})" for k, v in top))
    print(f"  -> {OUT / 'timeline.json'} and EVENTS.md")


def subject(name: str) -> None:
    tl = json.loads((OUT / "timeline.json").read_text(encoding="utf-8"))["timeline"]
    hits = [e for e in tl if name.lower() in e["item"].lower()
            or name.lower() in " ".join(e["observers"])]
    print(f"# {name} — {len(hits)} events")
    for e in hits:
        print(f"  {e['id']} · {e['date'] or 'undated'} — {e['item'][:150]}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--subject")
    a = ap.parse_args()
    if a.subject:
        return subject(a.subject)
    if a.build:
        return build()
    ap.print_help()


if __name__ == "__main__":
    main()
