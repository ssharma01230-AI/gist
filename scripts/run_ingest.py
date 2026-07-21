#!/usr/bin/env python3
"""Run the ingestion stage.

Live (needs network access to the feeds):
    python scripts/run_ingest.py --out data/articles.jsonl

Offline smoke test against the bundled fixtures (no network):
    python scripts/run_ingest.py --fixtures tests/fixtures --sources - --limit 2

Filter to a topic:
    python scripts/run_ingest.py --topic science
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.fetch import FixtureFetcher, HttpFetcher
from pipeline.orchestrator import Orchestrator
from pipeline.sinks import InMemorySink, JsonlSink
from pipeline.sources import load_sources
from pipeline.stages import IngestionStage
from pipeline.state import FeedStateStore


def main() -> int:
    ap = argparse.ArgumentParser(description="Gist ingestion runner")
    ap.add_argument("--sources", default=None, help="path to sources.json (default: repo sources.json)")
    ap.add_argument("--out", default=None, help="write articles as JSONL here (default: in-memory only)")
    ap.add_argument("--state", default=None, help="feed-state file for conditional GET (default: none)")
    ap.add_argument("--topic", default=None, help="only ingest this topic")
    ap.add_argument("--limit", type=int, default=0, help="cap number of sources (0 = all)")
    ap.add_argument("--fixtures", default=None, help="offline mode: read <source_id>.xml from this dir")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s %(message)s",
    )

    sources = load_sources(args.sources if args.sources not in (None, "-") else None)
    if args.topic:
        sources = [s for s in sources if s.topic == args.topic]
    if args.limit:
        sources = sources[: args.limit]

    fetcher = FixtureFetcher(fixtures_dir=args.fixtures) if args.fixtures else HttpFetcher()
    sink = JsonlSink(args.out) if args.out else InMemorySink()
    state = FeedStateStore(args.state) if args.state else None

    stage = IngestionStage(sources, fetcher, sink, state_store=state)
    report = Orchestrator([stage]).run(config={"topic": args.topic})

    detail = report.stages[0].detail
    print(json.dumps(detail, indent=2))
    print(
        f"\n{detail['sources_ok']}/{detail['sources_total']} sources ok, "
        f"{detail['articles_new']} new articles"
        + (f" -> {args.out}" if args.out else ""),
        file=sys.stderr,
    )
    return 0 if detail["sources_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
