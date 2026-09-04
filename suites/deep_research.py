"""Deep research — budget-driven, evidence-ledgered, adversarially checked.

Not "search once and summarize". A question tree with an evidence ledger, run in
rounds until the BUDGET is spent or the well runs dry, then passed through the
family's challenge panel before anything is concluded.

  1. PLAN      — decompose the question into sub-questions, each with a STATED
                 EXPECTATION recorded before searching (so surprise is measurable
                 and "found nothing" is distinguishable from "found the expected").
  2. GATHER    — per sub-question, web-grounded evidence rows: fragment, source,
                 date, type (primary/secondary/analysis), reliability.
  3. DEEPEN    — fetch full text of the highest-value sources (article/paper/
                 transcript) and extract claim structure, not a summary.
  4. RECONCILE — cross-check rows; CONTRADICTIONS are first-class output with a
                 named decider (what observation would settle it).
  5. GAP       — what the round failed to answer becomes next round's questions.
  6. Repeat while budget remains AND fresh-evidence yield stays above threshold.
  7. CHALLENGE — devil's advocate + base-rate librarian + Occam over the findings.
  8. EMIT      — evidence ledger, findings, candidate claims, named gaps.

Modes: --question (open) | --entity <slug> (research a dossier's blind spots)
       | --gap (research an empty map region for new models) | --source <path|url>
       (ingest a paper/book/transcript and extract its model)

Budget is in CALLS (each ~1 LLM call or 1 fetch). Every run reports spend.

  python -m suites.deep_research --entity openai --budget 25
  python -m suites.deep_research --question "..." --budget 40
  python -m suites.deep_research --source https://arxiv.org/abs/... --budget 15
  python -m suites.deep_research --list
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
TOOLS = ROOT.parent
RDIR = ROOT / "research"


class Budget:
    """Calls are the currency. Every LLM call and every fetch costs 1."""

    def __init__(self, total: int):
        self.total = total
        self.spent = 0
        self.log = []

    def can(self, n: int = 1) -> bool:
        return self.spent + n <= self.total

    def charge(self, what: str, n: int = 1) -> None:
        self.spent += n
        self.log.append({"what": what, "n": n, "running": self.spent})

    @property
    def left(self) -> int:
        return max(0, self.total - self.spent)


PLAN = """You are planning a DEEP RESEARCH run. Decompose the question into sub-questions that can
each be answered by evidence, not opinion. For EACH sub-question state what you EXPECT to find
BEFORE searching — this is recorded and compared to what is actually found, so that "surprise" is
measurable and "found nothing" is distinguishable from "found what we expected".

THE QUESTION: {question}
{context}

Rules: 3-6 sub-questions; each must name the KIND of source that would answer it (primary
document, filing/docket, paper, reporting, dataset); order them by what unlocks the others.

Return ONLY JSON:
{"sub_questions":[{"id":"q1","question":"...","expect":"what you expect to find, one line",
"source_kind":"primary|filing|paper|reporting|dataset","why_it_matters":"one line"}],
"stop_condition":"one line: what would make further research unnecessary"}"""

GATHER = """You have LIVE WEB ACCESS. Today is {today}. Answer ONE sub-question with EVIDENCE ROWS —
not prose. Each row is one findable fact with its source and date. Prefer primary documents over
reporting about them. If you cannot find evidence, return an empty rows list and say why in
`search_note` — an honest empty result is required, never filler.

SUB-QUESTION: {q}
WE EXPECTED: {expect}
PREFERRED SOURCE KIND: {kind}
ALREADY HAVE (do not duplicate): {have}

Return ONLY JSON:
{"rows":[{"fragment":"the specific fact or claim found, one or two sentences",
"source":"outlet/document name","date":"YYYY-MM-DD or period","url":"if known",
"type":"primary|secondary|analysis","reliability":"high|medium|low",
"why_reliable":"one line"}],
"answered":"yes|partly|no","surprise":"how what you found differs from what we expected, one line",
"search_note":"where you looked; what you could NOT reach"}"""

DEEPEN = """You are reading ONE source in full, not skimming it. Extract its CLAIM STRUCTURE — what
it asserts, what it rests on, and what it does not address. Do not summarize the prose; map the
argument.

SOURCE: {name}
CONTENT (may be truncated):
{content}

Return ONLY JSON:
{"central_claims":["the source's own load-bearing assertions"],
"evidence_offered":["what it presents as support"],
"reasoning":"2-3 lines: how it gets from evidence to claims",
"omissions":["what a careful reader notices it does NOT address"],
"falsifiable_commitments":["any statement it makes that could be checked against reality"],
"quality":"how much weight this source deserves and why, one line"}"""

RECONCILE = """You are reconciling an evidence ledger. Your job is NOT to average sources into a
consensus — it is to find where they CONFLICT and say what would settle it.

THE QUESTION: {question}
EVIDENCE LEDGER:
{ledger}

Produce:
- findings: what the evidence actually supports, each tagged with the row sources backing it.
- contradictions: where rows genuinely conflict — state both sides and a DECIDER (the observation
  that would settle it). Contradictions are output, not noise.
- density_check: does any finding correlate with how heavily a topic is COVERED rather than with
  evidence quality? (the documentary-density confound — name it if present.)
- gaps: what remains unanswered, phrased as next-round sub-questions.

Return ONLY JSON:
{"findings":[{"finding":"...","support":["source names"],"confidence":"high|medium|low"}],
"contradictions":[{"sides":"A says X; B says Y","decider":"what would settle it"}],
"density_check":"one line","gaps":["next-round sub-questions"],
"yield":"how much this round added: high|moderate|low|dry"}"""

CONCLUDE = """You are closing a deep research run. The findings below survived an evidence ledger and
a reconciliation pass, and have just been challenged by an adversarial panel. Produce the final
artifacts.

QUESTION: {question}
FINDINGS: {findings}
CHALLENGE PANEL: {panel}

Produce:
- conclusions: what we now believe, each with its confidence AND what the panel conceded/rebutted.
- candidate_claims: 1-3 registrable claims this research makes possible (criteria + date), or
  empty if the research does not support any.
- model_seeds: any RECURRING MECHANISM noticed that could become a model (or empty).
- remaining_gaps: what still is not known, and what it would take.
- honest_note: the weakest link in this entire run.

Return ONLY JSON:
{"conclusions":[{"conclusion":"...","confidence":"high|medium|low","panel_effect":"..."}],
"candidate_claims":[{"claim":"...","resolution_criteria":"...","resolve_by":"YYYY-MM-DD","confidence":0.0}],
"model_seeds":[{"name":"...","mechanism":"..."}],
"remaining_gaps":["..."],"honest_note":"..."}"""

PANEL = """Challenge these research findings. You are three voices at once — answer as all three.

QUESTION: {question}
FINDINGS: {findings}

Return ONLY JSON:
{"devils_advocate":{"shared_prior":"what could make all these sources agree without being true",
"counter_case":"the strongest argument the findings are wrong"},
"librarian":{"reference_class":"what class of situations this belongs to","base_rate":"what usually happens",
"outside_view":"what the base rate alone predicts"},
"occam":{"boring_explanation":"the simplest sufficient account","where_boring_loses":"what would force the richer reading"}}"""


def fetch_text(url: str) -> str:
    """Best-effort full-text fetch: youtube transcript, else article text."""
    try:
        if re.search(r"youtu\.?be", url):
            out = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--no-update", "--skip-download",
                 "--write-auto-sub", "--sub-lang", "en", "--convert-subs", "srt",
                 "-o", str(RDIR / "_tmp"), url],
                capture_output=True, text=True, timeout=180)
            f = RDIR / "_tmp.en.srt"
            if f.exists():
                t = f.read_text(encoding="utf-8", errors="replace")
                f.unlink()
                lines, seen = [], set()
                for l in t.splitlines():
                    l = l.strip()
                    if not l or l.isdigit() or "-->" in l or l in seen:
                        continue
                    seen.add(l)
                    lines.append(l)
                return " ".join(lines)
            return ""
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=45) as r:
            html = r.read().decode("utf-8", errors="replace")
        html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.S)
        html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.S)
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    except Exception as e:
        return f"(fetch failed: {str(e)[:120]})"


def _entity_context(slug: str) -> tuple[str, str]:
    f = TOOLS / "entity-atlas" / "dossiers" / f"{slug}.json"
    if not f.exists():
        return f"What have we not understood about {slug}?", ""
    d = json.load(f.open(encoding="utf-8"))
    syn = d.get("synthesis") or {}
    blind = syn.get("blind_spots", [])
    q = (f"What can be established about {d['name']} in the areas the fleet has "
         f"NOT modeled: {'; '.join(blind[:4]) if blind else 'unknown'}?")
    ctx = (f"CONTEXT — existing dossier confidence: {syn.get('confidence','none')}. "
           f"Known blind spots: {json.dumps(blind[:6], ensure_ascii=False)}. "
           f"Do NOT re-establish what the fleet already has; target the gaps.")
    return q, ctx


def run(question: str, context: str, budget: Budget, slug: str, llm: str,
        min_yield: int = 2) -> dict:
    RDIR.mkdir(exist_ok=True)
    wdir = RDIR / slug
    wdir.mkdir(exist_ok=True)
    today = datetime.date.today().isoformat()
    ledger_f = wdir / "evidence.jsonl"
    ledger: list = []
    # declared before flush() so a checkpoint at any stage has something to write
    plan_holder: dict = {}
    rounds: list = []
    all_findings: list = []
    all_contradictions: list = []
    deepened: list = []

    def flush(stage: str, extra: dict | None = None) -> None:
        """Checkpoint after every stage — an interrupted run keeps what it earned."""
        with ledger_f.open("w", encoding="utf-8") as f:
            for row in ledger:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        snap = {"slug": slug, "question": question, "at": today, "stage": stage,
                "budget": {"total": budget.total, "spent": budget.spent, "log": budget.log},
                "plan": plan_holder.get("plan"), "rounds": rounds,
                "evidence_count": len(ledger), "deep_reads": len(deepened),
                "contradictions": all_contradictions, "findings": all_findings,
                **(extra or {})}
        (wdir / "run.json").write_text(json.dumps(snap, ensure_ascii=False, indent=1),
                                       encoding="utf-8")

    def ask(prompt: str, online: bool = False, max_tokens: int = 1800, label: str = "call"):
        if not budget.can():
            return None
        budget.charge(label)
        r = chat(llm + (":online" if online else ""),
                 [{"role": "user", "content": prompt}],
                 temperature=0.3, max_tokens=max_tokens)
        return parse_json(r.text) if not r.error else None

    # 1. PLAN
    plan = ask(PLAN.replace("{question}", question).replace("{context}", context),
               label="plan")
    if not plan:
        raise SystemExit("planning failed (or budget too small)")
    print(f"[plan] {len(plan['sub_questions'])} sub-questions · stop: "
          f"{plan.get('stop_condition','')[:90]}")
    plan_holder["plan"] = plan
    queue = list(plan["sub_questions"])
    flush("planned")

    rnd = 0
    while queue and budget.can(2):
        rnd += 1
        batch = queue[:3]
        queue = queue[3:]
        print(f"\n[round {rnd}] {len(batch)} sub-question(s) · budget left {budget.left}")

        # 2. GATHER (parallel, budget-checked)
        def gather_one(q):
            have = "; ".join(r["fragment"][:60] for r in ledger[-12:])
            return q, ask(GATHER.replace("{today}", today)
                          .replace("{q}", q["question"])
                          .replace("{expect}", q.get("expect", ""))
                          .replace("{kind}", q.get("source_kind", "any"))
                          .replace("{have}", have or "(nothing yet)"),
                          online=True, max_tokens=2200, label=f"gather:{q['id']}")

        n_before = len(ledger)
        with ThreadPoolExecutor(max_workers=3) as ex:
            for q, res in ex.map(gather_one, batch):
                if not res:
                    continue
                for row in res.get("rows", []):
                    row["sub_question"] = q["id"]
                    row["round"] = rnd
                    ledger.append(row)
                print(f"  {q['id']}: {len(res.get('rows', []))} rows · "
                      f"answered={res.get('answered','?')} · "
                      f"surprise: {res.get('surprise','')[:70]}")
                if res.get("search_note"):
                    print(f"      note: {res['search_note'][:100]}")
        fresh = len(ledger) - n_before

        # 3. DEEPEN — full-text read of the best unread source with a url
        for row in ledger[n_before:]:
            if not budget.can(2) or row.get("url", "") in deepened:
                continue
            if row.get("reliability") == "high" and row.get("url", "").startswith("http"):
                budget.charge(f"fetch:{row['source'][:20]}")
                content = fetch_text(row["url"])[:12000]
                if len(content) > 500:
                    d = ask(DEEPEN.replace("{name}", row["source"])
                            .replace("{content}", content), max_tokens=1600,
                            label=f"deepen:{row['source'][:20]}")
                    if d:
                        d["source"] = row["source"]
                        deepened.append(row["url"])
                        row["deep_read"] = True
                        print(f"  [deep] {row['source'][:40]}: "
                              f"{len(d.get('central_claims', []))} claims, "
                              f"{len(d.get('omissions', []))} omissions")
                break  # one deep read per round keeps budget predictable

        # 4. RECONCILE
        rec = ask(RECONCILE.replace("{question}", question)
                  .replace("{ledger}", json.dumps(ledger[-40:], ensure_ascii=False)[:11000]),
                  max_tokens=2000, label=f"reconcile:r{rnd}")
        if rec:
            all_findings.extend(rec.get("findings", []))
            all_contradictions.extend(rec.get("contradictions", []))
            print(f"  reconcile: {len(rec.get('findings', []))} findings, "
                  f"{len(rec.get('contradictions', []))} contradictions · "
                  f"yield={rec.get('yield','?')}")
            if rec.get("density_check"):
                print(f"      density: {rec['density_check'][:110]}")
            rounds.append({"round": rnd, "fresh_rows": fresh, **rec})
            flush(f"round-{rnd}")
            # 5. GAP -> next round, while the well is not dry
            if rec.get("yield") not in ("dry", "low") and fresh >= min_yield:
                for i, g in enumerate(rec.get("gaps", [])[:3]):
                    queue.append({"id": f"r{rnd}g{i+1}", "question": g,
                                  "expect": "(gap-driven; no prior expectation)",
                                  "source_kind": "any"})
            else:
                print(f"  [stop] yield {rec.get('yield')} / fresh {fresh} — well is dry")
                break

    flush("gathering-done")
    # 7. CHALLENGE
    panel = ask(PANEL.replace("{question}", question)
                .replace("{findings}", json.dumps(all_findings, ensure_ascii=False)[:6000]),
                max_tokens=1400, label="panel") or {}
    # 8. CONCLUDE
    concl = ask(CONCLUDE.replace("{question}", question)
                .replace("{findings}", json.dumps(all_findings, ensure_ascii=False)[:6000])
                .replace("{panel}", json.dumps(panel, ensure_ascii=False)[:3000]),
                max_tokens=2000, label="conclude") or {}
    flush("concluded", {"panel": panel, "conclusions": concl})

    out = {"slug": slug, "question": question, "at": today,
           "budget": {"total": budget.total, "spent": budget.spent, "log": budget.log},
           "plan": plan, "rounds": rounds, "evidence_count": len(ledger),
           "deep_reads": len(deepened), "contradictions": all_contradictions,
           "panel": panel, "conclusions": concl}
    (wdir / "run.json").write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    _write_md(wdir, out)
    return out


def _write_md(wdir: Path, out: dict) -> None:
    c = out.get("conclusions", {})
    L = [f"# Deep research — {out['question'][:120]}",
         f"{out['at']} · budget {out['budget']['spent']}/{out['budget']['total']} calls · "
         f"{out['evidence_count']} evidence rows · {out['deep_reads']} full-text reads", ""]
    if c.get("conclusions"):
        L.append("## Conclusions")
        for x in c["conclusions"]:
            L.append(f"- **[{x.get('confidence','?')}]** {x.get('conclusion','')}")
            if x.get("panel_effect"):
                L.append(f"  - panel: {x['panel_effect']}")
    if out.get("contradictions"):
        L += ["", "## Contradictions (unresolved)"]
        for x in out["contradictions"]:
            L.append(f"- {x.get('sides','')} → **decider:** {x.get('decider','')}")
    p = out.get("panel", {})
    if p:
        L += ["", "## Challenge panel"]
        if p.get("devils_advocate"):
            L.append(f"- **Devil's advocate** — shared prior: "
                     f"{p['devils_advocate'].get('shared_prior','')} · counter-case: "
                     f"{p['devils_advocate'].get('counter_case','')}")
        if p.get("librarian"):
            L.append(f"- **Librarian** — class: {p['librarian'].get('reference_class','')} · "
                     f"base rate: {p['librarian'].get('base_rate','')} · outside view: "
                     f"{p['librarian'].get('outside_view','')}")
        if p.get("occam"):
            L.append(f"- **Occam** — {p['occam'].get('boring_explanation','')} · loses if: "
                     f"{p['occam'].get('where_boring_loses','')}")
    if c.get("candidate_claims"):
        L += ["", "## Candidate claims"]
        for x in c["candidate_claims"]:
            L.append(f"- ({x.get('confidence','?')}, by {x.get('resolve_by','?')}) "
                     f"{x.get('claim','')}\n  - criteria: {x.get('resolution_criteria','')}")
    if c.get("model_seeds"):
        L += ["", "## Model seeds"]
        for x in c["model_seeds"]:
            L.append(f"- **{x.get('name','')}** — {x.get('mechanism','')}")
    if c.get("remaining_gaps"):
        L += ["", "## Still unknown"] + [f"- {g}" for g in c["remaining_gaps"]]
    L += ["", f"_Weakest link: {c.get('honest_note','')}_"]
    (wdir / "REPORT.md").write_text("\n".join(L), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="Budget-driven deep research.")
    ap.add_argument("--question")
    ap.add_argument("--entity")
    ap.add_argument("--source")
    ap.add_argument("--slug")
    ap.add_argument("--budget", type=int, default=25, help="max LLM calls + fetches")
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        if RDIR.exists():
            for d in sorted(RDIR.iterdir()):
                f = d / "run.json"
                if f.exists():
                    r = json.load(f.open(encoding="utf-8"))
                    print(f"  [{r['at']}] {r['slug']:<24} {r['budget']['spent']:>3} calls · "
                          f"{r['evidence_count']:>3} rows · {r['question'][:60]}")
        return

    from suites.grade_claims import _load_env
    _load_env()
    import os
    if not (os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("LLM_BACKEND") == "claude-code"):
        raise SystemExit("no key and no claude-code backend")

    context = ""
    if a.entity:
        question, context = _entity_context(a.entity)
        slug = a.slug or f"entity-{a.entity}"
    elif a.source:
        question = f"What model does this source contain, and what does it commit to? ({a.source})"
        context = "SOURCE MODE: read the source itself first; its claims are the evidence."
        slug = a.slug or "source-" + re.sub(r"[^a-z0-9]+", "-",
                                            a.source.lower())[-40:].strip("-")
    elif a.question:
        question = a.question
        slug = a.slug or re.sub(r"[^a-z0-9]+", "-", a.question.lower())[:40].strip("-")
    else:
        raise SystemExit("need --question, --entity, or --source")

    b = Budget(a.budget)
    print(f"[deep-research] budget {a.budget} calls · {slug}")
    out = run(question, context, b, slug, a.model)
    c = out.get("conclusions", {})
    print(f"\n=== spent {b.spent}/{b.total} · {out['evidence_count']} rows · "
          f"{out['deep_reads']} deep reads ===")
    for x in c.get("conclusions", [])[:6]:
        print(f"  [{x.get('confidence','?')}] {x.get('conclusion','')[:150]}")
    if out.get("contradictions"):
        print(f"  contradictions: {len(out['contradictions'])}")
    print(f"-> research/{slug}/REPORT.md")


if __name__ == "__main__":
    main()
