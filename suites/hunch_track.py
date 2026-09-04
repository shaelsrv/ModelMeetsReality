"""Hunch tracker — register raw intuitions verbatim, formalize signals, scan the world.

Implements hunch-tracker/MODEL.md: D1 verbatim preservation, D2 formalize-without-
inflating, D3 statuses earned by scans, D4 graduation/burial. Hunches live in
hunch-tracker/hunches/<id>.json; scans run in the weekly loop.

  python -m suites.hunch_track --add "the hunch, exactly as stated" --id attention-competition
  python -m suites.hunch_track --scan
  python -m suites.hunch_track --list
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

from harness.openrouter import chat  # noqa: E402
from harness.actors import parse_json  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
HDIR = ROOT.parent / "hunch-tracker" / "hunches"

FORMALIZE = """A person has registered a raw hunch. Formalize it into trackable signals WITHOUT
inflating it — each signal must be something the hunch actually implies, stated as a concrete
observable with a rough window. 2-4 signals. Faithfulness beats testability.

THE HUNCH (verbatim; preserve its meaning, not its grammar):
{hunch}

Return ONLY JSON:
{"summary":"one neutral sentence of what the hunch claims",
"signals":[{"id":"s1","observable":"what would be seen, concretely","window":"rough timeframe",
"strength":"weak|moderate|strong (how strongly this signal would support the hunch)"}],
"family_bridge":"if this hunch relates to an existing model's mechanism, name it in one line, else empty"}"""

SCAN = """You have LIVE WEB ACCESS. Today is {today}. Scan for evidence bearing on ONE registered
hunch's signals. Report only what you actually find, with dates and sources; absence is a valid
and useful finding.

HUNCH (registered {date}): {summary}

SIGNALS TO CHECK:
{signals}

For each signal: found | partial | absent, with 1-2 dated concrete items if found/partial.
Then an overall read: is the hunch warming, unchanged, or contradicted by what you found?

Return ONLY JSON:
{"checks":[{"id":"s1","status":"found|partial|absent","evidence":"dated items or empty"}],
"overall":"warming|unchanged|contradicted","note":"one line"}"""


def load_all():
    HDIR.mkdir(parents=True, exist_ok=True)
    return {f.stem: json.load(f.open(encoding="utf-8")) for f in HDIR.glob("*.json")}


def save(hid, h):
    (HDIR / f"{hid}.json").write_text(json.dumps(h, ensure_ascii=False, indent=1),
                                      encoding="utf-8")


def cmd_add(hid: str, verbatim: str, model: str):
    r = chat(model, [{"role": "user", "content": FORMALIZE.replace("{hunch}", verbatim)}],
             temperature=0.2, max_tokens=1200)
    d = parse_json(r.text) if not r.error else None
    if not d:
        raise SystemExit(f"formalization failed: {r.error or 'unparseable'}")
    h = {"id": hid, "registered": datetime.date.today().isoformat(),
         "stated_verbatim": verbatim, "summary": d.get("summary", ""),
         "signals": d.get("signals", []), "family_bridge": d.get("family_bridge", ""),
         "status": "dormant", "log": []}
    save(hid, h)
    print(f"registered hunch '{hid}': {h['summary']}")
    for s in h["signals"]:
        print(f"  [{s.get('strength','?'):>8}] {s.get('observable','')[:90]} ({s.get('window','')})")
    if h["family_bridge"]:
        print(f"  bridge: {h['family_bridge']}")


AMEND = """A registered hunch is being AMENDED by its author. Original hunch and existing signals
below, then the amendment (verbatim). Produce 2-4 NEW signals covering the amendment's broader
scope — concrete observables with windows, faithful, non-inflating, NOT duplicating existing
signals.

ORIGINAL: {original}
EXISTING SIGNALS: {existing}
AMENDMENT (verbatim): {amendment}

Return ONLY JSON:
{"summary_updated":"one neutral sentence of the hunch as amended",
"new_signals":[{"id":"...","observable":"...","window":"...","strength":"weak|moderate|strong"}]}"""


def cmd_amend(hid: str, verbatim: str, model: str):
    f = HDIR / f"{hid}.json"
    h = json.load(f.open(encoding="utf-8"))
    existing = "; ".join(s["observable"][:60] for s in h["signals"])
    r = chat(model, [{"role": "user", "content":
                      AMEND.replace("{original}", h["stated_verbatim"])
                      .replace("{existing}", existing).replace("{amendment}", verbatim)}],
             temperature=0.2, max_tokens=1200)
    d = parse_json(r.text) if not r.error else None
    if not d:
        raise SystemExit(f"amendment formalization failed: {r.error or 'unparseable'}")
    nxt = len(h["signals"]) + 1
    for i, s in enumerate(d.get("new_signals", [])):
        s["id"] = f"s{nxt + i}"
        s["from_amendment"] = datetime.date.today().isoformat()
        h["signals"].append(s)
    h.setdefault("amendments", []).append(
        {"date": datetime.date.today().isoformat(), "stated_verbatim": verbatim})
    h["summary"] = d.get("summary_updated", h["summary"])
    save(hid, h)
    print(f"amended '{hid}' -> {h['summary']}")
    for s in d.get("new_signals", []):
        print(f"  +[{s.get('strength','?'):>8}] {s['observable'][:90]} ({s.get('window','')})")


def cmd_scan(model: str):
    today = datetime.date.today().isoformat()
    for hid, h in load_all().items():
        if h["status"] in ("confirmed", "dead"):
            continue
        sigs = "\n".join(f"- {s['id']}: {s['observable']} (window {s.get('window','')})"
                         for s in h["signals"])
        p = (SCAN.replace("{today}", today).replace("{date}", h["registered"])
             .replace("{summary}", h["summary"]).replace("{signals}", sigs))
        r = chat(model + ":online", [{"role": "user", "content": p}],
                 temperature=0.2, max_tokens=1800)
        d = parse_json(r.text) if not r.error else None
        if not d:
            print(f"[{hid}] scan failed: {r.error or 'unparseable'}")
            continue
        found = sum(1 for c in d.get("checks", []) if c.get("status") == "found")
        partial = sum(1 for c in d.get("checks", []) if c.get("status") == "partial")
        old = h["status"]
        if found >= max(1, len(h["signals"]) - 1):
            h["status"] = "confirmed"
        elif found or partial:
            h["status"] = "warming"
        h["log"].append({"scanned": today, "checks": d.get("checks", []),
                         "overall": d.get("overall", ""), "note": d.get("note", "")})
        save(hid, h)
        print(f"[{hid}] {old} -> {h['status']} · found {found}, partial {partial} · "
              f"{d.get('note','')[:90]}")
        for c in d.get("checks", []):
            if c.get("status") != "absent":
                print(f"    {c['id']} {c['status'].upper()}: {c.get('evidence','')[:110]}")
        if h["status"] == "confirmed":
            print(f"    >>> GRADUATION candidate: {h.get('family_bridge') or 'new model seed'}")


def cmd_list():
    for hid, h in sorted(load_all().items()):
        scans = len(h.get("log", []))
        print(f"  [{h['status']:>9}] {hid} ({h['registered']}, {scans} scans) — {h['summary'][:70]}")


def main():
    ap = argparse.ArgumentParser(description="Register and track hunches.")
    ap.add_argument("--add", metavar="VERBATIM")
    ap.add_argument("--id", default="")
    ap.add_argument("--amend", metavar="VERBATIM")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.list:
        cmd_list(); return
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    if a.add:
        cmd_add(a.id or f"hunch-{datetime.date.today().isoformat()}", a.add, a.model)
    if a.amend:
        if not a.id:
            raise SystemExit("--amend needs --id")
        cmd_amend(a.id, a.amend, a.model)
    if a.scan:
        cmd_scan(a.model)


if __name__ == "__main__":
    main()
