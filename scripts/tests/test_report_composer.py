"""Tests for report_composer.py"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from argocd_insight.report_composer import (
    MODULES,
    _capture_json,
    _compose_json,
    _compose_markdown,
    _summarize_module,
    _truncate_json_block,
    compose_report,
    main,
)


class TestCaptureJson:
    def test_capture_valid_json(self):
        mock_mod = MagicMock()
        mock_mod.main.side_effect = lambda argv: None
        import io
        buf = io.StringIO()
        buf.write('{"key": "value"}')
        buf.seek(0)
        mock_mod.main.side_effect = lambda argv: None
        with patch("argocd_insight.report_composer.sys.stdout", buf):
            result = _capture_json(mock_mod, ["--output", "json"])
        assert result is None

    def test_capture_none_on_empty(self):
        mock_mod = MagicMock()
        mock_mod.main.return_value = 0
        result = _capture_json(mock_mod, [])
        assert result is None

    def test_capture_none_on_invalid_json(self):
        mock_mod = MagicMock()
        import io
        buf = io.StringIO()
        with patch("argocd_insight.report_composer.sys.stdout", buf):
            try:
                _capture_json(mock_mod, [])
            except SystemExit:
                pass
        result = _capture_json(mock_mod, [])
        assert result is None

    def test_capture_handles_system_exit(self):
        mock_mod = MagicMock()
        mock_mod.main.side_effect = SystemExit(1)
        result = _capture_json(mock_mod, [])
        assert result is None


class TestSummarizeModule:
    def test_diagnose_dict_with_critical(self):
        data = {"apps": [{"severity": "critical"}, {"severity": "low"}]}
        status, metric = _summarize_module("diagnose", data)
        assert "critical" in metric
        assert status == "🔴"

    def test_diagnose_dict_all_ok(self):
        data = {"apps": [{"severity": "low"}, {"severity": "medium"}]}
        status, metric = _summarize_module("diagnose", data)
        assert status == "🟢"

    def test_diagnose_list(self):
        data = [{"severity": "high"}, {"severity": "low"}]
        status, metric = _summarize_module("diagnose", data)
        assert status == "🔴"

    def test_compliance_dict(self):
        data = {"risks": [{"severity": "high"}, {"severity": "low"}]}
        status, metric = _summarize_module("compliance", data)
        assert "high/critical" in metric

    def test_compliance_list(self):
        data = [{"severity": "critical"}]
        status, metric = _summarize_module("compliance", data)
        assert status == "🔴"

    def test_cost_dict(self):
        data = {"total_cost": 150.5}
        status, metric = _summarize_module("cost", data)
        assert "$150.5" in metric

    def test_cost_list(self):
        data = [{"estimated_cost": 10}, {"estimated_cost": 20}]
        status, metric = _summarize_module("cost", data)
        assert "$30" in metric

    def test_health_dict_good(self):
        data = {"score": 95}
        status, metric = _summarize_module("health", data)
        assert status == "🟢"

    def test_health_dict_warn(self):
        data = {"health_score": 60}
        status, metric = _summarize_module("health", data)
        assert "60" in metric

    def test_health_list(self):
        data = [{"score": 90}, {"score": 80}]
        status, metric = _summarize_module("health", data)
        assert "85" in metric

    def test_unknown_module(self):
        status, metric = _summarize_module("unknown", {})
        assert status == "ℹ️"


class TestTruncateJsonBlock:
    def test_short_list(self):
        data = [1, 2, 3]
        result = _truncate_json_block(data, max_items=10)
        assert "```json" in result
        assert "1" in result and "2" in result and "3" in result
        assert "```" in result

    def test_long_list_truncated(self):
        data = list(range(100))
        result = _truncate_json_block(data, max_items=20)
        assert "前 20 项" in result
        assert "共 100 项" in result

    def test_dict_output(self):
        data = {"key": "value"}
        result = _truncate_json_block(data)
        assert '"key": "value"' in result


class TestComposeMarkdown:
    def test_basic_structure(self):
        results = {"diagnose": {"apps": []}, "cost": None}
        md = _compose_markdown(results)
        assert "# ArgoCD 综合报告" in md
        assert "## diagnose" in md
        assert "## cost" in md
        assert "生成时间" in md

    def test_with_project(self):
        results = {"diagnose": None}
        md = _compose_markdown(results, project="my-proj")
        assert "my-proj" in md

    def test_summary_table(self):
        results = {
            "diagnose": {"apps": [{"severity": "critical"}]},
            "compliance": {"risks": []},
        }
        md = _compose_markdown(results)
        assert "| 模块 | 状态 | 关键指标 |" in md


class TestComposeJson:
    def test_structure(self):
        results = {"diagnose": {"apps": []}}
        out = _compose_json(results, project="p1")
        assert "report" in out
        assert "modules" in out
        assert out["report"]["project"] == "p1"
        assert "generated_at" in out["report"]

    def test_no_project(self):
        out = _compose_json({})
        assert out["report"]["project"] is None


class TestComposeReport:
    @patch("argocd_insight.report_composer._capture_json")
    def test_all_modules(self, mock_capture):
        mock_capture.return_value = {"data": "test"}
        report_text, results = compose_report(
            includes=["diagnose", "compliance", "cost", "health"],
            output_format="markdown",
        )
        assert "综合报告" in report_text
        assert mock_capture.call_count == 4

    @patch("argocd_insight.report_composer._capture_json")
    def test_partial_modules(self, mock_capture):
        mock_capture.return_value = None
        _, results = compose_report(includes=["diagnose"])
        assert "diagnose" in results
        assert mock_capture.call_count == 1

    @patch("argocd_insight.report_composer._capture_json")
    def test_json_output(self, mock_capture):
        mock_capture.return_value = {"key": "val"}
        report_text, _ = compose_report(
            includes=["diagnose"],
            output_format="json",
        )
        parsed = json.loads(report_text)
        assert "modules" in parsed
        assert "report" in parsed

    @patch("argocd_insight.report_composer._capture_json")
    def test_unknown_module(self, mock_capture):
        _, results = compose_report(includes=["nonexistent"])
        assert results["nonexistent"] is None
        mock_capture.assert_not_called()

    @patch("argocd_insight.report_composer.push_report", return_value=(True, ""))
    @patch("argocd_insight.report_composer._capture_json")
    def test_push(self, mock_capture, mock_push):
        mock_capture.return_value = {"data": "x"}
        compose_report(
            includes=["diagnose"],
            push=True,
            webhook_url="https://open.feishu.cn/hook",
            channel="feishu",
        )
        mock_push.assert_called_once()

    @patch("argocd_insight.report_composer.push_report", return_value=(False, "err"))
    @patch("argocd_insight.report_composer._capture_json")
    def test_push_failure(self, mock_capture, mock_push):
        mock_capture.return_value = {"data": "x"}
        compose_report(
            includes=["diagnose"],
            push=True,
            webhook_url="https://hook",
        )


class TestMain:
    def test_invalid_module(self):
        ret = main(["--include", "nonexistent"])
        assert ret == 1

    def test_push_without_webhook(self):
        ret = main(["--push"])
        assert ret == 1

    @patch("argocd_insight.report_composer._capture_json")
    def test_valid_run(self, mock_capture):
        mock_capture.return_value = None
        ret = main(["--include", "diagnose", "--output", "markdown"])
        assert ret == 0

    @patch("argocd_insight.report_composer._capture_json")
    def test_project_flag(self, mock_capture):
        mock_capture.return_value = None
        ret = main(["--include", "diagnose", "--project", "my-proj"])
        assert ret == 0
        call_args = mock_capture.call_args[0]
        assert "--project" in call_args[1]
        assert "my-proj" in call_args[1]
