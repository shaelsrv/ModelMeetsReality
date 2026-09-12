"""Generic live-watch loop for any sister model — config-driven (watch.json per repo).

Generalizes attention's live_predictions.py / my-model' action_watch.py so new instruments
need only a MODEL.md + watch.json, no bespoke script:

  python suites/model_watch.py --repo my-model --predict
  python suites/model_watch.py --repo my-model --assess
  python suites/model_watch.py --repo my-model --status

watch.json: {"model_file": "MODEL.md", "ledger": "predict/ledger.json",
             "frame": "one-paragraph instrument description for the prompt",
             "default_model": "openai/gpt-4o",
             "entities": [{"id": "...", "name": "...", "watch": "..."}]}

Same ledger schema as the other watches (sync_ledger.py consumes it directly); ends with the
auto public-site sync like every round script.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from harness.openrouter import chat
from harness.actors import parse_json

TOOLS = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# This repo — the main instance, whatever the user named its directory.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

PREDICT_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. You are running the model below as a
forecasting instrument. {frame}

=== THE MODEL ===
{model_text}
=== END MODEL ===

STEP 1 — OBSERVE (use the web): what has actually happened around {name} in the last 4-8 weeks?
({watch}) Cite 2-4 concrete items with dates/sources.
STEP 2 — MODEL READ: which of the model's mechanisms do the observations engage, and what state
does the model infer? If observations CONTRADICT the model, say so plainly — contradictions are
the valuable output.
STEP 3 — PREDICT: exactly 2 falsifiable SHORT-TERM predictions resolving by {resolve_by} that the
model read implies. Concrete observables only (a number, a dated decision, a filed/announced
action — checkable by web search on that date). QUALITY BAR: no base-rate-certain events; a good
prediction is one a smart skeptic might bet against. Neutral phrasing on politically contested
matters; predict observables, not judgments.

{learnings}

Return ONLY JSON:
{{"observed":[{{"item":"...","date":"...","source":"..."}}],
"model_read":"one paragraph",
"predictions":[{{"claim":"specific falsifiable claim","resolution_criteria":"what observable settles it",
"confidence":0.0-1.0,"mechanism":"which model mechanism drives this",
"possible_states":["every state this entity could plausibly be in at the resolve date"],
"predicted_state":"the ONE from possible_states you are calling"}}]}}

ON possible_states -- this is required, and it is not decoration.

List the states the entity could ACTUALLY be in on the resolve date, as short
noun phrases a stranger could check: "enforces", "extends the deadline",
"issues further requests only", "silent". Three to six. Include the states you
think are UNLIKELY, especially the do-nothing one -- a list containing only the
outcome you expect is not a list.

predicted_state must be one of them, verbatim.

Why: a bare claim that turns out wrong tells you only that it was wrong. A claim
that named its alternatives tells you WHICH WAY it was wrong, which is the part
that revises a model. And if the entity ends up in a state nobody listed, that
is the most informative outcome available -- the model did not know the option
existed."""

ASSESS_PROMPT = """You have LIVE WEB ACCESS. Today is {today}. Assess this prediction made on {made_on}
about {name}, due to resolve by {resolve_by}:

CLAIM: {claim}
RESOLUTION CRITERIA: {criteria}
CONFIDENCE GIVEN: {confidence}
MECHANISM CITED: {mechanism}
STATES THE MODEL NAMED: {possible_states}
STATE IT PREDICTED: {predicted_state}

STEP 1 — search the web for what ACTUALLY happened (cite sources/dates).
STEP 2 — verdict: hit / miss / partial / unresolvable.
STEP 3 — which of the named states did the entity actually end up in? Answer with
one of them verbatim, or with UNLISTED if it ended up somewhere nobody named.
UNLISTED is the most informative answer available and must never be forced into
the nearest listed state -- it means the model did not know the option existed,
which is a bigger finding than a wrong call among known options.
STEP 4 — if miss/partial: the LEARNING — what did the model read get wrong, one line usable in
future rounds?

Return ONLY JSON: {{"what_happened":"...with sources","verdict":"hit|miss|partial|unresolvable",
"actual_state":"the state it ended in, verbatim from the named list, or UNLISTED",
"learning":"one line (empty string if hit)"}}"""


def load_cfg(repo):
    root = os.path.join(TOOLS, repo)
    with open(os.path.join(root, "watch.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(root, cfg.get("model_file", "MODEL.md")), encoding="utf-8") as f:
        model_text = f.read()[:9000]
    ledger_path = os.path.join(root, cfg.get("ledger", "predict/ledger.json"))
    return cfg, model_text, ledger_path


def load_ledger(path):
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {"predictions": [], "learnings": [], "rounds": 0}


def save_ledger(path, led):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(led, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def cmd_predict(repo, model, horizon):
    cfg, model_text, lpath = load_cfg(repo)
    model = model or cfg.get("default_model", "openai/gpt-4o")
    today = datetime.date.today().isoformat()
    resolve_by = (datetime.date.today() + datetime.timedelta(days=horizon)).isoformat()
    # new_model scaffolds watch.json with a literal placeholder entity. Running
    # against it burns a minutes-long web search per entity and produces either
    # nothing (the model correctly refuses to invent observations about a
    # nonexistent target) or claims about whatever real thing it substituted on
    # its own initiative -- which is worse, because those look fine. Caught on a
    # 10-model install test where 2 refused and 8 quietly improvised.
    placeholders = [e for e in cfg.get("entities", [])
                    if str(e.get("id", "")).lower() == "example"
                    or "example entity" in str(e.get("name", "")).lower()
                    or str(e.get("watch", "")).strip() == "what to observe about it"]
    if placeholders:
        names = ", ".join(str(e.get("name")) for e in placeholders)
        raise SystemExit(
            repo + "/watch.json still has the scaffold placeholder (" + names + ")."
            + chr(10)
            + "  Edit entities[] to name what this model actually watches, then rerun."
            + chr(10)
            + "  Running as-is spends a web search per entity and returns nothing"
            + chr(10)
            + "  usable -- or worse, claims about a target you did not choose.")

    led = load_ledger(lpath)
    learn = ""
    if led["learnings"]:
        learn = ("ACCUMULATED LEARNINGS (apply these corrections):\n- "
                 + "\n- ".join(l["learning"] for l in led["learnings"][-12:]))
    print(f"[{repo}] PREDICT round {led['rounds']+1} · {today} → {resolve_by} · {model}")
    for e in cfg["entities"]:
        print(f"  · {e['name']}: observing + predicting…", flush=True)
        p = (PREDICT_PROMPT.replace("{today}", today).replace("{frame}", cfg.get("frame", ""))
             .replace("{model_text}", model_text).replace("{name}", e["name"])
             .replace("{watch}", e["watch"]).replace("{resolve_by}", resolve_by)
             .replace("{learnings}", learn))
        r = chat(model + ":online", [{"role": "user", "content": p}], temperature=0.4, max_tokens=2200)
        d = parse_json(r.text) if not r.error else None
        if not d or not d.get("predictions"):
            why = r.error or ("no 'predictions' key" if d else "unparseable")
            print("      ! " + str(why))
            # Keep the raw reply. A search pass costs minutes and money, and
            # "unparseable" with the evidence discarded cannot be diagnosed
            # afterwards -- which is what happened on the first install test.
            if r.text:
                dump = os.path.join(os.path.dirname(lpath), "failed")
                os.makedirs(dump, exist_ok=True)
                f = os.path.join(dump, today + "-" + str(e["id"]) + ".txt")
                open(f, "w", encoding="utf-8").write("# " + str(why) + chr(10)*2 + r.text)
                print("        raw reply kept: " + f)
            continue
        print(f"      read: {d.get('model_read','')[:100]}")
        for pred in d["predictions"]:
            led["predictions"].append({
                "entity": e["id"], "name": e["name"], "made_on": today, "resolve_by": resolve_by,
                "round": led["rounds"] + 1, "status": "open",
                "model_read": d.get("model_read", "")[:400],
                "observed": d.get("observed", []), **pred})
            print(f"      → [{pred.get('confidence','?')}] {pred.get('claim','')[:95]}")
    led["rounds"] += 1
    save_ledger(lpath, led)
    print(f"ledger: {sum(1 for p in led['predictions'] if p['status']=='open')} open")


def cmd_assess(repo, model):
    cfg, _mt, lpath = load_cfg(repo)
    model = model or cfg.get("default_model", "openai/gpt-4o")
    today = datetime.date.today().isoformat()
    led = load_ledger(lpath)
    due = [p for p in led["predictions"] if p["status"] == "open" and p["resolve_by"] <= today]
    if not due:
        nxt = min((p["resolve_by"] for p in led["predictions"] if p["status"] == "open"), default="—")
        print(f"[{repo}] nothing due; earliest open resolve-by: {nxt}"); return
    print(f"[{repo}] ASSESS · {len(due)} due")
    hits = misses = partials = 0
    brier = []
    for p in due:
        q = (ASSESS_PROMPT.replace("{today}", today).replace("{made_on}", p["made_on"])
             .replace("{name}", p["name"]).replace("{resolve_by}", p["resolve_by"])
             .replace("{claim}", p["claim"]).replace("{criteria}", p.get("resolution_criteria", ""))
             .replace("{confidence}", str(p.get("confidence")))
             .replace("{mechanism}", p.get("mechanism", ""))
             # Older rows predate possible_states; say so rather than substitute
             # an empty list, which would read as "the model named no options".
             .replace("{possible_states}",
                      " | ".join(p.get("possible_states") or [])
                      or "(not recorded -- this prediction predates state enumeration)")
             .replace("{predicted_state}", p.get("predicted_state") or "(not recorded)"))
        r = chat(model + ":online", [{"role": "user", "content": q}], temperature=0.3, max_tokens=1400)
        d = parse_json(r.text) if not r.error else None
        if not d:
            print(f"  ! {p['claim'][:60]}: {r.error or 'unparseable'}"); continue
        v = d.get("verdict", "unresolvable")
        p["status"], p["assessed_on"] = v, today
        p["what_happened"] = d.get("what_happened", "")[:500]
        # Which named alternative actually occurred. UNLISTED means the entity
        # went somewhere the model never listed -- a bigger finding than a wrong
        # call among known options, so it is recorded distinctly and printed.
        act = str(d.get("actual_state", "")).strip()
        if act:
            p["actual_state"] = act[:120]
            if act.upper() == "UNLISTED":
                p["unlisted_state"] = True
        outcome = {"hit": 1.0, "partial": 0.5, "miss": 0.0}.get(v)
        hits += v == "hit"; partials += v == "partial"; misses += v == "miss"
        if outcome is not None and isinstance(p.get("confidence"), (int, float)):
            brier.append((p["confidence"] - outcome) ** 2)
        if d.get("learning"):
            led["learnings"].append({"entity": p["entity"], "round": p["round"],
                                     "assessed": today, "learning": d["learning"]})
        tag = ""
        if p.get("unlisted_state"):
            tag = "  <- UNLISTED STATE"
        elif p.get("actual_state"):
            tag = f"  [{p['actual_state'][:40]}]"
        print(f"  {v.upper():>12} {p['claim'][:60]}{tag}")
    save_ledger(lpath, led)
    print(f"score: {hits} hit · {partials} partial · {misses} miss"
          + (f" · Brier {sum(brier)/len(brier):.3f}" if brier else ""))


def cmd_status(repo):
    _c, _m, lpath = load_cfg(repo)
    led = load_ledger(lpath)
    print(f"[{repo}] rounds {led['rounds']} · predictions {len(led['predictions'])} · learnings {len(led['learnings'])}")
    for p in led["predictions"]:
        print(f"  [{p['status']:>8}] ({p['made_on']}→{p['resolve_by']}) {p['claim'][:85]}")


def _post_analysis(repo):
    """Optional per-repo hook: watch.json {"post_analysis": "<suite>"} runs
    `python -m suites.<suite> --repo <repo>` after every predict/assess round
    (e.g. my-model_map re-maps the observed Mesh from each new round)."""
    import subprocess
    try:
        cfg, _m, _l = load_cfg(repo)
        suite = cfg.get("post_analysis")
        if not suite:
            return
        r = subprocess.run([sys.executable, "-m", f"suites.{suite}", "--repo", repo],
                           # The main instance is THIS repo, whatever the user named it.
                           # Hardcoding a directory name meant post_analysis
                           # silently failed on every install that followed
                           # SETUP.md and used a different one.
                           cwd=str(ROOT), timeout=900,
                           capture_output=True, text=True)
        for line in (r.stdout or "").strip().splitlines():
            print("  " + line)
        if r.returncode != 0:
            print(f"  [post_analysis {suite} failed] {(r.stderr or '').strip()[:200]}")
    except Exception as e:
        print("  [post_analysis skipped]", e)


def _auto_sync_public():
    import subprocess
    if os.environ.get("SKIP_AUTO_SYNC"):
        print("  [sync deferred to caller]"); return
    sl = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync_ledger.py")
    if not os.path.exists(sl):
        return
    try:
        r = subprocess.run([sys.executable, sl],
                           timeout=900, capture_output=True, text=True)
        for line in (r.stdout or "").strip().splitlines():
            print(line)
    except Exception as e:
        print("  [sync skipped]", e)


def main():
    # Load .env before any chat() call. Without this the backend
    # setting in .env is invisible and the suite reports 'no key'
    # while .env sits there correctly configured.
    from suites.grade_claims import _load_env
    _load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--predict", action="store_true")
    ap.add_argument("--assess", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--model", default=None)
    ap.add_argument("--horizon", type=int, default=45)
    a = ap.parse_args()
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        print("[note] no key and no claude-code backend"); return
    if a.assess:
        cmd_assess(a.repo, a.model); _post_analysis(a.repo); _auto_sync_public()
    elif a.status:
        cmd_status(a.repo)
    else:
        cmd_predict(a.repo, a.model, a.horizon); _post_analysis(a.repo); _auto_sync_public()


if __name__ == "__main__":
    main()
