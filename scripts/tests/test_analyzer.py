"""Tests for analyzer module (轨迹分析器)."""
import pytest
from argocd_insight.analyzer.stats import compute_stats
from argocd_insight.analyzer.bottleneck import find_bottlenecks
from argocd_insight.analyzer.error_classify import classify_errors


def test_compute_stats():
    events = [
        {"duration_ms": 100, "return_code": 0, "module": "diagnose"},
        {"duration_ms": 200, "return_code": 0, "module": "diagnose"},
        {"duration_ms": 300, "return_code": 1, "module": "diagnose"},
    ]
    stats = compute_stats(events)
    assert stats["total_calls"] == 3
    assert stats["error_rate"] == pytest.approx(1 / 3)
    assert stats["p50_ms"] == 200


def test_compute_stats_empty():
    stats = compute_stats([])
    assert stats["total_calls"] == 0


def test_error_classify():
    events = [
        {"return_code": 1, "error": "unauthorized", "command": "argocd app list"},
        {"return_code": -1, "error": "Timed out", "command": "argocd app sync"},
        {"return_code": 0, "error": "", "command": "argocd app get"},
    ]
    classified = classify_errors(events)
    assert "auth_error" in classified
    assert "network_timeout" in classified


def test_find_bottlenecks():
    events = [
        {"duration_ms": 100, "command": "argocd app list"},
        {"duration_ms": 200, "command": "argocd app list"},
        {"duration_ms": 5000, "command": "argocd app sync"},
        {"duration_ms": 100, "command": "argocd app get"},
        {"duration_ms": 100, "command": "argocd app get"},
        {"duration_ms": 100, "command": "argocd app get"},
        {"duration_ms": 100, "command": "argocd app get"},
    ]
    b = find_bottlenecks(events)
    assert b["p95_ms"] > 0
    assert len(b["hot_commands"]) > 0