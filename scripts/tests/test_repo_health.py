"""Tests for scripts/argocd_insight/repo_health.py

No network calls — all subprocess interactions are mocked.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from argocd_insight.repo_health import (
    build_report,
    check_branch_exists,
    check_repo_connectivity,
    fetch_apps,
    fetch_repos,
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
# check_repo_connectivity()
# ------------------------------------------------------------------

def test_check_repo_connectivity_reachable():
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=0)):
        result = check_repo_connectivity("https://example.com/repo.git")
        assert result["status"] == "reachable"
        assert result["error"] is None


def test_check_repo_connectivity_timeout():
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=-1, stderr="timeout")):
        result = check_repo_connectivity("https://example.com/repo.git")
        assert result["status"] == "timeout"


def test_check_repo_connectivity_unreachable():
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=128, stderr="fatal: not found")):
        result = check_repo_connectivity("https://example.com/repo.git")
        assert result["status"] == "unreachable_from_agent"
        assert "fatal" in result["error"]


# ------------------------------------------------------------------
# check_branch_exists()
# ------------------------------------------------------------------

def test_check_branch_exists_found():
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=0, stdout="abc123\trefs/heads/main")):
        result = check_branch_exists("https://example.com/repo.git", "main")
        assert result["exists"] is True
        assert result["method"] == "ls-remote"


def test_check_branch_exists_not_found():
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=1, stdout="")):
        result = check_branch_exists("https://example.com/repo.git", "nonexistent")
        assert result["exists"] is None
        assert result["method"] == "unknown_no_credential"


# ------------------------------------------------------------------
# fetch_repos() / fetch_apps()
# ------------------------------------------------------------------

def test_fetch_repos_returns_json():
    repos = [{"repo": "https://example.com/repo.git", "type": "git"}]
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=0, stdout=json.dumps(repos))):
        assert fetch_repos() == repos


def test_fetch_repos_empty_on_empty():
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=0, stdout="")):
        assert fetch_repos() == []


def test_fetch_apps_returns_json():
    apps = [{"metadata": {"name": "my-app"}}]
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=0, stdout=json.dumps(apps))):
        assert fetch_apps() == apps


def test_fetch_apps_empty_on_empty():
    with patch("argocd_insight.repo_health.run", side_effect=_mock_run(rc=0, stdout="")):
        assert fetch_apps() == []


# ------------------------------------------------------------------
# build_report()
# ------------------------------------------------------------------

def _make_repo(url="https://example.com/repo.git", state="Successful"):
    return {"repo": url, "connectionState": {"status": state}}


def _make_app(name="app-1", project="default", repo_url="https://example.com/repo.git",
              revision="main", sources=None):
    app = {
        "metadata": {"name": name},
        "spec": {"project": project, "source": {"repoURL": repo_url, "targetRevision": revision}},
    }
    if sources is not None:
        app["spec"]["sources"] = sources
    return app


def test_build_report_empty():
    report = build_report([], [], None)
    assert report["totalRepos"] == 0
    assert report["totalApps"] == 0
    assert report["byRepo"] == {}


def test_build_report_reachable():
    repos = [_make_repo()]
    apps = [_make_app()]
    with patch("argocd_insight.repo_health.check_repo_connectivity",
               return_value={"status": "reachable", "error": None}):
        report = build_report(repos, apps, None)
    assert report["totalRepos"] == 1
    assert report["reachableRepos"] == 1
    assert report["totalApps"] == 1
    assert report["byRepo"]["https://example.com/repo.git"]["appCount"] == 1


def test_build_report_unreachable():
    repos = [_make_repo()]
    with patch("argocd_insight.repo_health.check_repo_connectivity",
               return_value={"status": "timeout", "error": "timeout"}):
        report = build_report(repos, [], None)
    assert report["unreachableFromAgent"] == 1


def test_build_report_project_filter():
    repos = [_make_repo()]
    apps = [_make_app(name="a1", project="p1"), _make_app(name="a2", project="p2")]
    with patch("argocd_insight.repo_health.check_repo_connectivity",
               return_value={"status": "reachable", "error": None}):
        report = build_report(repos, apps, "p1")
    assert report["totalApps"] == 1


def test_build_report_multi_source():
    repos = [_make_repo(url="https://example.com/repo.git")]
    apps = [_make_app(sources=[
        {"repoURL": "https://example.com/repo.git", "targetRevision": "main"},
        {"repoURL": "https://example.com/values.git", "targetRevision": "main"},
    ])]
    with patch("argocd_insight.repo_health.check_repo_connectivity",
               return_value={"status": "reachable", "error": None}):
        report = build_report(repos, apps, None)
    assert report["totalApps"] == 1


def test_build_report_revisions_deduped():
    repos = [_make_repo()]
    apps = [
        _make_app(name="a1", revision="main"),
        _make_app(name="a2", revision="main"),
    ]
    with patch("argocd_insight.repo_health.check_repo_connectivity",
               return_value={"status": "reachable", "error": None}):
        report = build_report(repos, apps, None)
    repo_info = report["byRepo"]["https://example.com/repo.git"]
    assert repo_info["revisions"] == ["main"]


# ------------------------------------------------------------------
# print_markdown()
# ------------------------------------------------------------------

def _sample_report(**overrides) -> dict:
    report = {
        "generatedAt": "2026-07-01T12:00:00+00:00",
        "totalRepos": 3,
        "reachableRepos": 2,
        "unreachableFromAgent": 1,
        "totalApps": 10,
        "byRepo": {
            "https://example.com/repo1.git": {
                "connectionState": "Successful",
                "connectivity": {"status": "reachable"},
                "appCount": 5,
                "revisions": ["main"],
            },
            "https://example.com/repo2.git": {
                "connectionState": "Failed",
                "connectivity": {"status": "unreachable_from_agent"},
                "appCount": 3,
                "revisions": ["develop"],
            },
        },
    }
    report.update(overrides)
    return report


def test_print_markdown_basic(capsys):
    print_markdown(_sample_report())
    captured = capsys.readouterr().out
    assert "ArgoCD Git 源健康报告" in captured
    assert "仓库总数：3" in captured
    assert "可达（agent 侧）：2" in captured
    assert "repo1" in captured
    assert "repo2" in captured


def test_print_markdown_empty(capsys):
    report = _sample_report(totalRepos=0, reachableRepos=0, unreachableFromAgent=0, byRepo={})
    print_markdown(report)
    captured = capsys.readouterr().out
    assert "仓库总数：0" in captured
