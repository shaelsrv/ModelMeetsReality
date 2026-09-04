"""Empirical study pipeline — convert a model into a statistical hypothesis and test it.

Three stages, strictly ordered (family discipline: registration before data, data
before analysis, and the VERDICT is computed by pure Python — no LLM touches it):

  1. --formalize  : MODEL.md consequence -> pre-registered study (H0/H1, unit,
                    sampling frame, coding rules, registered test + alpha + min n,
                    confound guards incl. the mandatory documentary-density guard,
                    termination rule). Registrations are IMMUTABLE.
  2. --collect    : web-grounded data rows per the sampling frame (sources + dates
                    required per row; refusing to find data is a valid result).
  3. --analyze    : the registered statistic computed in pure Python (one/two-
                    proportion z, chi-square 2x2, Spearman, permutation) -> verdict
                    supported / refuted / insufficient-n, per the registered rule.

  python -m suites.empirical_study --formalize --repo fault-lines [--consequence 1]
  python -m suites.empirical_study --formalize --repo canon --card collective-action
  python -m suites.empirical_study --collect --repo canon --study st-...
  python -m suites.empirical_study --analyze --repo canon --study st-...
  python -m suites.empirical_study --list --repo canon
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import random
import re
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

FORMALIZE = """You are a methodologist converting ONE falsifiable consequence of a structural model into
a PRE-REGISTERED empirical study. Be conservative: operationalizations must be codable from public
sources by a stranger; prefer simple registered tests; make refutation genuinely reachable.

THE MODEL DOCUMENT:
{model}

TARGET CONSEQUENCE (formalize this one; if unclear, pick the most statistically testable): {target}

Produce the registration:
- h0 / h1: null and alternative, in plain words AND in terms of the test parameter.
- unit: what one observation is (an event, a fight, a launch, a market...).
- sampling_frame: how units are found WITHOUT outcome knowledge (the selection rule must not
  correlate with the DV — state how selection bias is avoided).
- iv / dv: variables with CODING RULES a blind coder could apply (categories or numeric, with
  thresholds). For proportion tests dv must code to 1/0.
- test: one of one_prop (params: p0, direction greater|less|two) | two_prop | chi2 |
  spearman | permutation. Choose the SIMPLEST adequate test.
- alpha: 0.05 unless justified otherwise. min_n: smallest sample for a meaningful verdict
  (justify in one line).
- confound_guards: 2-4 named guards, ALWAYS including a documentary-density guard (how you
  prevent the metric from tracking how well events are documented rather than what happened).
- termination_rule: when the study stops and what verdicts are possible.

Return ONLY JSON:
{"h0":"...","h1":"...","unit":"...","sampling_frame":"...",
"iv":{"name":"...","coding":"..."},"dv":{"name":"...","coding":"..."},
"test":{"type":"one_prop|two_prop|chi2|spearman|permutation","params":{"p0":0.5,"direction":"greater"}},
"alpha":0.05,"min_n":0,"min_n_why":"...",
"confound_guards":["..."],"termination_rule":"...","honest_note":"weakest link"}"""

COLLECT = """You have LIVE WEB ACCESS. Today is {today}. You are collecting data for a PRE-REGISTERED
study. Follow the registration EXACTLY — the sampling frame and coding rules are not yours to
improve. Every row needs a checkable source with a date. Finding fewer units than hoped is a
valid result; fabricating or stretching a coding is corruption.

REGISTRATION:
{reg}

ALREADY COLLECTED (do not duplicate these units):
{have}

Collect up to {batch} NEW units. Return ONLY JSON:
{"rows":[{"unit":"unique name","period":"when","iv":"coded value per rules","dv":"coded value per rules",
"source":"outlet/document + date","note":"one line of evidence"}],
"frame_note":"how you searched, and what the frame could NOT reach (selection honesty)"}"""


# ---------- pure-python statistics (no LLM beyond this point) ----------

def phi(x):  # standard normal CDF
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def p_from_z(z, direction):
    if direction == "greater":
        return 1.0 - phi(z)
    if direction == "less":
        return phi(z)
    return 2.0 * (1.0 - phi(abs(z)))


def _numeric(rows, field="dv"):
    """Parse a numeric field; excluded/uncodable rows are filtered and counted,
    never crashed on — the collector is allowed to log exclusions."""
    ok, dropped = [], 0
    for r in rows:
        try:
            v = float(str(r[field]).strip().split()[0])
            ok.append((r, v))
        except (ValueError, KeyError, IndexError):
            dropped += 1
    return ok, dropped


def one_prop(rows, params):
    parsed, dropped = _numeric(rows)
    xs = [int(v) for _r, v in parsed]
    n, k = len(xs), sum(xs)
    p0 = float(params.get("p0", 0.5))
    if n == 0:
        return None
    phat = k / n
    se = math.sqrt(p0 * (1 - p0) / n)
    z = (phat - p0) / se if se else 0.0
    return {"n": n, "k": k, "excluded": dropped, "estimate": round(phat, 3), "p0": p0,
            "z": round(z, 3),
            "p_value": round(p_from_z(z, params.get("direction", "two")), 4)}


def _groups(rows):
    gs = {}
    for r in rows:
        iv = str(r.get("iv", ""))
        if not iv or iv.lower().startswith(("n/a", "excluded")):
            continue
        gs.setdefault(iv, []).append(r)
    if len(gs) != 2:
        return None
    return list(gs.items())


def two_prop(rows, params):
    g = _groups(rows)
    if not g:
        return None
    (na_name, a), (nb_name, b) = g
    ka = sum(int(float(r["dv"])) for r in a)
    kb = sum(int(float(r["dv"])) for r in b)
    na, nb = len(a), len(b)
    p_pool = (ka + kb) / (na + nb)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / na + 1 / nb))
    z = ((ka / na) - (kb / nb)) / se if se else 0.0
    return {"n": na + nb, "groups": {na_name: f"{ka}/{na}", nb_name: f"{kb}/{nb}"},
            "z": round(z, 3), "p_value": round(p_from_z(z, params.get("direction", "two")), 4)}


def chi2_2x2(rows, params):
    r = two_prop(rows, {"direction": "two"})
    if r:
        r["note"] = "computed as two-proportion z (equivalent to 2x2 chi-square)"
    return r


def spearman(rows, params):
    def ranks(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(s):
            j = i
            while j + 1 < len(s) and v[s[j + 1]] == v[s[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for t in range(i, j + 1):
                rk[s[t]] = avg
            i = j + 1
        return rk
    try:
        xs = [float(r["iv"]) for r in rows]
        ys = [float(r["dv"]) for r in rows]
    except (ValueError, TypeError):
        return None
    n = len(xs)
    if n < 5:
        return None
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    rho = num / den if den else 0.0
    z = rho * math.sqrt(n - 1)
    return {"n": n, "rho": round(rho, 3), "z": round(z, 3),
            "p_value": round(p_from_z(z, params.get("direction", "two")), 4)}


def permutation(rows, params):
    g = _groups(rows)
    if not g:
        return None
    (na_name, a), (nb_name, b) = g
    try:
        va = [float(r["dv"]) for r in a]
        vb = [float(r["dv"]) for r in b]
    except (ValueError, TypeError):
        return None
    obs = sum(va) / len(va) - sum(vb) / len(vb)
    pool = va + vb
    rng = random.Random(20260909)  # fixed seed: analysis is reproducible
    hits = 0
    iters = 5000
    for _ in range(iters):
        rng.shuffle(pool)
        d = sum(pool[:len(va)]) / len(va) - sum(pool[len(va):]) / len(vb)
        if abs(d) >= abs(obs):
            hits += 1
    return {"n": len(pool), "groups": [na_name, nb_name], "mean_diff": round(obs, 4),
            "p_value": round(hits / iters, 4), "note": "two-sided permutation, 5000 iters, fixed seed"}


TESTS = {"one_prop": one_prop, "two_prop": two_prop, "chi2": chi2_2x2,
         "spearman": spearman, "permutation": permutation}


# ---------- stages ----------

def _model_text(repo: str, card: str | None):
    p = (TOOLS / repo / "models" / f"{card}.md") if card else (TOOLS / repo / "MODEL.md")
    if not p.exists():
        raise SystemExit(f"no model doc at {p}")
    return p.read_text(encoding="utf-8", errors="replace")[:9000]


def _sdir(repo: str):
    d = TOOLS / repo / "studies"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_formalize(repo, card, consequence, model):
    text = _model_text(repo, card)
    target = (f"consequence #{consequence}" if consequence else
              "the most statistically testable consequence")
    r = chat(model, [{"role": "user", "content":
                      FORMALIZE.replace("{model}", text).replace("{target}", target)}],
             temperature=0.2, max_tokens=2200)
    d = parse_json(r.text) if not r.error else None
    if not d or not d.get("h1") or d.get("test", {}).get("type") not in TESTS:
        raise SystemExit(f"formalize failed: {r.error or 'unparseable/unknown test'}")
    sid = f"st-{datetime.date.today().isoformat()}-{card or repo}"
    f = _sdir(repo) / f"{sid}.registration.json"
    if f.exists():
        raise SystemExit(f"{f.name} exists — registrations are immutable; new study, new day/slug")
    d.update({"id": sid, "repo": repo, "card": card,
              "registered_on": datetime.date.today().isoformat(), "status": "registered"})
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{sid}] REGISTERED — {d['test']['type']} · alpha {d['alpha']} · min n {d['min_n']}")
    print(f"  H0: {d['h0'][:100]}")
    print(f"  H1: {d['h1'][:100]}")
    print(f"  unit: {d['unit'][:90]}")
    print(f"  guards: {'; '.join(g[:50] for g in d.get('confound_guards', []))}")
    print(f"  weakest: {d.get('honest_note','')[:100]}")
    print(f"-> {f}")


def cmd_collect(repo, sid, batch, model):
    reg_f = _sdir(repo) / f"{sid}.registration.json"
    reg = json.load(reg_f.open(encoding="utf-8"))
    data_f = _sdir(repo) / f"{sid}.data.jsonl"
    have = []
    if data_f.exists():
        have = [json.loads(l)["unit"] for l in data_f.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    p = (COLLECT.replace("{today}", datetime.date.today().isoformat())
         .replace("{reg}", json.dumps({k: reg[k] for k in
                  ("h0", "h1", "unit", "sampling_frame", "iv", "dv", "confound_guards")},
                  ensure_ascii=False))
         .replace("{have}", ", ".join(have[:60]) or "(none)")
         .replace("{batch}", str(batch)))
    r = chat(model + ":online", [{"role": "user", "content": p}],
             temperature=0.2, max_tokens=3500)
    d = parse_json(r.text) if not r.error else None
    if not d:
        raise SystemExit(f"collect failed: {r.error or 'unparseable'}")
    rows = [x for x in d.get("rows", []) if x.get("unit") and x["unit"] not in have]
    with data_f.open("a", encoding="utf-8") as f:
        for x in rows:
            x["collected"] = datetime.date.today().isoformat()
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    reg["status"] = "collecting"
    reg_f.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[{sid}] +{len(rows)} rows (total {len(have) + len(rows)}, min_n {reg['min_n']})")
    for x in rows[:8]:
        print(f"  {x['unit'][:44]:<46} iv={str(x['iv'])[:16]:<18} dv={str(x['dv'])[:12]} ({x.get('source','')[:40]})")
    print(f"  frame note: {d.get('frame_note','')[:130]}")


def cmd_analyze(repo, sid):
    reg_f = _sdir(repo) / f"{sid}.registration.json"
    reg = json.load(reg_f.open(encoding="utf-8"))
    data_f = _sdir(repo) / f"{sid}.data.jsonl"
    rows = [json.loads(l) for l in data_f.read_text(encoding="utf-8").splitlines()
            if l.strip()] if data_f.exists() else []
    t = reg["test"]
    res = TESTS[t["type"]](rows, t.get("params", {})) if rows else None
    if not res or res["n"] < reg["min_n"]:
        verdict = "insufficient-n"
    else:
        verdict = "H1 supported" if res["p_value"] < reg["alpha"] else "H0 retained (H1 not supported)"
    reg["status"] = "analyzed"
    reg["verdict"] = verdict
    reg["result"] = res
    reg["analyzed_on"] = datetime.date.today().isoformat()
    reg_f.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
    L = [f"# Study {sid} — result", f"Analyzed {reg['analyzed_on']} · registered {reg['registered_on']}",
         "", f"**H0:** {reg['h0']}", f"**H1:** {reg['h1']}", "",
         f"**Registered test:** {t['type']} {json.dumps(t.get('params', {}))} · alpha {reg['alpha']} · min n {reg['min_n']}",
         f"**Data:** {len(rows)} rows", f"**Statistic:** {json.dumps(res)}",
         f"## VERDICT: {verdict}", "",
         "Analysis is pure computation on pre-registered rules; the registration was "
         "immutable before data collection began. Guards: " + "; ".join(reg.get("confound_guards", []))]
    out = _sdir(repo) / f"{sid}.results.md"
    out.write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:12]))
    print(f"-> {out}")


def cmd_list(repo):
    for f in sorted(_sdir(repo).glob("*.registration.json")):
        d = json.load(f.open(encoding="utf-8"))
        print(f"  [{d.get('status','?'):>12}] {d['id']} · {d['test']['type']} · "
              f"{d.get('verdict','')} — H1: {d['h1'][:70]}")


def main():
    ap = argparse.ArgumentParser(description="Model -> statistical hypothesis -> empirical study.")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--card", help="canon card slug (models/<card>.md) instead of MODEL.md")
    ap.add_argument("--consequence", type=int)
    ap.add_argument("--formalize", action="store_true")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--study", help="study id (st-...)")
    ap.add_argument("--batch", type=int, default=8,
                    help="small batches: careful sourcing yields ~3-6 rows per call")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="registrations + data land on disk — STRONG tier")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.list:
        cmd_list(a.repo); return
    if a.analyze:
        if not a.study:
            raise SystemExit("--analyze needs --study")
        cmd_analyze(a.repo, a.study); return   # no LLM needed
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    if a.formalize:
        cmd_formalize(a.repo, a.card, a.consequence, a.model)
    if a.collect:
        if not a.study:
            raise SystemExit("--collect needs --study")
        cmd_collect(a.repo, a.study, a.batch, a.model)


if __name__ == "__main__":
    main()
