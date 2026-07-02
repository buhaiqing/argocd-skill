"""Tests for scripts/argocd_deploy_stats/stats.py

No network calls — all subprocess interactions are mocked.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch


from argocd_deploy_stats.stats import (
    build_report,
    fetch_apps,
    fetch_history,
    print_markdown,
    run,
)


# ------------------------------------------------------------------
# run() — CLI wrapper (same signature as oos_analyzer)
# ------------------------------------------------------------------

def test_run_returns_stdout():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "hello\n"
        rc, out, _ = run(["echo", "hello"])
        assert rc == 0
        assert out == "hello\n"


def test_run_timeout():
    with patch.object(subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd=["x"], timeout=1)):
        rc, _, err = run(["x"], timeout=1)
        assert rc == -1
        assert "Timed out" in err


def test_run_not_found():
    rc, _, err = run(["nope-nope-nonexistent-12345"])
    assert rc == -2
    assert "Command not found" in err


def test_run_nonzero_rc_returns_empty():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = "error"
        rc, out, _ = run(["argocd", "app", "list", "--output", "json"])
        assert rc == 1
        assert out == "error"


# ------------------------------------------------------------------
# fetch_apps()
# ------------------------------------------------------------------

def test_fetch_apps_returns_parsed_json():
    apps = [{"metadata": {"name": "my-app"}}]
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(apps)
        assert fetch_apps() == apps


def test_fetch_apps_empty_on_rc_nonzero():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        assert fetch_apps() == []


def test_fetch_apps_empty_on_empty_output():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        assert fetch_apps() == []


# ------------------------------------------------------------------
# fetch_history()
# ------------------------------------------------------------------

def test_fetch_history_returns_parsed():
    raw = {"status": {"history": [{"deployedAt": "2026-07-01T12:00:00Z", "revision": "abc123"}]}}
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(raw)
        name, hist = fetch_history("my-app")
        assert name == "my-app"
        assert len(hist) == 1
        assert hist[0]["revision"] == "abc123"


def test_fetch_history_rc_nonzero_returns_empty():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        name, hist = fetch_history("my-app")
        assert name == "my-app"
        assert hist == []


def test_fetch_history_empty_output():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        name, hist = fetch_history("my-app")
        assert name == "my-app"
        assert hist == []


def test_fetch_history_malformed_json():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "not-json"
        name, hist = fetch_history("my-app")
        assert name == "my-app"
        assert hist == []


def test_fetch_history_missing_history_key():
    raw = {"status": {}}
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(raw)
        name, hist = fetch_history("my-app")
        assert name == "my-app"
        assert hist == []


# ------------------------------------------------------------------
# build_report() — aggregation
# ------------------------------------------------------------------

def _make_app(name: str, project: str = "default") -> dict:
    return {
        "metadata": {"name": name},
        "spec": {"project": project},
    }


def _make_history(deployed_at: str, automated: bool = False) -> dict:
    entry = {
        "deployedAt": deployed_at,
        "revision": "a1b2c3d4e5f6",
    }
    if automated:
        entry["initiatedBy"] = {"automated": True}
    else:
        entry["initiatedBy"] = {"username": "admin"}
    return entry


def test_build_report_empty_apps():
    report = build_report([], days=None, project_filter=None, concurrency=1)
    assert report["totalApps"] == 0
    assert report["totalDeploys"] == 0
    assert report["byProject"] == {}
    assert report["byInitiator"] == {}
    assert report["recentDeploys"] == []


def test_build_report_counts_deploys():
    apps = [_make_app("app-1")]
    hist = [_make_history("2026-07-01T12:00:00Z"), _make_history("2026-07-02T12:00:00Z")]

    with patch("argocd_deploy_stats.stats.fetch_history", return_value=("app-1", hist)):
        report = build_report(apps, days=None, project_filter=None, concurrency=1)

    assert report["totalApps"] == 1
    assert report["totalDeploys"] == 2


def test_build_report_by_initiator():
    apps = [_make_app("app-1")]
    hist = [
        _make_history("2026-07-01T12:00:00Z", automated=True),
        _make_history("2026-07-02T12:00:00Z", automated=False),
    ]

    with patch("argocd_deploy_stats.stats.fetch_history", return_value=("app-1", hist)):
        report = build_report(apps, days=None, project_filter=None, concurrency=1)

    assert report["byInitiator"]["automated"] == 1
    assert report["byInitiator"]["admin"] == 1


def test_build_report_project_filter():
    apps = [
        _make_app("app-a", project="proj-a"),
        _make_app("app-b", project="proj-b"),
    ]

    def fake_fetch(name):
        return name, [_make_history("2026-07-01T12:00:00Z")]

    with patch("argocd_deploy_stats.stats.fetch_history", side_effect=fake_fetch):
        report = build_report(apps, days=None, project_filter="proj-a", concurrency=1)

    assert report["totalApps"] == 1
    assert "proj-a" in report["byProject"]


def test_build_report_days_filter():
    apps = [_make_app("app-1")]
    hist = [
        _make_history("2026-01-01T12:00:00Z"),   # old, should be filtered out
        _make_history("2026-07-01T12:00:00Z"),   # recent
    ]

    with patch("argocd_deploy_stats.stats.fetch_history", return_value=("app-1", hist)):
        report = build_report(apps, days=10, project_filter=None, concurrency=1)

    assert report["totalDeploys"] == 1


def test_build_report_recent_deploys_sorted():
    apps = [_make_app("app-1")]
    hist = [
        _make_history("2026-07-01T12:00:00Z"),
        _make_history("2026-07-03T12:00:00Z"),
        _make_history("2026-07-02T12:00:00Z"),
    ]

    with patch("argocd_deploy_stats.stats.fetch_history", return_value=("app-1", hist)):
        report = build_report(apps, days=None, project_filter=None, concurrency=1)

    recent = report["recentDeploys"]
    assert len(recent) == 3
    # Should be sorted descending by deployedAt
    assert recent[0]["deployedAt"] > recent[1]["deployedAt"] > recent[2]["deployedAt"]


def test_build_report_recent_deploys_limited_to_50():
    apps = [_make_app("app-1")]
    hist = [_make_history(f"2026-07-{d:02d}T12:00:00Z") for d in range(1, 100)]

    with patch("argocd_deploy_stats.stats.fetch_history", return_value=("app-1", hist)):
        report = build_report(apps, days=None, project_filter=None, concurrency=1)

    assert len(report["recentDeploys"]) == 50


def test_build_report_multiple_apps_aggregation():
    apps = [
        _make_app("app-a", project="proj-x"),
        _make_app("app-b", project="proj-y"),
    ]

    def fake_fetch(name):
        hist = [_make_history("2026-07-01T12:00:00Z")]
        return name, hist

    with patch("argocd_deploy_stats.stats.fetch_history", side_effect=fake_fetch):
        report = build_report(apps, days=None, project_filter=None, concurrency=2)

    assert report["totalApps"] == 2
    assert report["totalDeploys"] == 2
    assert "proj-x" in report["byProject"]
    assert "proj-y" in report["byProject"]


# ------------------------------------------------------------------
# print_markdown() — output format
# ------------------------------------------------------------------

def _sample_report(**overrides) -> dict:
    report = {
        "generatedAt": "2026-07-01T12:00:00+00:00",
        "days": None,
        "projectFilter": None,
        "totalApps": 5,
        "totalDeploys": 20,
        "byProject": {"default": 15, "infra": 5},
        "byInitiator": {"automated": 12, "admin": 8},
        "recentDeploys": [
            {
                "app": "my-app",
                "project": "default",
                "deployedAt": "2026-07-01T12:00:00Z",
                "revision": "abc123",
                "initiatedBy": "admin",
            }
        ],
    }
    report.update(overrides)
    return report


def test_print_markdown_basic(capsys):
    print_markdown(_sample_report())
    captured = capsys.readouterr().out
    assert "ArgoCD 部署频率报告" in captured
    assert "统计 App 数：5" in captured
    assert "部署次数：20" in captured
    assert "按项目部署次数" in captured
    assert "按触发者部署次数" in captured
    assert "最近 1 次部署" in captured
    assert "default" in captured


def test_print_markdown_with_days(capsys):
    print_markdown(_sample_report(days=7, projectFilter="default"))
    captured = capsys.readouterr().out
    assert "最近 7 天" in captured
    assert "项目=default" in captured


def test_print_markdown_empty(capsys):
    report = _sample_report(totalApps=0, totalDeploys=0, byProject={}, byInitiator={}, recentDeploys=[])
    print_markdown(report)
    captured = capsys.readouterr().out
    assert "统计 App 数：0" in captured