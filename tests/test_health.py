"""Feed health checks: reachability + item count + freshness/staleness."""
from datetime import datetime, timezone
from pathlib import Path

from pipeline.fetch import FixtureFetcher
from pipeline.health import (
    FAIL, PASS, SKIP, WARN, check_sources, overall_ok, render_table, summarize,
)
from pipeline.models import SourceConfig

FIX = Path(__file__).parent / "fixtures"

# The science fixture's newest item is dated 2026-07-20T09:15:00Z.
JUST_AFTER = datetime(2026, 7, 20, 12, 0, 0, tzinfo=timezone.utc)   # ~3h later: fresh
LONG_AFTER = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)     # months later: stale


def _rss(sid="space-com"):
    return SourceConfig(sid, "science", "Sci", "rss", "https://s.test/rss", "ok")


def _fetcher():
    return FixtureFetcher(by_source={"space-com": (FIX / "rss2_science.xml").read_bytes()})


def test_healthy_fresh_source_passes():
    h = check_sources([_rss()], _fetcher(), now=JUST_AFTER, max_workers=1)[0]
    assert h.verdict == PASS
    assert h.item_count == 3
    assert h.newest_age_hours is not None and h.newest_age_hours < 4
    assert h.stale is False


def test_reachable_but_stale_source_warns():
    h = check_sources([_rss()], _fetcher(), now=LONG_AFTER, max_workers=1)[0]
    assert h.verdict == WARN
    assert h.stale is True
    assert "stale" in h.error
    # This is the CNN/Axios failure mode: HTTP-fine but abandoned.
    assert h.http_status == 200


def test_unreachable_source_fails():
    fetcher = FixtureFetcher(errors={"space-com": "ConnectTimeout: timed out"})
    h = check_sources([_rss()], fetcher, now=JUST_AFTER, max_workers=1)[0]
    assert h.verdict == FAIL
    assert "timed out" in h.error


def test_empty_or_malformed_feed_fails():
    fetcher = FixtureFetcher(by_source={"space-com": (FIX / "malformed.xml").read_bytes()})
    h = check_sources([_rss()], fetcher, now=JUST_AFTER, max_workers=1)[0]
    assert h.verdict == FAIL
    assert "zero items" in h.error


def test_api_source_is_skipped_not_failed():
    api = SourceConfig("alphavantage", "finance", "AV", "api", "https://x.test", "ok_caution")
    h = check_sources([api], _fetcher(), now=JUST_AFTER, max_workers=1)[0]
    assert h.verdict == SKIP


def test_overall_ok_gating():
    healths = check_sources([_rss()], _fetcher(), now=LONG_AFTER, max_workers=1)  # WARN (stale)
    assert overall_ok(healths, strict=False) is True    # warn alone doesn't fail
    assert overall_ok(healths, strict=True) is False     # strict fails on stale

    failing = check_sources(
        [_rss()], FixtureFetcher(errors={"space-com": "boom"}), now=JUST_AFTER, max_workers=1
    )
    assert overall_ok(failing, strict=False) is False    # a FAIL always fails


def test_summary_and_table_render():
    sources = [
        _rss("space-com"),
        SourceConfig("alphavantage", "finance", "AV", "api", "https://x.test", "ok_caution"),
    ]
    fetcher = FixtureFetcher(by_source={"space-com": (FIX / "rss2_science.xml").read_bytes()})
    healths = check_sources(sources, fetcher, now=JUST_AFTER, max_workers=1)
    counts = summarize(healths)
    assert counts[PASS] == 1 and counts[SKIP] == 1
    table = render_table(healths)
    assert "space-com" in table and "pass" in table.lower()
