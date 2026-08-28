"""YouTube ingestion — transcript in, timestamped text out.

The cheap path first: most channels worth modelling have captions, so `yt_dlp`
pulls them directly and no audio is ever downloaded. Whisper (see
`F:/tools/transcript/transcribe.py`) is the fallback for uncaptioned media and is
deliberately NOT wired in here — it needs a GPU and it is the slow path.

Ingestion is kept strictly separate from extraction so the pipeline can enforce
the discipline that makes accuracy-tracking meaningful: the extractor sees the
transcript text and nothing else. No outcome lookup, no browsing, no metadata
about what happened after the video was published.

Usage:
    python -m harness.ingest_youtube https://youtu.be/aV26V1UvkJw -o inbox/
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional


@dataclass
class Source:
    """Everything the extractor is allowed to know about where this came from."""
    video_id: str
    url: str
    title: str
    channel: str
    speakers_hint: str      # from title/description; the extractor confirms
    published: str          # YYYY-MM-DD -- the epistemic cutoff for every claim
    duration_s: int
    caption_kind: str       # "manual" | "auto" | "whisper"
    transcript_path: str


def _fmt_date(yyyymmdd: str) -> str:
    if yyyymmdd and len(yyyymmdd) == 8:
        return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"
    return yyyymmdd or ""


def _blocks_from_json3(raw: dict, block_seconds: int = 30) -> list[tuple[float, str]]:
    """json3 caption events -> ~block_seconds chunks of readable text."""
    lines: list[tuple[float, str]] = []
    for e in raw.get("events", []):
        segs = e.get("segs")
        if not segs:
            continue
        t = e.get("tStartMs", 0) / 1000.0
        txt = "".join(s.get("utf8", "") for s in segs).replace("\n", " ").strip()
        if txt:
            lines.append((t, txt))
    if not lines:
        return []
    out: list[tuple[float, str]] = []
    cur: list[str] = []
    start = lines[0][0]
    for t, txt in lines:
        if t - start > block_seconds and cur:
            out.append((start, " ".join(cur)))
            cur = []
            start = t
        cur.append(txt)
    if cur:
        out.append((start, " ".join(cur)))
    return out


def _hhmmss(t: float) -> str:
    m, s = divmod(int(t), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def ingest(url: str, outdir: Path, block_seconds: int = 30) -> Source:
    try:
        import yt_dlp
    except ImportError as e:
        raise SystemExit("yt_dlp is required: pip install yt-dlp") from e

    outdir.mkdir(parents=True, exist_ok=True)
    probe = {"skip_download": True, "quiet": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(probe) as y:
        info = y.extract_info(url, download=False)

    vid = info.get("id", "")
    manual = list((info.get("subtitles") or {}).keys())
    auto = [a for a in (info.get("automatic_captions") or {}) if a.startswith("en")]

    if any(k.startswith("en") for k in manual):
        kind, use_auto = "manual", False
    elif auto:
        kind, use_auto = "auto", True
    else:
        raise SystemExit(
            f"No English captions for {vid}. Fall back to Whisper "
            f"(F:/tools/transcript/transcribe.py) and re-run with --transcript."
        )

    opts = {
        "skip_download": True, "quiet": True, "no_warnings": True,
        "writesubtitles": not use_auto, "writeautomaticsub": use_auto,
        "subtitleslangs": ["en"], "subtitlesformat": "json3",
        "outtmpl": str(outdir / "raw_%(id)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as y:
        y.download([url])

    cand = list(outdir.glob(f"raw_{vid}*.json3"))
    if not cand:
        raise SystemExit(f"caption download produced no json3 for {vid}")
    raw = json.loads(cand[0].read_text(encoding="utf-8"))

    blocks = _blocks_from_json3(raw, block_seconds)
    tpath = outdir / f"transcript_{vid}.txt"
    with tpath.open("w", encoding="utf-8") as f:
        for t, txt in blocks:
            f.write(f"[{_hhmmss(t)}] {txt}\n")

    src = Source(
        video_id=vid,
        url=info.get("webpage_url", url),
        title=info.get("title", ""),
        channel=info.get("uploader", ""),
        speakers_hint=info.get("title", ""),
        published=_fmt_date(info.get("upload_date", "")),
        duration_s=int(info.get("duration") or 0),
        caption_kind=kind,
        transcript_path=str(tpath),
    )
    (outdir / f"source_{vid}.json").write_text(
        json.dumps(asdict(src), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return src


def main() -> None:
    ap = argparse.ArgumentParser(description="Pull a YouTube transcript for model extraction.")
    ap.add_argument("url")
    ap.add_argument("-o", "--outdir", default="inbox")
    ap.add_argument("--block-seconds", type=int, default=30)
    a = ap.parse_args()
    src = ingest(a.url, Path(a.outdir), a.block_seconds)
    print(json.dumps(asdict(src), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
