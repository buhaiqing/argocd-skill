"""Integration tests — end-to-end pipeline verification.

Tests the full chain: 采集 → 存储 → 查询 → 推送
(capture → store → query → push)
"""
from __future__ import annotations

import json
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path

import pytest

from argocd_insight.snapshot_store import SnapshotStore
from argocd_insight.trend import analyze_trend, compute_delta, format_trend_markdown
from argocd_insight.config_compare import compare_applications, format_compare_markdown
from argocd_insight.predict import predict_batch, format_predict_markdown
from argocd_insight.report_composer import _summarize_module, _truncate_json_block


def _make_app(
    name: str,
    repo: str = "https://github.com/test/repo",
    path: str = "apps/test",
    namespace: str = "default",
    server: str = "https://kubernetes.default.svc",
    sync_status: str = "Synced",
    auto_sync: bool = True,
) -> dict:
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    spec: dict = {
        "source": {"repoURL": repo, "targetRevision": "main", "path": path},
        "destination": {"server": server, "namespace": namespace},
    }
    if auto_sync:
        spec["syncPolicy"] = {"automated": {"prune": True, "selfHeal": True}}
    status: dict = {
        "sync": {"status": sync_status},
        "health": {"status": "Healthy"},
        "operationState": {"finishedAt": (now - timedelta(days=5)).isoformat()},
        "revisions": [{"revision": "abc", "committedAt": (now - timedelta(days=3)).isoformat()}],
    }
    return {"metadata": {"name": name}, "spec": spec, "status": status}


class TestSnapshotTrendPipeline:
    """采集 → 存储 → 查询: snapshot → trend analysis."""

    def test_save_snapshot_then_analyze_trend(self, tmp_path):
        store = SnapshotStore(tmp_path / "snapshots")

        snapshot1 = {
            "health": {"score": 85, "healthy_apps": 90, "degraded_apps": 5},
        }
        snapshot2 = {
            "health": {"score": 92, "healthy_apps": 95, "degraded_apps": 2},
        }

        ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2026, 1, 8, tzinfo=timezone.utc)

        store.save(snapshot1, ts=ts1)
        store.save(snapshot2, ts=ts2)

        assert store.count() == 2

        trend = analyze_trend(store)
        assert "error" not in trend
        assert trend["snapshot_count"] == 2
        assert "health.score" in trend["deltas"]

        health_delta = trend["deltas"]["health.score"]
        assert health_delta["delta"] == 7.0
        assert health_delta["pct_change"] > 0

        md = format_trend_markdown(trend)
        assert "# 趋势分析报告" in md
        assert "health.score" in md

    def test_specific_metric_trend(self, tmp_path):
        store = SnapshotStore(tmp_path / "snapshots")

        for i in range(5):
            ts = datetime(2026, 1, i + 1, tzinfo=timezone.utc)
            store.save({"health": {"score": 80 + i * 2}}, ts=ts)

        trend = analyze_trend(store, metric="health.score")
        assert "error" not in trend
        assert "health.score" in trend["deltas"]
        assert trend["deltas"]["health.score"]["delta"] == 8.0

    def test_snapshot_list_delete(self, tmp_path):
        store = SnapshotStore(tmp_path / "snapshots")

        ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        store.save({"a": 1}, ts=ts1)
        store.save({"b": 2}, ts=ts2)

        snapshots = store.list_snapshots()
        assert len(snapshots) == 2

        store.delete(snapshots[0])
        assert store.count() == 1

        loaded = store.load_latest()
        assert loaded["modules"] == {"b": 2}


class TestConfigComparePipeline:
    """配置对比: multiple apps → compare → report."""

    def test_compare_identical_apps(self):
        apps = {
            "app-a": _make_app("app-a", path="apps/web"),
            "app-b": _make_app("app-b", path="apps/web"),
        }
        result = compare_applications(apps)
        assert result["total_diffs"] == 0
        assert result["app_count"] == 2

    def test_compare_different_apps(self):
        apps = {
            "app-a": _make_app("app-a", namespace="prod"),
            "app-b": _make_app("app-b", namespace="staging"),
        }
        result = compare_applications(apps)
        assert result["total_diffs"] > 0

        md = format_compare_markdown(result)
        assert "# 配置对比报告" in md

    def test_compare_with_groups(self):
        apps = {
            "web-a": _make_app("web-a", path="apps/web", namespace="prod"),
            "web-b": _make_app("web-b", path="apps/web", namespace="staging"),
            "api-a": _make_app("api-a", path="apps/api", namespace="prod"),
        }
        groups = {"web": ["web-a", "web-b"], "api": ["api-a"]}
        result = compare_applications(apps, groups)
        assert result["group_count"] == 2
        assert "web" in result["groups"]
        assert "api" in result["groups"]


class TestPredictPipeline:
    """风险预测: apps → lag risk + cost risk → report."""

    def test_predict_low_risk(self):
        apps = {
            "app-a": _make_app("app-a", auto_sync=True, sync_status="Synced"),
            "app-b": _make_app("app-b", auto_sync=True, sync_status="Synced"),
        }
        result = predict_batch(apps)
        assert result["app_count"] == 2
        assert result["summary"]["total_warnings"] == 0

    def test_predict_high_risk(self):
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        app = {
            "metadata": {"name": "stale-app"},
            "spec": {"source": {"repoURL": "x", "targetRevision": "main", "path": "x"}, "destination": {"server": "x", "ns": "x"}},
            "status": {
                "sync": {"status": "OutOfSync"},
                "health": {"status": "Degraded"},
                "operationState": {"finishedAt": (now - timedelta(days=60)).isoformat()},
                "revisions": [{"revision": "old", "committedAt": (now - timedelta(days=45)).isoformat()}],
            },
        }
        result = predict_batch({"stale-app": app})
        assert result["summary"]["total_warnings"] > 0

        lag = next(r for r in result["lag_risks"] if r["name"] == "stale-app")
        assert lag["risk_score"] >= 50

    def test_predict_report_format(self):
        apps = {"app-a": _make_app("app-a")}
        result = predict_batch(apps)
        md = format_predict_markdown(result)
        assert "# 风险预测报告" in md


class TestReportComposerIntegration:
    """报告合成: summarize + truncate modules."""

    def test_summarize_health(self):
        data = {
            "health_score": 90,
            "total_apps": 100,
            "healthy": 85,
            "degraded": 10,
            "missing": 5,
        }
        summary = _summarize_module("health", data)
        assert isinstance(summary, tuple)
        assert len(summary) == 2

    def test_truncate_long_block(self):
        long_data = [{"key": f"value_{i}"} for i in range(100)]
        truncated = _truncate_json_block(long_data, max_items=10)
        assert isinstance(truncated, str)

    def test_truncate_short_block(self):
        short_data = [{"key": "value"}]
        result = _truncate_json_block(short_data, max_items=100)
        assert isinstance(result, str)


class TestReportPushPipeline:
    """报告合成 + 推送链路（mock webhook）。"""

    @unittest.mock.patch("argocd_insight.report_push.send_webhook")
    def test_compose_and_push(self, mock_send):
        mock_send.return_value = (200, "")

        from argocd_insight.report_composer import compose_report

        report_text, results = compose_report(
            includes=["health"],
            push=True,
            webhook_url="https://example.com/hook",
            channel="feishu",
        )

        assert "ArgoCD 综合报告" in report_text
        mock_send.assert_called_once()
        call_args = mock_send.call_args
        assert call_args[0][0] == "https://example.com/hook"

    @unittest.mock.patch("argocd_insight.report_push.send_webhook")
    def test_push_failure_returns_error(self, mock_send):
        mock_send.return_value = (500, "Internal Server Error")

        from argocd_insight.report_composer import compose_report

        # compose_report prints error to stderr but doesn't raise
        report_text, _ = compose_report(
            includes=["health"],
            push=True,
            webhook_url="https://example.com/hook",
        )
        assert report_text  # report still generated even if push fails
        mock_send.assert_called_once()

    def test_push_without_webhook_skipped(self):
        from argocd_insight.report_push import push_report

        ok, err = push_report("test", webhook_url="")
        assert ok is False
        assert "webhook" in err.lower() or "缺少" in err


class TestEndToEndChain:
    """Full pipeline: capture → store → analyze → compare → predict → report."""

    def test_full_pipeline(self, tmp_path):
        store = SnapshotStore(tmp_path / "snapshots")

        ts1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        ts2 = datetime(2026, 1, 7, tzinfo=timezone.utc)

        snap1 = {
            "health": {"score": 80, "healthy_apps": 80, "degraded_apps": 15},
            "cost": {"total": 500.0},
        }
        snap2 = {
            "health": {"score": 90, "healthy_apps": 90, "degraded_apps": 5},
            "cost": {"total": 550.0},
        }

        store.save(snap1, ts=ts1)
        store.save(snap2, ts=ts2)

        trend = analyze_trend(store)
        assert "error" not in trend
        assert trend["snapshot_count"] == 2

        apps = {
            "web-prod": _make_app("web-prod", namespace="prod"),
            "web-staging": _make_app("web-staging", namespace="staging"),
        }
        compare_result = compare_applications(apps)
        assert compare_result["app_count"] == 2

        predict_result = predict_batch(apps)
        assert predict_result["app_count"] == 2

        trend_md = format_trend_markdown(trend)
        compare_md = format_compare_markdown(compare_result)
        predict_md = format_predict_markdown(predict_result)

        combined = f"{trend_md}\n\n{compare_md}\n\n{predict_md}"
        assert "# 趋势分析报告" in combined
        assert "# 配置对比报告" in combined
        assert "# 风险预测报告" in combined
