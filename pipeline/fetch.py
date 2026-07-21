"""The network boundary.

Everything above this line is deterministic and testable; everything below
touches the internet. The Fetcher protocol is the seam: HttpFetcher in prod,
FixtureFetcher in tests and offline runs. Nothing else in the pipeline knows
whether bytes came from the network or disk.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Mapping, Protocol

from .models import FetchResult

# A browser-shaped UA. Several publishers (NASA, ESPN, The Hill…) soft-block
# non-browser agents with 202/403/429 and an empty body, even for public feeds.
# Sending a normal browser UA is standard practice for RSS readers.
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class Fetcher(Protocol):
    def fetch(self, source_id: str, url: str, *, etag: str = "", last_modified: str = "") -> FetchResult:
        ...


class HttpFetcher:
    """Real HTTP with timeouts, retries+backoff, and conditional GET.

    Conditional GET (If-None-Match / If-Modified-Since) means a feed that hasn't
    changed returns 304 and no body — polite to publishers and cheap for us.
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        retries: int = 3,
        backoff_base: float = 2.0,
        user_agent: str = DEFAULT_UA,
        sleep=time.sleep,
    ) -> None:
        self.timeout = timeout
        self.retries = retries
        self.backoff_base = backoff_base
        self.user_agent = user_agent
        self._sleep = sleep

    def fetch(self, source_id: str, url: str, *, etag: str = "", last_modified: str = "") -> FetchResult:
        import httpx  # imported lazily so tests don't need the network stack

        headers = {"User-Agent": self.user_agent, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified

        last_err = ""
        for attempt in range(1, self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                    resp = client.get(url, headers=headers)
                if resp.status_code == 304:
                    return FetchResult(source_id=source_id, url=url, status_code=304, not_modified=True)
                if resp.status_code >= 500 or resp.status_code == 429:
                    last_err = f"HTTP {resp.status_code}"
                    self._maybe_backoff(attempt)
                    continue
                return FetchResult(
                    source_id=source_id,
                    url=str(resp.url),
                    status_code=resp.status_code,
                    body=resp.content,
                    error="" if resp.is_success else f"HTTP {resp.status_code}",
                )
            except Exception as exc:  # network error: retry
                last_err = f"{type(exc).__name__}: {exc}"
                self._maybe_backoff(attempt)
        return FetchResult(source_id=source_id, url=url, error=last_err or "unknown fetch error")

    def _maybe_backoff(self, attempt: int) -> None:
        if attempt < self.retries:
            self._sleep(self.backoff_base ** (attempt - 1))


class FixtureFetcher:
    """Returns bytes from an in-memory map or a fixtures directory.

    Used by tests and offline/dry runs. Register by url or by source_id.
    """

    def __init__(
        self,
        by_url: Mapping[str, bytes] | None = None,
        by_source: Mapping[str, bytes] | None = None,
        fixtures_dir: str | Path | None = None,
        errors: Mapping[str, str] | None = None,
        results: Mapping[str, FetchResult] | None = None,
    ) -> None:
        self.by_url = dict(by_url or {})
        self.by_source = dict(by_source or {})
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else None
        self.errors = dict(errors or {})
        # Pre-baked FetchResults, for exercising specific HTTP outcomes (429, 404, 202…).
        self.results = dict(results or {})

    def fetch(self, source_id: str, url: str, *, etag: str = "", last_modified: str = "") -> FetchResult:
        if source_id in self.results:
            return self.results[source_id]
        if source_id in self.errors:
            return FetchResult(source_id=source_id, url=url, error=self.errors[source_id])
        body = self.by_source.get(source_id) or self.by_url.get(url)
        if body is None and self.fixtures_dir:
            candidate = self.fixtures_dir / f"{source_id}.xml"
            if candidate.exists():
                body = candidate.read_bytes()
        if body is None:
            return FetchResult(source_id=source_id, url=url, status_code=404, error="no fixture registered")
        return FetchResult(source_id=source_id, url=url, status_code=200, body=body)
