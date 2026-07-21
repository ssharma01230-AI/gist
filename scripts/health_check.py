#!/usr/bin/env python3
"""Check that every source in the manifest is alive, has items, and is fresh.

Live (needs internet — run locally or in CI):
    python scripts/health_check.py

Write a machine-readable report and gate on it:
    python scripts/health_check.py --json health-report.json
    echo $?          # 0 = all healthy, 1 = something failed

Treat stale feeds as failures too:
    python scripts/health_check.py --strict

Offline self-test against bundled fixtures (no network):
    python scripts/health_check.py --sources examples/offline_sources.json \
        --fixtures examples/offline_fixtures

Exit codes: 0 = healthy, 1 = one or more sources FAIL (or WARN under --strict).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.fetch import FixtureFetcher, HttpFetcher
from pipeline.health import (
    DEFAULT_MAX_AGE_HOURS, check_sources, overall_ok, render_table, summarize,
)
from pipeline.sources import load_sources


def main() -> int:
    ap = argparse.ArgumentParser(description="Gist feed health check")
    ap.add_argument("--sources", default=None, help="path to sources.json (default: repo sources.json)")
    ap.add_argument("--topic", default=None, help="only check this topic")
    ap.add_argument("--max-age-hours", type=float, default=DEFAULT_MAX_AGE_HOURS,
                    help=f"newest item older than this = stale/WARN (default {DEFAULT_MAX_AGE_HOURS:g})")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on WARN (stale) too, not just FAIL")
    ap.add_argument("--json", dest="json_out", default=None, help="write the full report to this path")
    ap.add_argument("--workers", type=int, default=8, help="concurrent fetches (default 8)")
    ap.add_argument("--fixtures", default=None, help="offline mode: read <source_id>.xml from this dir")
    args = ap.parse_args()

    sources = load_sources(args.sources)
    if args.topic:
        sources = [s for s in sources if s.topic == args.topic]

    fetcher = FixtureFetcher(fixtures_dir=args.fixtures) if args.fixtures else HttpFetcher()
    now = datetime.now(timezone.utc)

    healths = check_sources(
        sources, fetcher, now=now, max_age_hours=args.max_age_hours, max_workers=args.workers
    )

    print(render_table(healths))

    if args.json_out:
        report = {
            "checked_at": now.isoformat(timespec="seconds"),
            "max_age_hours": args.max_age_hours,
            "strict": args.strict,
            "summary": summarize(healths),
            "sources": [h.to_dict() for h in healths],
        }
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nreport written to {args.json_out}", file=sys.stderr)

    ok = overall_ok(healths, strict=args.strict)
    if not ok:
        print("\nFEED HEALTH CHECK FAILED", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
