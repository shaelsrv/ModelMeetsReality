"""Document ingestion — PDF / DOCX / TXT / HTML → inbox transcript + source stub.

Third leg of the ingest family (ingest_youtube: captions; ingest_substack: post archives).
Exists because the mesh import hand-rolled this extraction three times in one session
(two PDFs, three DOCX, one HTML article) — same ~15 lines each time. Extraction only:
no LLM, no claims, no side effects beyond the two output files. Downstream is unchanged
(`model_import --transcript ... --source ...`, or direct MODEL.md distillation for
private theory corpora).

  python -m harness.ingest_doc paper.pdf --title "..." --published 2026-03-01 -o inbox
  python -m harness.ingest_doc notes.docx article.html --channel "My Archive"

Writes, per input file: inbox/transcript_<slug>.txt and inbox/source_<slug>.json
(the source stub matches what model_import expects: title/channel/published/url).
PDF text needs pypdf; DOCX/HTML/TXT use the standard library.
"""
from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
import zipfile
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:60] or "doc"


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        from PyPDF2 import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)


def extract_docx(path: Path) -> str:
    x = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    x = re.sub(r"</w:p>", "\n", x)
    return _html.unescape(re.sub(r"<[^>]+>", "", x))


def extract_html(path: Path) -> str:
    s = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<article.*?</article>", s, re.S) or re.search(r"<main.*?</main>", s, re.S)
    a = m.group(0) if m else s
    a = re.sub(r"<script.*?</script>|<style.*?</style>", "", a, flags=re.S)
    a = re.sub(r"<(h[1-6])[^>]*>", r"\n\n## ", a)
    a = re.sub(r"</h[1-6]>", "\n", a)
    a = re.sub(r"<li[^>]*>", "\n- ", a)
    a = re.sub(r"<(p|div|blockquote|br)[^>]*>", "\n", a)
    return _html.unescape(re.sub(r"<[^>]+>", "", a))


EXTRACTORS = {".pdf": extract_pdf, ".docx": extract_docx,
              ".html": extract_html, ".htm": extract_html,
              ".txt": lambda p: p.read_text(encoding="utf-8", errors="replace")}


def ingest(path: Path, outdir: Path, meta: dict) -> tuple[Path, Path]:
    fn = EXTRACTORS.get(path.suffix.lower())
    if fn is None:
        raise SystemExit(f"unsupported extension: {path.suffix} ({path.name})")
    t = fn(path)
    t = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+", " ", t)).strip()
    if len(t) < 200:
        # An empty extraction is not a short document -- it's a failure that would
        # read downstream as "this source had nothing to say" (LEARNINGS 4).
        raise SystemExit(f"extraction produced only {len(t)} chars from {path.name} -- "
                         f"refusing to write a near-empty transcript")
    slug = _slug(meta.get("title") or path.stem)
    outdir.mkdir(parents=True, exist_ok=True)
    tpath = outdir / f"transcript_{slug}.txt"
    spath = outdir / f"source_{slug}.json"
    tpath.write_text(t, encoding="utf-8")
    src = {"video_id": slug, "url": meta.get("url", ""),
           "title": meta.get("title") or path.stem,
           "channel": meta.get("channel", ""),
           "speakers_hint": meta.get("speaker", ""),
           "published": meta.get("published", ""),
           "caption_kind": "document", "original_file": path.name,
           "transcript_path": str(tpath)}
    spath.write_text(json.dumps(src, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {path.name} -> {tpath.name} ({len(t):,} chars) + {spath.name}")
    return tpath, spath


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract documents into inbox transcript + source stub.")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--outdir", default="inbox")
    ap.add_argument("--title", default="", help="one file only; default: filename stem")
    ap.add_argument("--channel", default="")
    ap.add_argument("--speaker", default="")
    ap.add_argument("--published", default="", help="YYYY-MM-DD; the epistemic cutoff downstream")
    ap.add_argument("--url", default="")
    a = ap.parse_args()
    if a.title and len(a.files) > 1:
        raise SystemExit("--title applies to a single file; omit it for batches")
    for f in a.files:
        ingest(Path(f), Path(a.outdir),
               {"title": a.title, "channel": a.channel, "speaker": a.speaker,
                "published": a.published, "url": a.url})


if __name__ == "__main__":
    main()
