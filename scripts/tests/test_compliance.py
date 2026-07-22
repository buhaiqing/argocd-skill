"""Tests for scripts/argocd_insight/compliance.py

No network calls — all subprocess interactions are mocked.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from argocd_insight.compliance import (
    build_report,
    check_app,
    fetch_all,
    print_markdown,
)


# ------------------------------------------------------------------
# run() returns (rc, stdout, stderr) tuple — mock must match
# ------------------------------------------------------------------

def _mock_run(rc=0, stdout="", stderr=""):
    def _run(cmd, **kwargs):
        return (rc, stdout, stderr)
    return _run


# ------------------------------------------------------------------
# check_app() — individual risk rules
# ------------------------------------------------------------------

def _make_app(name="app-1", ns="production", auto=False, self_heal=False,
              prune_last=False, retry=None):
    """Build a minimal ArgoCD app dict for testing."""
    sync_opts = []
    if self_heal:
        sync_opts.append("CreateNamespace=true,SelfHeal=true")
    if prune_last:
        sync_opts.append("PruneLast=true")

    sync_policy = {}
    if auto:
        # Must be truthy — empty dict {} is falsy in Python; ArgoCD deserializes
        # automated: as {"prune": true, "selfHeal": true} when configured.
        sync_policy["automated"] = {"prune": True, "selfHeal": self_heal}
    if sync_opts:
        sync_policy["syncOptions"] = sync_opts
    if retry:
        sync_policy["retry"] = retry

    return {
        "metadata": {"name": name},
        "spec": {
            "destination": {"namespace": ns},
            "syncPolicy": sync_policy,
        },
    }


def test_check_app_clean():
    """No risks when automated + self-heal + retry + PruneLast."""
    app = _make_app(auto=True, self_heal=True, prune_last=True, retry={"limit": 3})
    risks = check_app(app)
    assert risks == []


def test_check_app_automated_no_retry():
    app = _make_app(auto=True, self_heal=True)
    risks = check_app(app)
    rules = [r["rule"] for r in risks]
    assert "automated-no-retry" in rules


def test_check_app_automated_no_selfheal():
    app = _make_app(auto=True, retry={"limit": 3})
    risks = check_app(app)
    rules = [r["rule"] for r in risks]
    assert "automated-no-selfheal" in rules
    assert any(r["severity"] == "high" for r in risks if r["rule"] == "automated-no-selfheal")


def test_check_app_automated_no_prune():
    app = _make_app(auto=True, self_heal=True, retry={"limit": 3})
    risks = check_app(app)
    rules = [r["rule"] for r in risks]
    assert "automated-no-prune" in rules


def test_check_app_prune_last_not_automated():
    app = _make_app(prune_last=True)
    risks = check_app(app)
    rules = [r["rule"] for r in risks]
    assert "prune-last-not-automated" in rules


def test_check_app_system_namespace():
    app = _make_app(ns="kube-system")
    risks = check_app(app)
    rules = [r["rule"] for r in risks]
    assert "system-namespace" in rules
    assert any(r["severity"] == "high" for r in risks if r["rule"] == "system-namespace")


def test_check_app_multiple_risks():
    app = _make_app(auto=True, ns="kube-system")
    risks = check_app(app)
    rules = [r["rule"] for r in risks]
    assert "automated-no-retry" in rules
    assert "automated-no-selfheal" in rules
    assert "automated-no-prune" in rules
    assert "system-namespace" in rules


def test_check_app_empty_spec():
    app = {"metadata": {"name": "empty"}, "spec": {}}
    risks = check_app(app)
    assert risks == []


# ------------------------------------------------------------------
# fetch_all()
# ------------------------------------------------------------------

def test_fetch_all_returns_json():
    apps = [{"metadata": {"name": "a1"}}]
    with patch("argocd_insight.compliance.run", side_effect=_mock_run(rc=0, stdout=json.dumps(apps))):
        assert fetch_all() == apps


def test_fetch_all_empty():
    with patch("argocd_insight.compliance.run", side_effect=_mock_run(rc=0, stdout="")):
        assert fetch_all() == []


# ------------------------------------------------------------------
# build_report()
# ------------------------------------------------------------------

def test_build_report_no_risks():
    apps = [_make_app(auto=True, self_heal=True, prune_last=True, retry={"limit": 3})]
    report = build_report(apps, min_severity="low")
    assert report["totalApps"] == 1
    assert report["riskyApps"] == 0
    assert report["totalRisks"] == 0


def test_build_report_with_risks():
    apps = [_make_app(auto=True, ns="kube-system")]
    report = build_report(apps, min_severity="low")
    assert report["totalApps"] == 1
    assert report["riskyApps"] == 1
    assert report["totalRisks"] >= 3  # no-retry + no-selfheal + no-prune + system-ns


def test_build_report_severity_filter():
    apps = [_make_app(auto=True)]
    # With min_severity=high, only automated-no-selfheal should show
    report = build_report(apps, min_severity="high")
    rules = list(report["byRule"].keys())
    assert "automated-no-retry" not in rules
    assert "automated-no-selfheal" in rules


def test_build_report_by_rule():
    apps = [
        _make_app(name="a1", auto=True, ns="kube-system"),
        _make_app(name="a2", auto=True, ns="kube-public"),
    ]
    report = build_report(apps, min_severity="low")
    assert report["byRule"]["system-namespace"]["count"] == 2
    assert "a1" in report["byRule"]["system-namespace"]["apps"]
    assert "a2" in report["byRule"]["system-namespace"]["apps"]


def test_build_report_empty():
    report = build_report([], min_severity="low")
    assert report["totalApps"] == 0
    assert report["totalRisks"] == 0


# ------------------------------------------------------------------
# print_markdown()
# ------------------------------------------------------------------

def _sample_report(**overrides) -> dict:
    report = {
        "generatedAt": "2026-07-01T12:00:00+00:00",
        "totalApps": 5,
        "riskyApps": 3,
        "totalRisks": 7,
        "bySeverity": {"high": 2, "medium": 3, "low": 2},
        "byRule": {
            "automated-no-selfheal": {"count": 2, "apps": ["app-1", "app-2"], "total": 2},
            "automated-no-retry": {"count": 3, "apps": ["app-1", "app-2", "app-3"], "total": 3},
        },
        "risks": [
            {"rule": "automated-no-selfheal", "severity": "high", "app": "app-1",
             "message": "no self-heal", "suggestion": "add --self-heal"},
            {"rule": "automated-no-retry", "severity": "medium", "app": "app-1",
             "message": "no retry", "suggestion": "add --retry"},
        ],
    }
    report.update(overrides)
    return report


def test_print_markdown_basic(capsys):
    print_markdown(_sample_report())
    captured = capsys.readouterr().out
    assert "ArgoCD 配置合规报告" in captured
    assert "总 App 数：5" in captured
    assert "有风险：3" in captured
    assert "风险项：7" in captured
    assert "high" in captured
    assert "medium" in captured


def test_print_markdown_empty(capsys):
    report = _sample_report(totalApps=0, riskyApps=0, totalRisks=0, bySeverity={}, byRule={}, risks=[])
    print_markdown(report)
    captured = capsys.readouterr().out
    assert "总 App 数：0" in captured
