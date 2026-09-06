"""Pressure watch — standing monitor for power holders and pressure dynamics.

Extends decision_trace (one-shot) into a REGISTRY-driven monitor (recurring). The
registry (`my-model/watch_registry.json`) lists offices worth standing coverage;
each monitor round does two things per office:

  1. POWER HOLDER — the incumbency gate run on schedule: verify who holds the office
     today; a succession/death/expiry is recorded as a `succession` event (itself a
     first-order pressure event: every stake installed at the office re-prices) and the
     registry updates.
  2. PRESSURE DYNAMICS — the model's dynamic quantities, observed for the office's arena
     over the recent window, each mapped to a model mechanism:
       installation   — new stakes broadcast at the office (who, what, which layer)
       phi_repair     — demonstrations/enforcement backing an existing stake
                        (credibility maintenance; the model's reading of "shows of force")
       decay          — lapsed threats/undemonstrated stakes visibly losing credibility
       saturation     — conflicting high-severity stakes piling up; dilemma signature
                        (delay, reframing) if no low-pressure option remains
       farming        — pressure-farming signatures if present (ritual inflation,
                        fear-language displacing cost-benefit, burnout under climbing
                        participation)

Everything appends to `my-model/dynamics/log.jsonl` (append-only, dated, per-office)
and renders `my-model/dynamics/DYNAMICS.md` (latest state per office + recent
events). Position/personal-power boundary: the monitor reads the OFFICE's publicly
documented stake landscape, never the person's inner life.

Runs inside the weekly grading loop (a `monitors` step), so coverage accrues on a
schedule, not on attention.

  python -m suites.pressure_watch --monitor
  python -m suites.pressure_watch --add "Chair of the SEC" --arena "US securities regulation"
  python -m suites.pressure_watch --status
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
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
from harness.fleet import DECISION_REPO
RDIR = TOOLS / (DECISION_REPO or "decision-model")
REGISTRY = RDIR / "watch_registry.json"
DYN = RDIR / "dynamics"

SEED = []  # add offices via --add

DYNAMICS_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. You are running the pressure model as a
standing monitor on ONE public office. This is institutional analysis of the office's publicly
documented stake landscape — never the officeholder's inner life.

OFFICE: {office}  (current holder: {holder})
ARENA: {arena}

Observe the last ~2-3 weeks via the web (cite dates). Report EVENTS in the model's categories,
each mapped to its mechanism:

- installation: a form (statute, party, market, electorate, press, foreign power) broadcast a NEW
  stake at the office ("do S or lose λ"). Name the installer, the stake, and the layer
  (mandate | operational | role-status | institutional-identity | mission).
- phi_repair: an EXISTING stake was demonstrated/enforced (sanction executed, market punished,
  vote whipped) — credibility maintenance of an installed stake.
- decay: a stake visibly lost credibility (deadline lapsed unenforced, threat ignored without
  consequence).
- saturation: evidence of conflicting high-severity stakes piling on the office; dilemma
  signature (delay, reframing, silence on a forced question) if present.
- farming: pressure-farming signatures in the arena (ritual inflation, fear-appeals displacing
  cost-benefit language, burnout/churn under climbing participation metrics).

Only report what the window supports — an empty list is a valid answer. 2-6 events, most
significant first. Then rate the office's current pressure state and trend.

Return ONLY JSON:
{"events":[{"kind":"installation|phi_repair|decay|saturation|farming","what":"one concrete line",
"installer_or_actor":"...","layer":"mandate|operational|role-status|institutional-identity|mission|n/a",
"date":"YYYY-MM-DD (approx)","source":"..."}],
"pressure_state":"low|moderate|high|saturated","trend":"rising|steady|falling",
"read":"2 sentences: the office's current pressure landscape through the model"}"""


def load_registry() -> dict:
    if REGISTRY.exists():
        return json.load(REGISTRY.open(encoding="utf-8"))
    return {"offices": SEED, "updated": ""}


def save_registry(reg: dict) -> None:
    json.dump(reg, REGISTRY.open("w", encoding="utf-8"), ensure_ascii=False, indent=1)


def log_events(rows: list[dict]) -> None:
    DYN.mkdir(exist_ok=True)
    with (DYN / "log.jsonl").open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def render(reg: dict) -> None:
    rows = []
    lf = DYN / "log.jsonl"
    if lf.exists():
        rows = [json.loads(l) for l in lf.read_text(encoding="utf-8").splitlines() if l.strip()]
    lines = ["# Pressure dynamics — standing monitor",
             f"Updated {reg.get('updated','')} · {len(reg['offices'])} offices · "
             f"{len(rows)} logged events", ""]
    for o in reg["offices"]:
        lines.append(f"## {o['office']}")
        lines.append(f"- holder: **{o.get('holder') or '?'}** (since {o.get('since') or '?'}) · "
                     f"arena: {o.get('arena','')}")
        if o.get("pressure_state"):
            lines.append(f"- state: **{o['pressure_state']}** ({o.get('trend','?')}) — "
                         f"{o.get('read','')}")
        recent = [r for r in rows if r.get("office") == o["office"]][-6:]
        for r in reversed(recent):
            lines.append(f"  - [{r.get('monitored','')}] `{r.get('kind','')}` "
                         f"{r.get('what','')} ({r.get('installer_or_actor','')}, "
                         f"{r.get('date','')})")
        lines.append("")
    (DYN / "DYNAMICS.md").write_text("\n".join(lines), encoding="utf-8")


def monitor(model: str) -> None:
    from suites.decision_trace import verify_holder, _same_person
    reg = load_registry()
    today = datetime.date.today().isoformat()
    all_events = []
    for o in reg["offices"]:
        print(f"[pressure-watch] {o['office']}")
        # 1 — power holder
        v = verify_holder(o["office"], "openai/gpt-4o", today)
        if v and v.get("holder"):
            if o.get("holder") and not _same_person(v["holder"], o["holder"]):
                ev = {"office": o["office"], "monitored": today, "kind": "succession",
                      "what": f"holder changed: {o['holder']} -> {v['holder']}",
                      "installer_or_actor": v.get("source", ""), "layer": "n/a",
                      "date": v.get("since", ""), "source": v.get("source", "")}
                all_events.append(ev)
                print(f"  !! SUCCESSION: {o['holder']} -> {v['holder']} "
                      f"(since {v.get('since','?')}) — every installed stake re-prices")
            o["holder"], o["since"] = v["holder"], v.get("since", o.get("since", ""))
            print(f"  holder: {o['holder']} (verified)")
        else:
            print("  ! holder verification unavailable this round")
        # 2 — pressure dynamics
        p = (DYNAMICS_PROMPT.replace("{today}", today).replace("{office}", o["office"])
             .replace("{holder}", o.get("holder", "?")).replace("{arena}", o.get("arena", "")))
        r = chat(model + ":online", [{"role": "user", "content": p}],
                 temperature=0.2, max_tokens=2200)
        d = parse_json(r.text) if not r.error else None
        if not d:
            print(f"  ! dynamics read failed: {r.error or 'unparseable'}")
            continue
        o["pressure_state"] = d.get("pressure_state", "")
        o["trend"] = d.get("trend", "")
        o["read"] = d.get("read", "")[:300]
        o["last_monitored"] = today
        for e in d.get("events", []):
            e["office"] = o["office"]
            e["monitored"] = today
            all_events.append(e)
        print(f"  state: {o['pressure_state']} ({o['trend']}) · "
              f"{len(d.get('events', []))} events")
        for e in d.get("events", []):
            print(f"    {e.get('kind',''):>12} {e.get('what','')[:80]}")
    reg["updated"] = today
    save_registry(reg)
    if all_events:
        log_events(all_events)
    render(reg)
    print(f"[pressure-watch] {len(all_events)} events logged -> dynamics/DYNAMICS.md")


def main() -> None:
    ap = argparse.ArgumentParser(description="Standing monitor: power holders + pressure dynamics.")
    ap.add_argument("--monitor", action="store_true")
    ap.add_argument("--add", metavar="OFFICE")
    ap.add_argument("--arena", default="")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    if a.add:
        reg = load_registry()
        reg["offices"].append({"office": a.add, "arena": a.arena, "holder": "", "since": ""})
        save_registry(reg)
        print(f"added: {a.add} ({len(reg['offices'])} offices)")
        return
    if a.status:
        reg = load_registry()
        for o in reg["offices"]:
            print(f"  {o['office']:<42} {o.get('holder') or '?':<20} "
                  f"{o.get('pressure_state','-'):>9} {o.get('trend','')}")
        return
    if not os.environ.get("OPENROUTER_API_KEY"):
        if os.environ.get("LLM_BACKEND") != "claude-code":
            raise SystemExit("OPENROUTER_API_KEY not set (or set LLM_BACKEND=claude-code)")
    monitor(a.model)


if __name__ == "__main__":
    main()
