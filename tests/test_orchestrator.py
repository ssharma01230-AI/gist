"""Orchestration layer: stages run in order, report, and hand off via blackboard."""
from pathlib import Path

from pipeline.fetch import FixtureFetcher
from pipeline.models import SourceConfig
from pipeline.orchestrator import Orchestrator, PipelineContext, Stage, StageError
from pipeline.sinks import InMemorySink
from pipeline.stages import IngestionStage

FIX = Path(__file__).parent / "fixtures"


def _sources():
    return [
        SourceConfig("example-science", "science", "Sci", "rss", "https://s.test/rss", "ok"),
        SourceConfig("example-tech", "technology", "Tech", "api", "https://t.test/api", "ok_caution"),
    ]


def test_ingestion_stage_runs_and_reports():
    fetcher = FixtureFetcher(by_source={"example-science": (FIX / "rss2_science.xml").read_bytes()})
    sink = InMemorySink()
    orch = Orchestrator([IngestionStage(_sources(), fetcher, sink)])
    report = orch.run()

    assert len(report.stages) == 1
    stage = report.stages[0]
    assert stage.stage == "ingest"
    assert stage.ok is True
    # Only the rss source is fetchable; the api source is skipped for now.
    assert stage.detail["sources_total"] == 1
    assert stage.detail["articles_new"] == 3


def test_blackboard_handoff_exposes_sink_for_next_stage():
    fetcher = FixtureFetcher(by_source={"example-science": (FIX / "rss2_science.xml").read_bytes()})
    sink = InMemorySink()

    captured = {}

    class PeekStage:
        name = "peek"

        def run(self, ctx: PipelineContext):
            captured["sink"] = ctx.blackboard.get("article_sink")
            captured["summary"] = ctx.blackboard.get("ingest_summary")
            return {"saw_articles": len(ctx.blackboard["article_sink"].articles)}

    report = Orchestrator([IngestionStage(_sources(), fetcher, sink), PeekStage()]).run()
    assert captured["sink"] is sink
    assert captured["summary"].articles_new == 3
    assert report.stages[1].detail["saw_articles"] == 3


def test_fatal_stage_halts_run():
    class BoomStage:
        name = "boom"

        def run(self, ctx: PipelineContext):
            raise StageError("cannot continue")

    class ShouldNotRun:
        name = "after"

        def run(self, ctx: PipelineContext):
            raise AssertionError("must not execute after a fatal stage")

    report = Orchestrator([BoomStage(), ShouldNotRun()]).run()
    assert len(report.stages) == 1
    assert report.stages[0].ok is False
    assert report.stages[0].detail["error"] == "cannot continue"
