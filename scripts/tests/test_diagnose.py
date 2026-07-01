"""Tests for scripts/argocd_insight/diagnose.py — diagnose_app() logic.

No network calls — all argocd CLI invocations are mocked.
"""
from __future__ import annotations

from unittest.mock import patch

from argocd_insight.diagnose import diagnose_app


def _app(health="Healthy", sync="Synced", sources=None, sync_policy=None):
    spec = {"project": "default", "destination": {"namespace": "default"}}
    if sources:
        spec["sources"] = sources
    else:
        spec["source"] = {"repoURL": "https://github.com/example/repo"}
    if sync_policy:
        spec["syncPolicy"] = sync_policy
    return {
        "metadata": {"name": "my-app"},
        "spec": spec,
        "status": {
            "health": {"status": health},
            "sync": {"status": sync, "revision": "abc123def456"},
        },
    }


def _fake_run(cmd, timeout=30):
    if "resources" in cmd:
        return 0, "", ""
    if "diff" in cmd:
        return 0, "", ""
    if "events" in cmd:
        return 0, "", ""
    if "history" in cmd:
        return 0, "[]", ""
    return 0, "", ""


# healthy app -> None

def test_healthy_app_returns_none():
    with patch("argocd_insight.diagnose._run", side_effect=_fake_run):
        r = diagnose_app("my-app", _app(health="Healthy", sync="Synced"))
        assert r is None


# OutOfSync — Git additions

def test_oos_git_additions_returns_diagnosis():
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
        if "events" in cmd:
            return 0, "", ""
        if "history" in cmd:
            return 0, "[]", ""
        return 0, "", ""

    with patch("argocd_insight.diagnose._run", side_effect=fake_run):
        r = diagnose_app("my-app", _app(health="Healthy", sync="OutOfSync"))
        assert r is not None
        assert r.severity in ("critical", "high", "medium", "low", "info")
        assert "Git" in r.root_cause or "新增" in r.root_cause or "尚未" in r.root_cause
        assert len(r.actions) >= 1
        assert r.category != ""


# OutOfSync — orphaned resources

def test_oos_orphaned_returns_diagnosis():
    res_out = (
        "Group\tKind\tNamespace\tName\tStatus\tOrphaned\n"
        "\tPod\tdefault\tstale-pod\tOutOfSync\tYes\n"
    )

    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, res_out, ""
        if "diff" in cmd:
            return 0, "", ""
        if "events" in cmd:
            return 0, "", ""
        if "history" in cmd:
            return 0, "[]", ""
        return 0, "", ""

    with patch("argocd_insight.diagnose._run", side_effect=fake_run):
        r = diagnose_app("my-app", _app(health="Healthy", sync="OutOfSync"))
        assert r is not None
        assert "孤儿" in r.category or "Orphaned" in r.category or "orphan" in r.root_cause.lower()
        assert any("孤儿资源" in s or "stale-pod" in s for s in r.symptoms)


# health = Degraded

def test_health_degraded_returns_diagnosis():
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, "", ""
        if "diff" in cmd:
            return 0, "", ""
        if "events" in cmd:
            return 0, "", ""
        if "history" in cmd:
            return 0, "[]", ""
        return 0, "", ""

    with patch("argocd_insight.diagnose._run", side_effect=fake_run):
        r = diagnose_app("my-app", _app(health="Degraded", sync="Synced"))
        assert r is not None
        assert r.root_cause != ""


# sync = Error

def test_sync_error_returns_diagnosis():
    def fake_run(cmd, timeout=30):
        if "resources" in cmd:
            return 0, "", ""
        if "diff" in cmd:
            return 0, "", ""
        if "events" in cmd:
            return 0, "", ""
        if "history" in cmd:
            return 0, "[]", ""
        return 0, "", ""

    with patch("argocd_insight.diagnose._run", side_effect=fake_run):
        r = diagnose_app("my-app", _app(health="Healthy", sync="Error"))
        assert r is not None
        assert r.severity in ("critical", "high")


# Unknown sync alone -> None (not actionable)

def test_unknown_sync_returns_none():
    with patch("argocd_insight.diagnose._run", side_effect=_fake_run):
        r = diagnose_app("my-app", _app(health="Healthy", sync="Unknown"))
        assert r is None
