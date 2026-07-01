"""Tests for scripts/argocd_deploy_stats/oos_analyzer.py

No network calls — all subprocess interactions are mocked.
"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from argocd_deploy_stats.oos_analyzer import (
    build_report,
    classify_app,
    fetch_apps,
    print_markdown,
    run,
)

# ------------------------------------------------------------------
# run() — CLI wrapper
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


# ------------------------------------------------------------------
# fetch_apps()
# ------------------------------------------------------------------

def test_fetch_apps_returns_parsed_json():
    apps = [{"metadata": {"name": "my-app"}}]
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = json.dumps(apps)
        assert fetch_apps() == apps


def test_fetch_apps_empty():
    with patch.object(subprocess, "run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        assert fetch_apps() == []


# ------------------------------------------------------------------
# classify_app()  — core classification
# ------------------------------------------------------------------

def test_classify_synced():
    """No diff → diff_rc=0 → cause=None (synced)."""
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, "", ""
        if "diff" in cmd:
            return 0, "", ""
        return 0, "", ""
    with patch("argocd_deploy_stats.oos_analyzer.run", side_effect=fake_run):
        r = classify_app("my-app")
        assert r["cause"] is None
        assert r["diffRc"] == 0


def test_classify_git_additions():
    """Only `+` lines → Git新增."""
    diff_out = (
        "===== apps/Deployment default/my-app =====\n"
        "--- /tmp/desired\n"
        "+++ /tmp/live\n"
        "@@ -0,0 +1 @@\n"
        "+new-resource\n"
    )
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, "", ""
        if "diff" in cmd:
            return 1, diff_out, ""
        return 0, "", ""
    with patch("argocd_deploy_stats.oos_analyzer.run", side_effect=fake_run):
        r = classify_app("my-app")
        assert r["cause"] == "Git 新增/未部署"
        assert r["hasAdditions"] is True
        assert r["hasDeletions"] is False


def test_classify_manual_drift():
    """Only `-` lines → 手动漂移."""
    diff_out = (
        "===== apps/ConfigMap default/my-cm =====\n"
        "--- /tmp/desired\n"
        "+++ /tmp/live\n"
        "@@ -1 +0,0 @@\n"
        "-manual-entry\n"
    )
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, "", ""
        if "diff" in cmd:
            return 1, diff_out, ""
        return 0, "", ""
    with patch("argocd_deploy_stats.oos_analyzer.run", side_effect=fake_run):
        r = classify_app("my-app")
        assert r["cause"] == "手动漂移（集群多出 Git 没有的资源）"
        assert r["hasAdditions"] is False
        assert r["hasDeletions"] is True


def test_classify_content_drift():
    """Both `+` and `-` → 内容漂移."""
    diff_out = (
        "===== apps/Deployment default/my-app =====\n"
        "--- /tmp/desired\n"
        "+++ /tmp/live\n"
        "@@ -1 +1 @@\n"
        "-replicas: 2\n"
        "+replicas: 3\n"
    )
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, "", ""
        if "diff" in cmd:
            return 1, diff_out, ""
        return 0, "", ""
    with patch("argocd_deploy_stats.oos_analyzer.run", side_effect=fake_run):
        r = classify_app("my-app")
        assert r["cause"] == "内容漂移（Git 与集群不一致）"
        assert r["hasAdditions"] is True
        assert r["hasDeletions"] is True


def test_classify_plain_diff_format():
    """Old-style `>` / `<` diff format should also be detected."""
    diff_out = (
        "> new-resource\n"
    )
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, "", ""
        if "diff" in cmd:
            return 1, diff_out, ""
        return 0, "", ""
    with patch("argocd_deploy_stats.oos_analyzer.run", side_effect=fake_run):
        r = classify_app("my-app")
        assert r["cause"] == "Git 新增/未部署"
        assert r["hasAdditions"] is True


def test_classify_diff_rc_1_no_content():
    """diff_rc=1 but no +/- lines → 未知差异."""
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, "", ""
        if "diff" in cmd:
            return 1, "", ""
        return 0, "", ""
    with patch("argocd_deploy_stats.oos_analyzer.run", side_effect=fake_run):
        r = classify_app("my-app")
        assert r["cause"] == "未知差异"


def test_classify_orphaned_detected():
    """Tabular `resources` output with Orphaned=Yes → orphaned list populated."""
    res_out = (
        "Group\tKind\tNamespace\tName\tStatus\tOrphaned\n"
        "apps\tConfigMap\tdefault\tmy-cm\tSynced\tNo\n"
        "\tPod\tops\tstale-pod\tOutOfSync\tYes\n"
    )
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, res_out, ""
        if "diff" in cmd:
            return 0, "", ""
        return 0, "", ""
    with patch("argocd_deploy_stats.oos_analyzer.run", side_effect=fake_run):
        r = classify_app("my-app")
        assert len(r["orphaned"]) == 1
        assert "Pod/" in r["orphaned"][0] or "stale-pod" in r["orphaned"][0]


def test_classify_timeout_handled():
    """Subprocess timeout → -1 rc, no crash."""
    with patch("argocd_deploy_stats.oos_analyzer.run", return_value=(-1, "", "Timed out after 30s")):
        r = classify_app("my-app")
        # Should not crash; timeout causes empty diff → no cause
        assert r["cause"] is None


# ------------------------------------------------------------------
# build_report() — aggregation
# ------------------------------------------------------------------

def test_build_report_filters_and_aggregates():
    apps = [
        {"metadata": {"name": "a-ok"}, "status": {"sync": {"status": "Synced"}}},
        {"metadata": {"name": "a-oos"}, "status": {"sync": {"status": "OutOfSync"}}},
    ]
    def fake_classify(name):
        return {"app": name, "cause": "Git 新增/未部署", "hasAdditions": True,
                "hasDeletions": False, "orphaned": [], "diffRc": 1}

    with patch("argocd_deploy_stats.oos_analyzer.classify_app", side_effect=fake_classify):
        report = build_report(apps, days=None, project_filter=None, concurrency=1)
        assert report["totalApps"] == 2
        assert report["oosCount"] == 1
        assert report["byCause"]["Git 新增/未部署"] == 1


def test_build_report_project_filter():
    apps = [
        {"metadata": {"name": "a1"}, "spec": {"project": "proj-a"},
         "status": {"sync": {"status": "OutOfSync"}}},
        {"metadata": {"name": "a2"}, "spec": {"project": "proj-b"},
         "status": {"sync": {"status": "OutOfSync"}}},
    ]
    with patch("argocd_deploy_stats.oos_analyzer.classify_app",
               return_value={"app": "a1", "cause": "Git 新增/未部署",
                             "hasAdditions": True, "hasDeletions": False,
                             "orphaned": [], "diffRc": 1}):
        report = build_report(apps, days=None, project_filter="proj-a", concurrency=1)
        assert report["oosCount"] == 1
        assert "a1" in report["details"]


# ------------------------------------------------------------------
# print_markdown() — output format
# ------------------------------------------------------------------

def test_print_markdown_output(capsys):
    report = {
        "generatedAt": "2026-07-01T12:00:00+00:00",
        "days": None,
        "totalApps": 10,
        "oosCount": 2,
        "byCause": {"Git 新增/未部署": 2},
        "byCauseApps": {"Git 新增/未部署": ["app-1", "app-2"]},
        "details": {
            "app-1": {"app": "app-1", "cause": "Git 新增/未部署",
                      "hasAdditions": True, "hasDeletions": False,
                      "orphaned": [], "diffRc": 1},
            "app-2": {"app": "app-2", "cause": "Git 新增/未部署",
                      "hasAdditions": True, "hasDeletions": False,
                      "orphaned": ["Pod/stale-pod"], "diffRc": 1},
        },
    }
    print_markdown(report)
    captured = capsys.readouterr().out
    assert "ArgoCD OutOfSync 根因分析" in captured
    assert "总 App 数：10" in captured
    assert "OutOfSync：2" in captured
    assert "Git 新增/未部署" in captured
    assert "app-1" in captured
    assert "孤儿" in captured