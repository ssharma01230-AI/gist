"""Turn a raw feed entry into normalized fields.

Kept separate from parse.py so the messy, edge-case-ridden bits (dates, HTML,
image extraction) live in one testable place.
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_IMG_SRC_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


def clean_text(html: str | None, max_len: int = 600) -> str:
    """Strip tags/entities and collapse whitespace into a plain summary."""
    if not html:
        return ""
    text = _TAG_RE.sub(" ", html)
    text = unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].rstrip() + "…"
    return text


def to_iso_utc(struct_time: Any) -> str:
    """feedparser's *_parsed struct_time (UTC) -> ISO 8601 UTC string."""
    if not struct_time:
        return ""
    try:
        ts = calendar.timegm(struct_time)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
    except (ValueError, OverflowError, TypeError):
        return ""


def entry_key(entry: Any) -> str:
    """Stable identity for a feed entry: prefer guid/id, fall back to link, then title."""
    for attr in ("id", "guid"):
        val = getattr(entry, attr, None) or (entry.get(attr) if isinstance(entry, dict) else None)
        if val:
            return str(val).strip()
    link = _get(entry, "link")
    if link:
        return str(link).strip()
    return _get(entry, "title", "").strip()


def extract_image(entry: Any) -> str:
    """Best-effort image: media:content, media:thumbnail, enclosure, or first <img>."""
    for key in ("media_content", "media_thumbnail"):
        media = _get(entry, key)
        if media:
            for m in media:
                url = m.get("url") if isinstance(m, dict) else None
                if url:
                    return url
    for enc in _get(entry, "enclosures", []) or []:
        etype = enc.get("type", "") if isinstance(enc, dict) else ""
        url = enc.get("href") or enc.get("url") if isinstance(enc, dict) else None
        if url and (etype.startswith("image") or _looks_like_image(url)):
            return url
    for body_key in ("content", "summary"):
        body = _get(entry, body_key)
        html = ""
        if isinstance(body, list) and body:
            html = body[0].get("value", "") if isinstance(body[0], dict) else ""
        elif isinstance(body, str):
            html = body
        m = _IMG_SRC_RE.search(html or "")
        if m:
            return m.group(1)
    return ""


def extract_authors(entry: Any) -> tuple[str, ...]:
    authors = _get(entry, "authors")
    names: list[str] = []
    if authors:
        for a in authors:
            name = a.get("name") if isinstance(a, dict) else str(a)
            if name and name.strip():
                names.append(name.strip())
    if not names:
        single = _get(entry, "author", "")
        if single:
            names.append(str(single).strip())
    seen: set[str] = set()
    return tuple(n for n in names if not (n in seen or seen.add(n)))  # type: ignore[func-returns-value]


def extract_tags(entry: Any) -> tuple[str, ...]:
    tags = _get(entry, "tags")
    out: list[str] = []
    if tags:
        for t in tags:
            term = t.get("term") if isinstance(t, dict) else str(t)
            if term and term.strip():
                out.append(term.strip())
    seen: set[str] = set()
    return tuple(t for t in out if not (t in seen or seen.add(t)))  # type: ignore[func-returns-value]


def _looks_like_image(url: str) -> bool:
    return url.lower().rsplit("?", 1)[0].endswith((".jpg", ".jpeg", ".png", ".webp", ".gif"))


def _get(entry: Any, key: str, default: Any = None) -> Any:
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)
