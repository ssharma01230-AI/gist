"""The ingestion stage's core: fetch every source, parse, dedup, emit.

Robustness contract: one bad source never aborts the run. Every source ends
with a SourceReport (ok / not_modified / empty / error); the run returns a
summary the orchestrator records and the learn stage can score later.
"""
from __future__ import annotations

import logging
from typing import Callable, Sequence

from .fetch import Fetcher
from .models import Article, SourceConfig, SourceReport, utcnow_iso
from .parse import parse_feed
from .sinks import ArticleSink
from .state import FeedState, FeedStateStore

log = logging.getLogger("gist.ingest")


class IngestSummary:
    def __init__(self, reports: list[SourceReport], started_at: str, finished_at: str) -> None:
        self.reports = reports
        self.started_at = started_at
        self.finished_at = finished_at

    @property
    def sources_total(self) -> int:
        return len(self.reports)

    @property
    def sources_ok(self) -> int:
        return sum(1 for r in self.reports if r.status in ("ok", "not_modified"))

    @property
    def sources_failed(self) -> int:
        return sum(1 for r in self.reports if r.status == "error")

    @property
    def articles_new(self) -> int:
        return sum(r.articles_new for r in self.reports)

    @property
    def articles_parsed(self) -> int:
        return sum(r.articles_parsed for r in self.reports)

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "sources_total": self.sources_total,
            "sources_ok": self.sources_ok,
            "sources_failed": self.sources_failed,
            "articles_parsed": self.articles_parsed,
            "articles_new": self.articles_new,
            "sources": [vars(r) for r in self.reports],
        }


def ingest(
    sources: Sequence[SourceConfig],
    fetcher: Fetcher,
    sink: ArticleSink,
    *,
    state_store: FeedStateStore | None = None,
    now: Callable[[], str] = utcnow_iso,
) -> IngestSummary:
    started = now()
    reports: list[SourceReport] = []

    for source in sources:
        report = _ingest_one(source, fetcher, sink, state_store, now)
        reports.append(report)
        log.info(
            "ingest %-22s %-13s parsed=%d new=%d %s",
            source.id,
            report.status,
            report.articles_parsed,
            report.articles_new,
            f"({report.error})" if report.error else "",
        )

    sink.flush()
    if state_store is not None:
        state_store.save()
    return IngestSummary(reports, started, now())


def _ingest_one(
    source: SourceConfig,
    fetcher: Fetcher,
    sink: ArticleSink,
    state_store: FeedStateStore | None,
    now: Callable[[], str],
) -> SourceReport:
    prior = state_store.get(source.id) if state_store else FeedState()
    try:
        result = fetcher.fetch(
            source.id, source.url, etag=prior.etag, last_modified=prior.last_modified
        )
    except Exception as exc:  # a fetcher should not raise, but never trust it
        return SourceReport(source.id, "error", error=f"fetch raised {type(exc).__name__}: {exc}")

    if result.not_modified:
        return SourceReport(source.id, "not_modified", http_status=304)
    if not result.ok:
        return SourceReport(source.id, "error", http_status=result.status_code, error=result.error or "fetch failed")

    try:
        articles = parse_feed(source, result.body, fetched_at=now())
    except Exception as exc:
        return SourceReport(source.id, "error", http_status=result.status_code, error=f"parse failed: {type(exc).__name__}: {exc}")

    new = _emit_new(articles, sink)

    if state_store is not None:
        state_store.set(
            source.id,
            FeedState(etag=prior.etag, last_modified=prior.last_modified, last_fetched=now()),
        )

    status = "ok" if articles else "empty"
    return SourceReport(
        source.id,
        status,
        articles_parsed=len(articles),
        articles_new=new,
        http_status=result.status_code,
    )


def _emit_new(articles: list[Article], sink: ArticleSink) -> int:
    new = 0
    for art in articles:
        if sink.seen(art.id):
            continue
        sink.put(art)
        new += 1
    return new
