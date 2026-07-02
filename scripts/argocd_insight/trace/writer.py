"""JSONL 轨迹写入。"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, TextIO


class TraceWriter:
    """JSONL 轨迹写入器。"""

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._file_index = 0
        self._file: TextIO | None = None
        self._open_file()

    def _open_file(self):
        self._file = open(
            self.session_dir / f"trace_{self._file_index:03d}.jsonl",
            "a",
            encoding="utf-8",
        )

    def write_event(self, event: dict[str, Any]):
        if self._file is None:
            self._open_file()
        if "ts" not in event:
            event["ts"] = datetime.now(timezone.utc).isoformat()
        self._file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None