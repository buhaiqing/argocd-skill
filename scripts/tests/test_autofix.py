"""Tests for autofix module."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from argocd_insight.autofix import _is_fixable, _determine_fix, execute_fixes


def test_is_fixable_outofsync():
    diag = {"app": "test", "category": "OutOfSync", "severity": "high",
            "actions": [{"priority": 1, "command": "argocd app sync test", "risk": "low"}]}
    assert _is_fixable(diag) is True


def test_is_fixable_degraded():
    diag = {"app": "test", "category": "Degraded", "severity": "critical",
            "actions": [{"priority": 1, "command": "argocd app rollback test 3", "risk": "medium"}]}
    assert _is_fixable(diag) is True


def test_not_fixable_missing():
    diag = {"app": "test", "category": "Missing", "severity": "high",
            "actions": [{"priority": 1, "command": "kubectl apply", "risk": "high"}]}
    assert _is_fixable(diag) is False


def test_not_fixable_high_risk():
    diag = {"app": "test", "category": "OutOfSync", "severity": "high",
            "actions": [{"priority": 1, "command": "argocd app sync test", "risk": "high"}]}
    assert _is_fixable(diag) is False


def test_not_fixable_severity_filter():
    diag = {"app": "test", "category": "OutOfSync", "severity": "low",
            "actions": [{"priority": 1, "command": "argocd app sync test", "risk": "low"}]}
    assert _is_fixable(diag, min_severity="critical") is False


def test_determine_fix_sync():
    diag = {"app": "myapp", "category": "OutOfSync", "severity": "high",
            "actions": [{"priority": 1, "command": "argocd app sync myapp --prune", "risk": "low"}]}
    op, cmd = _determine_fix(diag)
    assert op == "sync"
    assert "argocd" in cmd
    assert "sync" in cmd
    assert "myapp" in cmd


def test_determine_fix_rollback():
    diag = {"app": "myapp", "category": "Degraded", "severity": "critical",
            "actions": [{"priority": 1, "command": "argocd app rollback myapp 3", "risk": "medium"}]}
    op, cmd = _determine_fix(diag)
    assert op == "rollback"
    assert "rollback" in cmd
    assert "3" in cmd


def test_determine_fix_default_sync():
    diag = {"app": "myapp", "category": "OutOfSync", "severity": "medium",
            "actions": []}
    op, cmd = _determine_fix(diag)
    assert op == "sync"
    assert "sync" in cmd


def test_execute_fixes_dry_run():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([{
            "app": "test-app", "category": "OutOfSync", "severity": "high",
            "actions": [{"priority": 1, "command": "argocd app sync test-app", "risk": "low"}],
        }], f)
        f.flush()

        results = execute_fixes(f.name, dry_run=True)
        assert len(results) == 1
        assert results[0].operation == "sync"
        assert "[DRY RUN]" in results[0].message

        Path(f.name).unlink()


def test_execute_fixes_skip_unfixable():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([{
            "app": "missing-app", "category": "Missing", "severity": "critical",
            "actions": [{"priority": 1, "command": "kubectl apply", "risk": "high"}],
        }], f)
        f.flush()

        results = execute_fixes(f.name, dry_run=True)
        assert len(results) == 1
        assert results[0].operation == "skip"

        Path(f.name).unlink()


def test_execute_fixes_severity_filter():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump([{
            "app": "low-app", "category": "OutOfSync", "severity": "low",
            "actions": [{"priority": 1, "command": "argocd app sync low-app", "risk": "low"}],
        }], f)
        f.flush()

        results = execute_fixes(f.name, dry_run=True, min_severity="critical")
        assert len(results) == 1
        assert results[0].operation == "skip"

        Path(f.name).unlink()
