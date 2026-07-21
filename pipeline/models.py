"""Canonical data shapes passed between pipeline stages."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class SourceConfig:
    """One entry from sources.json."""

    id: str
    topic: str
    name: str
    type: str  # "rss", "api", "rss+api"
    url: str
    status: str  # "ok", "ok_caution", "url_corrected"
    notes: str = ""

    @property
    def fetchable(self) -> bool:
        """APIs need keys/quota handling we don't do yet; RSS is fetchable now."""
        return self.type.startswith("rss")


@dataclass(frozen=True)
class Article:
    """A single story as ingested from one source, normalized.

    `id` is stable across runs: hash of source id + the entry's guid (or link),
    so the same story fetched twice dedupes, while the same story from a
    different outlet keeps its own id (that pairing happens later, in select).
    """

    id: str
    source_id: str
    topic: str
    title: str
    url: str
    summary: str = ""
    published_at: str = ""  # ISO 8601 UTC, "" when the feed gave no date
    fetched_at: str = ""
    image_url: str = ""
    authors: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @staticmethod
    def make_id(source_id: str, entry_key: str) -> str:
        digest = hashlib.sha256(f"{source_id}\n{entry_key}".encode()).hexdigest()
        return digest[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["authors"] = list(self.authors)
        d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Article":
        return cls(
            **{
                **d,
                "authors": tuple(d.get("authors", ())),
                "tags": tuple(d.get("tags", ())),
            }
        )


@dataclass
class FetchResult:
    """Outcome of fetching one source URL."""

    source_id: str
    url: str
    status_code: int = 0
    body: bytes = b""
    not_modified: bool = False  # 304 via ETag/Last-Modified
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and (self.not_modified or 200 <= self.status_code < 300)


@dataclass
class SourceReport:
    """Per-source outcome of an ingestion run."""

    source_id: str
    status: str  # "ok" | "not_modified" | "empty" | "error"
    articles_parsed: int = 0
    articles_new: int = 0
    http_status: int = 0
    error: str = ""


@dataclass
class StageResult:
    stage: str
    ok: bool
    started_at: str
    finished_at: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunReport:
    run_id: str
    started_at: str
    finished_at: str = ""
    stages: list[StageResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "stages": [asdict(s) for s in self.stages],
        }


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
