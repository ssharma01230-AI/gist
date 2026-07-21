"""Parsing + normalization: feed bytes -> canonical Article records."""
from pathlib import Path

from pipeline.models import SourceConfig
from pipeline.parse import parse_feed, feed_is_wellformed

FIX = Path(__file__).parent / "fixtures"


def _src(sid="example-science", topic="science", url="https://example-science.test/rss"):
    return SourceConfig(id=sid, topic=topic, name=sid, type="rss", url=url, status="ok")


def test_rss2_parses_all_items():
    arts = parse_feed(_src(), (FIX / "rss2_science.xml").read_bytes())
    assert len(arts) == 3
    lead = arts[0]
    assert lead.title.startswith("New telescope detects")
    assert lead.url == "https://example-science.test/k2-18b"
    assert lead.topic == "science"
    assert lead.source_id == "example-science"


def test_summary_html_is_stripped_to_plain_text():
    arts = parse_feed(_src(), (FIX / "rss2_science.xml").read_bytes())
    summary = arts[0].summary
    assert "<" not in summary and ">" not in summary
    assert "biological processes" in summary
    assert "’" in summary  # &#8217; entity decoded


def test_pubdate_normalized_to_iso_utc():
    arts = parse_feed(_src(), (FIX / "rss2_science.xml").read_bytes())
    assert arts[0].published_at == "2026-07-20T09:15:00+00:00"


def test_image_extracted_from_media_enclosure_or_body():
    arts = parse_feed(_src(), (FIX / "rss2_science.xml").read_bytes())
    assert arts[0].image_url == "https://media.example-science.test/k2-18b-lead.jpg"  # media:content
    assert arts[2].image_url == "https://media.example-science.test/mars.png"  # enclosure


def test_authors_and_tags():
    arts = parse_feed(_src(), (FIX / "rss2_science.xml").read_bytes())
    assert arts[0].authors == ("A. Astronomer",)
    assert "Astronomy" in arts[0].tags


def test_ids_are_stable_across_reparse():
    body = (FIX / "rss2_science.xml").read_bytes()
    first = [a.id for a in parse_feed(_src(), body)]
    second = [a.id for a in parse_feed(_src(), body)]
    assert first == second
    assert len(set(first)) == 3  # unique per item


def test_same_story_different_source_gets_different_id():
    body = (FIX / "rss2_science.xml").read_bytes()
    a = parse_feed(_src(sid="source-a"), body)[0]
    b = parse_feed(_src(sid="source-b"), body)[0]
    assert a.id != b.id  # dedup is per-source; cross-source pairing is the select stage's job


def test_atom_feed_parses_with_published_and_content_image():
    src = _src(sid="example-tech", topic="technology", url="https://example-tech.test/atom")
    arts = parse_feed(src, (FIX / "atom_tech.xml").read_bytes())
    assert len(arts) == 2
    assert arts[0].published_at == "2026-07-21T07:15:00+00:00"
    assert arts[0].authors == ("T. Writer",)
    assert arts[1].image_url == "https://img.example-tech.test/oss.png"  # pulled from content <img>


def test_malformed_feed_does_not_crash():
    # feedparser flags it as not well-formed, but parsing must not raise.
    arts = parse_feed(_src(), (FIX / "malformed.xml").read_bytes())
    assert isinstance(arts, list)
    assert feed_is_wellformed((FIX / "rss2_science.xml").read_bytes()) is True
    assert feed_is_wellformed((FIX / "malformed.xml").read_bytes()) is False
