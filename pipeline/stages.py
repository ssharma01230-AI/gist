"""Concrete pipeline stages.

Only IngestionStage exists so far. The rest of the pipeline (queue, store,
select, create, check, deploy, learn) will each land here as its own Stage.
"""
from __future__ import annotations

from typing import Any

from .fetch import Fetcher
from .ingest import ingest
from .models import SourceConfig
from .orchestrator import PipelineContext, Stage, StageError
from .sinks import ArticleSink
from .sources import fetchable_sources
from .state import FeedStateStore


class IngestionStage:
    """Pull every fetchable source and hand the new articles to the queue sink."""

    name = "ingest"

    def __init__(
        self,
        sources: list[SourceConfig],
        fetcher: Fetcher,
        sink: ArticleSink,
        *,
        state_store: FeedStateStore | None = None,
        only_fetchable: bool = True,
    ) -> None:
        self.sources = fetchable_sources(sources) if only_fetchable else sources
        self.fetcher = fetcher
        self.sink = sink
        self.state_store = state_store

    def run(self, ctx: PipelineContext) -> dict[str, Any]:
        if not self.sources:
            raise StageError("no fetchable sources configured")
        summary = ingest(self.sources, self.fetcher, self.sink, state_store=self.state_store)
        # Hand the sink to whatever queue/store stage runs next.
        ctx.blackboard["article_sink"] = self.sink
        ctx.blackboard["ingest_summary"] = summary
        return summary.to_dict()
