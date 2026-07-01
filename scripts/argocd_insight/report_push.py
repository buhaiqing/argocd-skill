#!/usr/bin/env python3
"""
report_push — 报告推送工具

将诊断/成本/对比报告推送到 飞书/钉钉/Slack 等通知渠道。

Usage:
  # 推送 Markdown 文件
  python -m argocd_insight report_push --file report.md --channel feishu --webhook URL

  # 推送 JSON 文件
  python -m argocd_insight report_push --file report.json --channel dingtalk --webhook URL

  # 从 stdin 读取
  cat report.md | python -m argocd_insight report_push --channel slack --webhook URL

  # 支持的报告模块 pipe 推送
  python -m argocd_insight cost --output json | python -m argocd_insight report_push --channel feishu --webhook URL
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


# ---------------------------------------------------------------------------
# 各渠道消息格式化
# ---------------------------------------------------------------------------

def _fmt_feishu(title: str, content: str) -> dict:
    """飞书机器人消息体（富文本或 Markdown）"""
    return {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": title}},
            "elements": [
                {"tag": "markdown", "content": content[:32000]},  # 飞书限制 32KB
            ],
        },
    }


def _fmt_dingtalk(title: str, content: str) -> dict:
    """钉钉机器人消息体（Markdown）"""
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": content[:20000],  # 钉钉限制 20KB
        },
    }


def _fmt_slack(title: str, content: str) -> dict:
    """Slack Webhook 消息体"""
    return {
        "text": title,
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": content[:4000]}},  # Slack 限制 4KB
        ],
    }


_FORMATTERS = {
    "feishu": _fmt_feishu,
    "dingtalk": _fmt_dingtalk,
    "slack": _fmt_slack,
}


def _detect_channel(webhook_url: str) -> str | None:
    """根据 webhook URL 自动检测渠道"""
    if not webhook_url:
        return None
    url = webhook_url.lower()
    if "feishu" in url or "larksuite" in url:
        return "feishu"
    if "dingtalk" in url or "oapi.dingtalk" in url:
        return "dingtalk"
    if "hooks.slack" in url:
        return "slack"
    return None


def send_webhook(webhook_url: str, payload: dict, timeout: int = 15) -> tuple[int, str]:
    """发送 webhook 请求"""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, body
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        return -1, str(e.reason)
    except Exception as e:
        return -1, str(e)


def push_report(
    content: str,
    title: str = "ArgoCD 报告",
    channel: str = "feishu",
    webhook_url: str = "",
) -> tuple[bool, str]:
    """推送报告到指定渠道

    Returns:
        (success, error_message)
    """
    fmt_fn = _FORMATTERS.get(channel.lower())
    if not fmt_fn:
        return False, f"不支持的渠道: {channel}（支持: {', '.join(_FORMATTERS)}）"

    if not webhook_url:
        return False, "缺少 webhook URL"

    # 截断长消息
    max_len = {
        "feishu": 32000,
        "dingtalk": 20000,
        "slack": 4000,
    }.get(channel.lower(), 32000)
    if len(content) > max_len:
        content = content[:max_len] + "\n\n...（消息已截断）"

    payload = fmt_fn(title, content)
    status, body = send_webhook(webhook_url, payload)

    if 200 <= status < 300:
        return True, ""
    return False, f"HTTP {status}: {body}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ArgoCD 报告推送工具")
    p.add_argument("--file", "-f", help="报告文件路径（留空则从 stdin 读取）")
    p.add_argument("--channel", choices=["feishu", "dingtalk", "slack"],
                   help="通知渠道（留空则从 webhook URL 自动检测）")
    p.add_argument("--webhook", required=True, help="Webhook URL")
    p.add_argument("--title", default="ArgoCD 报告", help="消息标题（默认：ArgoCD 报告）")
    p.add_argument("--style", choices=["markdown", "json"], default="markdown",
                   help="报告格式（默认：markdown）")
    args = p.parse_args(argv)

    # 读取报告内容
    if args.file and args.file != "-":
        with open(args.file, "r", encoding="utf-8") as f:
            content = f.read()
    else:
        content = sys.stdin.read().strip()
        if not content:
            print("错误：未提供报告内容（文件为空或 stdin 无数据）", file=sys.stderr)
            return 1

    # 自动检测渠道
    channel = args.channel or _detect_channel(args.webhook)
    if not channel:
        print("错误：无法自动检测通知渠道，请使用 --channel 指定", file=sys.stderr)
        return 1

    print(f"Pushing report to {channel}...", file=sys.stderr)
    success, err = push_report(content, title=args.title, channel=channel,
                                webhook_url=args.webhook)
    if success:
        print(f"✓ Report pushed to {channel} successfully", file=sys.stderr)
        return 0
    else:
        print(f"✗ Push failed: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())