"""快照存储层 — 管理历史快照的持久化与查询。"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STORE_DIR = Path.home() / ".argocd_insight" / "snapshots"


class SnapshotStore:
    """基于文件系统的快照存储。每个快照为一个 JSON 文件。"""

    def __init__(self, store_dir: str | Path | None = None):
        self._dir = Path(store_dir) if store_dir else DEFAULT_STORE_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def store_dir(self) -> Path:
        return self._dir

    def save(
        self,
        data: dict[str, Any],
        ts: datetime | None = None,
    ) -> Path:
        """保存一个快照，返回文件路径。"""
        ts = ts or datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        path = self._dir / f"{ts_str}.json"

        envelope = {
            "timestamp": ts_str,
            "modules": data,
        }
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load(self, ts_str: str) -> dict[str, Any] | None:
        """按时间戳字符串加载快照，不存在返回 None。"""
        path = self._dir / f"{ts_str}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def load_latest(self) -> dict[str, Any] | None:
        """加载最新快照。"""
        snapshots = self.list_snapshots()
        if not snapshots:
            return None
        return self.load(snapshots[-1])

    def list_snapshots(self) -> list[str]:
        """列出所有快照时间戳（升序）。"""
        files = sorted(self._dir.glob("*.json"))
        return [f.stem for f in files if self._is_valid_snapshot(f)]

    def delete(self, ts_str: str) -> bool:
        """删除指定快照。"""
        path = self._dir / f"{ts_str}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def delete_before(self, cutoff_ts: str) -> int:
        """删除指定时间戳之前的所有快照，返回删除数量。"""
        count = 0
        for ts_str in self.list_snapshots():
            if ts_str < cutoff_ts:
                if self.delete(ts_str):
                    count += 1
        return count

    def count(self) -> int:
        """返回快照总数。"""
        return len(self.list_snapshots())

    @staticmethod
    def _is_valid_snapshot(path: Path) -> bool:
        """检查文件是否为有效快照。"""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return "timestamp" in data and "modules" in data
        except (json.JSONDecodeError, OSError):
            return False
