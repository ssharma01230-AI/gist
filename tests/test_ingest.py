"""Ingestor orchestration: fetch -> parse -> dedup -> emit, with robustness."""
from pathlib import Path

from pipeline.fetch import FixtureFetcher
from pipeline.ingest import ingest
from pipeline.models import SourceConfig
from pipeline.sinks import InMemorySink, JsonlSink, read_jsonl
from pipeline.state import FeedState, FeedStateStore

FIX = Path(__file__).parent / "fixtures"


def _sources():
    return [
        SourceConfig("example-science", "science", "Sci", "rss", "https://s.test/rss", "ok"),
        SourceConfig("example-tech", "technology", "Tech", "rss", "https://t.test/atom", "ok"),
    ]


def _fetcher():
    return FixtureFetcher(
        by_source={
            "example-science": (FIX / "rss2_science.xml").read_bytes(),
            "example-tech": (FIX / "atom_tech.xml").read_bytes(),
        }
    )


def test_ingest_collects_all_sources():
    sink = InMemorySink()
    summary = ingest(_sources(), _fetcher(), sink)
    assert summary.sources_total == 2
    assert summary.sources_ok == 2
    assert summary.sources_failed == 0
    assert summary.articles_new == 5  # 3 science + 2 tech
    assert len(sink.articles) == 5
    assert {a.topic for a in sink.articles} == {"science", "technology"}


def test_rerun_dedups_no_new_articles():
    sink = InMemorySink()
    ingest(_sources(), _fetcher(), sink)
    summary2 = ingest(_sources(), _fetcher(), sink)
    assert summary2.articles_new == 0
    assert summary2.articles_parsed == 5  # still parsed, just already seen
    assert len(sink.articles) == 5


def test_one_bad_source_does_not_abort_the_run():
    fetcher = FixtureFetcher(
        by_source={"example-science": (FIX / "rss2_science.xml").read_bytes()},
        errors={"example-tech": "TimeoutError: read timed out"},
    )
    sink = InMemorySink()
    summary = ingest(_sources(), fetcher, sink)
    assert summary.sources_failed == 1
    assert summary.articles_new == 3  # the healthy source still delivered
    failed = [r for r in summary.reports if r.status == "error"][0]
    assert failed.source_id == "example-tech"
    assert "timed out" in failed.error


def test_missing_fixture_is_reported_as_error_not_crash():
    fetcher = FixtureFetcher(by_source={})  # nothing registered
    summary = ingest(_sources(), fetcher, InMemorySink())
    assert summary.sources_failed == 2
    assert all(r.status == "error" for r in summary.reports)


def test_not_modified_is_counted_ok_with_no_articles():
    class NotModifiedFetcher:
        def fetch(self, source_id, url, *, etag="", last_modified=""):
            from pipeline.models import FetchResult

            return FetchResult(source_id=source_id, url=url, status_code=304, not_modified=True)

    summary = ingest(_sources(), NotModifiedFetcher(), InMemorySink())
    assert summary.sources_ok == 2
    assert summary.articles_new == 0
    assert all(r.status == "not_modified" for r in summary.reports)


def test_jsonl_sink_persists_and_dedups_across_process_restart(tmp_path):
    out = tmp_path / "articles.jsonl"
    ingest(_sources(), _fetcher(), JsonlSink(out))
    assert out.exists()
    first = list(read_jsonl(out))
    assert len(first) == 5

    # Fresh sink object (simulates a new process) must dedup against the file.
    summary2 = ingest(_sources(), _fetcher(), JsonlSink(out))
    assert summary2.articles_new == 0
    assert len(list(read_jsonl(out))) == 5


def test_conditional_get_sends_stored_validators(tmp_path):
    seen_headers = {}

    class RecordingFetcher:
        def fetch(self, source_id, url, *, etag="", last_modified=""):
            from pipeline.models import FetchResult

            seen_headers[source_id] = (etag, last_modified)
            return FetchResult(source_id=source_id, url=url, status_code=200, body=b"<rss></rss>")

    store = FeedStateStore(tmp_path / "state.json")
    store.set("example-science", FeedState(etag='"abc"', last_modified="Mon, 20 Jul 2026 09:15:00 GMT"))
    ingest(_sources()[:1], RecordingFetcher(), InMemorySink(), state_store=store)
    assert seen_headers["example-science"] == ('"abc"', "Mon, 20 Jul 2026 09:15:00 GMT")
