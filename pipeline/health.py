"""Feed health checks.

Ingestion answers "did the fetch+parse succeed?". Health answers the harder
question a news aggregator actually cares about: "is this source still alive?"
A feed can return HTTP 200 with valid XML yet be *stale* — its newest item is
months old because the publisher quietly abandoned it (this is exactly how the
original CNN and Axios feeds died). So each source gets a verdict:

  pass  — reachable, has items, newest item is fresh
  warn  — reachable with items, but stale (or no dates to judge freshness)
  fail  — unreachable, errored, or returned zero items
  skip  — not health-checkable here (API sources needing keys/quota)
"""
from __future__ import annotations

import concurrent.futures as cf
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Sequence

from .fetch import Fetcher
from .models import SourceConfig
from .parse import parse_feed

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"
DEFAULT_MAX_AGE_HOURS = 96.0

# Statuses that mean "try again later", not "this feed is dead". A shared cloud
# IP (like a CI runner) routinely trips these even when the feed is perfectly
# healthy from a normal host — NASA 429-rate-limits them, some CDNs answer bot
# traffic with 403/202. These become WARN (surfaced, not fatal); genuinely dead
# feeds (404/410, or 200 with an empty/unparseable body) stay FAIL.
SOFT_HTTP = {403, 408, 425, 429, 500, 502, 503, 504}


@dataclass
class SourceHealth:
    source_id: str
    name: str
    topic: str
    url: str
    verdict: str
    http_status: int = 0
    item_count: int = 0
    newest_published: str = ""
    newest_age_hours: float | None = None
    stale: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def check_source(
    source: SourceConfig,
    fetcher: Fetcher,
    *,
    now: datetime,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
) -> SourceHealth:
    if not source.fetchable:
        return SourceHealth(
            source.id, source.name, source.topic, source.url, SKIP,
            error="API source — needs a key/quota, not health-checked here",
        )

    try:
        result = fetcher.fetch(source.id, source.url)  # no conditional GET: we want a live pull
    except Exception as exc:
        return SourceHealth(source.id, source.name, source.topic, source.url, WARN,
                            error=f"transient: fetch raised {type(exc).__name__}: {exc}")

    if result.not_modified:
        return SourceHealth(source.id, source.name, source.topic, source.url, PASS,
                            http_status=304, error="not modified since last fetch")

    if not result.ok:
        # status 0 = no HTTP response at all (timeout/connection reset) -> transient.
        soft = result.status_code == 0 or result.status_code in SOFT_HTTP
        return SourceHealth(
            source.id, source.name, source.topic, source.url,
            WARN if soft else FAIL,
            http_status=result.status_code,
            error=("transient: " if soft else "") + (result.error or "fetch failed"),
        )

    try:
        articles = parse_feed(source, result.body, fetched_at=now.isoformat(timespec="seconds"))
    except Exception as exc:
        return SourceHealth(source.id, source.name, source.topic, source.url, FAIL,
                            http_status=result.status_code, error=f"parse failed: {type(exc).__name__}: {exc}")

    if not articles:
        # 200 + no items = a genuinely empty feed (hard). A non-200 2xx (202/203/206)
        # with no items is almost always a bot-challenge body, not a dead feed (soft).
        if result.status_code != 200:
            return SourceHealth(source.id, source.name, source.topic, source.url, WARN,
                                http_status=result.status_code,
                                error=f"transient: HTTP {result.status_code} with no items (bot challenge?)")
        return SourceHealth(source.id, source.name, source.topic, source.url, FAIL,
                            http_status=result.status_code, error="feed returned zero items")

    newest_iso, age_hours = _newest_age(articles, now)
    stale = age_hours is None or age_hours > max_age_hours
    return SourceHealth(
        source.id, source.name, source.topic, source.url,
        WARN if stale else PASS,
        http_status=result.status_code,
        item_count=len(articles),
        newest_published=newest_iso,
        newest_age_hours=age_hours,
        stale=stale,
        error="no dated items — cannot judge freshness" if age_hours is None else
              (f"stale: newest item is {age_hours:.0f}h old" if stale else ""),
    )


def check_sources(
    sources: Sequence[SourceConfig],
    fetcher: Fetcher,
    *,
    now: datetime | None = None,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    max_workers: int = 8,
) -> list[SourceHealth]:
    now = now or datetime.now(timezone.utc)
    if max_workers <= 1:
        return [check_source(s, fetcher, now=now, max_age_hours=max_age_hours) for s in sources]
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        return list(ex.map(
            lambda s: check_source(s, fetcher, now=now, max_age_hours=max_age_hours), sources
        ))


def _newest_age(articles, now: datetime) -> tuple[str, float | None]:
    newest: datetime | None = None
    for a in articles:
        if not a.published_at:
            continue
        try:
            dt = datetime.fromisoformat(a.published_at)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if newest is None or dt > newest:
            newest = dt
    if newest is None:
        return "", None
    age = (now - newest).total_seconds() / 3600.0
    return newest.isoformat(timespec="seconds"), round(age, 1)


def summarize(healths: Sequence[SourceHealth]) -> dict:
    counts = {PASS: 0, WARN: 0, FAIL: 0, SKIP: 0}
    for h in healths:
        counts[h.verdict] = counts.get(h.verdict, 0) + 1
    return counts


def overall_ok(healths: Sequence[SourceHealth], *, strict: bool = False) -> bool:
    """Gate for CI. Any FAIL fails the run; --strict also fails on WARN (stale)."""
    bad = {FAIL, WARN} if strict else {FAIL}
    return not any(h.verdict in bad for h in healths)


_ICON = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", SKIP: "skip"}


def render_table(healths: Sequence[SourceHealth]) -> str:
    rows = []
    header = f"{'':4} {'source':24} {'topic':16} {'http':>4} {'items':>5} {'age(h)':>7}  note"
    rows.append(header)
    rows.append("-" * len(header))
    for h in sorted(healths, key=lambda x: (_ORDER[x.verdict], x.topic, x.source_id)):
        age = "" if h.newest_age_hours is None else f"{h.newest_age_hours:.0f}"
        rows.append(
            f"{_ICON[h.verdict]:4} {h.source_id:24} {h.topic:16} "
            f"{h.http_status or '':>4} {h.item_count or '':>5} {age:>7}  {h.error}"
        )
    counts = summarize(healths)
    rows.append("-" * len(header))
    rows.append(
        f"{counts[PASS]} pass · {counts[WARN]} warn · {counts[FAIL]} fail · {counts[SKIP]} skip "
        f"({len(healths)} sources)"
    )
    return "\n".join(rows)


_ORDER = {FAIL: 0, WARN: 1, SKIP: 2, PASS: 3}  # worst first in the table
