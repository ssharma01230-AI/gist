"""The orchestration layer.

A Stage is one step of ingest -> queue -> store -> select -> create -> check ->
deploy -> learn. The Orchestrator runs registered stages in order, gives each a
shared PipelineContext, records a StageResult per stage, and stops early if a
stage marks itself fatal. Adding a stage later means writing one class and
registering it — no orchestrator changes.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import RunReport, StageResult, utcnow_iso

log = logging.getLogger("gist.orchestrator")


@dataclass
class PipelineContext:
    """Shared state threaded through a run.

    `blackboard` is the inter-stage handoff: a stage writes what the next one
    reads (e.g. ingestion drops the queue sink or the run summary here).
    """

    run_id: str
    config: dict[str, Any] = field(default_factory=dict)
    blackboard: dict[str, Any] = field(default_factory=dict)


class StageError(Exception):
    """Raise from a stage to signal a fatal condition that should halt the run."""


class Stage(Protocol):
    name: str

    def run(self, ctx: PipelineContext) -> dict[str, Any]:
        """Do the work; return a JSON-able detail dict for the report."""
        ...


class Orchestrator:
    def __init__(self, stages: list[Stage]) -> None:
        self.stages = stages

    def run(self, *, config: dict[str, Any] | None = None, run_id: str | None = None) -> RunReport:
        rid = run_id or uuid.uuid4().hex[:12]
        ctx = PipelineContext(run_id=rid, config=config or {})
        report = RunReport(run_id=rid, started_at=utcnow_iso())
        log.info("run %s start (%d stages)", rid, len(self.stages))

        for stage in self.stages:
            started = utcnow_iso()
            try:
                detail = stage.run(ctx) or {}
                report.stages.append(
                    StageResult(stage.name, True, started, utcnow_iso(), detail)
                )
            except StageError as exc:
                report.stages.append(
                    StageResult(stage.name, False, started, utcnow_iso(), {"error": str(exc)})
                )
                log.error("run %s halted at stage %s: %s", rid, stage.name, exc)
                break
            except Exception as exc:  # unexpected: record and halt
                report.stages.append(
                    StageResult(
                        stage.name,
                        False,
                        started,
                        utcnow_iso(),
                        {"error": f"{type(exc).__name__}: {exc}"},
                    )
                )
                log.exception("run %s crashed at stage %s", rid, stage.name)
                break

        report.finished_at = utcnow_iso()
        return report
