"""Tests for impact module."""
from __future__ import annotations

from argocd_insight.impact import ImpactAnalysis, ResourceImpact, AppDependency


def test_resource_impact_dataclass():
    r = ResourceImpact(kind="Deployment", name="nginx", namespace="default",
                       status="modified", risk="low")
    assert r.kind == "Deployment"
    assert r.status == "modified"
    assert r.risk == "low"


def test_app_dependency_dataclass():
    d = AppDependency(app="parent-app", relationship="parent", risk="high")
    assert d.app == "parent-app"
    assert d.risk == "high"


def test_impact_analysis_dataclass():
    a = ImpactAnalysis(
        app="myapp", operation="sync",
        current_status={"health": "Healthy", "sync": "Synced"},
        resources_affected=[], dependencies=[], risks=[], recommendations=[],
        estimated_duration="< 30s",
    )
    assert a.app == "myapp"
    assert a.operation == "sync"
    assert a.estimated_duration == "< 30s"


def test_resource_impact_various_statuses():
    statuses = ["created", "modified", "deleted", "unchanged"]
    for s in statuses:
        r = ResourceImpact(kind="Deployment", name="test", namespace="ns",
                           status=s, risk="low")
        assert r.status == s


def test_app_dependency_relationships():
    for rel in ["parent", "child", "peer"]:
        d = AppDependency(app="test", relationship=rel, risk="low")
        assert d.relationship == rel
