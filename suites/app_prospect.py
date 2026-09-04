"""Application prospector — explore what else the copilot harness could serve.

Implements application-model/MODEL.md: the harness pentad (register / seal / grade /
provenance / postmortem) is general (P1); applications are located by structural fit,
not topic (P2); every candidate carries an adoption bet (P3); deepening is legible
looping — recurrence with receipts, every pass appended to disk (P4, the anti-Astra).

  python -m suites.app_prospect --inventory
  python -m suites.app_prospect --prospect --n 3 [--seed 7]
  python -m suites.app_prospect --deepen --id <candidate> [--passes 3]
  python -m suites.app_prospect --list
"""
from __future__ import annotations

import argparse
import datetime
import json
import random
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
REPO = ROOT.parent / "application-model"
ADIR = REPO / "applications"
INV = REPO / "machinery.json"

USER_TYPES = ["investigative journalists", "equity/VC analysts", "policy advisors",
              "research lab PIs", "corporate strategy teams", "insurance underwriters",
              "NGO field monitors", "independent forecasters", "physicians (diagnostics)",
              "educators & students", "auditors & compliance officers", "product managers",
              "litigation teams", "grant-making foundations", "open-source maintainers",
              "city administrators", "security/threat-intel analysts", "individual decision-makers"]

DOMAINS = ["hiring & talent evaluation", "scientific replication", "public procurement",
           "media accountability", "startup theses", "clinical judgment",
           "policy impact evaluation", "supply-chain risk", "expert-witness credibility",
           "philanthropy outcomes", "editorial predictions", "M&A integration",
           "academic peer review", "election administration", "disaster preparedness",
           "product roadmaps", "regulatory forecasting", "personal career decisions"]

PROSPECT = """You are an application prospector for a private research harness whose core machinery is
a pentad: (1) claims REGISTERED before outcomes, (2) reasoning/mechanism SEALED at claim time and
disclosed only at grading, (3) scheduled GRADING against reality, (4) provenance + confidence on
every row, (5) POSTMORTEMS splitting earned hits from lucky ones. Plus supporting instruments:
structural classifiers, audience/resonance mapping, narrative-competition tracing, pre-registered
blind-spot lists, hunch tracking, and a candidate generator.

MACHINERY DETAIL:
{machinery}

THE DRAW (prospect exactly this intersection):
- User type: {user}
- Domain: {domain}

Apply the FOUR-CONDITION FIT TEST (score each 0-1 with one line of evidence-shaped reasoning):
A. implicit_predictions — do these users already make consequential predictions there?
B. resolution — do outcomes actually resolve observably, on what timescale?
C. no_loop — is there currently NO grading loop (or only a broken/gamed one)?
D. transfer_value — would a graded track record transfer value (hiring, funding, trust, pricing)?
E. wrongness_affordable — can these users afford to be SEEN being wrong? Fails when graded
   misses damage a relationship the user must keep (they grade entities they transact with) or a
   narrative they must control (their misses become evidence against them). Users who
   structurally prefer no receipts fail E no matter how well A-D score.

If total fit >= 3.2 (of 5) AND E >= 0.5, produce ONE application candidate: what the user would register, what grades
it, which machinery pieces map to which step, the smallest viable pilot, and the ADOPTION BET —
a falsifiable line naming who adopts and what observable shows it within ~12 months. Also name
the failure mode most likely to kill it (gaming, resolution ambiguity, incentive to not-register).
If fit < 2.5, say so and return the fit scores with candidate null — a clean miss is data.

Return ONLY JSON:
{"fit":{"implicit_predictions":0.0,"resolution":0.0,"no_loop":0.0,"transfer_value":0.0,
"wrongness_affordable":0.0,"notes":"one line each, semicolon-joined"},
"candidate":{"name":"short handle","what_registers":"...","what_grades_it":"...",
"machinery_map":"pentad piece -> step, one line","pilot":"smallest viable pilot",
"adoption_bet":"who adopts + the observable, falsifiable","kill_risk":"likeliest failure mode"}
 or null,
"honest_note":"weakest link"}"""

CRITIQUE = """You are pass {k} of a legible deepening loop on ONE application candidate. Your job is
to attack it, then either KILL it or STRENGTHEN it. Attack surfaces: is the adoption bet actually
falsifiable; would users game the register; does resolution really resolve; is the pilot truly
minimal; does anything here require capabilities the harness does not have; is there an incentive
for the target user to NOT want a track record (often fatal). Then revise.

THE CANDIDATE (with all prior passes):
{candidate}

Return ONLY JSON:
{"verdict":"strengthen|kill",
"attack":"the strongest objection this pass found, 2-3 lines",
"revision":{"name":"...","what_registers":"...","what_grades_it":"...","machinery_map":"...",
"pilot":"...","adoption_bet":"...","kill_risk":"..."} or null,
"weakest_link":"what remains weakest after this pass"}"""


def build_inventory() -> dict:
    suites = sorted((ROOT / "suites").glob("*.py"))
    caps = []
    for s in suites:
        head = s.read_text(encoding="utf-8", errors="replace").split('"""')
        if len(head) > 1:
            caps.append({"suite": s.stem, "does": head[1].strip().splitlines()[0][:160]})
    inv = {"built": datetime.date.today().isoformat(), "capabilities": caps}
    REPO.mkdir(exist_ok=True)
    INV.write_text(json.dumps(inv, ensure_ascii=False, indent=1), encoding="utf-8")
    return inv


def cmd_prospect(n: int, seed: int | None, model: str) -> None:
    ADIR.mkdir(parents=True, exist_ok=True)
    inv = json.load(INV.open(encoding="utf-8")) if INV.exists() else build_inventory()
    mach = "\n".join(f"- {c['suite']}: {c['does']}" for c in inv["capabilities"])[:4000]
    if seed is None:
        seed = random.SystemRandom().randrange(10**6)
    rng = random.Random(seed)
    today = datetime.date.today().isoformat()
    print(f"[prospect] seed={seed} · {n} draws · {model}")
    for i in range(n):
        user, domain = rng.choice(USER_TYPES), rng.choice(DOMAINS)
        p = (PROSPECT.replace("{machinery}", mach).replace("{user}", user)
             .replace("{domain}", domain))
        r = chat(model, [{"role": "user", "content": p}], temperature=0.6, max_tokens=2200)
        d = parse_json(r.text) if not r.error else None
        if not d:
            print(f"  draw {i+1} [{user} x {domain}]: failed ({r.error or 'unparseable'})")
            continue
        fit = d.get("fit", {})
        total = sum(float(fit.get(k, 0)) for k in
                    ("implicit_predictions", "resolution", "no_loop", "transfer_value",
                     "wrongness_affordable"))
        cid = f"app-{today}-s{seed}-{i+1}"
        row = {"id": cid, "prospected": today, "seed": seed, "user": user,
               "domain": domain, "fit": fit, "fit_total": round(total, 2),
               "candidate": d.get("candidate"), "honest_note": d.get("honest_note", ""),
               "passes": [], "status": "candidate" if d.get("candidate") else "no-fit"}
        (ADIR / f"{cid}.json").write_text(json.dumps(row, ensure_ascii=False, indent=1),
                                          encoding="utf-8")
        c = d.get("candidate")
        print(f"  [{cid}] {user} x {domain} · fit {total:.1f}/5 · "
              f"{'MISS (clean)' if not c else c.get('name','')}")
        if c:
            print(f"    registers: {c.get('what_registers','')[:95]}")
            print(f"    bet: {c.get('adoption_bet','')[:105]}")
            print(f"    kill risk: {c.get('kill_risk','')[:95]}")


def cmd_deepen(cid: str, passes: int, model: str) -> None:
    f = ADIR / f"{cid}.json"
    if not f.exists():
        raise SystemExit(f"no candidate {cid}")
    d = json.load(f.open(encoding="utf-8"))
    if not d.get("candidate"):
        raise SystemExit(f"{cid} was a no-fit miss — nothing to deepen")
    for k in range(len(d["passes"]) + 1, len(d["passes"]) + 1 + passes):
        p = CRITIQUE.replace("{k}", str(k)).replace(
            "{candidate}", json.dumps(d, ensure_ascii=False)[:9000])
        r = chat(model, [{"role": "user", "content": p}], temperature=0.4, max_tokens=2000)
        v = parse_json(r.text) if not r.error else None
        if not v:
            print(f"  pass {k}: failed ({r.error or 'unparseable'})")
            break
        # P4: append, never overwrite — the whole recurrence stays on disk
        d["passes"].append({"k": k, "date": datetime.date.today().isoformat(),
                            "verdict": v.get("verdict"), "attack": v.get("attack", ""),
                            "weakest_link": v.get("weakest_link", "")})
        print(f"  pass {k}: {v.get('verdict','?').upper()} — {v.get('attack','')[:100]}")
        if v.get("verdict") == "kill":
            d["status"] = "killed"
            print(f"    killed at pass {k}; prior state preserved")
            break
        if v.get("revision"):
            d["passes"][-1]["superseded_candidate"] = d["candidate"]
            d["candidate"] = v["revision"]
        print(f"    weakest now: {v.get('weakest_link','')[:100]}")
    f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {f} ({len(d['passes'])} passes on disk)")


def cmd_list() -> None:
    if not ADIR.exists():
        print("(no candidates)")
        return
    for f in sorted(ADIR.glob("*.json")):
        d = json.load(f.open(encoding="utf-8"))
        c = d.get("candidate") or {}
        print(f"  [{d.get('status','?'):>9}] {d['id']} · fit {d.get('fit_total','?')}/4 · "
              f"{len(d.get('passes', []))}p · {d.get('user','')} x {d.get('domain','')}")
        if c:
            print(f"      {c.get('name','')} — {c.get('adoption_bet','')[:90]}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Prospect applications of the copilot harness.")
    ap.add_argument("--inventory", action="store_true")
    ap.add_argument("--prospect", action="store_true")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int)
    ap.add_argument("--deepen", action="store_true")
    ap.add_argument("--id", default="")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4",
                    help="candidates steer the family's future — STRONG tier")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()
    import os
    if a.list:
        cmd_list(); return
    if a.inventory:
        inv = build_inventory()
        print(f"{len(inv['capabilities'])} capabilities -> {INV}")
        return
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")
    if a.prospect:
        cmd_prospect(a.n, a.seed, a.model)
    if a.deepen:
        if not a.id:
            raise SystemExit("--deepen needs --id")
        cmd_deepen(a.id, a.passes, a.model)


if __name__ == "__main__":
    main()
