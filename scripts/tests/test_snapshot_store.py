"""Tests for snapshot_store.py"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from argocd_insight.snapshot_store import SnapshotStore


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(tmp_path)


@pytest.fixture
def store_dir(tmp_path):
    return tmp_path


class TestSnapshotStore:
    def test_save_and_load(self, store):
        data = {"health": {"score": 90}}
        path = store.save(data)
        assert path.exists()

        snapshots = store.list_snapshots()
        assert len(snapshots) == 1

        loaded = store.load(snapshots[0])
        assert loaded["modules"] == data
        assert "timestamp" in loaded

    def test_load_nonexistent(self, store):
        assert store.load("2099-01-01T00:00:00Z") is None

    def test_load_latest(self, store):
        store.save({"a": 1})
        store.save({"b": 2})
        latest = store.load_latest()
        assert latest["modules"] == {"b": 2}

    def test_load_latest_empty(self, store):
        assert store.load_latest() is None

    def test_list_sorted(self, store):
        for i in range(3):
            ts = datetime(2026, 1, 1, i, 0, 0, tzinfo=timezone.utc)
            store.save({"i": i}, ts=ts)
        snapshots = store.list_snapshots()
        assert snapshots == sorted(snapshots)

    def test_delete(self, store):
        store.save({"x": 1})
        snapshots = store.list_snapshots()
        assert store.delete(snapshots[0])
        assert store.count() == 0

    def test_delete_nonexistent(self, store):
        assert not store.delete("2099-01-01T00:00:00Z")

    def test_delete_before(self, store):
        ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2026, 6, 1, tzinfo=timezone.utc)
        store.save({"a": 1}, ts=ts1)
        store.save({"b": 2}, ts=ts2)
        deleted = store.delete_before("2026-03-01T00:00:00Z")
        assert deleted == 1
        assert store.count() == 1

    def test_count(self, store):
        assert store.count() == 0
        store.save({"a": 1})
        assert store.count() == 1

    def test_is_valid_snapshot(self, store):
        valid = store.save({"x": 1})
        assert SnapshotStore._is_valid_snapshot(valid)

    def test_invalid_json_file(self, store_dir):
        bad_file = store_dir / "bad.json"
        bad_file.write_text("not json")
        assert not SnapshotStore._is_valid_snapshot(bad_file)

    def test_missing_fields(self, store_dir):
        incomplete = store_dir / "inc.json"
        incomplete.write_text(json.dumps({"timestamp": "x"}))
        assert not SnapshotStore._is_valid_snapshot(incomplete)

    def test_store_dir_created(self, store_dir):
        new_dir = store_dir / "nested" / "store"
        s = SnapshotStore(new_dir)
        assert new_dir.exists()
