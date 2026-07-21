"""Per-source fetch state (ETag / Last-Modified) for conditional GET.

Small JSON file keyed by source id. Optional: pass None to the ingestor to
disable conditional GET entirely.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class FeedState:
    etag: str = ""
    last_modified: str = ""
    last_fetched: str = ""


class FeedStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._data: dict[str, FeedState] = {}
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for sid, s in raw.items():
                self._data[sid] = FeedState(**s)

    def get(self, source_id: str) -> FeedState:
        return self._data.get(source_id, FeedState())

    def set(self, source_id: str, state: FeedState) -> None:
        self._data[source_id] = state

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {sid: vars(s) for sid, s in self._data.items()}
        self.path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
