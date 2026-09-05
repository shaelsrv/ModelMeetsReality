"""Local cockpit UI for the model family — zero dependencies, stdlib only.

  python ui/server.py            # http://127.0.0.1:8787  (localhost ONLY)

Tabs: Models (see/create), Tasks (due work + your own), Assessments (trajectory,
attribution scoreboard, postmortems), Connect (how this UI reaches a live Claude
Code session).

The Claude bridge: POST /api/inbox appends one JSON line to ui/inbox.jsonl.
A Claude Code session watching that file (persistent Monitor on `tail -f`)
receives each line as an event and acts on it — same effect as typing in the
session. Headless alternative per instruction: `claude -p "<instruction>"`.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]       # this instance
_cfg = {}
_fleet_f = ROOT / "fleet.json"
if _fleet_f.exists():
    try:
        _cfg = json.load(_fleet_f.open(encoding="utf-8"))
    except (OSError, ValueError):
        _cfg = {}
# where this instance's model repos live: its own subdirectory when fleet.json sets
# models_dir, else the shared parent. Two instances under one parent otherwise
# share a namespace and collide.
TOOLS = (ROOT / _cfg["models_dir"]).resolve() if _cfg.get("models_dir") else ROOT.parent
UI = ROOT / "ui"
# so `import chat` works regardless of the cwd the server is started from
sys.path.insert(0, str(UI))
sys.path.insert(0, str(ROOT))
TASKS = UI / "tasks.json"
INBOX = UI / "inbox.jsonl"
EVENTS = UI / "events.jsonl"


def load_events():
    if not EVENTS.exists():
        return []
    return [json.loads(l) for l in EVENTS.read_text(encoding="utf-8").splitlines()
            if l.strip()]


def save_events(evs):
    EVENTS.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in evs) + "\n",
                      encoding="utf-8")

def _repos():
    """This instance's model repos: fleet.json first, then anything with a
    MODEL.md in the models directory (so a hand-added repo is not invisible).

    Re-read on every access. Caching this at import time made a model imported
    while the cockpit was running invisible until restart — which is exactly the
    moment someone tries a shared model and concludes the import failed.
    """
    cfg = _cfg
    f = ROOT / "fleet.json"
    if f.exists():
        try:
            cfg = json.load(f.open(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    named = list(cfg.get("models", [])) + list(cfg.get("classifiers", []))
    found = sorted(d.name for d in TOOLS.iterdir()
                   if d.is_dir() and (d / "MODEL.md").exists()) if TOOLS.exists() else []
    seen, out = set(), []
    for r in named + found:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


class _LiveRepos(list):
    """Behaves like the list the handlers already iterate, but always current."""

    def _now(self):
        return _repos()

    def __iter__(self):
        return iter(self._now())

    def __len__(self):
        return len(self._now())

    def __contains__(self, item):
        return item in self._now()

    def __getitem__(self, i):
        return self._now()[i]


REPOS = _LiveRepos()


def ledger_counts(repo: Path):
    n_open = n_res = 0
    for rel in ("predict/ledger.json", "predict/live_ledger.json",
                "signals/signal_ledger.json"):
        p = repo / rel
        if not p.exists():
            continue
        try:
            d = json.load(p.open(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in (d.get("predictions", d) if isinstance(d, dict) else d):
            if row.get("status", "open") == "open":
                n_open += 1
            else:
                n_res += 1
    return n_open, n_res


def model_info(name: str):
    r = TOOLS / name
    mm = r / "MODEL.md"
    if not mm.exists():
        return None
    text = mm.read_text(encoding="utf-8", errors="replace")
    title = text.splitlines()[0].lstrip("# ").strip() if text else name
    kind = ""
    m = re.search(r"\*\*The kind:?\*\*:?\s*([^\n]+)", text)
    if m:
        kind = m.group(1)[:140]
    n_open, n_res = ledger_counts(r)
    return {"name": name, "title": title, "kind": kind, "open": n_open,
            "resolved": n_res, "deletion_clause": "eletion clause" in text}


def due_tasks():
    """Computed queue: what the system itself says is pending."""
    out = []
    today = date.today().isoformat()
    for name in REPOS:
        for rel in ("predict/ledger.json", "predict/live_ledger.json",
                    "signals/signal_ledger.json"):
            p = TOOLS / name / rel
            if not p.exists():
                continue
            try:
                d = json.load(p.open(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            n = sum(1 for r in (d.get("predictions", d) if isinstance(d, dict) else d)
                    if r.get("status") == "open" and (r.get("resolve_by") or "9999") <= today)
            if n:
                out.append({"kind": "due", "text": f"{name}: {n} claim(s) due for grading",
                            "hint": "python -m suites.grading_loop"})
    cdir = TOOLS / "hunch-tracker" / "candidates"
    if cdir.exists():
        n = sum(1 for f in cdir.glob("*.json")
                if not json.load(f.open(encoding="utf-8")).get("promoted"))
        if n:
            out.append({"kind": "review", "text": f"{n} generator candidate(s) await review",
                        "hint": "python -m suites.hunch_gen --list"})
    return out


def manual_tasks():
    if TASKS.exists():
        return json.load(TASKS.open(encoding="utf-8"))
    return []


def save_manual(tasks):
    TASKS.write_text(json.dumps(tasks, ensure_ascii=False, indent=1), encoding="utf-8")


def model_full(name: str):
    r = TOOLS / name
    mm = (r / "MODEL.md").read_text(encoding="utf-8", errors="replace")
    info = model_info(name) or {}
    claims = []
    for rel in ("predict/ledger.json", "predict/live_ledger.json",
                "signals/signal_ledger.json"):
        lp = r / rel
        if not lp.exists():
            continue
        try:
            d = json.load(lp.open(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in (d.get("predictions", d) if isinstance(d, dict) else d):
            claims.append({"status": row.get("status", "?"),
                           "resolve_by": row.get("resolve_by", ""),
                           "made_on": row.get("made_on", ""),
                           "confidence": row.get("confidence"),
                           "claim": row.get("claim", "")[:400],
                           "criteria": (row.get("resolution_criteria")
                                        or row.get("criteria") or "")[:400],
                           "mechanism": row.get("mechanism", "")[:300],
                           "ledger": rel.split("/")[-1],
                           "what_happened": row.get("what_happened", "")[:400]})
    history = []
    try:
        out = subprocess.run(["git", "log", "--format=%ad|%s", "--date=short",
                              "--", "MODEL.md"], cwd=r, capture_output=True,
                             text=True, timeout=20)
        history = [{"date": l.split("|", 1)[0], "msg": l.split("|", 1)[1][:110]}
                   for l in out.stdout.strip().splitlines() if "|" in l][:20]
    except Exception:
        pass
    traj_rows, briers = [], []
    tf = ROOT / "trajectory" / "trajectory.jsonl"
    if tf.exists():
        for l in tf.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            row = json.loads(l)
            if row.get("model") == name and row.get("brier") is not None:
                briers.append(row["brier"])
                if len(traj_rows) < 10:
                    traj_rows.append({"claim": row.get("claim", "")[:160],
                                      "brier": row["brier"],
                                      "outcome": row.get("outcome", row.get("status", ""))})
    pms = []
    pf = ROOT / "trajectory" / "postmortems.jsonl"
    if pf.exists():
        for l in pf.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            row = json.loads(l)
            if row.get("model") == name and len(pms) < 8:
                pms.append({"verdict": row.get("verdict", row.get("category", "")),
                            "claim": row.get("claim", "")[:140],
                            "lesson": (row.get("lesson") or row.get("why") or "")[:220]})
    as_author = as_driver = 0
    att = TOOLS / "attribution-model" / "attributions" / "attributions.jsonl"
    if att.exists():
        for l in att.read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            row = json.loads(l)
            if row.get("author") == name:
                as_author += 1
            if row.get("primary") == name or row.get("secondary") == name:
                as_driver += 1
    artifacts = []
    for f in sorted(r.glob("*.md")):
        if f.name != "MODEL.md":
            artifacts.append({"path": f.name, "n": None})
    for sub in ("traces", "registrations", "candidates", "hunches", "annotations",
                "trials", "dissections", "applications", "watch", "launch_assets",
                "models", "attributions", "instances"):
        d = r / sub
        if d.exists():
            artifacts.append({"path": sub + "/", "n": len(list(d.iterdir()))})
    studies = []
    sdir = r / "studies"
    if sdir.exists():
        for f in sorted(sdir.glob("*.registration.json")):
            s = json.load(f.open(encoding="utf-8"))
            studies.append({"id": s.get("id"), "status": s.get("status"),
                            "h1": s.get("h1", "")[:200], "test": s.get("test", {}).get("type"),
                            "verdict": s.get("verdict", ""),
                            "result": s.get("result")})
    return {"info": info, "model_md": mm[:20000], "claims": claims, "studies": studies,
            "history": history,
            "trajectory": {"n": len(briers),
                           "mean_brier": round(sum(briers) / len(briers), 3) if briers else None,
                           "rows": traj_rows},
            "postmortems": pms,
            "attribution": {"as_author": as_author, "as_driver": as_driver},
            "artifacts": artifacts}


MANUAL_ALIASES = {  # alias -> the glossary term it belongs to
    "t1": "Tiers T1", "t2": "Tiers T1", "t3": "Tiers T1", "t4": "Tiers T1",
    "t2a": "T2a", "t2b": "T2a", "postmortem": "The pentad",
    "postmortems": "The pentad", "brier": "Brier score", "sealed": "Sealed mechanism",
    "pre-registered": "Pre-registration", "cross-hits": "Cross-hit",
    "blind-spot": "Monitored set", "no-go": "GO", "candidates": "Candidate vs finding",
    "candidate": "Candidate vs finding", "graded cohort": "Grading window",
}
GENERIC = {"model", "models", "the gap", "the hinge", "reveal", "keying", "grade",
           "register", "seal", "hold", "go", "burial", "the freeze", "budget"}


def glossary_terms():
    g = ROOT / "docs" / "GLOSSARY.md"
    if not g.exists():
        return []
    text = g.read_text(encoding="utf-8")
    entries = []
    for m in re.finditer(r"^- \*\*(.+?)\*\*\s+—\s+(.+?)(?=\n- \*\*|\n\n|\n##|\Z)",
                         text, re.M | re.S):
        term = m.group(1).strip()
        definition = re.sub(r"\s+", " ", re.sub(r"\*\*?", "", m.group(2))).strip()[:300]
        slug = "g-" + re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")[:50]
        aliases = set()
        base = re.sub(r"\([^)]*\)", "", term)
        for part in re.split(r"\s*/\s*", base):
            a = part.strip().lower()
            a = re.sub(r"^the\s+", "", a)
            if a and (len(a) >= 4 or a in ("t2a", "t2b")) and a not in GENERIC:
                aliases.add(a)
        entries.append({"term": term, "slug": slug, "def": definition,
                        "aliases": sorted(aliases)})
    for alias, prefix in MANUAL_ALIASES.items():
        for e in entries:
            if e["term"].startswith(prefix):
                if alias not in GENERIC:
                    e["aliases"].append(alias)
                break
    return entries


def create_model(slug: str, title: str, domain: str):
    slug = re.sub(r"[^a-z0-9-]", "-", slug.lower()).strip("-")
    if not slug:
        return {"error": "bad slug"}
    r = TOOLS / slug
    if r.exists():
        return {"error": f"{slug} already exists"}
    (r / "predict").mkdir(parents=True)
    (r / "MODEL.md").write_text(f"""# {title or slug} — (v1)

**The kind:** (state it — forecaster / classifier / finder / tracker / generator /
tracer / prospector / timer / attributor / your own)
**The domain:** {domain or "(what it models)"}

## Premises

**P1 — .** (Each load-bearing claim, with honest confidence.)

## Falsifiable consequences (v1)

1. **:** a concrete observable that would count against the model.

## Deletion clause

If the falsifiable consequences fail or stay untested while claims accumulate,
this model retires to notation and the retirement is logged.

## Epistemic status

v1. All claims candidates until graded.
""", encoding="utf-8")
    (r / "predict" / "ledger.json").write_text('{"predictions": []}', encoding="utf-8")
    try:
        subprocess.run(["git", "init", "-q"], cwd=r, timeout=30)
        subprocess.run(["git", "add", "-A"], cwd=r, timeout=30)
        subprocess.run(["git", "-c", "user.name=cockpit", "-c", "user.email=cockpit@local",
                        "commit", "-q", "-m", f"{slug} v1 scaffold (cockpit)"],
                       cwd=r, timeout=30)
    except Exception:
        pass
    return {"ok": True, "slug": slug,
            "next": ("Scaffolded. To wire it into grading/classifiers, send an instruction "
                     "via Connect: 'wire " + slug + " into the rosters'.")}


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Model Cockpit</title>
<style>
:root { --bg:#0c1014; --panel:#141a21; --ink:#e9e7e2; --sub:#95a0ac; --line:#242d38;
        --acc:#4fc3a1; --accd:#83dfc3; --warn:#e08050; }
* { box-sizing:border-box; margin:0; }
body { background:var(--bg); color:var(--ink); font:15px/1.6 "IBM Plex Sans",system-ui,sans-serif;
       padding:1.5rem 1rem 4rem; }
main { max-width:60rem; margin:0 auto; }
h1 { font-size:1.5rem; letter-spacing:-.01em; }
h1 small { color:var(--sub); font-weight:400; font-size:.75rem; margin-left:.8rem;
           font-family:"IBM Plex Mono",monospace; }
nav { display:flex; gap:.5rem; margin:1.1rem 0 1.4rem; flex-wrap:wrap; }
nav button { font:600 .85rem "IBM Plex Sans",sans-serif; padding:.5rem 1rem; cursor:pointer;
  border:1px solid var(--line); background:var(--panel); color:var(--sub); border-radius:999px; }
nav button.on { background:var(--acc); border-color:var(--acc); color:var(--bg); }
section { display:none; } section.on { display:block; }
table { width:100%; border-collapse:collapse; font-size:.9rem; }
th, td { text-align:left; padding:.45rem .6rem; border-bottom:1px solid var(--line); }
th { color:var(--sub); font-size:.72rem; text-transform:uppercase; letter-spacing:.08em; }
tr.mrow { cursor:pointer; } tr.mrow:hover td { background:var(--panel); }
.badge { font-family:"IBM Plex Mono",monospace; font-size:.72rem; padding:.1rem .45rem;
  border-radius:3px; border:1px solid var(--line); color:var(--sub); }
.badge.ok { border-color:var(--acc); color:var(--accd); }
.badge.warn { border-color:var(--warn); color:var(--warn); }
.card { border:1px solid var(--line); background:var(--panel); border-radius:10px;
  padding:1rem 1.2rem; margin:.9rem 0; }
.card h3 { font-size:1rem; margin-bottom:.4rem; }
pre { background:var(--bg); border:1px solid var(--line); border-radius:8px; padding:.9rem 1rem;
  overflow:auto; font:12.5px/1.55 "IBM Plex Mono",monospace; white-space:pre-wrap; max-height:26rem; }
input, textarea { width:100%; background:var(--bg); border:1px solid var(--line); border-radius:7px;
  color:var(--ink); padding:.55rem .7rem; font:inherit; margin:.25rem 0 .7rem; }
textarea { min-height:5.5rem; font-family:"IBM Plex Mono",monospace; font-size:.85rem; }
button.act { font:600 .88rem "IBM Plex Sans",sans-serif; background:var(--acc); color:var(--bg);
  border:none; border-radius:7px; padding:.55rem 1.1rem; cursor:pointer; }
button.act:disabled { opacity:.5 }
label { font-size:.78rem; color:var(--sub); text-transform:uppercase; letter-spacing:.07em; }
.task { display:flex; gap:.7rem; align-items:baseline; padding:.5rem .2rem;
  border-bottom:1px solid var(--line); font-size:.92rem; }
.task .k { font-family:"IBM Plex Mono",monospace; font-size:.68rem; color:var(--accd);
  text-transform:uppercase; min-width:4.2rem; }
.task .hint { color:var(--sub); font-family:"IBM Plex Mono",monospace; font-size:.75rem;
  margin-left:auto; }
.muted { color:var(--sub); font-size:.85rem; }
.okmsg { color:var(--accd); font-size:.85rem; margin:.4rem 0; }
kbd { font-family:"IBM Plex Mono",monospace; background:var(--panel); border:1px solid var(--line);
  padding:.05rem .35rem; border-radius:4px; font-size:.82em; }
.term { border-bottom:1px dotted var(--accd); cursor:help; position:relative; }
.term:hover { color:var(--accd); }
.term:hover::after { content:attr(data-def); position:absolute; left:0; bottom:1.5em;
  z-index:9; width:min(24rem,72vw); background:var(--panel); border:1px solid var(--acc);
  border-radius:8px; padding:.6rem .8rem; font:400 .78rem/1.5 "IBM Plex Sans",sans-serif;
  color:var(--ink); box-shadow:0 6px 24px rgba(0,0,0,.5); }
.ghl { animation:ghl 2.2s ease-out; }
@keyframes ghl { 0% { background:rgba(79,195,161,.25); } 100% { background:transparent; } }
/* phone: eleven nav buttons in a row and wide tables were unusable on mobile */
@media (max-width: 720px) {
  body { padding:1rem .7rem 3rem; }
  h1 { font-size:1.25rem; }
  nav { overflow-x:auto; flex-wrap:nowrap; -webkit-overflow-scrolling:touch;
        scrollbar-width:none; padding-bottom:.3rem; }
  nav::-webkit-scrollbar { display:none; }
  nav button { flex:0 0 auto; font-size:.8rem; padding:.45rem .8rem; }
  table { display:block; overflow-x:auto; white-space:nowrap; }
  .card { padding:.8rem .85rem; }
  .task { flex-wrap:wrap; gap:.3rem; }
  .task .hint { margin-left:0; width:100%; }
  pre { font-size:11.5px; }
  .term:hover::after { width:min(20rem,88vw); }
}
@keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:.45; } }
</style></head><body><main>
<h1>Model Cockpit <small>local · 127.0.0.1 only</small></h1>
<div style="display:flex;gap:.6rem;align-items:center;margin:.9rem 0 .2rem;flex-wrap:wrap">
  <input id="gq" placeholder="Search everything the fleet knows…  (semantic, 1300+ fragments)"
    onkeydown="if(event.key==='Enter')doSearch()"
    style="flex:1;min-width:18rem;background:var(--bg);border:1px solid var(--line);
           border-radius:999px;color:var(--ink);padding:.6rem 1rem;font:inherit;font-size:.9rem">
  <button class="act" style="border-radius:999px" onclick="doSearch()">Search</button>
</div>
<nav>
  <button data-t="home" class="on">Home</button>
  <button data-t="verdict">Verdict</button>
  <button data-t="models">Models</button>
  <button data-t="events">Events</button>
  <button data-t="brainstorm">Brainstorm</button>
  <button data-t="entities">Entities</button>
  <button data-t="map">Map</button>
  <button data-t="tasks">Tasks</button>
  <button data-t="assess">Assessments</button>
  <button data-t="glossary">Glossary</button>
  <button data-t="connect">Connect to Claude</button>
</nav>

<button id="capbtn" onclick="openCapture()" title="Register a claim (c)"
  style="position:fixed;right:1.2rem;bottom:1.2rem;z-index:40;width:3.2rem;height:3.2rem;
         border-radius:50%;border:none;background:var(--acc);color:var(--bg);
         font-size:1.7rem;font-weight:700;cursor:pointer;box-shadow:0 4px 18px rgba(0,0,0,.5)">+</button>

<div id="capmodal" style="display:none;position:fixed;inset:0;z-index:50;
     background:rgba(6,8,11,.74);padding:2rem 1rem;overflow:auto">
  <div style="max-width:40rem;margin:0 auto;background:var(--panel);border:1px solid var(--line);
       border-radius:14px;padding:1.3rem 1.4rem">
    <div style="display:flex;justify-content:space-between;align-items:baseline">
      <h3 style="font-size:1.05rem">Register a claim</h3>
      <span style="cursor:pointer;color:var(--sub);font-size:.8rem" onclick="closeCapture()">esc</span>
    </div>
    <p class="muted" style="font-size:.82rem;margin:.3rem 0 .8rem">
      Write the version you would be embarrassed to get wrong. Criteria and a date are
      required &mdash; a claim that cannot lose is not a claim.</p>
    <label>the claim</label>
    <textarea id="cap-claim" placeholder="By &lt;date&gt;, &lt;specific observable&gt; will…"></textarea>
    <label>resolution criteria &mdash; how a stranger would score it</label>
    <textarea id="cap-crit" placeholder="Counts as a hit if… measured from…"></textarea>
    <div style="display:flex;gap:.7rem;flex-wrap:wrap">
      <div style="flex:1;min-width:9rem"><label>resolves by</label>
        <input id="cap-date" type="date"></div>
      <div style="flex:1;min-width:9rem"><label>confidence 0&ndash;1</label>
        <input id="cap-conf" type="number" min="0" max="1" step="0.05" value="0.6"></div>
      <div style="flex:2;min-width:12rem"><label>model</label>
        <select id="cap-repo" style="width:100%;background:var(--bg);border:1px solid var(--line);
          border-radius:7px;color:var(--ink);padding:.55rem .7rem;font:inherit"></select></div>
    </div>
    <label>mechanism &mdash; why you believe it (sealed with the claim)</label>
    <textarea id="cap-mech" placeholder="The reason this should happen…"></textarea>
    <button class="act" onclick="submitCapture()">Register</button>
    <span id="cap-msg" class="muted" style="margin-left:.6rem"></span>
  </div>
</div>

<div id="shortcuts" style="display:none"></div>

<section id="searchres">
  <div class="card"><h3>Search results</h3><div id="sres"></div></div>
</section>

<section id="home" class="on">
  <div id="homebody"><p class="muted">loading…</p></div>
</section>

<section id="verdict">
  <div id="verdictbody"><p class="muted">loading…</p></div>
</section>

<section id="models">
  <div id="mlist"><p class="muted">loading…</p></div>
  <div id="mdetail"></div>
  <div class="card"><h3>Create a model</h3>
    <label>slug (kebab-case)</label><input id="c-slug" placeholder="my-theory">
    <label>title</label><input id="c-title" placeholder="My Theory">
    <label>domain — what it models</label><input id="c-domain" placeholder="how X behaves under Y">
    <button class="act" onclick="createModel()">Scaffold model repo</button>
    <div id="c-msg"></div>
    <p class="muted">Scaffolds a sibling repo with MODEL.md (premises, falsifiable
    consequences, deletion clause) + empty ledger, git-initialized. Wiring into the
    grading rosters is a one-line instruction via Connect.</p>
  </div>
</section>

<section id="events">
  <div class="card"><h3>Submit an event for analysis</h3>
    <label>source — url / youtube link (optional if text given)</label>
    <input id="e-src" placeholder="https://… or https://youtu.be/…">
    <label>text / note — what is this, what should be looked at</label>
    <textarea id="e-note" placeholder="paste text or describe the event…"></textarea>
    <label>analyze with (click to toggle; empty = let the session pick)</label>
    <div id="e-models" style="display:flex;gap:.4rem;flex-wrap:wrap;margin:.3rem 0 .8rem"></div>
    <button class="act" onclick="addEvent()">Queue for analysis</button>
    <div id="e-msg"></div>
    <p class="muted">Queued events are forwarded to the session inbox: a watching
    Claude Code session picks them up live (YouTube links get their transcript
    pulled), runs the chosen models&rsquo; suites, and writes the assessment back
    here.</p>
  </div>
  <div class="card"><h3>Events &amp; assessments</h3><div id="elist"></div></div>
</section>

<section id="brainstorm">
  <div class="card"><h3>Bring models together on one event</h3>
    <label>the event — text or a short description (paste a url in the text if relevant)</label>
    <textarea id="b-event" placeholder="what happened / what's developing…"></textarea>
    <label>lenses — pick 2 or more models</label>
    <div id="b-models" style="display:flex;gap:.4rem;flex-wrap:wrap;margin:.3rem 0 .8rem"></div>
    <button class="act" onclick="startBrainstorm()">Start brainstorm</button>
    <div id="b-msg"></div>
    <p class="muted">Each chosen model reads the event through its own mechanism
    (weak-grip admissions welcome); the synthesis maps convergences, tensions with
    their deciders, crossed insights, and joint candidate claims. Runs in the
    watching session; results appear below.</p>
  </div>
  <div class="card"><h3>Past brainstorms</h3><div id="blist"></div></div>
</section>

<section id="tasks">
  <div class="card"><h3>Due now (computed from the ledgers)</h3><div id="due"></div></div>
  <div class="card"><h3>Your tasks</h3><div id="manual"></div>
    <input id="t-text" placeholder="add a task…">
    <button class="act" onclick="addTask()">Add task</button>
  </div>
</section>

<section id="assess">
  <div id="assessbody"><p class="muted">loading…</p></div>
</section>

<section id="entities">
  <div class="card"><h3>What the fleet has understood about&hellip;</h3>
    <p class="muted">Dossiers invert the fleet: instead of &ldquo;what does model X say&rdquo;,
    these ask &ldquo;what do ALL models say about entity Y&rdquo;. Everything is
    <b>extracted</b> from artifacts the fleet actually produced &mdash; claims, brainstorm
    lenses, blind-spot registrations, attributions, traces, studies &mdash; never from an
    LLM&rsquo;s general knowledge. A thin dossier is an honest dossier.</p>
    <div id="elist"><p class="muted">loading…</p></div>
  </div>
  <div class="card"><h3>Mindmap <span class="muted" style="font-weight:400;font-size:.8rem">
    · from embeddings, v1 — read the caveats</span></h3>
    <div id="mmcaveat" class="muted" style="font-size:.8rem;border-left:3px solid var(--warn);
      padding-left:.7rem;margin:.5rem 0 .8rem">
      <b style="color:var(--warn)">Read as coverage, not truth:</b> an edge means our
      artifacts discuss two entities <i>together</i> (co-occurring fragments, weighted by
      Jaccard &times; co-mention volume) &mdash; a claim about this fleet&rsquo;s attention,
      not a verified real-world relationship. Officeholders nest under institutions
      (<span class="mono">part_of</span>) instead of appearing as edges. Density still
      favours our best-covered subjects, so FIFA-side links dominate.
    </div>
    <div style="display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin:.4rem 0 .6rem">
      <label style="font-size:.78rem;color:var(--sub)">edge strength ≥
        <input type="range" id="mmw" min="0" max="100" value="70"
          oninput="mmFilter()" style="vertical-align:middle;width:9rem">
        <span id="mmwval" class="mono" style="font-size:.75rem"></span></label>
      <label style="font-size:.78rem;color:var(--sub);cursor:pointer">
        <input type="checkbox" id="mmspin" checked onchange="mmSpin()"> auto-rotate</label>
      <span class="muted" style="font-size:.75rem">drag to rotate · scroll to zoom · click a node for its dossier</span>
    </div>
    <div id="mmbody" style="touch-action:none"><p class="muted">loading…</p></div>
  </div>
  <div id="edetail"></div>
</section>

<section id="map">
  <div class="card"><h3>The reality map — this instance&rsquo;s slice</h3>
    <p class="muted">Rows are aspects of reality; each bar is one model spanning the
    emergence floors (E0 physics &rarr; E14 civilizational) its mechanism operates on.
    Color = validation tier. The empty space is the point: no single instance can
    cover the map — gaps are invitations for contributors.</p>
    <p class="muted" id="mapproj" style="font-size:.8rem;border-left:3px solid var(--acc);padding-left:.7rem"></p>
    <div id="maplegend" style="display:flex;gap:.8rem;flex-wrap:wrap;margin:.6rem 0;font-size:.75rem"></div>
    <div id="mapbody"><p class="muted">loading…</p></div>
    <div id="mapgaps" class="muted" style="margin-top:.8rem;font-size:.85rem"></div>
    <p class="muted" style="margin-top:.8rem">Share a model to the commons:
    <kbd>python -m suites.reality_map --export --repo &lt;model&gt;</kbd> — mapcards
    carry aspects, span, mechanism, and record COUNTS only; never claims or
    reasoning. See <kbd>docs/REALITY_MAP.md</kbd> for the federation protocol.</p>
  </div>
</section>

<section id="glossary">
  <div class="card md" id="glossbody" style="line-height:1.7"><p class="muted">loading…</p></div>
</section>

<section id="connect">
  <div class="card"><h3>Send an instruction to the live session</h3>
    <textarea id="ibox" placeholder="Exactly what you would type in the Claude Code session…"></textarea>
    <button class="act" onclick="sendInstr()">Send to session</button>
    <div id="i-msg"></div>
    <p class="muted">How it works: this appends one line to <kbd>ui/inbox.jsonl</kbd>.
    A Claude Code session that has armed its inbox watch (ask it: “watch the cockpit
    inbox”) receives each line as a live event and acts on it — same effect as typing
    there. If no session is watching, lines simply wait in the file.</p>
  </div>
  <div class="card"><h3>Other ways in</h3>
    <p class="muted" style="line-height:1.8">
    · Headless one-shot: <kbd>claude -p "your instruction"</kbd> from
    <kbd>F:\\tools\\meta-copilot</kbd> — a fresh session with repo context, prints the
    result, exits. This is what the suites themselves use as the LLM backend.<br>
    · Interactive: <kbd>claude</kbd> in the repo — the full experience this cockpit
    mirrors.<br>
    · Scheduled: the weekly grading loop already runs headless via the Windows task
    <kbd>meta-copilot-grading-loop</kbd> — no session needed.</p>
  </div>
</section>

<script>
const $ = s => document.querySelector(s);
/* Tab state lives in the URL hash, so refresh / back / forward / bookmarks all
   land where you were instead of dumping you on Home. */
const TABS = ['home','verdict','models','events','brainstorm','entities','map','tasks',
              'assess','glossary','connect','searchres'];
function showTab(id, push){
  if (!TABS.includes(id)) id = 'home';
  document.querySelectorAll('nav button').forEach(x =>
    x.classList.toggle('on', x.dataset.t === id));
  document.querySelectorAll('section').forEach(s =>
    s.classList.toggle('on', s.id === id));
  if (push && location.hash !== '#' + id){
    history.pushState({tab:id}, '', '#' + id);
  }
  document.title = 'Cockpit · ' + id.charAt(0).toUpperCase() + id.slice(1);
}
document.querySelectorAll('nav button').forEach(b =>
  b.onclick = () => showTab(b.dataset.t, true));

/* keyboard: / focuses search, g+<key> jumps, ? lists shortcuts, Esc leaves a field */
const GOTO = {h:'home', v:'verdict', m:'models', e:'events', b:'brainstorm', n:'entities',
              p:'map', t:'tasks', a:'assess', l:'glossary', c:'connect'};
let gPending = false;
document.addEventListener('keydown', ev => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  const capOpen = document.getElementById('capmodal').style.display !== 'none';
  if (ev.key === 'Escape'){
    if (capOpen){ closeCapture(); return; }
    if (typing){ document.activeElement.blur(); return; }
  }
  if (typing || capOpen) return;
  if (ev.key === 'c'){ ev.preventDefault(); openCapture(); return; }
  if (ev.key === '/'){ ev.preventDefault(); document.getElementById('gq').focus(); return; }
  if (ev.key === '?'){ ev.preventDefault(); showShortcuts(); return; }
  if (ev.key === 'g'){ gPending = true; setTimeout(()=>gPending=false, 900); return; }
  if (gPending && GOTO[ev.key]){ gPending = false; showTab(GOTO[ev.key], true); }
});
/* ---- VERDICT: "am I actually any good at this?" answered without flattery ---- */
async function loadVerdict(){
  let d;
  try { d = await (await fetch('/api/verdict')).json(); }
  catch(e){ $('#verdictbody').innerHTML = '<p class="muted">verdict unavailable</p>'; return; }
  const hits = d.earned + d.lucky;
  const pct = hits ? Math.round(100 * d.earned / hits) : null;
  let h = '';
  if (d.honest){
    h += `<div class="card" style="border-color:var(--base)">`+
      `<h3 style="color:var(--base)">Not answerable yet</h3>`+
      `<p class="muted">${esc(d.honest)}</p>`+
      `<p class="muted" style="font-size:.82rem">${d.open} claims are open and dated. `+
      `The first live grading is what turns this page into an answer.</p></div>`;
  }
  h += `<div class="card"><h3>Earned vs lucky</h3>`+
    `<p class="muted" style="font-size:.83rem">A hit only counts as <b>earned</b> if the `+
    `stated mechanism actually operated. Right-for-the-wrong-reason is <b>lucky</b> — `+
    `it feels identical from the inside, which is the whole reason to measure it.</p>`;
  if (hits){
    h += `<div style="display:flex;height:1.5rem;border-radius:6px;overflow:hidden;margin:.7rem 0">`+
      `<div style="width:${100*d.earned/hits}%;background:var(--acc)"></div>`+
      `<div style="width:${100*d.lucky/hits}%;background:var(--base)"></div></div>`+
      `<p class="meta"><b>${d.earned}</b> earned · <b>${d.lucky}</b> lucky · `+
      `${d.other} misses/other &nbsp;—&nbsp; <b>${pct}%</b> of hits were earned</p>`;
    if (pct !== null && pct < 50)
      h += `<p class="muted" style="font-size:.83rem;color:var(--warn)">Most hits so far were `+
        `right for the wrong reason. The honest hit rate is roughly half the naive one.</p>`;
  } else {
    h += `<p class="muted">no postmortems yet.</p>`;
  }
  h += `</div>`;

  if (d.miss_why && Object.keys(d.miss_why).length){
    const tot = Object.values(d.miss_why).reduce((a,b)=>a+b,0);
    h += `<div class="card"><h3>Why claims missed</h3><table>`+
      Object.entries(d.miss_why).sort((a,b)=>b[1]-a[1]).map(([k,v]) =>
        `<tr><td>${esc(k)}</td><td class="mono">${v}</td>`+
        `<td class="muted">${Math.round(100*v/tot)}%</td></tr>`).join('')+
      `</table><p class="muted" style="font-size:.8rem">mechanism = the theory was wrong; `+
      `calibration = right direction, wrong confidence; criteria = the claim was `+
      `unscoreable; information = we didn't know something knowable.</p></div>`;
  }

  const a = d.attribution || {};
  const at = (a.internal||0) + (a.canon||0) + (a.none||0);
  if (at){
    h += `<div class="card"><h3>Whose mechanism did reality use?</h3>`+
      `<p class="meta"><b>${a.internal}</b> our models · <b>${a.canon}</b> textbook `+
      `· <b>${a.none}</b> unexplained</p>`+
      `<p class="muted" style="font-size:.82rem">If textbook mechanisms consistently `+
      `out-attribute the fleet's own, the originals are vocabulary riding on canon.</p></div>`;
  }

  const pm = Object.entries(d.per_model || {}).sort((x,y)=>y[1].n - x[1].n);
  if (pm.length){
    h += `<div class="card"><h3>Per model (Brier — lower is better)</h3><table>`+
      `<tr><th>model</th><th>graded</th><th>brier</th><th>vs baseline</th></tr>`+
      pm.map(([m,s]) => {
        const beat = s.mean_baseline != null
          ? (s.mean_brier < s.mean_baseline
             ? '<span style="color:var(--accd)">beats baseline</span>'
             : '<span style="color:var(--miss)">worse than baseline</span>')
          : '<span class="muted">no baseline</span>';
        return `<tr><td>${esc(m)}</td><td>${s.n}</td><td class="mono">${s.mean_brier}</td>`+
               `<td>${beat}</td></tr>`;
      }).join('')+`</table>`+
      `<p class="muted" style="font-size:.8rem">${d.graded_total} graded rows `+
      `(${d.graded_live} live). Backtest rows test the machinery, not the judgment.</p></div>`;
  }
  $('#verdictbody').innerHTML = h;
  try { linkify(document.getElementById('verdict')); } catch(e){}
}

/* ---- CAPTURE: registering a claim must be the cheapest action in the app ---- */
async function openCapture(){
  const sel = document.getElementById('cap-repo');
  if (!sel.options.length){
    try {
      const ms = await (await fetch('/api/models')).json();
      sel.innerHTML = ms.map(m => `<option value="${esc(m.name)}">${esc(m.name)}</option>`).join('');
    } catch(e){}
  }
  if (!document.getElementById('cap-date').value){
    const d = new Date(); d.setMonth(d.getMonth() + 3);
    document.getElementById('cap-date').value = d.toISOString().slice(0, 10);
  }
  document.getElementById('capmodal').style.display = '';
  document.getElementById('cap-claim').focus();
}
function closeCapture(){ document.getElementById('capmodal').style.display = 'none'; }
async function submitCapture(){
  const msg = document.getElementById('cap-msg');
  msg.textContent = 'registering…';
  const body = {
    repo: document.getElementById('cap-repo').value,
    claim: document.getElementById('cap-claim').value,
    criteria: document.getElementById('cap-crit').value,
    resolve_by: document.getElementById('cap-date').value,
    confidence: document.getElementById('cap-conf').value,
    mechanism: document.getElementById('cap-mech').value,
  };
  let r;
  try { r = await (await fetch('/api/capture', {method:'POST', body: JSON.stringify(body)})).json(); }
  catch(e){ msg.textContent = 'failed: ' + e; return; }
  if (r.error){ msg.innerHTML = '<span style="color:var(--miss)">' + esc(r.error) + '</span>'; return; }
  msg.innerHTML = '<span style="color:var(--accd)">registered &mdash; ' +
    `<a href="/claim/${r.id}" style="color:var(--accd)">open the claim</a></span>`;
  ['cap-claim','cap-crit','cap-mech'].forEach(i => document.getElementById(i).value = '');
  loadHome();
}
function showShortcuts(){
  const rows = Object.entries(GOTO).map(([k,v]) =>
    `<tr><td class="mono">g ${k}</td><td class="muted">${v}</td></tr>`).join('');
  const el = document.getElementById('shortcuts');
  el.innerHTML = `<div class="card"><h3>Keyboard</h3><table>`+
    `<tr><td class="mono">/</td><td class="muted">focus search</td></tr>`+
    `<tr><td class="mono">?</td><td class="muted">this list</td></tr>`+
    `<tr><td class="mono">Esc</td><td class="muted">leave the field</td></tr>`+
    rows + `</table></div>`;
  el.style.display = el.style.display === 'none' ? '' : 'none';
}
window.addEventListener('popstate', () => {
  const h = location.hash.replace('#','');
  showTab(TABS.includes(h) ? h : 'home', false);
});
// glossary deep links (#g-slug) are handled by loadGloss; plain tab hashes here
(function(){
  const h = location.hash.replace('#','');
  if (h && !h.startsWith('g-')) showTab(h, false);
})();
const esc = t => { const d=document.createElement('div'); d.textContent=t; return d.innerHTML; };

const LEVEL_LABEL = {0:'Level 0 · models the world',
                     1:'Level 1 · models the fleet\\u2019s models',
                     2:'Level 2 · models the modelling process'};
async function loadModels(){
  const ms = await (await fetch('/api/models')).json();
  let levels = {};
  try {
    const mp = await (await fetch('/api/map')).json();
    (mp.cards||[]).forEach(c => levels[c.model] = c.level ?? 0);
  } catch(e){}
  const groups = {0:[],1:[],2:[]};
  ms.forEach(m => groups[levels[m.name] ?? 0].push(m));
  $('#mlist').innerHTML = [0,1,2].filter(l => groups[l].length).map(l =>
    `<h3 style="font-size:.85rem;color:var(--accd);margin:1.1rem 0 .3rem;`+
    `font-family:'IBM Plex Mono',monospace;letter-spacing:.06em">${LEVEL_LABEL[l]} `+
    `<span class="muted" style="font-weight:400">· ${groups[l].length}</span></h3>`+
    '<table><tr><th>model</th><th>kind</th><th>open</th>'+
    '<th>graded</th><th>discipline</th></tr>' + groups[l].map(m =>
    `<tr class="mrow" onclick="location.href='/model/${m.name}'"><td><b>${esc(m.name)}</b></td>`+
    `<td class="muted">${esc((m.kind||'').slice(0,60))}</td><td>${m.open}</td><td>${m.resolved}</td>`+
    `<td>${m.deletion_clause?'<span class="badge ok">deletion clause</span>':'<span class="badge warn">no clause</span>'}</td></tr>`
    ).join('') + '</table>'
  ).join('');
  linkify(document.getElementById('models'));
}
async function detail(name){
  const d = await (await fetch('/api/model/'+name)).json();
  $('#mdetail').innerHTML = `<div class="card"><h3>${esc(name)}</h3>`+
    `<pre>${esc(d.model_md)}</pre>`+
    (d.claims.length? `<h3>claims (${d.claims.length})</h3><pre>${esc(d.claims.map(c =>
      `[${c.status}] ${c.resolve_by||''}  ${c.claim}`).join('\\n\\n'))}</pre>`:'')+`</div>`;
  $('#mdetail').scrollIntoView({behavior:'smooth'});
}
async function createModel(){
  const r = await (await fetch('/api/models', {method:'POST', body: JSON.stringify({
    slug:$('#c-slug').value, title:$('#c-title').value, domain:$('#c-domain').value})})).json();
  $('#c-msg').innerHTML = r.error? `<p class="muted">✗ ${esc(r.error)}</p>`
    : `<p class="okmsg">✓ created ${esc(r.slug)} — ${esc(r.next)}</p>`;
  loadModels();
}
async function loadTasks(){
  const t = await (await fetch('/api/tasks')).json();
  $('#due').innerHTML = t.due.length ? t.due.map(x =>
    `<div class="task"><span class="k">${x.kind}</span>${esc(x.text)}`+
    `<span class="hint">${esc(x.hint||'')}</span></div>`).join('') :
    '<p class="muted">nothing due — the ledgers are quiet.</p>';
  $('#manual').innerHTML = t.manual.map((x,i) =>
    `<div class="task"><span class="k">${x.done?'done':'todo'}</span>`+
    `<span style="${x.done?'text-decoration:line-through;color:var(--sub)':''}">${esc(x.text)}</span>`+
    `<span class="hint"><a href="#" onclick="toggleTask(${i});return false" style="color:var(--accd)">toggle</a></span></div>`
  ).join('') || '<p class="muted">no tasks yet.</p>';
  linkify(document.getElementById('tasks'));
}
async function addTask(){
  await fetch('/api/tasks', {method:'POST', body: JSON.stringify({text:$('#t-text').value})});
  $('#t-text').value=''; loadTasks();
}
async function toggleTask(i){
  await fetch('/api/tasks/toggle', {method:'POST', body: JSON.stringify({i})}); loadTasks();
}
async function loadAssess(){
  const a = await (await fetch('/api/assessments')).json();
  $('#assessbody').innerHTML =
    `<div class="card"><h3>State</h3><p class="muted">${a.summary}</p></div>`+
    (a.scoreboard? `<div class="card"><h3>Attribution — which mechanisms does reality use?</h3><pre>${esc(a.scoreboard)}</pre></div>`:'')+
    (a.joins? `<div class="card"><h3>Classifier joins</h3><pre>${esc(a.joins)}</pre></div>`:'');
  linkify(document.getElementById('assess'));
}
/* ---- Home: what is late, what is next, what changed ---- */
async function loadHome(){
  let d;
  try { d = await (await fetch('/api/home')).json(); }
  catch(e){ $('#homebody').innerHTML = '<p class="muted">home unavailable</p>'; return; }
  const row = (x, cls) =>
    `<div class="task"><span class="k" style="min-width:5.6rem">${esc(x.resolve_by)}</span>`+
    `<span style="flex:1">${esc(x.claim)}</span>`+
    `<span class="hint">${esc(x.repo)}${x.confidence!=null?' · '+x.confidence:''}</span></div>`;
  let h = '';
  if (d.late.length){
    h += `<div class="card" style="border-color:var(--miss)">`+
      `<h3 style="color:var(--miss)">Past due — ${d.counts.late} claim(s) need grading</h3>`+
      `<p class="muted" style="font-size:.82rem">These resolve dates have passed. Grading them `+
      `is the pledge the ledger makes.</p>`+
      d.late.map(x=>row(x)).join('')+
      `<p class="muted" style="font-size:.8rem;margin-top:.5rem">`+
      `<kbd>python -m suites.grading_loop</kbd></p></div>`;
  } else {
    h += `<div class="card"><h3>Nothing past due</h3>`+
      `<p class="muted">Every open claim still has time on the clock.</p></div>`;
  }
  h += `<div class="card"><h3>Coming due (${d.counts.horizon} open)</h3>`+
    (d.horizon.length ? d.horizon.map(x=>row(x)).join('')
                      : '<p class="muted">no dated claims open.</p>')+`</div>`;
  h += `<div class="card"><h3>Recent activity</h3>`+
    (d.recent.length ? d.recent.map(r =>
      `<div class="task"><span class="k" style="min-width:5.6rem">${esc(r.date)}</span>`+
      `<span style="flex:1">${esc(r.msg)}</span>`+
      `<span class="hint">${esc(r.repo)}</span></div>`).join('')
      : '<p class="muted">no recent commits found.</p>')+`</div>`;
  h += `<div class="card"><h3>Run a pass</h3>`+
    `<p class="muted" style="font-size:.82rem">Triggers the same suites the CLI runs, `+
    `in the background. Output streams below.</p>`+
    `<div style="display:flex;gap:.4rem;flex-wrap:wrap;margin:.5rem 0">`+
    [['grade','Grade due claims'],['attribute','Attribute outcomes'],
     ['calibrate','Recalibrate'],['memory','Reindex memory'],
     ['entities','Rebuild dossiers'],['mindmap','Rebuild mindmap'],
     ['map','Rebuild map'],['sleep','Dependency report']].map(([a,label]) =>
      `<button class="act" style="font-size:.78rem;padding:.4rem .8rem;background:var(--panel);`+
      `color:var(--accd);border:1px solid var(--acc)" onclick="runAction('${a}',this)">`+
      `${label}</button>`).join('')+
    `</div><pre id="runlog" style="display:none;max-height:18rem"></pre></div>`;
  $('#homebody').innerHTML = h;
  try { linkify(document.getElementById('home')); } catch(e){}
}

let runPoll = null;
async function runAction(act, btn){
  const prev = btn.textContent;
  btn.textContent = 'running…'; btn.disabled = true;
  const log = document.getElementById('runlog');
  log.style.display = '';
  log.textContent = 'starting ' + act + '…';
  try { await fetch('/api/run', {method:'POST', body: JSON.stringify({action: act})}); }
  catch(e){ log.textContent = 'failed to start: ' + e; btn.textContent = prev;
            btn.disabled = false; return; }
  if (runPoll) clearInterval(runPoll);
  let ticks = 0;
  runPoll = setInterval(async () => {
    ticks++;
    try {
      const d = await (await fetch('/api/runlog/' + act)).json();
      log.textContent = d.log;
      log.scrollTop = log.scrollHeight;
    } catch(e){}
    if (ticks > 240){ clearInterval(runPoll); }
  }, 2500);
  setTimeout(() => { btn.textContent = prev; btn.disabled = false; }, 4000);
}

/* ---- global semantic search over the memory index ---- */
async function doSearch(){
  const q = document.getElementById('gq').value.trim();
  if (!q) return;
  showTab('searchres', true);
  $('#sres').innerHTML = '<p class="muted">searching…</p>';
  let hits;
  try { hits = await (await fetch('/api/search?q='+encodeURIComponent(q))).json(); }
  catch(e){ $('#sres').innerHTML = '<p class="muted">search failed</p>'; return; }
  if (hits.error){ $('#sres').innerHTML = '<p class="muted">'+esc(hits.error)+'</p>'; return; }
  if (!hits.length){ $('#sres').innerHTML = '<p class="muted">nothing found for “'+esc(q)+'”</p>'; return; }
  $('#sres').innerHTML = `<p class="muted" style="font-size:.82rem">`+
    `${hits.length} fragments for “${esc(q)}” — ranked by meaning, not keywords`+
    `${hits.some(h=>h.hop) ? ' (dotted = reached by association)' : ''}</p>`+
    hits.map(h =>
    `<div class="claim"${h.hop?' style="border-style:dashed"':''}>`+
    `<div class="chead"><span class="mono">${h.score}</span>`+
    `<span class="badge" style="background:transparent;border:1px solid var(--line);`+
    `color:var(--sub)">${esc(h.kind)}</span>`+
    `<span style="cursor:pointer;color:var(--accd)" onclick="location.href='/model/${esc(h.repo)}'">`+
    `${esc(h.repo)}</span>${h.hop?'<span class="muted">via '+esc(h.via||'')+'</span>':''}</div>`+
    `<div style="font-size:.87rem;color:var(--sub);line-height:1.6">${esc(h.text)}</div></div>`).join('');
}

const CONF_COLOR = { substantial:'var(--acc)', moderate:'var(--base)', thin:'var(--sub)' };
const KIND_COLOR = { company:'#4fc3a1', market:'#d4b45a', nation:'#7aa7e0',
                     institution:'#c08fd8', person:'#e0805a' };
/* ---- 3D force graph: 185 edges are unreadable on a plane but separable in space ---- */
let MM = null, mmRot = {x:-0.35, y:0.6}, mmZoom = 1, mmTimer = null, mmDrag = null;
const MM_W = 780, MM_H = 520;

function mmSimulate(nodes, edges){
  // 3D spring-electrical layout: repulsion between all nodes, springs along edges,
  // mild centring. Deterministic seed so the picture is stable between reloads.
  let seed = 42;
  const rnd = () => (seed = (seed*1103515245 + 12345) & 0x7fffffff) / 0x7fffffff - 0.5;
  nodes.forEach(n => { n.x = rnd()*260; n.y = rnd()*260; n.z = rnd()*260;
                       n.vx = n.vy = n.vz = 0; });
  const byId = {}; nodes.forEach(n => byId[n.id] = n);
  for (let step = 0; step < 320; step++){
    const cool = 1 - step/320;
    for (let i=0;i<nodes.length;i++) for (let j=i+1;j<nodes.length;j++){
      const a=nodes[i], b=nodes[j];
      let dx=a.x-b.x, dy=a.y-b.y, dz=a.z-b.z;
      let d2 = dx*dx+dy*dy+dz*dz + 0.01;
      const f = 26000 / d2;            // repulsion
      const d = Math.sqrt(d2);
      dx/=d; dy/=d; dz/=d;
      a.vx+=dx*f; a.vy+=dy*f; a.vz+=dz*f;
      b.vx-=dx*f; b.vy-=dy*f; b.vz-=dz*f;
    }
    edges.forEach(e => {
      const a=byId[e.a], b=byId[e.b];
      if(!a||!b) return;
      const dx=b.x-a.x, dy=b.y-a.y, dz=b.z-a.z;
      const d = Math.sqrt(dx*dx+dy*dy+dz*dz)+0.01;
      const rest = 150 - 90*Math.min(e.weight,1);   // stronger edge = shorter spring
      const f = (d-rest) * 0.012 * (0.35 + e.weight);
      a.vx+=dx/d*f; a.vy+=dy/d*f; a.vz+=dz/d*f;
      b.vx-=dx/d*f; b.vy-=dy/d*f; b.vz-=dz/d*f;
    });
    nodes.forEach(n => {
      n.vx -= n.x*0.004; n.vy -= n.y*0.004; n.vz -= n.z*0.004;   // centring
      n.x += n.vx*cool*0.5; n.y += n.vy*cool*0.5; n.z += n.vz*cool*0.5;
      n.vx*=0.82; n.vy*=0.82; n.vz*=0.82;
    });
  }
}

function mmProject(n){
  const cy=Math.cos(mmRot.y), sy=Math.sin(mmRot.y);
  const cx=Math.cos(mmRot.x), sx=Math.sin(mmRot.x);
  let x = n.x*cy - n.z*sy;
  let z = n.x*sy + n.z*cy;
  let y = n.y*cx - z*sx;
  z = n.y*sx + z*cx;
  const persp = 620 / (620 + z);          // depth: nearer = larger and brighter
  return { px: MM_W/2 + x*persp*mmZoom, py: MM_H/2 + y*persp*mmZoom, depth: persp };
}

function mmRender(){
  if (!MM) return;
  const thr = MM.threshold;
  const edges = MM.edges.filter(e => e.weight >= thr);
  const live = new Set(); edges.forEach(e => { live.add(e.a); live.add(e.b); });
  const nodes = MM.nodes.filter(n => live.has(n.id) || MM.showAll);
  const P = {}; MM.nodes.forEach(n => P[n.id] = mmProject(n));
  let svg = `<svg viewBox="0 0 ${MM_W} ${MM_H}" style="width:100%;height:auto;display:block;`+
    `cursor:grab" id="mmsvg">`;
  // paint far-to-near so nearer elements overlap correctly
  edges.slice().sort((a,b) => (P[a.a].depth+P[a.b].depth) - (P[b.a].depth+P[b.b].depth))
    .forEach(e => {
      const p=P[e.a], q=P[e.b]; if(!p||!q) return;
      const dep = (p.depth+q.depth)/2;
      const t = Math.min(e.weight/0.6, 1);
      svg += `<line x1="${p.px.toFixed(1)}" y1="${p.py.toFixed(1)}" x2="${q.px.toFixed(1)}" `+
        `y2="${q.py.toFixed(1)}" stroke="var(--acc)" stroke-width="${(0.4+t*2.2*dep).toFixed(2)}" `+
        `opacity="${(0.06+t*0.4*dep*dep).toFixed(3)}"><title>${esc(e.a)} — ${esc(e.b)}: `+
        `${e.weight}\n${esc(e.why||'')}</title></line>`;
    });
  nodes.slice().sort((a,b) => P[a.id].depth - P[b.id].depth).forEach(n => {
    const p = P[n.id];
    const r = (5 + Math.min(n.fragments,100)/9) * p.depth * mmZoom;
    const col = KIND_COLOR[n.kind] || 'var(--sub)';
    svg += `<circle cx="${p.px.toFixed(1)}" cy="${p.py.toFixed(1)}" r="${r.toFixed(1)}" `+
      `fill="${col}" opacity="${(0.35+p.depth*0.5).toFixed(2)}" style="cursor:pointer" `+
      `onclick="entDetail('${n.id}')"><title>${esc(n.name)} (${esc(n.kind)}) · `+
      `${n.fragments} fragments · ${n.repos.length} repos</title></circle>`;
    if (n.fragments >= 14 || p.depth > 1.02)
      svg += `<text x="${p.px.toFixed(1)}" y="${(p.py - r - 4).toFixed(1)}" `+
        `text-anchor="middle" style="font-size:${(9.5*p.depth).toFixed(1)}px;`+
        `fill:var(--ink);opacity:${(p.depth-0.55).toFixed(2)};pointer-events:none">`+
        `${esc(n.name.length>22?n.name.slice(0,21)+'…':n.name)}</text>`;
  });
  svg += '</svg>';
  const legend = Object.entries(KIND_COLOR).map(([k,c]) =>
    `<span style="margin-right:.7rem"><span style="display:inline-block;width:.65rem;`+
    `height:.65rem;border-radius:50%;background:${c};vertical-align:-.05rem"></span> ${k}</span>`).join('');
  $('#mmbody').innerHTML = svg +
    `<p class="muted" style="font-size:.75rem;margin-top:.4rem">${legend}</p>`+
    `<p class="muted" style="font-size:.75rem">${nodes.length} nodes · ${edges.length} of `+
    `${MM.edges.length} edges shown · size = fragments · depth = distance</p>`;
  mmBindDrag();
}

function mmBindDrag(){
  const svg = document.getElementById('mmsvg');
  if (!svg) return;
  svg.onmousedown = e => { mmDrag = {x:e.clientX, y:e.clientY}; svg.style.cursor='grabbing'; };
  window.onmouseup = () => { mmDrag = null; const s=document.getElementById('mmsvg');
                             if(s) s.style.cursor='grab'; };
  window.onmousemove = e => {
    if (!mmDrag) return;
    mmRot.y += (e.clientX - mmDrag.x) * 0.008;
    mmRot.x += (e.clientY - mmDrag.y) * 0.008;
    mmDrag = {x:e.clientX, y:e.clientY};
    mmRender();
  };
  svg.onwheel = e => { e.preventDefault();
    mmZoom = Math.max(0.4, Math.min(2.6, mmZoom * (e.deltaY>0 ? 0.92 : 1.08)));
    mmRender(); };
}

function mmFilter(){
  if (!MM) return;
  const pct = +document.getElementById('mmw').value;
  const ws = MM.edges.map(e=>e.weight).sort((a,b)=>b-a);
  const idx = Math.min(ws.length-1, Math.floor(ws.length * (1 - pct/100)));
  MM.threshold = ws.length ? ws[idx] : 0;
  document.getElementById('mmwval').textContent = MM.threshold.toFixed(3);
  mmRender();
}

function mmSpin(){
  const on = document.getElementById('mmspin').checked;
  if (mmTimer){ clearInterval(mmTimer); mmTimer = null; }
  if (on) mmTimer = setInterval(() => {
    if (document.hidden || mmDrag) return;
    mmRot.y += 0.004; mmRender();
  }, 60);
}

async function loadMindmap(){
  let d;
  try { d = await (await fetch('/api/mindmap')).json(); }
  catch(e){ $('#mmbody').innerHTML = '<p class="muted">mindmap unavailable</p>'; return; }
  if (d.error){ $('#mmbody').innerHTML = '<p class="muted">'+esc(d.error)+'</p>'; return; }
  MM = d; MM.showAll = false;
  mmSimulate(MM.nodes, MM.edges);
  mmFilter();
  mmSpin();
}
async function loadEntities(){
  let es;
  try {
    es = await (await fetch('/api/entities')).json();
  } catch(err) {
    $('#elist').innerHTML = '<p class="muted">could not load entities: '+esc(String(err))+'</p>';
    return;
  }
  if (!Array.isArray(es) || !es.length){
    $('#elist').innerHTML = '<p class="muted">no dossiers yet — run '+
      '<kbd>python -m suites.entities --build</kbd></p>';
    return;
  }
  try {
  $('#elist').innerHTML = '<table><tr><th>entity</th><th>kind</th><th>claims</th>'+
    '<th>graded</th><th>lenses</th><th>attrib</th><th>models</th><th>confidence</th></tr>'+
    es.map(e => {
      const c = (e.synthesis||{}).confidence;
      return `<tr class="mrow" onclick="entDetail('${e.slug}')"><td><b>${esc(e.name)}</b></td>`+
      `<td class="muted">${esc(e.kind)}</td><td>${e.stats.claims}</td>`+
      `<td>${e.stats.graded}</td><td>${e.stats.lenses}</td>`+
      `<td>${e.stats.attributions}</td><td>${e.stats.models_touching.length}</td>`+
      `<td>${c?`<span class="badge" style="border-color:${CONF_COLOR[c]||'var(--line)'};`+
        `color:${CONF_COLOR[c]||'var(--sub)'}">${esc(c)}</span>`:'<span class="muted">—</span>'}</td></tr>`;
    }).join('') + '</table>';
  } catch(err) {
    $('#elist').innerHTML = '<p class="muted">render failed: '+esc(String(err))+'</p>';
    return;
  }
  try { linkify(document.getElementById('entities')); } catch(e) {}
}
async function entDetail(slug){
  const d = await (await fetch('/api/entity/'+slug)).json();
  const s = d.synthesis || {}, ev = d.evidence || {}, st = d.stats;
  const list = (arr, cls) => (arr||[]).map(x=>`<li style="margin:.3rem 0 .3rem 1.1rem;`+
    `color:var(--sub);font-size:.88rem">${esc(x)}</li>`).join('');
  let h = `<div class="card"><h3>${esc(d.name)} <span class="muted" style="font-weight:400">`+
    `· ${esc(d.kind)} · built ${esc(d.built)}</span></h3>`;
  h += `<p class="muted" style="font-size:.85rem">${st.claims} claims (${st.open} open, `+
    `${st.graded} graded, ${st.hits} hits) · ${st.lenses} lens reads · `+
    `${st.registrations} blind-spot regs · ${st.attributions} attributions · `+
    `${st.studies} studies · touched by ${st.models_touching.length} models</p>`;
  if (s.understanding){
    h += `<h3 style="font-size:.95rem;margin-top:.9rem">What we have understood `+
      `<span class="badge" style="border-color:${CONF_COLOR[s.confidence]||'var(--line)'};`+
      `color:${CONF_COLOR[s.confidence]||'var(--sub)'}">${esc(s.confidence||'?')}</span></h3>`+
      `<ul>${list(s.understanding)}</ul>`+
      `<p class="muted" style="font-size:.8rem">${esc(s.confidence_why||'')}</p>`;
    if (s.mechanisms) h += `<h3 style="font-size:.95rem">Mechanisms shown</h3><ul>${list(s.mechanisms)}</ul>`;
    if (s.open_questions) h += `<h3 style="font-size:.95rem">Open bets</h3><ul>${list(s.open_questions)}</ul>`;
    if (s.blind_spots) h += `<h3 style="font-size:.95rem;color:var(--warn)">Nobody modeled this</h3>`+
      `<ul>${list(s.blind_spots)}</ul>`;
  } else {
    h += `<p class="muted">No synthesis yet — run <kbd>python -m suites.entities `+
      `--synthesize ${esc(slug)}</kbd> or ask the session via Connect.</p>`;
  }
  if ((ev.claims||[]).length){
    h += `<h3 style="font-size:.95rem;margin-top:1rem">Claims mentioning ${esc(d.name)}</h3>`+
      (ev.claims.slice(0,25).map(c =>
      `<div class="claim"><div class="chead"><span class="badge ${esc(c.status)}">${esc(c.status)}</span>`+
      `<span>${esc(c.model)}</span><span>by ${esc(c.resolve_by||'?')}</span>`+
      (c.confidence!=null?`<span>conf ${c.confidence}</span>`:'')+`</div>`+
      `<div class="ctext" style="font-weight:400;font-size:.88rem">${esc(c.claim)}</div>`+
      (c.what_happened?`<div class="cmeta"><b>what happened:</b> ${esc(c.what_happened)}</div>`:'')+
      `</div>`).join(''));
  }
  if ((ev.lenses||[]).length){
    h += `<h3 style="font-size:.95rem;margin-top:1rem">Lens reads</h3>`+
      ev.lenses.slice(0,12).map(l =>
      `<div class="claim"><div class="chead"><span>${esc(l.model)}</span>`+
      `<span>grip: ${esc(l.grip)}</span><span>${esc(l.brainstorm)}</span></div>`+
      `<div style="font-size:.87rem;color:var(--sub)">${esc(l.read)}</div></div>`).join('');
  }
  if ((ev.registrations||[]).length){
    h += `<h3 style="font-size:.95rem;margin-top:1rem">Registered blind spots</h3>`+
      ev.registrations.map(r =>
      `<div class="claim"><div class="chead"><span>${esc(r.case)}</span>`+
      `<span>resolves ${esc(r.resolve_by||'?')}</span></div>`+
      `<ul>${list(r.blindspots)}</ul></div>`).join('');
  }
  h += '</div>';
  $('#edetail').innerHTML = h;
  linkify(document.getElementById('edetail'));
  $('#edetail').scrollIntoView({behavior:'smooth'});
}
const TIER_COLOR = { attributed:'#4fc3a1', graded:'#83dfc3', registered:'#3d6b5e',
                     declared:'#2a323c' };
async function loadMap(){
  const m = await (await fetch('/api/map')).json();
  if (m.error){ $('#mapbody').innerHTML = '<p class="muted">'+esc(m.error)+'</p>'; return; }
  const pj = m.projection || {};
  $('#mapproj').innerHTML = `Rendered under projection <b style="color:var(--accd)">${esc(pj.id)}.v${pj.version}</b> `+
    `(${esc(pj.status)}) — the mapping model is itself a model: versioned, adequacy-graded, `+
    `replaceable by a challenger under the succession rule. Adequacy: ${esc(pj.adequacy_graded||'ungraded')}.`;
  $('#maplegend').innerHTML = Object.entries(TIER_COLOR).map(([t,c]) =>
    `<span><span style="display:inline-block;width:.8rem;height:.8rem;background:${c};`+
    `border-radius:2px;vertical-align:-.1rem"></span> ${t}</span>`).join('') +
    `<span><span style="display:inline-block;width:.8rem;height:.8rem;border:1px dashed var(--base);`+
    `border-radius:2px;vertical-align:-.1rem"></span> canon (external)</span>`;
  const byAspect = {};
  m.cards.forEach(c => c.aspects.forEach(a => (byAspect[a] = byAspect[a]||[]).push(c)));
  const scale = e => (e/14*100);
  $('#mapbody').innerHTML =
    `<div style="display:flex;font-family:'IBM Plex Mono',monospace;font-size:.62rem;color:var(--sub);`+
    `margin:0 0 .3rem 11rem;justify-content:space-between"><span>E0</span><span>E4</span>`+
    `<span>E8</span><span>E9</span><span>E12</span><span>E14</span></div>` +
    m.aspects.map(a => {
      const cs = (byAspect[a]||[]);
      const bars = cs.map(c => {
        const l = scale(c.e_span[0]), w = Math.max(scale(c.e_span[1]) - l, 2.5);
        const canon = c.kind === 'canon';
        const col = TIER_COLOR[c.tier] || '#2a323c';
        const refuted = c.record.refuted > 2;
        return `<div title="${esc(c.model)} · E${c.e_span[0]}–E${c.e_span[1]} · ${esc(c.tier)}`+
          ` · open ${c.record.open}, graded ${c.record.graded}${refuted?' · refutations logged':''}\n${esc(c.mechanism)}"`+
          ` onclick="location.href='/model/${canon?'canon':c.model}'"`+
          ` style="position:relative;height:.85rem;margin:.15rem 0;cursor:pointer">`+
          `<div style="position:absolute;left:${l}%;width:${w}%;height:100%;border-radius:3px;`+
          `background:${canon?'transparent':col};border:1px ${canon?'dashed var(--base)':'solid transparent'};`+
          `${refuted?'box-shadow:inset 0 0 0 1px var(--miss);':''}"'></div>`+
          `<span style="position:absolute;left:${l}%;margin-left:.2rem;font-size:.6rem;`+
          `font-family:'IBM Plex Mono',monospace;color:var(--ink);line-height:.9rem;`+
          `white-space:nowrap;pointer-events:none">${esc(c.model)}</span></div>`;
      }).join('');
      return `<div style="display:flex;align-items:flex-start;border-top:1px solid var(--line);padding:.35rem 0">`+
        `<div style="width:11rem;flex:none;font-size:.75rem;color:var(--sub);padding-top:.2rem">${esc(a)}`+
        `${cs.length?'':' <span style="color:var(--flag)">· EMPTY</span>'}</div>`+
        `<div style="flex:1;position:relative">`+
        `<div style="position:absolute;left:${scale(8.5)}%;top:0;bottom:0;border-left:1px dashed var(--line)"></div>`+
        (bars||'<div style="height:.9rem"></div>')+`</div></div>`;
    }).join('');
  const cov = m.coverage;
  $('#mapgaps').innerHTML =
    `<b style="color:var(--ink)">${cov.cells_covered}/${cov.cells_total}</b> aspect×floor cells covered · `+
    `empty floors: <b style="color:var(--flag)">${cov.empty_floors.join(', ')||'none'}</b>`+
    (cov.empty_aspects.length?` · empty aspects: <b style="color:var(--flag)">${cov.empty_aspects.join(', ')}</b>`:'')+
    ` — every gap is a standing invitation.`;
}
let bsModels = new Set();
async function loadBrainstorm(){
  if (!$('#b-models').innerHTML){
    const ms = await (await fetch('/api/models')).json();
    $('#b-models').innerHTML = ms.map(m =>
      `<span class="badge${bsModels.has(m.name)?' ok':''}" style="cursor:pointer" `+
      `onclick="toggleBsModel('${m.name}',this)">${esc(m.name)}</span>`).join('') +
      `<span class="badge" style="border-color:var(--miss);color:var(--miss)" title="mandatory">devils-advocate (always on)</span>`;
  }
  const bs = await (await fetch('/api/brainstorms')).json();
  if (bsExpanded === null){          // first paint: open the newest finished result
    bsExpanded = new Set();
    const newest = bs.find(x => x.status !== 'queued');
    if (newest) bsExpanded.add(newest.id);
  }
  $('#blist').innerHTML = bs.length ? bs.map(b =>
    b.status === 'queued' ?
    `<div class="claim" style="border-style:dashed"><div class="chead" style="font-family:'IBM Plex Mono',monospace;`+
    `font-size:.72rem;color:var(--sub);display:flex;gap:.7rem;flex-wrap:wrap">`+
    `<span class="badge" style="background:var(--base);animation:pulse 1.4s ease-in-out infinite">running</span>`+
    `<span>${esc(b.id)}</span><span>${esc(b.models.join(' + '))}</span></div>`+
    `<div class="ctext" style="font-weight:400;font-size:.88rem">${esc(b.event)}</div>`+
    `<div class="muted" style="font-size:.8rem;margin-top:.3rem">lenses + adversary + synthesis in progress — `+
    `this card updates itself when the result lands.</div></div>` :
    `<div class="claim"><div class="chead" style="font-family:'IBM Plex Mono',monospace;`+
    `font-size:.72rem;color:var(--sub);display:flex;gap:.7rem;flex-wrap:wrap">`+
    `<span>${esc(b.id)}</span><span>${esc(b.models.join(' + '))}</span></div>`+
    `<div class="ctext" style="font-weight:400;font-size:.88rem">${esc(b.event)}</div>`+
    `<details style="margin-top:.4rem" data-bs="${esc(b.id)}"${bsOpen(b.id)?' open':''} `+
    `ontoggle="bsRemember('${b.id}', this.open)">`+
    `<summary class="muted" style="cursor:pointer">full synthesis</summary>`+
    `<pre style="margin-top:.5rem">${esc(b.md)}</pre></details>`+
    `<div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.6rem">`+
    `<button class="act" style="font-size:.78rem;padding:.4rem .8rem" onclick="bsAct('${b.id}','register',this)">Register joint claims</button>`+
    `<button class="act" style="font-size:.78rem;padding:.4rem .8rem;background:var(--panel);color:var(--accd);border:1px solid var(--acc)" onclick="bsAct('${b.id}','seed',this)">Seed candidate model</button>`+
    `<button class="act" style="font-size:.78rem;padding:.4rem .8rem;background:var(--panel);color:var(--sub);border:1px solid var(--line)" onclick="bsAct('${b.id}','deciders',this)">Track deciders as tasks</button>`+
    `<span class="muted" id="bsact-${b.id}"></span></div></div>`).join('')
    : '<p class="muted">none yet — pick an event and 2+ lenses above.</p>';
  linkify(document.getElementById('brainstorm'));
}
/* the 6s poll re-renders the list, which destroys <details> elements and slams
   open synthesis shut — remember expansion state across renders instead */
let bsExpanded = null;          // null until first render: newest card defaults open
function bsOpen(id){
  if (bsExpanded === null) return false;
  return bsExpanded.has(id);
}
function bsRemember(id, open){
  if (bsExpanded === null) bsExpanded = new Set();
  open ? bsExpanded.add(id) : bsExpanded.delete(id);
}
function toggleBsModel(n, el){
  bsModels.has(n) ? bsModels.delete(n) : bsModels.add(n);
  el.classList.toggle('ok', bsModels.has(n));
}
async function bsAct(id, action, btn){
  btn.disabled = true;
  const r = await (await fetch('/api/brainstorm/act', {method:'POST',
    body: JSON.stringify({id, action})})).json();
  document.getElementById('bsact-'+id).textContent =
    r.error ? ('✗ ' + r.error) : ('✓ ' + r.msg);
  btn.disabled = false;
  loadTasks();
}
async function startBrainstorm(){
  const r = await (await fetch('/api/brainstorm', {method:'POST', body: JSON.stringify({
    event:$('#b-event').value, models:[...bsModels]})})).json();
  $('#b-msg').innerHTML = r.error? `<p class="muted">✗ ${esc(r.error)}</p>`
    : '<p class="okmsg">✓ queued — the watching session runs the lenses and synthesis; refresh this tab for the result.</p>';
}
let evModels = new Set();
async function loadEvents(){
  if (!$('#e-models').innerHTML){
  const ms = await (await fetch('/api/models')).json();
  $('#e-models').innerHTML = ms.map(m =>
    `<span class="badge${evModels.has(m.name)?' ok':''}" style="cursor:pointer" `+
    `onclick="toggleEvModel('${m.name}',this)">${esc(m.name)}</span>`).join('');
  }
  const evs = await (await fetch('/api/events')).json();
  $('#elist').innerHTML = evs.length ? evs.map(e =>
    `<div class="claim"><div class="chead" style="display:flex;gap:.7rem;flex-wrap:wrap;`+
    `font-family:'IBM Plex Mono',monospace;font-size:.72rem;color:var(--sub)">`+
    `<span class="badge ${e.status==='queued'?'':'ok'}">${esc(e.status)}</span>`+
    `<span>${esc(e.id)}</span><span>${esc(e.source_type)}</span>`+
    `<span>${esc((e.models||[]).join(', ')||'session picks')}</span></div>`+
    (e.source?`<div class="cmeta" style="font-size:.82rem;word-break:break-all">`+
      `<a href="${esc(e.source)}" style="color:var(--accd)">${esc(e.source)}</a></div>`:'')+
    (e.note?`<div class="ctext" style="font-weight:400;font-size:.88rem">${esc(e.note)}</div>`:'')+
    (e.assessment?`<div class="cmeta" style="border-top:1px solid var(--line);margin-top:.5rem;`+
      `padding-top:.5rem;white-space:pre-wrap"><b>assessment:</b> ${esc(e.assessment)}</div>`:'')+
    `</div>`).join('') : '<p class="muted">no events yet.</p>';
  linkify(document.getElementById('events'));
}
function toggleEvModel(n, el){
  evModels.has(n) ? evModels.delete(n) : evModels.add(n);
  el.classList.toggle('ok', evModels.has(n));
}
async function addEvent(){
  const r = await (await fetch('/api/events', {method:'POST', body: JSON.stringify({
    source:$('#e-src').value, note:$('#e-note').value, models:[...evModels]})})).json();
  $('#e-msg').innerHTML = r.error? `<p class="muted">✗ ${esc(r.error)}</p>`
    : `<p class="okmsg">✓ ${esc(r.id)} queued and forwarded to the session</p>`;
  $('#e-src').value=''; $('#e-note').value=''; evModels.clear(); loadEvents();
}
async function sendInstr(){
  const text = $('#ibox').value.trim(); if(!text) return;
  await fetch('/api/inbox', {method:'POST', body: JSON.stringify({text})});
  $('#i-msg').innerHTML = '<p class="okmsg">✓ queued for the session (inbox.jsonl)</p>';
  $('#ibox').value='';
}
/* --- glossary linkifier: dotted terms with hover definitions, click -> entry --- */
let GTERMS = [], GRE = null;
function buildTermIndex(terms){
  GTERMS = [];
  const byAlias = {};
  terms.forEach(t => t.aliases.forEach(a => { byAlias[a.toLowerCase()] = t; }));
  const aliases = Object.keys(byAlias).sort((a,b)=>b.length-a.length);
  if (!aliases.length) return;
  GRE = new RegExp('\\\\b(' + aliases.map(a =>
    a.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&')).join('|') + ')\\\\b','gi');
  GTERMS = byAlias;
}
function linkify(root){
  if (!GRE || !root) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.parentElement && !n.parentElement.closest('a,script,style,nav,button,h1,h2,h3,.term,input,textarea,#glossbody'))
      ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
  const nodes = []; let n;
  while ((n = walker.nextNode())) nodes.push(n);
  nodes.forEach(node => {
    const text = node.nodeValue;
    GRE.lastIndex = 0;
    if (!GRE.test(text)) return;
    GRE.lastIndex = 0;
    const frag = document.createDocumentFragment();
    let last = 0, m, seen = new Set();
    while ((m = GRE.exec(text))) {
      const t = GTERMS[m[1].toLowerCase()];
      if (!t || seen.has(t.slug)) continue;      // first occurrence per node only
      seen.add(t.slug);
      frag.appendChild(document.createTextNode(text.slice(last, m.index)));
      const s = document.createElement('span');
      s.className = 'term'; s.textContent = m[1];
      s.setAttribute('data-def', t.term + ' — ' + t.def);
      s.onclick = () => openGloss(t.slug);
      frag.appendChild(s);
      last = m.index + m[1].length;
    }
    frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode.replaceChild(frag, node);
  });
}
function openGloss(slug){
  showTab('glossary', false);
  if (location.hash !== '#' + slug) history.pushState({tab:'glossary'}, '', '#' + slug);
  const el = document.getElementById(slug);
  if (el){ el.scrollIntoView({behavior:'smooth', block:'center'});
           el.classList.remove('ghl'); void el.offsetWidth; el.classList.add('ghl'); }
}
function gslug(t){ return 'g-'+t.toLowerCase().replace(/[^a-z0-9]+/g,'-')
  .replace(/^-+|-+$/g,'').slice(0,50); }
function mdlite(t){
  let h = esc(t);
  h = h.replace(/^- \\*\\*(.+?)\\*\\*/gm, (mm,term) =>
        '<li id="'+gslug(term)+'" style="margin:.4em 0 .4em 1.1em;color:var(--sub);'+
        'font-size:.9rem"><strong style="color:var(--ink)">'+term+'</strong>')
       .replace(/^### (.*)$/gm,'<h3 style="margin:1em 0 .4em">$1</h3>')
       .replace(/^## (.*)$/gm,'<h3 style="margin:1.4em 0 .5em;color:var(--accd);font-size:1.02rem">$1</h3>')
       .replace(/^# (.*)$/gm,'<h2 style="border:none;text-transform:none;letter-spacing:0;font-family:inherit;font-size:1.2rem;color:var(--ink)">$1</h2>')
       .replace(/\\*\\*([^*]+)\\*\\*/g,'<strong style="color:var(--ink)">$1</strong>')
       .replace(/^- (.*)$/gm,'<li style="margin:.35em 0 .35em 1.1em;color:var(--sub);font-size:.9rem">$1</li>');
  return h.split(/\\n{2,}/).map(b =>
    /^<h|^<li/.test(b.trim()) ? b : '<p class="muted" style="margin:.4em 0">'+b.replace(/\\n/g,' ')+'</p>').join('\\n');
}
function relinkAll(){
  ['models','events','tasks','assess','connect'].forEach(id =>
    linkify(document.getElementById(id)));
}
async function loadGloss(){
  const g = await (await fetch('/api/glossary')).json();
  $('#glossbody').innerHTML = mdlite(g.text);
  buildTermIndex(g.terms||[]);
  relinkAll();
  if (location.hash.startsWith('#g-')) setTimeout(()=>openGloss(location.hash.slice(1)), 250);
}
loadHome(); loadVerdict(); loadModels(); loadTasks(); loadAssess(); loadEvents(); loadGloss(); loadBrainstorm(); loadMap();
loadEntities(); loadMindmap();
// live delivery: poll for queued work flipping to results (skip when tab hidden)
let pollBusy = false;
setInterval(async () => {
  if (document.hidden || pollBusy) return;
  pollBusy = true;
  try { await loadBrainstorm(); await loadEvents(); } finally { pollBusy = false; }
}, 6000);
</script>
</main></body></html>"""


CLAIM_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claim — Cockpit</title>
<style>
:root { --bg:#0c1014; --panel:#141a21; --ink:#e9e7e2; --sub:#95a0ac; --line:#242d38;
        --acc:#4fc3a1; --accd:#83dfc3; --warn:#e08050; --miss:#e0705c; --base:#d4b45a; }
* { box-sizing:border-box; margin:0; }
body { background:var(--bg); color:var(--ink); font:15px/1.65 "IBM Plex Sans",system-ui,sans-serif;
       padding:1.5rem 1rem 4rem; }
main { max-width:50rem; margin:0 auto; }
a.back { color:var(--accd); text-decoration:none; font-size:.85rem; }
h1 { font-size:1.25rem; margin:.5rem 0 .3rem; font-weight:600; line-height:1.4; }
h2 { font-family:"IBM Plex Mono",monospace; font-size:.75rem; letter-spacing:.18em;
  text-transform:uppercase; color:var(--sub); margin:1.8rem 0 .7rem;
  padding-bottom:.35rem; border-bottom:1px solid var(--line); }
.card { border:1px solid var(--line); background:var(--panel); border-radius:10px;
  padding:.9rem 1.1rem; margin:.6rem 0; }
.meta { font-size:.83rem; color:var(--sub); margin:.2rem 0; }
.meta b { color:var(--ink); font-weight:600; }
.mono { font-family:"IBM Plex Mono",monospace; font-size:.8rem; }
.muted { color:var(--sub); font-size:.85rem; }
/* the lineage rail: a claim's life as a visible chain */
.rail { list-style:none; margin:.6rem 0; padding-left:1.4rem; border-left:2px solid var(--line); }
.rail li { position:relative; padding:.5rem 0 .5rem .3rem; }
.rail li::before { content:""; position:absolute; left:-1.72rem; top:.95rem;
  width:.7rem; height:.7rem; border-radius:50%; background:var(--line); }
.rail li.done::before { background:var(--acc); }
.rail li.now::before { background:var(--base); box-shadow:0 0 0 4px rgba(212,180,90,.18); }
.rail .st { font-family:"IBM Plex Mono",monospace; font-size:.72rem; letter-spacing:.08em;
  text-transform:uppercase; color:var(--sub); }
.rail .st.done { color:var(--accd); } .rail .st.now { color:var(--base); }
.badge { font-size:.68rem; font-weight:700; padding:.1rem .5rem; border-radius:3px;
  color:var(--bg); background:var(--sub); letter-spacing:.05em; }
.badge.open { background:var(--acc); } .badge.hit { background:var(--accd); }
.badge.miss { background:var(--miss); } .badge.partial { background:var(--base); }
</style></head><body><main>
<a class="back" href="/#home">&larr; cockpit</a>
<div id="body"><p class="muted">loading…</p></div>
<script>
const CID = "__CID__";
const esc = t => { const d=document.createElement('div'); d.textContent=t||''; return d.innerHTML; };
(async function(){
  let d;
  try { d = await (await fetch('/api/claim/'+CID)).json(); }
  catch(e){ document.getElementById('body').innerHTML='<p class="muted">load failed</p>'; return; }
  if (d.error){ document.getElementById('body').innerHTML='<p class="muted">'+esc(d.error)+'</p>'; return; }
  const c = d.claim, L = d.lineage, graded = c.status && c.status !== 'open';
  const today = new Date().toISOString().slice(0,10);
  const due = c.resolve_by && c.resolve_by < today;
  let h = `<h1>${esc(c.claim||'')}</h1>`+
    `<p class="meta"><span class="badge ${esc(c.status||'open')}">${esc(c.status||'open')}</span> `+
    `&nbsp;<a href="/model/${esc(c.repo)}" style="color:var(--accd)">${esc(c.repo)}</a>`+
    `${c.resolve_by?' · resolves '+esc(c.resolve_by):''}`+
    `${c.confidence!=null?' · confidence '+c.confidence:''}</p>`;

  h += `<h2>Life of this claim</h2><ul class="rail">`;
  const step = (label, state, body) =>
    `<li class="${state}"><div class="st ${state}">${label}</div>`+
    `<div class="meta">${body}</div></li>`;
  h += step('Registered', 'done',
    (c.made_on?('on '+esc(c.made_on)):'date not recorded') +
    (c.depends_on?' · declares its dependencies':''));
  h += step('Criteria sealed', c.resolution_criteria||c.criteria ? 'done':'',
    esc(c.resolution_criteria || c.criteria || 'no resolution criteria recorded — this claim cannot be graded cleanly'));
  h += step('Mechanism', c.mechanism ? 'done':'',
    c.mechanism ? esc(c.mechanism) : 'no sealed mechanism recorded');
  h += step(graded ? 'Graded' : (due ? 'Past due — awaiting grading' : 'Awaiting outcome'),
    graded ? 'done' : 'now',
    graded ? ('verdict <b>'+esc(String(c.status))+'</b>' +
              (c.what_happened?' — '+esc(c.what_happened):''))
           : (due ? 'the resolve date has passed; run the grading loop'
                  : 'resolves '+esc(c.resolve_by||'(undated)')));
  h += step('Postmortem', L.postmortems.length?'done':'',
    L.postmortems.length ? L.postmortems.map(p =>
      '<b>'+esc(p.verdict||p.category||'')+'</b> — '+esc(p.lesson||p.why||'')).join('<br>')
      : 'none yet — postmortems run after grading');
  h += step('Attribution', L.attributions.length?'done':'',
    L.attributions.length ? L.attributions.map(a =>
      'reality used <b>'+esc(a.primary||'?')+'</b>'+(a.why?' — '+esc(a.why):'')).join('<br>')
      : 'none yet — which mechanism actually drove the outcome');
  h += `</ul>`;

  if (c.depends_on){
    h += `<h2>Depends on</h2><div class="card meta mono">${esc(JSON.stringify(c.depends_on))}</div>`;
  }
  h += `<h2>Raw record</h2><div class="card"><pre class="mono" style="white-space:pre-wrap;`+
    `color:var(--sub)">${esc(JSON.stringify(c, null, 1))}</pre></div>`;
  document.getElementById('body').innerHTML = h;
  document.title = 'Claim · ' + (c.repo||'');
})();
</script>
</main></body></html>"""


MODEL_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__NAME__ — Model Cockpit</title>
<style>
:root { --bg:#0c1014; --panel:#141a21; --ink:#e9e7e2; --sub:#95a0ac; --line:#242d38;
        --acc:#4fc3a1; --accd:#83dfc3; --warn:#e08050; --miss:#e0705c; --base:#d4b45a; }
* { box-sizing:border-box; margin:0; }
body { background:var(--bg); color:var(--ink); font:15px/1.65 "IBM Plex Sans",system-ui,sans-serif;
       padding:1.5rem 1rem 4rem; }
main { max-width:56rem; margin:0 auto; }
a.back { color:var(--accd); text-decoration:none; font-size:.85rem; }
h1 { font-size:1.6rem; margin:.4rem 0 .2rem; letter-spacing:-.01em; }
.statrow { display:flex; gap:.6rem; flex-wrap:wrap; margin:.8rem 0 1.4rem; }
.stat { font-family:"IBM Plex Mono",monospace; font-size:.74rem; padding:.45rem .8rem;
  border:1px solid var(--line); background:var(--panel); border-radius:7px; color:var(--sub); }
.stat b { display:block; color:var(--ink); font-size:1.05rem; }
.stat.ok b { color:var(--accd); } .stat.warn b { color:var(--warn); }
h2 { font-family:"IBM Plex Mono",monospace; font-size:.78rem; letter-spacing:.18em;
  text-transform:uppercase; color:var(--sub); margin:2rem 0 .8rem; padding-bottom:.4rem;
  border-bottom:1px solid var(--line); }
.card { border:1px solid var(--line); background:var(--panel); border-radius:10px;
  padding:1rem 1.2rem; margin:.7rem 0; }
.md h1, .md h2, .md h3 { font-family:inherit; letter-spacing:0; text-transform:none;
  border:none; color:var(--ink); margin:1em 0 .4em; }
.md h1 { font-size:1.25rem } .md h2 { font-size:1.05rem; padding:0 } .md h3 { font-size:.95rem }
.md p { margin:.5em 0; color:var(--sub); font-size:.92rem; }
.md strong { color:var(--ink); } .md em { color:var(--ink); }
.md li { color:var(--sub); font-size:.92rem; margin:.25em 0 .25em 1.2em; }
.md blockquote { border-left:3px solid var(--acc); padding-left:.9em; color:var(--sub);
  font-style:italic; margin:.6em 0; }
.claim { border:1px solid var(--line); background:var(--bg); border-radius:8px;
  padding:.75rem .95rem; margin:.55rem 0; }
.chead { display:flex; gap:.7rem; align-items:baseline; flex-wrap:wrap; font-size:.75rem;
  font-family:"IBM Plex Mono",monospace; color:var(--sub); margin-bottom:.3rem; }
.badge { font-weight:700; padding:.08rem .5rem; border-radius:3px; font-size:.68rem;
  letter-spacing:.05em; color:var(--bg); background:var(--sub); }
.badge.open { background:var(--acc); } .badge.hit { background:var(--accd); }
.badge.miss { background:var(--miss); } .badge.partial { background:var(--base); }
.ctext { font-weight:600; font-size:.92rem; margin:.2rem 0; }
.cmeta { font-size:.8rem; color:var(--sub); margin:.25rem 0; }
.cmeta b { color:var(--ink); font-weight:600; }
table { width:100%; border-collapse:collapse; font-size:.85rem; }
th, td { text-align:left; padding:.4rem .55rem; border-bottom:1px solid var(--line); }
th { color:var(--sub); font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; }
.mono { font-family:"IBM Plex Mono",monospace; font-size:.8rem; }
.muted { color:var(--sub); font-size:.85rem; }
.term { border-bottom:1px dotted var(--accd); cursor:help; position:relative; }
.term:hover { color:var(--accd); }
.term:hover::after { content:attr(data-def); position:absolute; left:0; bottom:1.5em;
  z-index:9; width:min(24rem,72vw); background:var(--panel); border:1px solid var(--acc);
  border-radius:8px; padding:.6rem .8rem; font:400 .78rem/1.5 "IBM Plex Sans",sans-serif;
  color:var(--ink); box-shadow:0 6px 24px rgba(0,0,0,.5); }
#chatwrap { border:1px solid var(--line); background:var(--panel); border-radius:12px;
  padding:1rem 1.1rem; margin:.8rem 0; transition:border-color .2s, background .2s; }
#chatwrap.incog { border-color:#7a5cc4; background:#15121d;
  box-shadow:inset 0 0 0 1px rgba(122,92,196,.25); }
#chatlog { max-height:26rem; overflow:auto; margin:.6rem 0; }
.msg { margin:.5rem 0; padding:.55rem .75rem; border-radius:8px; font-size:.9rem;
  line-height:1.6; white-space:pre-wrap; }
.msg.user { background:var(--bg); border:1px solid var(--line); }
.msg.bot { background:transparent; border-left:2px solid var(--acc); border-radius:0;
  padding-left:.8rem; color:var(--sub); }
#chatwrap.incog .msg.bot { border-left-color:#7a5cc4; }
.chatrow { display:flex; gap:.5rem; align-items:flex-end; }
#chatbox { flex:1; background:var(--bg); border:1px solid var(--line); border-radius:8px;
  color:var(--ink); padding:.55rem .7rem; font:inherit; font-size:.9rem; min-height:2.6rem;
  resize:vertical; }
.chatbtn { font:600 .85rem "IBM Plex Sans",sans-serif; background:var(--acc); color:var(--bg);
  border:none; border-radius:8px; padding:.6rem 1.1rem; cursor:pointer; }
.chatbtn:disabled { opacity:.5; cursor:wait; }
#chatwrap.incog .chatbtn { background:#7a5cc4; color:#fff; }
.incogbar { display:flex; align-items:center; gap:.6rem; flex-wrap:wrap; font-size:.8rem;
  color:var(--sub); }
.toggle { display:inline-flex; align-items:center; gap:.4rem; cursor:pointer;
  border:1px solid var(--line); border-radius:999px; padding:.3rem .7rem; font-size:.78rem; }
.toggle.on { border-color:#7a5cc4; color:#c3aef0; background:rgba(122,92,196,.12); }
.suggest { display:flex; gap:.4rem; flex-wrap:wrap; margin:.4rem 0 .2rem; }
.suggest span { font-size:.75rem; color:var(--sub); border:1px solid var(--line);
  border-radius:999px; padding:.25rem .6rem; cursor:pointer; }
.suggest span:hover { border-color:var(--acc); color:var(--accd); }
</style></head><body><main>
<a class="back" href="/">&larr; cockpit</a>
<h1 id="title">__NAME__</h1>
<div class="statrow" id="stats"></div>

<h2>Ask this model</h2>
<div id="chatwrap">
  <div class="incogbar">
    <span class="toggle" id="incogtoggle" onclick="toggleIncog()">
      <span id="incogdot">○</span> <span id="incoglabel">Normal — saved to this model&rsquo;s chat log</span>
    </span>
    <a href="#" onclick="clearChat();return false" style="font-size:.78rem">clear log</a>
    <span id="incognote" class="muted" style="display:none;font-size:.75rem">
      Nothing is written to disk: no transcript, no inbox, no memory. History lives only in this
      tab &mdash; closing it destroys the conversation.</span>
  </div>
  <div class="suggest">
    <span onclick="preset('What would falsify this model fastest?')">what would falsify it fastest?</span>
    <span onclick="preset('Where is this model weakest right now, given its record?')">where is it weakest?</span>
    <span onclick="preset('Propose a new falsifiable claim for this model, with criteria and a date.')">propose a claim</span>
    <span onclick="preset('What does this model say about a live situation I describe?')">test it on a situation</span>
  </div>
  <div id="chatlog"></div>
  <div class="chatrow">
    <textarea id="chatbox" placeholder="Ask about this model, or test it on a case…"
      onkeydown="if(event.key==='Enter'&&(event.metaKey||event.ctrlKey))send()"></textarea>
    <button class="chatbtn" id="sendbtn" onclick="send()">Send</button>
  </div>
</div>

<div id="body"><p class="muted">loading…</p></div>
<script>
const NAME = "__NAME__";
const esc = t => { const d=document.createElement('div'); d.textContent=t||''; return d.innerHTML; };
function md(t){
  let h = esc(t);
  h = h.replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>')
       .replace(/^# (.*)$/gm,'<h1>$1</h1>')
       .replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>')
       .replace(/(^|[^*])\\*([^*\\n]+)\\*/g,'$1<em>$2</em>')
       .replace(/^&gt; (.*)$/gm,'<blockquote>$1</blockquote>')
       .replace(/^- (.*)$/gm,'<li>$1</li>')
       .replace(/^\\d+\\. (.*)$/gm,'<li>$1</li>');
  return h.split(/\\n{2,}/).map(b =>
    /^<h|^<li|^<blockquote/.test(b.trim()) ? b : '<p>'+b.replace(/\\n/g,' ')+'</p>').join('\\n');
}
/* --- per-model chat + incognito ---------------------------------------- */
let INCOG = false, INCOG_HIST = [];   // incognito history: this tab only, never sent to disk
function toggleIncog(){
  INCOG = !INCOG;
  document.getElementById('chatwrap').classList.toggle('incog', INCOG);
  document.getElementById('incogtoggle').classList.toggle('on', INCOG);
  document.getElementById('incogdot').textContent = INCOG ? '●' : '○';
  document.getElementById('incoglabel').textContent = INCOG
    ? 'Incognito — nothing is recorded anywhere'
    : 'Normal — saved to this model’s chat log';
  document.getElementById('incognote').style.display = INCOG ? '' : 'none';
  INCOG_HIST = [];
  renderChat(INCOG ? [] : null);
}
function preset(t){ document.getElementById('chatbox').value = t;
                    document.getElementById('chatbox').focus(); }
function bubble(role, content){
  const d = document.createElement('div');
  d.className = 'msg ' + (role === 'user' ? 'user' : 'bot');
  d.textContent = content;
  return d;
}
async function renderChat(turns){
  const log = document.getElementById('chatlog');
  log.innerHTML = '';
  let rows = turns;
  if (rows === null || rows === undefined){
    try { rows = await (await fetch('/api/chat/'+NAME)).json(); } catch(e){ rows = []; }
  }
  (rows||[]).forEach(t => log.appendChild(bubble(t.role, t.content)));
  if (!(rows||[]).length){
    const p = document.createElement('p'); p.className = 'muted';
    p.style.fontSize = '.85rem';
    p.textContent = INCOG
      ? 'Incognito session — this conversation exists only in this tab.'
      : 'No conversation yet about this model.';
    log.appendChild(p);
  }
  log.scrollTop = log.scrollHeight;
}
async function send(){
  const box = document.getElementById('chatbox');
  const msg = box.value.trim();
  if (!msg) return;
  const btn = document.getElementById('sendbtn');
  btn.disabled = true; box.value = '';
  const log = document.getElementById('chatlog');
  if (INCOG && !INCOG_HIST.length) log.innerHTML = '';
  log.appendChild(bubble('user', msg));
  const thinking = bubble('assistant', '…');
  log.appendChild(thinking); log.scrollTop = log.scrollHeight;
  try {
    const r = await (await fetch('/api/chat', {method:'POST', body: JSON.stringify({
      model: NAME, message: msg, incognito: INCOG,
      history: INCOG ? INCOG_HIST : undefined })})).json();
    thinking.textContent = r.error ? ('error: ' + r.error) : r.reply;
    if (INCOG && !r.error){
      INCOG_HIST.push({role:'user', content: msg});
      INCOG_HIST.push({role:'assistant', content: r.reply});
    }
  } catch(e){ thinking.textContent = 'error: ' + e; }
  btn.disabled = false; log.scrollTop = log.scrollHeight;
}
async function clearChat(){
  if (INCOG){ INCOG_HIST = []; renderChat([]); return; }
  await fetch('/api/chat/clear', {method:'POST', body: JSON.stringify({model: NAME})});
  renderChat(null);
}
renderChat(null);

(async function(){
  const d = await (await fetch('/api/model/'+NAME+'/full')).json();
  const i = d.info||{};
  document.getElementById('stats').innerHTML =
    `<span class="stat"><b>${i.open??'?'}</b>open claims</span>`+
    `<span class="stat"><b>${i.resolved??'?'}</b>graded</span>`+
    `<span class="stat ${d.trajectory.mean_brier==null?'':'ok'}"><b>${d.trajectory.mean_brier??'—'}</b>mean Brier (${d.trajectory.n})</span>`+
    `<span class="stat"><b>${d.attribution.as_author}</b>outcomes authored</span>`+
    `<span class="stat ok"><b>${d.attribution.as_driver}</b>times reality's driver</span>`+
    `<span class="stat ${i.deletion_clause?'ok':'warn'}"><b>${i.deletion_clause?'yes':'NO'}</b>deletion clause</span>`;
  let h = '';
  h += '<h2>Model document</h2><div class="card md">'+md(d.model_md)+'</div>';
  if (d.claims.length){
    h += `<h2>Claims (${d.claims.length})</h2>` + d.claims.map(c =>
      `<div class="claim"><div class="chead"><span class="badge ${esc(c.status)}">${esc(c.status)}</span>`+
      `<span>made ${esc(c.made_on)}</span><span>resolves ${esc(c.resolve_by)}</span>`+
      (c.confidence!=null?`<span>conf ${c.confidence}</span>`:'')+
      `<span>${esc(c.ledger)}</span></div>`+
      `<div class="ctext">${esc(c.claim)}</div>`+
      (c.criteria?`<div class="cmeta"><b>criteria:</b> ${esc(c.criteria)}</div>`:'')+
      (c.mechanism?`<div class="cmeta"><b>mechanism:</b> ${esc(c.mechanism)}</div>`:'')+
      (c.what_happened?`<div class="cmeta"><b>what happened:</b> ${esc(c.what_happened)}</div>`:'')+
      `</div>`).join('');
  }
  h += `<h2>Empirical studies</h2>`;
  if (d.studies.length){
    h += d.studies.map(s =>
      `<div class="claim"><div class="chead"><span class="badge ${s.verdict&&s.verdict.startsWith('H1')?'hit':(s.status==='analyzed'?'partial':'open')}">${esc(s.status)}</span>`+
      `<span>${esc(s.id)}</span><span>${esc(s.test||'')}</span></div>`+
      `<div class="ctext">H1: ${esc(s.h1)}</div>`+
      (s.verdict?`<div class="cmeta"><b>verdict:</b> ${esc(s.verdict)} `+
        (s.result?`<span class="mono">${esc(JSON.stringify(s.result))}</span>`:'')+`</div>`:'')+
      `</div>`).join('');
  } else { h += '<p class="muted">none yet.</p>'; }
  h += `<div class="card"><button onclick="convertStudy()" style="font:600 .88rem 'IBM Plex Sans',sans-serif;`+
    `background:var(--acc);color:var(--bg);border:none;border-radius:7px;padding:.55rem 1.1rem;cursor:pointer">`+
    `Convert to statistical hypothesis</button> <span class="muted" id="cs-msg">`+
    `— pre-registers H0/H1 + test from a falsifiable consequence, then collects data and computes the verdict (pure statistics).</span></div>`;
  if (d.trajectory.rows.length){
    h += `<h2>Graded trajectory (${d.trajectory.n} rows, mean Brier ${d.trajectory.mean_brier})</h2>`+
      '<div class="card"><table><tr><th>outcome</th><th>brier</th><th>claim</th></tr>'+
      d.trajectory.rows.map(r=>`<tr><td>${esc(String(r.outcome))}</td><td class="mono">${r.brier}</td>`+
        `<td>${esc(r.claim)}</td></tr>`).join('')+'</table></div>';
  }
  if (d.postmortems.length){
    h += `<h2>Postmortems</h2><div class="card"><table><tr><th>verdict</th><th>claim</th><th>lesson</th></tr>`+
      d.postmortems.map(p=>`<tr><td class="mono">${esc(p.verdict)}</td><td>${esc(p.claim)}</td>`+
        `<td class="muted">${esc(p.lesson)}</td></tr>`).join('')+'</table></div>';
  }
  if (d.history.length){
    h += `<h2>Version history (MODEL.md)</h2><div class="card"><table>`+
      d.history.map(x=>`<tr><td class="mono">${esc(x.date)}</td><td>${esc(x.msg)}</td></tr>`).join('')+
      '</table></div>';
  }
  if (d.artifacts.length){
    h += `<h2>Artifacts in the repo</h2><div class="card"><table>`+
      d.artifacts.map(a=>`<tr><td class="mono">${esc(a.path)}</td>`+
        `<td class="muted">${a.n==null?'':a.n+' file(s)'}</td></tr>`).join('')+'</table></div>';
  }
  document.getElementById('body').innerHTML = h;
  window.convertStudy = async function(){
    await fetch('/api/inbox', {method:'POST', body: JSON.stringify({
      text: 'convert ' + NAME + ' to a statistical hypothesis and run the empirical study '+
            '(suites.empirical_study: formalize -> collect -> analyze)'})});
    document.getElementById('cs-msg').textContent = '✓ queued — the watching session will formalize, collect, and analyze.';
  };
  // glossary terms: dotted + hover def + click through to the glossary tab
  try {
    const g = await (await fetch('/api/glossary')).json();
    const byAlias = {};
    (g.terms||[]).forEach(t => t.aliases.forEach(a => { byAlias[a.toLowerCase()] = t; }));
    const aliases = Object.keys(byAlias).sort((a,b)=>b.length-a.length);
    if (aliases.length){
      const re = new RegExp('\\\\b(' + aliases.map(a =>
        a.replace(/[.*+?^${}()|[\\]\\\\]/g,'\\\\$&')).join('|') + ')\\\\b','gi');
      const walker = document.createTreeWalker(document.getElementById('body'),
        NodeFilter.SHOW_TEXT, { acceptNode: n => (n.parentElement &&
          !n.parentElement.closest('a,script,style,h1,h2,h3,.term'))
          ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
      const nodes = []; let n;
      while ((n = walker.nextNode())) nodes.push(n);
      nodes.forEach(node => {
        const text = node.nodeValue; re.lastIndex = 0;
        if (!re.test(text)) return;
        re.lastIndex = 0;
        const frag = document.createDocumentFragment();
        let last = 0, m, seen = new Set();
        while ((m = re.exec(text))) {
          const t = byAlias[m[1].toLowerCase()];
          if (!t || seen.has(t.slug)) continue;
          seen.add(t.slug);
          frag.appendChild(document.createTextNode(text.slice(last, m.index)));
          const s = document.createElement('span');
          s.className = 'term'; s.textContent = m[1];
          s.setAttribute('data-def', t.term + ' — ' + t.def);
          s.onclick = () => location.href = '/#' + t.slug;
          frag.appendChild(s);
          last = m.index + m[1].length;
        }
        frag.appendChild(document.createTextNode(text.slice(last)));
        node.parentNode.replaceChild(frag, node);
      });
    }
  } catch(e) {}
})();
</script>
</main></body></html>"""


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/":
            return self._send(200, PAGE.encode(), "text/html")
        if p == "/api/models":
            return self._send(200, [m for m in (model_info(n) for n in REPOS) if m])
        if p.startswith("/claim/"):
            cid = p.rsplit("/", 1)[1]
            if not re.fullmatch(r"[0-9a-f]{6,16}", cid):
                return self._send(404, {"error": "bad claim id"})
            return self._send(200, CLAIM_PAGE.replace("__CID__", cid).encode(), "text/html")
        if p.startswith("/model/"):
            name = p.rsplit("/", 1)[1]
            if not re.fullmatch(r"[a-z0-9-]{1,60}", name) or not (TOOLS / name / "MODEL.md").exists():
                return self._send(404, {"error": "unknown model"})
            return self._send(200, MODEL_PAGE.replace("__NAME__", name).encode(), "text/html")
        if p.endswith("/full") and p.startswith("/api/model/"):
            name = p.split("/")[3]
            if not re.fullmatch(r"[a-z0-9-]{1,60}", name) or not (TOOLS / name / "MODEL.md").exists():
                return self._send(404, {"error": "unknown model"})
            return self._send(200, model_full(name))
        if p.startswith("/api/model/"):
            name = p.rsplit("/", 1)[1]
            if name not in REPOS and not (TOOLS / name / "MODEL.md").exists():
                return self._send(404, {"error": "unknown model"})
            mm = (TOOLS / name / "MODEL.md").read_text(encoding="utf-8", errors="replace")
            claims = []
            lp = TOOLS / name / "predict" / "ledger.json"
            if lp.exists():
                d = json.load(lp.open(encoding="utf-8"))
                claims = [{"status": r.get("status", "?"), "resolve_by": r.get("resolve_by", ""),
                           "claim": r.get("claim", "")[:280]}
                          for r in d.get("predictions", [])]
            return self._send(200, {"model_md": mm[:12000], "claims": claims})
        if p == "/api/tasks":
            return self._send(200, {"due": due_tasks(), "manual": manual_tasks()})
        if p == "/api/events":
            return self._send(200, list(reversed(load_events())))
        if p.startswith("/api/chat/"):
            name = p.rsplit("/", 1)[1]
            if not re.fullmatch(r"[a-z0-9-]{1,60}", name):
                return self._send(404, {"error": "bad model"})
            try:
                from chat import history
                return self._send(200, history(name))
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if p == "/api/mindmap":
            f = TOOLS / "entity-atlas" / "mindmap.json"
            if not f.exists():
                return self._send(404, {"error": "no mindmap yet — run "
                                                 "python -m suites.mindmap --build"})
            return self._send(200, json.load(f.open(encoding="utf-8")))
        if p.startswith("/api/runlog/"):
            act = p.rsplit("/", 1)[1]
            if not re.fullmatch(r"[a-z-]{1,20}", act):
                return self._send(404, {"error": "bad action"})
            f = UI / "runs" / f"{act}.log"
            return self._send(200, {"log": f.read_text(encoding="utf-8", errors="replace")[-6000:]
                                    if f.exists() else "(not run yet)"})
        if p.startswith("/api/claim/"):
            cid = p.rsplit("/", 1)[1]
            if not re.fullmatch(r"[0-9a-f]{6,16}", cid):
                return self._send(404, {"error": "bad claim id"})
            import hashlib as _h
            found = None
            for repo in REPOS:
                for rel in ("predict/ledger.json", "predict/live_ledger.json",
                            "signals/signal_ledger.json"):
                    f = TOOLS / repo / rel
                    if not f.exists():
                        continue
                    try:
                        d = json.load(f.open(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    for r in (d.get("predictions", d) if isinstance(d, dict) else d):
                        cl = r.get("claim") or ""
                        h = _h.sha256((repo + cl).encode()).hexdigest()[:12]
                        if h == cid:
                            found = {"id": h, "repo": repo, "ledger": rel, **r}
                            break
                    if found:
                        break
                if found:
                    break
            if not found:
                return self._send(404, {"error": "claim not found"})
            # lineage: postmortem + attribution rows that mention this claim text
            key = (found.get("claim") or "")[:80]
            lineage = {"postmortems": [], "attributions": []}
            pf = ROOT / "trajectory" / "postmortems.jsonl"
            if pf.exists():
                for l in pf.read_text(encoding="utf-8").splitlines():
                    if l.strip() and key and key[:50] in l:
                        lineage["postmortems"].append(json.loads(l))
            af = TOOLS / "attribution-model" / "attributions" / "attributions.jsonl"
            if af.exists():
                for l in af.read_text(encoding="utf-8").splitlines():
                    if l.strip() and key and key[:50] in l:
                        lineage["attributions"].append(json.loads(l))
            return self._send(200, {"claim": found, "lineage": lineage})
        if p == "/api/claims":
            import hashlib as _h
            out = []
            for repo in REPOS:
                for rel in ("predict/ledger.json", "predict/live_ledger.json",
                            "signals/signal_ledger.json"):
                    f = TOOLS / repo / rel
                    if not f.exists():
                        continue
                    try:
                        d = json.load(f.open(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    for r in (d.get("predictions", d) if isinstance(d, dict) else d):
                        cl = r.get("claim") or ""
                        if not cl:
                            continue
                        out.append({"id": _h.sha256((repo + cl).encode()).hexdigest()[:12],
                                    "repo": repo, "claim": cl[:200],
                                    "status": r.get("status", "open"),
                                    "resolve_by": r.get("resolve_by", ""),
                                    "confidence": r.get("confidence")})
            out.sort(key=lambda x: (x["status"] != "open", x["resolve_by"] or "9999"))
            return self._send(200, out)
        if p == "/api/verdict":
            # "Am I actually any good at this?" — answered honestly, including
            # when the honest answer is "not enough evidence yet".
            OUTCOME = {"hit": 1.0, "partial": 0.5, "miss": 0.0}
            per, rows = {}, []
            tf = ROOT / "trajectory" / "trajectory.jsonl"
            if tf.exists():
                for l in tf.read_text(encoding="utf-8").splitlines():
                    if not l.strip():
                        continue
                    r = json.loads(l)
                    if r.get("brier") is None:
                        continue
                    m = r.get("model", "?")
                    s = per.setdefault(m, {"n": 0, "brier": 0.0, "base": 0.0,
                                           "source": r.get("source", "")})
                    s["n"] += 1
                    s["brier"] += r["brier"]
                    if isinstance(r.get("baseline_brier"), (int, float)):
                        s["base"] += r["baseline_brier"]
                    rows.append(r)
            for s in per.values():
                if s["n"]:
                    s["mean_brier"] = round(s["brier"] / s["n"], 3)
                    s["mean_baseline"] = round(s["base"] / s["n"], 3) if s["base"] else None
            # earned vs lucky, from the postmortem layer. The field is `correctness`
            # (earned_hit / lucky_hit / mechanism_miss / near_miss); `miss_category`
            # says WHY a miss happened. Both are the honest half of the scoreboard.
            earned = lucky = other = 0
            miss_why = {}
            pf = ROOT / "trajectory" / "postmortems.jsonl"
            if pf.exists():
                for l in pf.read_text(encoding="utf-8").splitlines():
                    if not l.strip():
                        continue
                    r = json.loads(l)
                    c = str(r.get("correctness", "")).lower()
                    if c == "earned_hit":
                        earned += 1
                    elif c == "lucky_hit":
                        lucky += 1
                    else:
                        other += 1
                    mc = r.get("miss_category")
                    if mc and mc != "none":
                        miss_why[mc] = miss_why.get(mc, 0) + 1
            # live vs backtest: only live grades answer the real question
            live = sum(1 for r in rows if r.get("source") == "live")
            # attribution: how often reality used OUR mechanism vs canon vs none
            att = {"internal": 0, "canon": 0, "none": 0}
            CANON = set()
            cdir = TOOLS / "canon" / "models"
            if cdir.exists():
                CANON = {f.stem for f in cdir.glob("*.md")}
            af = TOOLS / "attribution-model" / "attributions" / "attributions.jsonl"
            if af.exists():
                for l in af.read_text(encoding="utf-8").splitlines():
                    if not l.strip():
                        continue
                    pri = json.loads(l).get("primary", "none")
                    att["none" if pri in ("none", None) else
                        ("canon" if pri in CANON else "internal")] += 1
            n_open = sum(1 for repo in REPOS
                         for rel in ("predict/ledger.json", "predict/live_ledger.json",
                                     "signals/signal_ledger.json")
                         if (TOOLS / repo / rel).exists()
                         for r in (lambda d: d.get("predictions", d) if isinstance(d, dict) else d)(
                             json.load((TOOLS / repo / rel).open(encoding="utf-8")))
                         if r.get("status", "open") == "open")
            return self._send(200, {
                "graded_total": len(rows), "graded_live": live, "open": n_open,
                "per_model": per, "earned": earned, "lucky": lucky, "other": other,
                "miss_why": miss_why, "attribution": att,
                "honest": ("No live claim has been graded yet. Everything below is "
                           "backtest, which cannot tell you whether YOU are any good — "
                           "only that the machinery runs.") if live == 0 else ""})
        if p == "/api/home":
            import subprocess as _sp
            today = date.today().isoformat()
            horizon, late = [], []
            for repo in REPOS:
                for rel in ("predict/ledger.json", "predict/live_ledger.json",
                            "signals/signal_ledger.json"):
                    f = TOOLS / repo / rel
                    if not f.exists():
                        continue
                    try:
                        d = json.load(f.open(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    for r in (d.get("predictions", d) if isinstance(d, dict) else d):
                        if r.get("status", "open") != "open":
                            continue
                        rb = r.get("resolve_by") or ""
                        if not rb:
                            continue
                        row = {"repo": repo, "resolve_by": rb,
                               "claim": (r.get("claim") or "")[:150],
                               "confidence": r.get("confidence")}
                        (late if rb < today else horizon).append(row)
            horizon.sort(key=lambda x: x["resolve_by"])
            late.sort(key=lambda x: x["resolve_by"])
            # recent activity: newest commits across the fleet
            recent = []
            for repo in REPOS[:40]:
                d = TOOLS / repo
                if not (d / ".git").exists():
                    continue
                try:
                    out = _sp.run(["git", "log", "-3", "--format=%ad|%s", "--date=short"],
                                  cwd=d, capture_output=True, text=True, timeout=8)
                    for line in out.stdout.strip().splitlines():
                        if "|" in line:
                            when, msg = line.split("|", 1)
                            recent.append({"repo": repo, "date": when, "msg": msg[:110]})
                except Exception:
                    pass
            recent.sort(key=lambda x: x["date"], reverse=True)
            return self._send(200, {"today": today, "late": late[:12],
                                    "horizon": horizon[:14], "recent": recent[:16],
                                    "counts": {"late": len(late), "horizon": len(horizon)}})
        if p.startswith("/api/search"):
            q = parse_qs(urlparse(self.path).query).get("q", [""])[0].strip()
            if not q:
                return self._send(400, {"error": "empty query"})
            try:
                sys.path.insert(0, str(ROOT))
                from suites.memory_index import recall
                hits = recall(q, k=14)
                return self._send(200, [{k: h[k] for k in h if k != "vec"} for h in hits])
            except Exception as e:
                return self._send(500, {"error": str(e)[:200]})
        if p == "/api/entities":
            ddir = TOOLS / "entity-atlas" / "dossiers"
            out = []
            if ddir.exists():
                for f in sorted(ddir.glob("*.json")):
                    d = json.load(f.open(encoding="utf-8"))
                    out.append({"slug": d["slug"], "name": d["name"], "kind": d["kind"],
                                "stats": d["stats"], "synthesis": d.get("synthesis") or {}})
            return self._send(200, sorted(out, key=lambda x: -x["stats"]["claims"]))
        if p.startswith("/api/entity/"):
            slug = p.rsplit("/", 1)[1]
            f = TOOLS / "entity-atlas" / "dossiers" / f"{slug}.json"
            if not re.fullmatch(r"[a-z0-9-]{1,60}", slug) or not f.exists():
                return self._send(404, {"error": "unknown entity"})
            return self._send(200, json.load(f.open(encoding="utf-8")))
        if p == "/api/map":
            mf = ROOT / "map" / "mapcards.json"
            if not mf.exists():
                try:
                    from suites.reality_map import build as _mapbuild
                    return self._send(200, _mapbuild())
                except Exception as e:
                    return self._send(500, {"error": str(e)[:200]})
            return self._send(200, json.load(mf.open(encoding="utf-8")))
        if p == "/api/brainstorms":
            bdir = ROOT / "brainstorms"
            out = []
            if bdir.exists():
                for f in sorted(bdir.glob("*.json"), reverse=True):
                    if f.name == "ledger.json":
                        continue
                    d = json.load(f.open(encoding="utf-8"))
                    if f.name.endswith(".queued.json"):
                        # skip the marker if the result has already landed
                        if (bdir / (d["id"] + ".json")).exists():
                            continue
                        out.append({"id": d["id"], "at": d["at"], "models": d["models"],
                                    "event": d["event"][:200], "status": "queued", "md": ""})
                        continue
                    md = bdir / (f.stem + ".md")
                    out.append({"id": d["id"], "at": d["at"], "models": d["models"],
                                "event": d["event"][:200], "status": "done",
                                "md": md.read_text(encoding="utf-8")[:9000] if md.exists() else ""})
            return self._send(200, out)
        if p == "/api/glossary":
            g = ROOT / "docs" / "GLOSSARY.md"
            return self._send(200, {"text": g.read_text(encoding="utf-8")
                                    if g.exists() else "(no glossary yet)",
                                    "terms": glossary_terms()})
        if p == "/api/assessments":
            traj = ROOT / "trajectory" / "trajectory.jsonl"
            n_traj = len(traj.read_text(encoding="utf-8").splitlines()) if traj.exists() else 0
            pm = ROOT / "trajectory" / "postmortems.jsonl"
            n_pm = len(pm.read_text(encoding="utf-8").splitlines()) if pm.exists() else 0
            tot_open = sum(ledger_counts(TOOLS / n)[0] for n in REPOS)
            tot_res = sum(ledger_counts(TOOLS / n)[1] for n in REPOS)
            sb = TOOLS / "attribution-model" / "SCOREBOARD.md"
            joins = ROOT / "trajectory" / "CLASSIFIER_JOINS.md"
            return self._send(200, {
                "summary": (f"{len(REPOS)} models · {tot_open} open claims · {tot_res} resolved · "
                            f"{n_traj} trajectory rows · {n_pm} postmortems"),
                "scoreboard": sb.read_text(encoding="utf-8")[:6000] if sb.exists() else "",
                "joins": joins.read_text(encoding="utf-8")[:4000] if joins.exists() else ""})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
                              or b"{}")
        except json.JSONDecodeError:
            return self._send(400, {"error": "bad json"})
        if p == "/api/models":
            return self._send(200, create_model(body.get("slug", ""), body.get("title", ""),
                                                body.get("domain", "")))
        if p == "/api/tasks":
            t = manual_tasks()
            if body.get("text", "").strip():
                t.append({"text": body["text"].strip(), "done": False,
                          "added": date.today().isoformat()})
                save_manual(t)
            return self._send(200, {"ok": True})
        if p == "/api/tasks/toggle":
            t = manual_tasks()
            i = body.get("i", -1)
            if 0 <= i < len(t):
                t[i]["done"] = not t[i]["done"]
                save_manual(t)
            return self._send(200, {"ok": True})
        if p == "/api/events":
            src = (body.get("source") or "").strip()
            note = (body.get("note") or "").strip()
            models = body.get("models") or []
            if not (src or note):
                return self._send(400, {"error": "need a source or text"})
            evs = load_events()
            eid = f"ev-{date.today().isoformat()}-{len(evs)+1}"
            stype = ("youtube" if re.search(r"youtu\.?be", src)
                     else "url" if src.startswith("http") else "text")
            evs.append({"id": eid, "at": date.today().isoformat(), "source_type": stype,
                        "source": src[:600], "note": note[:1200], "models": models,
                        "status": "queued", "assessment": ""})
            save_events(evs)
            # forward to the session inbox so a watching Claude picks it up live
            UI.mkdir(exist_ok=True)
            with INBOX.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": date.today().isoformat(),
                                    "text": (f"analyze event {eid}: "
                                             f"[{stype}] {src or '(text only)'} — "
                                             f"note: {note[:200] or '(none)'} — "
                                             f"with models: {', '.join(models) or 'your pick'}")},
                                   ensure_ascii=False) + "\n")
            return self._send(200, {"ok": True, "id": eid})
        if p == "/api/brainstorm":
            ev = (body.get("event") or "").strip()
            models = body.get("models") or []
            if not ev or len(models) < 2:
                return self._send(400, {"error": "need an event and 2+ models"})
            import secrets
            bid = f"bs-{date.today().isoformat()}-{secrets.token_hex(2)}"
            bdir = ROOT / "brainstorms"
            bdir.mkdir(exist_ok=True)
            (bdir / f"{bid}.queued.json").write_text(json.dumps({
                "id": bid, "at": date.today().isoformat(), "event": ev[:1200],
                "models": models, "status": "queued"}, ensure_ascii=False, indent=1),
                encoding="utf-8")
            UI.mkdir(exist_ok=True)
            with INBOX.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": date.today().isoformat(),
                                    "text": (f"brainstorm this event with models "
                                             f"{','.join(models)} --id {bid} "
                                             f"(suites.brainstorm): {ev[:800]}")},
                                   ensure_ascii=False) + "\n")
            return self._send(200, {"ok": True, "id": bid})
        if p == "/api/capture":
            # Register a claim from the UI. Writes the same shape the suites read,
            # into the target model's own ledger — no special-case store.
            repo = (body.get("repo") or "").strip()
            claim = (body.get("claim") or "").strip()
            criteria = (body.get("criteria") or "").strip()
            resolve_by = (body.get("resolve_by") or "").strip()
            conf = body.get("confidence")
            mech = (body.get("mechanism") or "").strip()
            if not re.fullmatch(r"[a-z0-9-]{1,60}", repo) or not (TOOLS / repo / "MODEL.md").exists():
                return self._send(400, {"error": "pick an existing model"})
            if len(claim) < 12:
                return self._send(400, {"error": "the claim needs to be a real sentence"})
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", resolve_by or ""):
                return self._send(400, {"error": "resolve_by must be YYYY-MM-DD — "
                                                 "an undated claim cannot be graded"})
            if not criteria:
                return self._send(400, {"error": "resolution criteria are required — "
                                                 "without them the claim cannot lose"})
            try:
                conf = float(conf)
                assert 0.0 <= conf <= 1.0
            except Exception:
                return self._send(400, {"error": "confidence must be between 0 and 1"})
            led = TOOLS / repo / "predict" / "ledger.json"
            led.parent.mkdir(parents=True, exist_ok=True)
            d = json.load(led.open(encoding="utf-8")) if led.exists() else {"predictions": []}
            rows = d.setdefault("predictions", [])
            if any((r.get("claim") or "").strip() == claim for r in rows):
                return self._send(400, {"error": "this exact claim is already registered"})
            rows.append({"made_on": date.today().isoformat(), "claim": claim,
                         "resolution_criteria": criteria, "resolve_by": resolve_by,
                         "confidence": conf, "mechanism": mech,
                         "status": "open", "source": "cockpit"})
            json.dump(d, led.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
            import hashlib as _h
            return self._send(200, {"ok": True, "repo": repo,
                                    "id": _h.sha256((repo + claim).encode()).hexdigest()[:12]})
        if p == "/api/run":
            # Whitelisted, argument-free suite runs. Nothing here takes user input as
            # a shell argument — the action name selects a fixed command.
            import subprocess as _sp, threading as _th
            ACTIONS = {
                "grade":     ["-m", "suites.grading_loop"],
                "map":       ["-m", "suites.reality_map", "--build"],
                "mindmap":   ["-m", "suites.mindmap", "--build"],
                "entities":  ["-m", "suites.entities", "--build"],
                "memory":    ["-m", "suites.memory_index", "--build"],
                "attribute": ["-m", "suites.attribute_outcomes", "--run", "--scoreboard"],
                "calibrate": ["-m", "suites.calibrate"],
                "sleep":     ["-m", "suites.sleep", "--dependency-report"],
            }
            act = (body.get("action") or "").strip()
            if act not in ACTIONS:
                return self._send(400, {"error": f"unknown action '{act}'"})
            logf = UI / "runs" / f"{act}.log"
            logf.parent.mkdir(parents=True, exist_ok=True)
            def _go():
                with logf.open("w", encoding="utf-8") as fh:
                    fh.write("$ python " + " ".join(ACTIONS[act]) + "\n\n")
                    fh.flush()
                    try:
                        _sp.run([sys.executable, "-u"] + ACTIONS[act], cwd=str(ROOT),
                                stdout=fh, stderr=_sp.STDOUT, timeout=3600)
                    except Exception as e:
                        fh.write("\n[failed] " + str(e) + "\n")
            _th.Thread(target=_go, daemon=True).start()
            return self._send(200, {"ok": True, "action": act})
        if p == "/api/chat":
            name = (body.get("model") or "").strip()
            msg = (body.get("message") or "").strip()
            incog = bool(body.get("incognito"))
            if not re.fullmatch(r"[a-z0-9-]{1,60}", name) or \
                    not (TOOLS / name / "MODEL.md").exists():
                return self._send(404, {"error": "unknown model"})
            if not msg:
                return self._send(400, {"error": "empty message"})
            try:
                from chat import ask
                return self._send(200, ask(name, msg, incog, body.get("history")))
            except Exception as e:
                return self._send(500, {"error": str(e)[:300]})
        if p == "/api/chat/clear":
            name = (body.get("model") or "").strip()
            if re.fullmatch(r"[a-z0-9-]{1,60}", name):
                f = ROOT / "ui" / "chats" / f"{name}.jsonl"
                if f.exists():
                    f.unlink()
            return self._send(200, {"ok": True})
        if p == "/api/brainstorm/act":
            # pure file ops — no LLM: turn a brainstorm into artifacts
            bid = body.get("id", "")
            action = body.get("action", "")
            bf = ROOT / "brainstorms" / f"{bid}.json"
            if not bf.exists():
                return self._send(404, {"error": "unknown brainstorm"})
            b = json.load(bf.open(encoding="utf-8"))
            syn = b.get("synthesis", {})
            today = date.today().isoformat()
            if action == "register":
                lp = ROOT / "brainstorms" / "ledger.json"
                led = json.load(lp.open(encoding="utf-8")) if lp.exists() else {"predictions": []}
                have = {r["claim"] for r in led["predictions"]}
                n = 0
                for jc in syn.get("joint_claims", []):
                    if jc.get("claim") and jc["claim"] not in have:
                        led["predictions"].append({
                            "made_on": today, "entity": bid, "claim": jc["claim"],
                            "resolution_criteria": jc.get("resolution_criteria", ""),
                            "confidence": jc.get("confidence"),
                            "resolve_by": jc.get("resolve_by", ""),
                            "mechanism": ("ensemble claim from brainstorm; backed by "
                                          + ", ".join(jc.get("backed_by", []))),
                            "status": "open"})
                        n += 1
                json.dump(led, lp.open("w", encoding="utf-8"), ensure_ascii=False, indent=2)
                return self._send(200, {"ok": True, "msg": f"{n} joint claim(s) registered "
                                        f"(graded by the weekly loop)"})
            if action == "seed":
                crossed = syn.get("crossed", [])
                if not crossed:
                    return self._send(400, {"error": "no crossed insights to seed from"})
                cdir = TOOLS / "hunch-tracker" / "candidates"
                cdir.mkdir(parents=True, exist_ok=True)
                n = 0
                for i, x in enumerate(crossed):
                    pair = x.get("pair", [])
                    name = "-".join(re.sub(r"[^a-z0-9]+", "", p.split("-")[0].lower())
                                    for p in pair)[:30] + "-bridge"
                    cid = f"bs-seed-{today}-{bid.split('-')[-1]}{chr(97+i)}"
                    cf = cdir / f"{cid}.json"
                    if cf.exists():
                        continue
                    cf.write_text(json.dumps({
                        "id": cid, "generated": today, "source": "brainstorm",
                        "kind": "model-seed", "hunch": x.get("insight", ""),
                        "proposed_model_name": name,
                        "core_mechanism": f"the {' x '.join(pair)} crossing, observed live "
                                          f"in brainstorm {bid}",
                        "draw": {"models": pair, "origin": bid}, "promoted": False},
                        ensure_ascii=False, indent=1), encoding="utf-8")
                    n += 1
                return self._send(200, {"ok": True, "msg": f"{n} model-seed candidate(s) "
                                        f"quarantined in hunch-tracker/candidates "
                                        f"(promote via suites.hunch_gen --promote)"})
            if action == "deciders":
                t = manual_tasks()
                n = 0
                for x in syn.get("tensions", []):
                    txt = (f"DECIDER [{bid}]: {x.get('decider','')[:220]} "
                           f"(settles {' vs '.join(x.get('models', []))})")
                    if x.get("decider") and not any(tt["text"] == txt for tt in t):
                        t.append({"text": txt, "done": False, "added": today})
                        n += 1
                save_manual(t)
                return self._send(200, {"ok": True, "msg": f"{n} decider(s) now tracked as tasks"})
            return self._send(400, {"error": "unknown action"})
        if p == "/api/events/assess":
            evs = load_events()
            for e in evs:
                if e["id"] == body.get("id"):
                    e["status"] = body.get("status", "assessed")
                    e["assessment"] = (body.get("assessment") or "")[:6000]
                    save_events(evs)
                    return self._send(200, {"ok": True})
            return self._send(404, {"error": "unknown event id"})
        if p == "/api/inbox":
            text = (body.get("text") or "").strip()
            if not text:
                return self._send(400, {"error": "empty"})
            UI.mkdir(exist_ok=True)
            with INBOX.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"at": date.today().isoformat(), "text": text},
                                   ensure_ascii=False) + "\n")
            return self._send(200, {"ok": True})
        return self._send(404, {"error": "not found"})


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    INBOX.touch(exist_ok=True)
    # Port is configurable so two instances can run their cockpits side by side:
    # --port, else COCKPIT_PORT, else fleet.json's cockpit_port, else 8787.
    port = 8787
    if _cfg.get("cockpit_port"):
        port = int(_cfg["cockpit_port"])
    if os.environ.get("COCKPIT_PORT"):
        port = int(os.environ["COCKPIT_PORT"])
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    except OSError as e:
        raise SystemExit(f"cannot bind 127.0.0.1:{port} ({e}). Another instance may "
                         f"already be running — pass --port 8788 or set cockpit_port "
                         f"in fleet.json.")
    print(f"Model Cockpit ({ROOT.name}) -> http://127.0.0.1:{port}  (Ctrl+C to stop)")
    srv.serve_forever()
