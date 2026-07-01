"""Tests for report_push.py"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argocd_insight.report_push import (
    _detect_channel,
    _fmt_dingtalk,
    _fmt_feishu,
    _fmt_slack,
    main,
    push_report,
    send_webhook,
)


class TestDetectChannel:
    def test_feishu_url(self):
        assert _detect_channel("https://open.feishu.cn/open-apis/bot/v2/hook/xxx") == "feishu"

    def test_dingtalk_url(self):
        assert _detect_channel("https://oapi.dingtalk.com/robot/send?access_token=xxx") == "dingtalk"

    def test_slack_url(self):
        assert _detect_channel("https://hooks.slack.com/services/T00/B00/xxx") == "slack"

    def test_larksuite(self):
        assert _detect_channel("https://open.larksuite.com/open-apis/bot/v2/hook/xxx") == "feishu"

    def test_empty(self):
        assert _detect_channel("") is None

    def test_unknown(self):
        assert _detect_channel("https://example.com/hook") is None


class TestFormatters:
    def test_feishu_card_structure(self):
        payload = _fmt_feishu("标题", "内容")
        assert payload["msg_type"] == "interactive"
        assert payload["card"]["header"]["title"]["content"] == "标题"
        assert payload["card"]["elements"][0]["content"] == "内容"

    def test_dingtalk_structure(self):
        payload = _fmt_dingtalk("标题", "内容")
        assert payload["msgtype"] == "markdown"
        assert payload["markdown"]["title"] == "标题"
        assert payload["markdown"]["text"] == "内容"

    def test_slack_structure(self):
        payload = _fmt_slack("标题", "内容")
        assert payload["text"] == "标题"
        assert len(payload["blocks"]) == 2
        assert payload["blocks"][0]["text"]["text"] == "标题"
        assert payload["blocks"][1]["text"]["text"] == "内容"


class TestSendWebhook:
    @patch("argocd_insight.report_push.urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b"ok"
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        status, body = send_webhook("https://hook.example.com", {"key": "val"})
        assert status == 200
        assert body == "ok"

    @patch("argocd_insight.report_push.urllib.request.urlopen")
    def test_http_error(self, mock_urlopen):
        import urllib.error
        err = urllib.error.HTTPError("http://example.com", 403, "Forbidden", {}, None)
        err.read = lambda: b'{"error":"invalid webhook"}'
        mock_urlopen.side_effect = err

        status, body = send_webhook("https://hook.example.com", {})
        assert status == 403
        assert "invalid webhook" in body

    @patch("argocd_insight.report_push.urllib.request.urlopen")
    def test_timeout(self, mock_urlopen):
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("timed out")

        status, body = send_webhook("https://hook.example.com", {})
        assert status == -1
        assert "timed out" in body


class TestPushReport:
    def test_unsupported_channel(self):
        ok, err = push_report("content", channel="wechat", webhook_url="https://hook")
        assert not ok
        assert "不支持" in err

    def test_missing_webhook(self):
        ok, err = push_report("content", webhook_url="")
        assert not ok
        assert "缺少 webhook URL" in err

    @patch("argocd_insight.report_push.send_webhook", return_value=(200, ""))
    def test_feishu_success(self, mock_send):
        ok, err = push_report("## 报告", title="Cost Report", channel="feishu",
                               webhook_url="https://open.feishu.cn/hook")
        assert ok
        assert err == ""

    @patch("argocd_insight.report_push.send_webhook", return_value=(200, ""))
    def test_dingtalk_success(self, mock_send):
        ok, err = push_report("## 报告", channel="dingtalk",
                               webhook_url="https://oapi.dingtalk.com/robot/send")
        assert ok

    @patch("argocd_insight.report_push.send_webhook", return_value=(200, ""))
    def test_slack_success(self, mock_send):
        ok, err = push_report("## Report", channel="slack",
                               webhook_url="https://hooks.slack.com/services/T00/B00")
        assert ok

    @patch("argocd_insight.report_push.send_webhook", return_value=(403, '{"error":"invalid"}'))
    def test_push_failure(self, mock_send):
        ok, err = push_report("content", channel="feishu", webhook_url="https://hook")
        assert not ok
        assert "403" in err

    @patch("argocd_insight.report_push.send_webhook", return_value=(200, ""))
    def test_content_truncation(self, mock_send):
        long_content = "x" * 50000
        ok, _ = push_report(long_content, channel="feishu", webhook_url="https://hook")
        assert ok


class TestMain:
    def test_missing_webhook(self):
        with pytest.raises(SystemExit) as exc:
            main(["--file", "/dev/null"])
        assert exc.value.code == 2

    @patch("argocd_insight.report_push.sys.stdin")
    def test_no_input(self, mock_stdin):
        mock_stdin.read.return_value = ""
        ret = main(["--webhook", "https://hook.example.com", "--channel", "feishu"])
        assert ret == 1

    @patch("argocd_insight.report_push.push_report", return_value=(True, ""))
    def test_from_file(self, mock_push):
        assert main(["--file", "/dev/null", "--webhook", "https://hook",
                      "--channel", "feishu"]) == 0

    @patch("argocd_insight.report_push.push_report", return_value=(True, ""))
    def test_auto_detect_channel(self, mock_push):
        assert main(["--file", "/dev/null", "--webhook",
                      "https://hooks.slack.com/services/T00/B00"]) == 0