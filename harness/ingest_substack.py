"""Substack ingestion — an analyst's written archive, for backfill.

Why this exists: legitimacy is earned from RESOLVED claims, so it cannot accrue
from claims that resolve in 2027. A written archive goes back years, which means
its claims have already met reality. That makes backfill the only path to a working
legitimacy signal before the forward-looking horizons arrive.

PAYWALL DISCIPLINE. Public preview text only. The Substack API returns the free
preview of a paid post — the body stops at the paywall break — and this module
takes exactly that and never attempts to go past it. Paid analysis is the
publication's business.

That limit costs less than it sounds. Legitimacy scoring needs the CLAIM ("X will
happen by Y"), not the reasoning behind it, and the claim is usually in the preview
because the claim is the hook. `paywalled: true` is recorded on every post so any
downstream score can tell how much of the piece was visible.

Usage:
    python -m harness.ingest_substack some-newsletter.substack.com --since 2024-01-01
    python -m harness.ingest_substack some-newsletter.substack.com --free-only --limit 20
"""
from __future__ import annotations

import argparse
import html
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

UA = "Mozilla/5.0 (compatible; MMR model-import/1.0)"


@dataclass
class Post:
    post_id: str
    url: str
    title: str
    subtitle: str
    publication: str
    author_hint: str
    published: str          # YYYY-MM-DD -- the epistemic cutoff for its claims
    audience: str           # "everyone" | "only_paid"
    paywalled: bool         # True if we only have the free preview
    chars: int
    text_path: str


def _api(url: str, retries: int = 3) -> object:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"API failed for {url}: {last}")


def _text(body_html: str) -> str:
    """HTML -> readable text, keeping paragraph breaks so claims stay in context."""
    s = body_html or ""
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"</(p|div|h[1-6]|li|blockquote)>", "\n\n", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def archive(domain: str, max_posts: int = 400, page: int = 50) -> list[dict]:
    out: list[dict] = []
    for off in range(0, max_posts, page):
        batch = _api(f"https://{domain}/api/v1/archive?sort=new&offset={off}&limit={page}")
        if not isinstance(batch, list) or not batch:
            break
        out.extend(batch)
        time.sleep(0.35)
    return out


def fetch_post(domain: str, slug: str) -> dict:
    return _api(f"https://{domain}/api/v1/posts/{slug}")


def ingest(domain: str, outdir: Path, since: str = "", until: str = "",
           free_only: bool = False, limit: int = 0, min_chars: int = 1200) -> list[Post]:
    outdir.mkdir(parents=True, exist_ok=True)
    index = archive(domain)
    print(f"  archive: {len(index)} posts "
          f"({index[-1]['post_date'][:10]} .. {index[0]['post_date'][:10]})")

    sel = []
    for p in index:
        d = (p.get("post_date") or "")[:10]
        if since and d < since:
            continue
        if until and d > until:
            continue
        if free_only and p.get("audience") != "everyone":
            continue
        sel.append(p)
    sel.sort(key=lambda p: p.get("post_date", ""))
    if limit:
        sel = sel[:limit]
    print(f"  selected: {len(sel)} posts"
          + (f"  (free only)" if free_only else "")
          + (f"  since {since}" if since else ""))

    posts: list[Post] = []
    for i, p in enumerate(sel, 1):
        slug = p.get("slug")
        if not slug:
            continue
        try:
            d = fetch_post(domain, slug)
        except RuntimeError as e:
            print(f"    [{i}/{len(sel)}] {slug}: {e}")
            continue

        txt = _text(d.get("body_html") or "")
        if len(txt) < min_chars:
            print(f"    [{i}/{len(sel)}] {p['post_date'][:10]} skipped "
                  f"({len(txt)} chars, below min) {p.get('title','')[:44]}")
            time.sleep(0.3)
            continue

        audience = d.get("audience") or p.get("audience") or ""
        paywalled = audience != "everyone"
        by = d.get("publishedBylines") or []
        author = ", ".join(b.get("name", "") for b in by if b.get("name")) or ""

        stem = f"{p['post_date'][:10]}_{slug}"[:90]
        tpath = outdir / f"post_{stem}.txt"
        head = (
            f"# {d.get('title') or p.get('title','')}\n"
            f"{d.get('subtitle') or ''}\n"
            f"published: {p['post_date'][:10]}   audience: {audience}"
            f"{'   [FREE PREVIEW ONLY -- paid analysis not included]' if paywalled else ''}\n\n"
        )
        tpath.write_text(head + txt, encoding="utf-8")

        post = Post(
            post_id=str(d.get("id") or p.get("id") or slug),
            url=d.get("canonical_url") or f"https://{domain}/p/{slug}",
            title=d.get("title") or p.get("title", ""),
            subtitle=d.get("subtitle") or "",
            publication=domain,
            author_hint=author,
            published=p["post_date"][:10],
            audience=audience,
            paywalled=paywalled,
            chars=len(txt),
            text_path=str(tpath),
        )
        posts.append(post)
        print(f"    [{i}/{len(sel)}] {post.published}  {post.chars:6d}ch  "
              f"{'preview' if paywalled else 'full   '}  {post.title[:48]}")
        time.sleep(0.35)

    (outdir / f"index_{domain.replace('.', '_')}.json").write_text(
        json.dumps([asdict(x) for x in posts], indent=2, ensure_ascii=False),
        encoding="utf-8")
    return posts


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest a Substack archive (public preview text only) for model import.")
    ap.add_argument("domain", help="e.g. some-newsletter.substack.com")
    ap.add_argument("-o", "--outdir", default="inbox/posts")
    ap.add_argument("--since", default="", help="YYYY-MM-DD")
    ap.add_argument("--until", default="", help="YYYY-MM-DD")
    ap.add_argument("--free-only", action="store_true", help="skip paid posts entirely")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--min-chars", type=int, default=1200)
    a = ap.parse_args()

    posts = ingest(a.domain, Path(a.outdir), a.since, a.until,
                   a.free_only, a.limit, a.min_chars)
    npw = sum(1 for p in posts if p.paywalled)
    print(f"\n  {len(posts)} posts ingested "
          f"({npw} preview-only, {len(posts)-npw} full)")
    print(f"  chars: {sum(p.chars for p in posts):,}")


if __name__ == "__main__":
    main()
