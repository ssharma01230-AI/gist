"""Where ingested articles go next — the queue handoff.

ArticleSink is the boundary between ingest and the rest of the pipeline. Today
we have in-memory (tests) and JSONL-on-disk (local runs) implementations;
tomorrow a Redis/SQS/Kafka sink implements the same three methods and nothing
upstream changes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Protocol

from .models import Article


class ArticleSink(Protocol):
    def seen(self, article_id: str) -> bool:
        """True if this id was already emitted (dedup across runs)."""
        ...

    def put(self, article: Article) -> None:
        ...

    def flush(self) -> None:
        ...


class InMemorySink:
    def __init__(self) -> None:
        self.articles: list[Article] = []
        self._ids: set[str] = set()

    def seen(self, article_id: str) -> bool:
        return article_id in self._ids

    def put(self, article: Article) -> None:
        self.articles.append(article)
        self._ids.add(article.id)

    def flush(self) -> None:  # nothing to flush
        pass


class JsonlSink:
    """Append-only JSONL, one article per line. Loads existing ids on open so
    re-runs dedup against what's already on disk."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ids: set[str] = set()
        self._buffer: list[str] = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue

    def seen(self, article_id: str) -> bool:
        return article_id in self._ids

    def put(self, article: Article) -> None:
        self._buffer.append(json.dumps(article.to_dict(), ensure_ascii=False))
        self._ids.add(article.id)

    def flush(self) -> None:
        if not self._buffer:
            return
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(self._buffer) + "\n")
        self._buffer.clear()


def read_jsonl(path: str | Path) -> Iterable[Article]:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            yield Article.from_dict(json.loads(line))
