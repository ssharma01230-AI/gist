#!/usr/bin/env python3
"""Turn an ingestion JSONL dump into a human-friendly CSV.

    python scripts/snapshot_to_csv.py data/snapshot/articles.jsonl --out data/snapshot/articles.csv

Columns: published_at, topic, source, title, url. Sorted by topic (canonical
order) then newest-first within each topic.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.sources import load_sources

TOPIC_ORDER = [
    "politics", "breaking-news", "finance", "world", "sports",
    "entertainment", "technology", "science", "culture-arts", "gaming-esports",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", help="input articles.jsonl")
    ap.add_argument("--sources", default=None, help="sources.json for id->name mapping")
    ap.add_argument("--out", required=True, help="output CSV path")
    args = ap.parse_args()

    name = {s.id: s.name for s in load_sources(args.sources)}
    rank = {t: i for i, t in enumerate(TOPIC_ORDER)}

    rows = []
    for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))

    # topic ascending, newest-first within topic
    rows.sort(key=lambda d: d.get("published_at") or "", reverse=True)
    rows.sort(key=lambda d: rank.get(d["topic"], 99))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["published_at", "topic", "source", "title", "url"])
        for d in rows:
            w.writerow([
                d.get("published_at", ""),
                d["topic"],
                name.get(d["source_id"], d["source_id"]),
                d.get("title", ""),
                d.get("url", ""),
            ])

    by_topic = Counter(d["topic"] for d in rows)
    by_source = Counter(d["source_id"] for d in rows)
    print(f"{len(rows)} articles -> {out}")
    print("SNAP_TOPIC " + json.dumps({t: by_topic.get(t, 0) for t in TOPIC_ORDER}))
    print("SNAP_TOTAL " + json.dumps({"articles": len(rows), "sources_with_items": len(by_source)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
