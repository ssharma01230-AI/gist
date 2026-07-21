"""Load and query the source manifest (sources.json)."""
from __future__ import annotations

import json
from pathlib import Path

from .models import SourceConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCES_PATH = _REPO_ROOT / "sources.json"


def load_sources(path: str | Path | None = None) -> list[SourceConfig]:
    p = Path(path) if path else DEFAULT_SOURCES_PATH
    data = json.loads(p.read_text(encoding="utf-8"))
    out: list[SourceConfig] = []
    for row in data["sources"]:
        out.append(
            SourceConfig(
                id=row["id"],
                topic=row["topic"],
                name=row["name"],
                type=row["type"],
                url=row["url"],
                status=row["status"],
                notes=row.get("notes", ""),
            )
        )
    _assert_unique_ids(out)
    return out


def _assert_unique_ids(sources: list[SourceConfig]) -> None:
    seen: set[str] = set()
    dupes = {s.id for s in sources if s.id in seen or seen.add(s.id)}  # type: ignore[func-returns-value]
    if dupes:
        raise ValueError(f"Duplicate source ids in manifest: {sorted(dupes)}")


def fetchable_sources(sources: list[SourceConfig]) -> list[SourceConfig]:
    return [s for s in sources if s.fetchable]
