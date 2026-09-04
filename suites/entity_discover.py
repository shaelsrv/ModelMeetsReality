"""Entity discovery — find what the fleet is already talking about but never registered.

Nine entities existed because a human typed nine slugs. The corpus names hundreds.
This proposes candidates from the artifacts themselves, so the atlas grows from what
the fleet studies rather than from what someone remembered to add.

Discrimination is the whole problem: "Hugging Face" and "FairSquare" are entities,
"Falsifiable" and "PRIVATE" are MODEL.md boilerplate that happens to be capitalised.
Filters, in order of what they catch:
  1. structural  — drop terms that appear mostly in headings, keys, or template
                   scaffolding (our own docs are the biggest noise source)
  2. dispersion  — a real entity appears across MULTIPLE repos and kinds; a local
                   heading appears in one place many times
  3. context     — entities co-occur with verbs of action/attribution, not with
                   "## " or ": {"
  4. LLM triage  — only the survivors, judged in one batch: is this a real-world
                   actor, and of what kind?

Proposals are written for review; --accept promotes them into the registry.

  python -m suites.entity_discover --scan            # propose candidates
  python -m suites.entity_discover --accept openai-rival,china
  python -m suites.entity_discover --accept-all --min-score 0.7
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from suites.memory_index import load_indexes  # noqa: E402

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
EDIR = TOOLS / "entity-atlas"
PROPOSALS = EDIR / "proposals.json"

# our own document furniture — the dominant false-positive source
BOILERPLATE = {
    "premises", "falsifiable", "deletion", "epistemic", "standing", "private",
    "operations", "consequences", "status", "statement", "model", "claim",
    "mechanism", "prediction", "evidence", "note", "context", "verdict",
    "confidence", "criteria", "resolution", "intact", "degraded", "both",
    "every", "other", "what", "when", "two", "all", "the", "kind", "premise",
    "brainstorm", "synthesis", "lens", "panel", "advocate", "librarian",
    "occam", "convergence", "tension", "crossed", "joint", "load", "weakest",
}
MONTHS = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept",
          "oct", "nov", "dec", "january", "february", "march", "april", "june",
          "july", "august", "september", "october", "november", "december"}

# Sentence-openers and connectives sail through capitalisation + dispersion filters
# BECAUSE they are common: "This" appeared in 20 repos, scoring 1.00. Dispersion
# measures entity-ness only among terms that are already plausible names, so the
# function-word class has to be removed before scoring, not by it.
FUNCTION_WORDS = {
    "this", "that", "these", "those", "there", "here", "each", "every", "some",
    "any", "many", "most", "much", "more", "less", "few", "both", "either",
    "neither", "such", "same", "other", "another", "before", "after", "during",
    "while", "since", "until", "unless", "although", "though", "because", "for",
    "nor", "yet", "so", "than", "then", "thus", "hence", "however", "moreover",
    "therefore", "otherwise", "instead", "rather", "also", "only", "even",
    "still", "already", "always", "never", "nothing", "nobody", "everything",
    "anything", "something", "someone", "everyone", "which", "who", "whom",
    "whose", "where", "why", "how", "what", "when", "whether", "not", "no",
    "within", "without", "across", "against", "between", "among", "under",
    "over", "above", "below", "through", "into", "onto", "upon", "from", "with",
    "about", "per", "via", "given", "based", "using", "including", "regarding",
    "registered", "section", "figure", "table", "appendix", "example", "note",
    "first", "second", "third", "next", "last", "new", "old", "same", "one",
}

TERM = re.compile(r"\b([A-Z][a-zA-Z&.\-]+(?:\s+[A-Z][a-zA-Z&.\-]+){0,3}|[A-Z]{2,6})\b")

TRIAGE = """Below are candidate entity names extracted from a research fleet's own artifacts.
Decide which are REAL-WORLD ENTITIES worth tracking in an entity atlas (companies, institutions,
markets, nations, people, named programs/products) versus artifacts of our own document
templates, section headings, generic nouns, dates, or jargon.

For each REAL entity give: slug (kebab-case), canonical name, kind
(company|institution|market|nation|person|program), and 2-5 aliases INCLUDING the form seen here.
Be strict — when unsure, reject. Rejecting a real entity costs little (it will reappear);
accepting boilerplate pollutes the atlas permanently.

CANDIDATES (name — how many fragments, how many repos, sample context):
{cands}

Return ONLY JSON:
{"entities":[{"slug":"...","name":"...","kind":"...","aliases":["..."],
"why":"one line: what makes this a real entity here"}],
"rejected":[{"name":"...","reason":"boilerplate|heading|date|generic|jargon|unclear"}]}"""


def scan(min_frags: int = 4, top: int = 60) -> list:
    rows = load_indexes()
    reg = json.load((EDIR / "entities.json").open(encoding="utf-8")) \
        if (EDIR / "entities.json").exists() else {}
    known = {a.lower() for e in reg.values() for a in e["aliases"]}
    known |= {e["name"].lower() for e in reg.values()}

    frag_count = Counter()
    repos = defaultdict(set)
    kinds = defaultdict(set)
    heading_hits = Counter()
    samples = {}

    for r in rows:
        text = r.get("text", "")
        seen = set()
        for m in TERM.finditer(text):
            name = m.group(1).strip()
            low = name.lower()
            if len(name) < 3 or low in MONTHS:
                continue
            words = low.split()
            # a name that IS a function word, or starts with one, is a sentence
            # opener rather than an entity ("This", "Within", "Each ...")
            if words[0] in FUNCTION_WORDS or low in FUNCTION_WORDS:
                continue
            if any(w in BOILERPLATE for w in words):
                continue
            if low in known or any(low in k or k in low for k in known):
                continue
            if name in seen:
                continue
            seen.add(name)
            frag_count[name] += 1
            repos[name].add(r["repo"])
            kinds[name].add(r["kind"])
            # structural signal: sitting right after a heading marker or as a JSON key
            before = text[max(0, m.start() - 4):m.start()]
            after = text[m.end():m.end() + 3]
            if "##" in before or before.strip().endswith('"') or after.startswith('":'):
                heading_hits[name] += 1
            if name not in samples:
                samples[name] = text[max(0, m.start() - 70):m.start() + 90]

    cands = []
    for name, n in frag_count.items():
        if n < min_frags:
            continue
        n_repos, n_kinds = len(repos[name]), len(kinds[name])
        head_ratio = heading_hits[name] / n
        if head_ratio > 0.5:                      # mostly structural = our own furniture
            continue
        if n_repos < 2 and n < 8:                 # local to one repo and rare = probably local
            continue
        # dispersion score: real entities spread across repos and artifact kinds
        score = min(n / 20, 1) * 0.4 + min(n_repos / 6, 1) * 0.4 + min(n_kinds / 4, 1) * 0.2
        cands.append({"name": name, "fragments": n, "repos": sorted(repos[name])[:6],
                      "n_repos": n_repos, "kinds": sorted(kinds[name])[:4],
                      "heading_ratio": round(head_ratio, 2),
                      "dispersion": round(score, 3),
                      "sample": re.sub(r"\s+", " ", samples[name])[:160]})
    cands.sort(key=lambda c: -c["dispersion"])
    return cands[:top]


def triage(cands: list, model: str) -> dict:
    from harness.openrouter import chat
    from harness.actors import parse_json
    listing = "\n".join(
        f"- {c['name']} — {c['fragments']} frags, {c['n_repos']} repos "
        f"({', '.join(c['repos'][:3])}); ctx: {c['sample'][:110]}"
        for c in cands)
    r = chat(model, [{"role": "user", "content": TRIAGE.replace("{cands}", listing[:12000])}],
             temperature=0.1, max_tokens=3000)
    d = parse_json(r.text) if not r.error else None
    if not d:
        raise SystemExit(f"triage failed: {r.error or 'unparseable'}")
    return d


def main():
    ap = argparse.ArgumentParser(description="Discover unregistered entities.")
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--raw", action="store_true", help="skip LLM triage; show raw candidates")
    ap.add_argument("--accept", help="comma-separated slugs from the proposals file")
    ap.add_argument("--accept-all", action="store_true")
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--min-frags", type=int, default=4)
    ap.add_argument("--model", default="anthropic/claude-sonnet-4")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()

    if a.accept or a.accept_all:
        if not PROPOSALS.exists():
            raise SystemExit("no proposals — run --scan first")
        props = json.load(PROPOSALS.open(encoding="utf-8"))
        regf = EDIR / "entities.json"
        reg = json.load(regf.open(encoding="utf-8")) if regf.exists() else {}
        want = None if a.accept_all else {s.strip() for s in a.accept.split(",")}
        added = []
        for e in props.get("entities", []):
            if want is not None and e["slug"] not in want:
                continue
            if e["slug"] in reg:
                continue
            reg[e["slug"]] = {"name": e["name"], "kind": e["kind"],
                              "aliases": e["aliases"], "discovered": True}
            added.append(e["slug"])
        regf.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"registered {len(added)}: {', '.join(added) or '(none)'}")
        print("  next: python -m suites.entities --build")
        return

    cands = scan(min_frags=a.min_frags)
    print(f"[discover] {len(cands)} candidates survived structural + dispersion filters")
    if a.raw:
        for c in cands[:40]:
            print(f"  {c['dispersion']:.2f}  {c['name']:<26} {c['fragments']:>3} frags · "
                  f"{c['n_repos']} repos · head={c['heading_ratio']}")
        return
    d = triage(cands, a.model)
    EDIR.mkdir(parents=True, exist_ok=True)
    d["scanned"] = datetime.date.today().isoformat()
    PROPOSALS.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  PROPOSED ({len(d.get('entities', []))}):")
    for e in d.get("entities", []):
        print(f"    {e['slug']:<24} {e['kind']:<12} {e['name']}")
        print(f"      aliases: {', '.join(e['aliases'][:5])}")
        print(f"      why: {e.get('why','')[:100]}")
    rej = d.get("rejected", [])
    if rej:
        by = Counter(r.get("reason", "?") for r in rej)
        print(f"\n  rejected {len(rej)}: " +
              ", ".join(f"{k} {v}" for k, v in by.most_common()))
    print(f"\n  -> {PROPOSALS}")
    print("  accept with: python -m suites.entity_discover --accept slug1,slug2")


if __name__ == "__main__":
    main()
