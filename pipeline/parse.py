"""Parse feed bytes into normalized Article records.

feedparser handles the RSS 2.0 / Atom / RDF format zoo and malformed markup;
we own the Article schema and the normalization on top of it.
"""
from __future__ import annotations

import feedparser

from . import normalize as N
from .models import Article, SourceConfig, utcnow_iso


def parse_feed(source: SourceConfig, body: bytes, *, fetched_at: str = "") -> list[Article]:
    fetched_at = fetched_at or utcnow_iso()
    parsed = feedparser.parse(body)
    articles: list[Article] = []
    seen_ids: set[str] = set()

    for entry in parsed.entries:
        title = N.clean_text(N._get(entry, "title", ""), max_len=300)
        link = (N._get(entry, "link", "") or "").strip()
        key = N.entry_key(entry)
        if not (title or link or key):
            continue

        art_id = Article.make_id(source.id, key or link or title)
        if art_id in seen_ids:  # de-dup within a single feed pull
            continue
        seen_ids.add(art_id)

        published = N.to_iso_utc(
            N._get(entry, "published_parsed") or N._get(entry, "updated_parsed")
        )
        summary = N.clean_text(_summary_html(entry))

        articles.append(
            Article(
                id=art_id,
                source_id=source.id,
                topic=source.topic,
                title=title,
                url=link,
                summary=summary,
                published_at=published,
                fetched_at=fetched_at,
                image_url=N.extract_image(entry),
                authors=N.extract_authors(entry),
                tags=N.extract_tags(entry),
            )
        )
    return articles


def feed_is_wellformed(body: bytes) -> bool:
    """feedparser sets .bozo on malformed input; entries may still parse."""
    parsed = feedparser.parse(body)
    return not parsed.bozo


def _summary_html(entry) -> str:
    content = N._get(entry, "content")
    if isinstance(content, list) and content:
        val = content[0].get("value") if isinstance(content[0], dict) else None
        if val:
            return val
    return N._get(entry, "summary", "") or ""
