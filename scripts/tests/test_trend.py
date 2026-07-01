"""Tests for trend.py"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from argocd_insight.snapshot_store import SnapshotStore
from argocd_insight.trend import (
    _count_by_severity,
    _extract_number,
    analyze_trend,
    compute_delta,
    format_trend_markdown,
    main,
)


class TestExtractNumber:
    def test_simple(self):
        assert _extract_number({"score": 90}, "score") == 90.0

    def test_nested(self):
        assert _extract_number({"health": {"score": 85}}, "health", "score") == 85.0

    def test_missing(self):
        assert _extract_number({"a": 1}, "b") is None

    def test_non_number(self):
        assert _extract_number({"a": "x"}, "a") is None

    def test_deeply_nested(self):
        assert _extract_number({"a": {"b": {"c": 42}}}, "a", "b", "c") == 42.0


class TestCountBySeverity:
    def test_diagnose_apps(self):
        data = {"apps": [{"severity": "critical"}, {"severity": "low"}]}
        assert _count_by_severity(data, "critical") == 1

    def test_list_input(self):
        data = [{"severity": "high"}, {"severity": "high"}]
        assert _count_by_severity(data, "high") == 2

    def test_none(self):
        assert _count_by_severity(None, "critical") == 0

    def test_no_matching_key(self):
        assert _count_by_severity({"x": 1}, "critical") == 0


class TestComputeDelta:
    def _make_snapshot(self, modules, ts="2026-01-01T00:00:00Z"):
        return {"timestamp": ts, "modules": modules}

    def test_basic(self):
        s1 = self._make_snapshot({"health": {"score": 80}})
        s2 = self._make_snapshot({"health": {"score": 90}}, "2026-06-01T00:00:00Z")
        result = compute_delta([s1, s2], "health.score")
        assert result["first_value"] == 80.0
        assert result["last_value"] == 90.0
        assert result["delta"] == 10.0
        assert result["pct_change"] == 12.5

    def test_decrease(self):
        s1 = self._make_snapshot({"cost": {"total": 100}})
        s2 = self._make_snapshot({"cost": {"total": 80}})
        result = compute_delta([s1, s2], "cost.total")
        assert result["delta"] == -20.0
        assert result["pct_change"] == -20.0

    def test_insufficient_snapshots(self):
        result = compute_delta([], "x")
        assert "error" in result

    def test_single_snapshot(self):
        result = compute_delta([self._make_snapshot({})], "x")
        assert "error" in result

    def test_missing_metric(self):
        s1 = self._make_snapshot({})
        s2 = self._make_snapshot({})
        result = compute_delta([s1, s2], "nonexistent")
        assert "error" in result

    def test_zero_first_value(self):
        s1 = self._make_snapshot({"a": {"b": 0}})
        s2 = self._make_snapshot({"a": {"b": 10}})
        result = compute_delta([s1, s2], "a.b")
        assert result["pct_change"] == 0.0


@pytest.fixture
def trend_store(tmp_path):
    return SnapshotStore(tmp_path)


class TestAnalyzeTrend:
    def test_no_snapshots(self, trend_store):
        result = analyze_trend(trend_store)
        assert "error" in result

    def test_single_snapshot(self, trend_store):
        trend_store.save({"health": {"score": 90}})
        result = analyze_trend(trend_store)
        assert "error" in result

    def test_two_snapshots(self, trend_store):
        trend_store.save({"health": {"score": 80}}, ts=datetime(2026, 1, 1, tzinfo=timezone.utc))
        trend_store.save({"health": {"score": 90}}, ts=datetime(2026, 1, 2, tzinfo=timezone.utc))
        result = analyze_trend(trend_store)
        assert "error" not in result
        assert result["snapshot_count"] == 2
        assert "health.score" in result["deltas"]

    def test_specific_metric(self, trend_store):
        trend_store.save({"cost": {"total": 100}}, ts=datetime(2026, 1, 1, tzinfo=timezone.utc))
        trend_store.save({"cost": {"total": 120}}, ts=datetime(2026, 1, 2, tzinfo=timezone.utc))
        result = analyze_trend(trend_store, metric="cost.total")
        assert "cost.total" in result["deltas"]
        assert result["deltas"]["cost.total"]["delta"] == 20.0


class TestFormatTrendMarkdown:
    def test_error(self):
        result = format_trend_markdown({"error": "no data"})
        assert "⚠️" in result

    def test_normal(self):
        trend = {
            "snapshot_count": 2,
            "first_ts": "2026-01-01T00:00:00Z",
            "last_ts": "2026-06-01T00:00:00Z",
            "deltas": {
                "health.score": {
                    "first_value": 80.0,
                    "last_value": 90.0,
                    "delta": 10.0,
                    "pct_change": 12.5,
                },
            },
        }
        md = format_trend_markdown(trend)
        assert "# 趋势分析报告" in md
        assert "health.score" in md
        assert "80.0" in md
        assert "90.0" in md


class TestMain:
    def test_no_snapshots(self, tmp_path):
        ret = main(["--store-dir", str(tmp_path)])
        assert ret == 0
