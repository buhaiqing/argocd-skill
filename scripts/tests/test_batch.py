"""Tests for batch.py — 批量操作模块。"""
from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch, call
import pytest

from argocd_insight.batch import (
    execute_batch,
    _list_apps,
    _execute_operation,
    _run_cli,
    BatchResult,
    BatchSummary,
)


# ── Fixtures ──────────────────────────────────────────────────────

SAMPLE_APPS = [
    {"name": "app-1", "status": {"health": {"status": "Healthy"}}},
    {"name": "app-2", "status": {"health": {"status": "Degraded"}}},
    {"name": "app-3", "status": {"health": {"status": "Healthy"}}},
]

SAMPLE_APPS_JSON = json.dumps(SAMPLE_APPS)


# ── _run_cli tests ────────────────────────────────────────────────

class TestRunCli:
    """_run_cli 单元测试。"""

    @patch("argocd_insight.batch.subprocess.run")
    def test_success(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        rc, out, err = _run_cli(["argocd", "version"])
        assert rc == 0
        assert out == "ok"

    @patch("argocd_insight.batch.subprocess.run")
    def test_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        rc, out, err = _run_cli(["argocd", "bad"])
        assert rc == 1
        assert "error" in err

    @patch("argocd_insight.batch.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5))
    def test_timeout(self, mock_run: MagicMock) -> None:
        rc, out, err = _run_cli(["argocd", "slow"])
        assert rc == -1
        assert "Timed out" in err

    @patch("argocd_insight.batch.subprocess.run", side_effect=FileNotFoundError)
    def test_not_found(self, mock_run: MagicMock) -> None:
        rc, out, err = _run_cli(["nonexistent"])
        assert rc == -2
        assert "Not found" in err


# ── _list_apps tests ──────────────────────────────────────────────

class TestListApps:
    """_list_apps 单元测试。"""

    @patch("argocd_insight.batch._run_cli")
    def test_list_all(self, mock_cli: MagicMock) -> None:
        mock_cli.return_value = (0, SAMPLE_APPS_JSON, "")
        apps = _list_apps()
        assert apps == ["app-1", "app-2", "app-3"]

    @patch("argocd_insight.batch._run_cli")
    def test_list_by_status(self, mock_cli: MagicMock) -> None:
        mock_cli.return_value = (0, SAMPLE_APPS_JSON, "")
        apps = _list_apps(status="Degraded")
        assert apps == ["app-2"]

    @patch("argocd_insight.batch._run_cli")
    def test_list_empty(self, mock_cli: MagicMock) -> None:
        mock_cli.return_value = (0, "[]", "")
        apps = _list_apps()
        assert apps == []

    @patch("argocd_insight.batch._run_cli")
    def test_list_error(self, mock_cli: MagicMock) -> None:
        mock_cli.return_value = (1, "", "connection refused")
        apps = _list_apps()
        assert apps == []


# ── _execute_operation tests ──────────────────────────────────────

class TestExecuteOperation:
    """_execute_operation 单元测试。"""

    @patch("argocd_insight.batch._run_cli")
    def test_sync_success(self, mock_cli: MagicMock) -> None:
        mock_cli.return_value = (0, "App synced", "")
        result = _execute_operation("my-app", "sync", dry_run=False, timeout=60)
        assert result.success is True
        assert "sync" in result.command.lower()

    @patch("argocd_insight.batch._run_cli")
    def test_sync_dry_run(self, mock_cli: MagicMock) -> None:
        result = _execute_operation("my-app", "sync", dry_run=True, timeout=60)
        assert result.success is True
        assert "DRY RUN" in result.message
        mock_cli.assert_not_called()

    @patch("argocd_insight.batch._run_cli")
    def test_rollback_success(self, mock_cli: MagicMock) -> None:
        mock_cli.return_value = (0, "Rolled back", "")
        result = _execute_operation("my-app", "rollback", dry_run=False)
        assert result.success is True
        assert "rollback" in result.command.lower()

    @patch("argocd_insight.batch._run_cli")
    def test_refresh_success(self, mock_cli: MagicMock) -> None:
        mock_cli.return_value = (0, "Refreshed", "")
        result = _execute_operation("my-app", "refresh", dry_run=False)
        assert result.success is True
        assert "refresh" in result.command.lower()

    def test_unknown_operation(self) -> None:
        result = _execute_operation("my-app", "unknown")
        assert result.success is False
        assert "Unknown operation" in result.message


# ── execute_batch tests ───────────────────────────────────────────

class TestExecuteBatch:
    """execute_batch 集成测试。"""

    @patch("argocd_insight.batch._list_apps")
    @patch("argocd_insight.batch._execute_operation")
    def test_batch_with_apps_list(
        self, mock_exec: MagicMock, mock_list: MagicMock
    ) -> None:
        mock_exec.return_value = BatchResult(
            app="app-1", operation="sync", success=True,
            message="ok", command="argocd app sync app-1", duration=1.0,
        )
        summary = execute_batch("sync", apps=["app-1", "app-2"], dry_run=True)
        assert summary.total == 2
        assert summary.succeeded == 2
        mock_list.assert_not_called()

    @patch("argocd_insight.batch._list_apps")
    @patch("argocd_insight.batch._execute_operation")
    def test_batch_with_filter(
        self, mock_exec: MagicMock, mock_list: MagicMock
    ) -> None:
        mock_list.return_value = ["app-1", "app-2"]
        mock_exec.return_value = BatchResult(
            app="app-1", operation="sync", success=True,
            message="ok", command="", duration=0.5,
        )
        summary = execute_batch("sync", project="my-project")
        assert summary.total == 2
        mock_list.assert_called_once_with("my-project", None, None)

    @patch("argocd_insight.batch._list_apps")
    def test_batch_empty(self, mock_list: MagicMock) -> None:
        mock_list.return_value = []
        summary = execute_batch("sync", project="empty")
        assert summary.total == 0

    @patch("argocd_insight.batch._execute_operation")
    def test_batch_mixed_results(self, mock_exec: MagicMock) -> None:
        mock_exec.side_effect = [
            BatchResult("app-1", "sync", True, "ok", "", 1.0),
            BatchResult("app-2", "sync", False, "error", "", 2.0),
            BatchResult("app-3", "sync", True, "ok", "", 0.5),
        ]
        summary = execute_batch("sync", apps=["app-1", "app-2", "app-3"])
        assert summary.total == 3
        assert summary.succeeded == 2
        assert summary.failed == 1


# ── Main function tests ───────────────────────────────────────────

class TestMain:
    """main() CLI 入口测试。"""

    @patch("argocd_insight.batch.execute_batch")
    def test_main_sync(self, mock_batch: MagicMock) -> None:
        mock_batch.return_value = BatchSummary(
            operation="sync", total=1, succeeded=1, failed=0,
            skipped=0, duration=1.0, results=[],
        )
        from argocd_insight.batch import main
        rc = main(["sync", "--all"])
        assert rc == 0

    @patch("argocd_insight.batch.execute_batch")
    def test_main_has_failures(self, mock_batch: MagicMock) -> None:
        mock_batch.return_value = BatchSummary(
            operation="sync", total=1, succeeded=0, failed=1,
            skipped=0, duration=1.0, results=[],
        )
        from argocd_insight.batch import main
        rc = main(["sync", "--all"])
        assert rc == 1

    def test_main_no_filter(self) -> None:
        from argocd_insight.batch import main
        with pytest.raises(SystemExit):
            main(["sync"])
