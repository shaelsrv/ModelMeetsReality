"""Associative memory — per-repo embedding indexes and spreading-activation recall.

The fleet is a distributed mind, not a database. Each model repo owns its own
index (index.jsonl, next to its artifacts); recall fans out across repos, asks
each "what do you have near this cue?", and merges. No central store: an index
travels with its model, so a contributor can ship one alongside a mapcard and the
commons can recall across instances it never crawled.

Retrieval is deliberately memory-shaped:
  · cue -> vector similarity (the "feeling of knowing"), cheap, top-k per repo
  · spreading activation: strong hits activate their co-occurrence neighbours,
    so an artifact that never names OpenAI but sits beside three that do is found
  · lossy by design — a little recall loss is acceptable, EXCEPT for graded
    outcomes, refutations, and tombstones, which are pinned and never decay

Backends (EMBED_BACKEND): "local" (sentence-transformers, default, nothing
leaves the machine) | "openrouter" (API; faster, needs a key).

  python -m suites.memory_index --build            # index every repo
  python -m suites.memory_index --build --repo my-model
  python -m suites.memory_index --recall "what do we know about OpenAI's finances"
  python -m suites.memory_index --stats
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
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
TOOLS = ROOT.parent
INDEX_NAME = "index.jsonl"

# fragments carrying verdicts are pinned: evidence may fade, verdicts may not
PINNED_KINDS = {"graded_claim", "refutation", "postmortem", "attribution", "study_result"}

_model_cache = {}

CHUNK = 900          # chars per fragment — one idea, not one document
OVERLAP = 150        # carry-over so an idea split across a boundary is still findable

# Scale guards. The rule: never silently drop content. Anything skipped is
# COUNTED and reported, so "we indexed everything" is a checkable claim rather
# than an assumption that quietly stops being true as the fleet grows.
MAX_FILE_BYTES = 2_000_000    # refuse absurd files (data dumps, bundles), report them
MAX_CHUNKS_PER_DOC = 400      # ~360k chars of one artifact; beyond this, report and stop
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
             "build", "static", "media", ".next", "site-packages"}
_skipped: list = []           # (path, reason, size) — surfaced in --build output


def chunk_text(text: str, limit: int = CHUNK, overlap: int = OVERLAP) -> list[str]:
    """Split long artifacts into overlapping passages.

    Whole-document embedding was the original bug: a vector averaging eight lens
    reads matches no single question well, and truncation silently discarded most
    of every long artifact. Prefer splitting on structure (markdown headings,
    blank lines) and fall back to hard slicing.
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return [text] if len(text) >= 40 else []
    if len(text) > MAX_CHUNKS_PER_DOC * limit:
        _skipped.append(("(oversized artifact)", "truncated to chunk cap", len(text)))
        text = text[:MAX_CHUNKS_PER_DOC * limit]
    parts, buf = [], ""
    for piece in re.split(r"(?=##\s)|(?<=\.)\s(?=[A-Z])", text):
        if len(buf) + len(piece) <= limit:
            buf += (" " if buf else "") + piece
        else:
            if len(buf) >= 40:
                parts.append(buf)
            buf = (buf[-overlap:] + " " + piece) if buf else piece
            while len(buf) > limit:                      # a single huge piece
                parts.append(buf[:limit])
                buf = buf[limit - overlap:]
    if len(buf) >= 40:
        parts.append(buf)
    return parts


def _readable(f: Path) -> bool:
    """Gate a file into the index. Skips are RECORDED, never silent."""
    if any(part in SKIP_DIRS for part in f.parts):
        return False
    try:
        sz = f.stat().st_size
    except OSError:
        return False
    if sz > MAX_FILE_BYTES:
        _skipped.append((f.as_posix()[-60:], "over size limit", sz))
        return False
    return True


def _embed_local(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer
    if "local" not in _model_cache:
        name = os.environ.get("EMBED_MODEL", "all-MiniLM-L6-v2")
        _model_cache["local"] = SentenceTransformer(name)
    m = _model_cache["local"]
    return [list(map(float, v)) for v in m.encode(texts, normalize_embeddings=True,
                                                  show_progress_bar=False)]


def _embed_openrouter(texts: list[str]) -> list[list[float]]:
    import urllib.request
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("EMBED_BACKEND=openrouter needs OPENROUTER_API_KEY")
    model = os.environ.get("EMBED_MODEL", "openai/text-embedding-3-small")
    out = []
    for i in range(0, len(texts), 64):
        body = json.dumps({"model": model, "input": texts[i:i + 64]}).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/embeddings", data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.loads(r.read().decode())
        for row in d["data"]:
            v = row["embedding"]
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
    return out


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    backend = os.environ.get("EMBED_BACKEND", "local")
    return _embed_openrouter(texts) if backend == "openrouter" else _embed_local(texts)


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))          # vectors are normalized


# ---------- fragment extraction: what a repo remembers ----------

def fragments(repo: Path) -> list[dict]:
    """One fragment per rememberable thing. Kind drives pinning and weighting."""
    out = []
    name = repo.name

    def add(kind, text, meta=None):
        for i, part in enumerate(chunk_text(text)):
            out.append({"repo": name, "kind": kind, "text": part,
                        **({"chunk": i} if i else {}), **(meta or {})})

    mm = repo / "MODEL.md"
    if mm.exists():
        doc = mm.read_text(encoding="utf-8", errors="replace")
        for sec in re.split(r"\n(?=##\s)", doc):
            head = sec.splitlines()[0].strip("# ").strip() if sec.strip() else ""
            add("model_doc", sec, {"section": head[:60]})

    for rel in ("predict/ledger.json", "predict/live_ledger.json",
                "signals/signal_ledger.json", "brainstorms/ledger.json"):
        f = repo / rel
        if not f.exists():
            continue
        try:
            d = json.load(f.open(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for r in (d.get("predictions", d) if isinstance(d, dict) else d):
            st = r.get("status", "open")
            add("graded_claim" if st not in ("open", "?") else "open_claim",
                f"{r.get('claim','')} {r.get('mechanism','')} {r.get('what_happened','')}",
                {"status": st, "resolve_by": r.get("resolve_by", ""),
                 "entity": r.get("entity", "")})

    for sub, kind in (("traces", "trace"), ("registrations", "registration"),
                      ("studies", "study_result"), ("dossiers", "dossier"),
                      ("trials", "trial"), ("dissections", "dissection")):
        d = repo / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):          # no file-count cap: index it all
            if not _readable(f):
                continue
            try:
                j = json.load(f.open(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            add(kind, json.dumps(j, ensure_ascii=False), {"file": f.name})
        for f in sorted(d.glob("*.md")):
            if not _readable(f):
                continue
            add(kind, f.read_text(encoding="utf-8", errors="replace"), {"file": f.name})
    return out


def meta_fragments() -> list[dict]:
    """Fleet-level artifacts that live in meta-copilot, not in a model repo."""
    out = []

    def add(kind, text, meta=None):
        for i, part in enumerate(chunk_text(text)):
            out.append({"repo": "meta-copilot", "kind": kind, "text": part,
                        **({"chunk": i} if i else {}), **(meta or {})})

    bdir = ROOT / "brainstorms"
    if bdir.exists():
        for f in sorted(bdir.glob("*.md")):
            if _readable(f):
                add("brainstorm", f.read_text(encoding="utf-8", errors="replace"),
                    {"file": f.name})
    rdir = ROOT / "research"
    if rdir.exists():
        for ef in sorted(rdir.glob("*/evidence.jsonl")):
            for l in ef.read_text(encoding="utf-8").splitlines():   # all evidence rows
                if l.strip():
                    r = json.loads(l)
                    add("evidence", f"{r.get('fragment','')} [{r.get('source','')}]",
                        {"source": r.get("source", ""), "date": r.get("date", "")})
    pf = ROOT / "trajectory" / "postmortems.jsonl"
    if pf.exists():
        for l in pf.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                add("postmortem", f"{r.get('claim','')} {r.get('lesson') or r.get('why','')}",
                    {"model": r.get("model", "")})
    af = TOOLS / "attribution-model" / "attributions" / "attributions.jsonl"
    if af.exists():
        for l in af.read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                add("attribution", f"{r.get('claim','')} driven by {r.get('primary','')}: "
                                   f"{r.get('why','')}", {"primary": r.get("primary", "")})
    return out


def _fid(fr: dict) -> str:
    return hashlib.sha256((fr["repo"] + fr["kind"] + fr["text"]).encode()).hexdigest()[:16]


def build(only: str | None = None) -> dict:
    """Write index.jsonl into each repo. Incremental: unchanged fragments keep vectors."""
    targets = []
    for p in sorted(TOOLS.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        if only and p.name != only:
            continue
        if (p / "MODEL.md").exists() or p.name == "meta-copilot":
            targets.append(p)
    stats = {}
    for repo in targets:
        frs = meta_fragments() if repo.name == "meta-copilot" else fragments(repo)
        if not frs:
            continue
        idx_f = repo / INDEX_NAME
        have = {}
        if idx_f.exists():
            for l in idx_f.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    r = json.loads(l)
                    have[r["id"]] = r
        need, rows = [], []
        for fr in frs:
            fid = _fid(fr)
            if fid in have:
                rows.append(have[fid])
            else:
                fr["id"] = fid
                need.append(fr)
        if need:
            vecs = embed([f["text"] for f in need])
            for fr, v in zip(need, vecs):
                fr["vec"] = v
                rows.append(fr)
        with idx_f.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        stats[repo.name] = {"fragments": len(rows), "new": len(need)}
        print(f"  {repo.name:<26} {len(rows):>4} fragments ({len(need)} new)")
    if _skipped:
        print(f"\n  [skipped {len(_skipped)} item(s) — nothing is dropped silently]")
        for path, why, sz in _skipped[:8]:
            print(f"    {sz:>9}  {why:<24} {path}")
        if len(_skipped) > 8:
            print(f"    ... and {len(_skipped) - 8} more")
    return stats


def load_indexes() -> list[dict]:
    rows = []
    for p in sorted(TOOLS.iterdir()):
        f = p / INDEX_NAME
        if p.is_dir() and f.exists():
            for l in f.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    rows.append(json.loads(l))
    return rows


def recall(cue: str, k: int = 12, spread: bool = True, min_sim: float = 0.25) -> list[dict]:
    """Two-stage, memory-shaped: similarity hits, then one hop of activation spread."""
    rows = load_indexes()
    if not rows:
        return []
    qv = embed([cue])[0]
    scored = []
    for r in rows:
        s = cosine(qv, r["vec"])
        if r["kind"] in PINNED_KINDS:
            s += 0.03                       # verdicts never decay out of reach
        if s >= min_sim:
            scored.append((s, r))
    scored.sort(key=lambda x: -x[0])
    top = scored[:k]
    out = [{"score": round(s, 3), "hop": 0, **{x: r[x] for x in r if x != "vec"}}
           for s, r in top]
    if spread and top:
        seen = {r["id"] for _s, r in top}
        # activation spreads to fragments near the strongest hits (co-activation)
        for s0, r0 in top[:3]:
            for s, r in scored:
                if r["id"] in seen:
                    continue
                link = cosine(r0["vec"], r["vec"])
                if link > 0.55:
                    seen.add(r["id"])
                    out.append({"score": round(s0 * link, 3), "hop": 1,
                                "via": r0["repo"],
                                **{x: r[x] for x in r if x != "vec"}})
                if len(out) >= k * 2:
                    break
    out.sort(key=lambda x: -x["score"])
    return out[:k * 2]


def main():
    ap = argparse.ArgumentParser(description="Associative memory index over the fleet.")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--repo")
    ap.add_argument("--recall")
    ap.add_argument("--k", type=int, default=12)
    ap.add_argument("--no-spread", action="store_true")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    from suites.grade_claims import _load_env
    _load_env()

    if a.stats:
        rows = load_indexes()
        by_repo, by_kind = {}, {}
        for r in rows:
            by_repo[r["repo"]] = by_repo.get(r["repo"], 0) + 1
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
        print(f"[memory] {len(rows)} fragments across {len(by_repo)} repos "
              f"· backend {os.environ.get('EMBED_BACKEND','local')}")
        for k, v in sorted(by_kind.items(), key=lambda x: -x[1]):
            print(f"  {k:<16} {v}")
        return
    if a.recall:
        hits = recall(a.recall, k=a.k, spread=not a.no_spread)
        print(f"[recall] '{a.recall}' -> {len(hits)} fragments")
        for h in hits:
            via = f" via {h['via']}" if h.get("hop") else ""
            print(f"  {h['score']:.3f} [{h['kind']:<13}] {h['repo']:<22}{via}")
            print(f"        {h['text'][:150]}")
        return
    print(f"[memory] building indexes · backend {os.environ.get('EMBED_BACKEND','local')}")
    build(a.repo)


if __name__ == "__main__":
    main()
