#!/usr/bin/env python3
"""
report_composer — 报告合成器

组合 diagnose + compliance + cost + health 四模块输出为 Markdown 报告。
支持选择性包含模块、自动推送、JSON 输出。

Usage:
  # 合成全量报告（Markdown）
  python -m argocd_insight report-compose

  # 仅合成诊断+成本
  python -m argocd_insight report-compose --include diagnose,cost

  # 合成并推送
  python -m argocd_insight report-compose --push --webhook URL --channel feishu

  # JSON 输出
  python -m argocd_insight report-compose --output json
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from datetime import datetime, timezone

from . import compliance, cost, diagnose, health
from .report_push import push_report, _detect_channel


# ---------------------------------------------------------------------------
# 可用模块注册表
# ---------------------------------------------------------------------------

MODULES = {
    "diagnose": {
        "module": diagnose,
        "help": "问题 App 智能诊断",
    },
    "compliance": {
        "module": compliance,
        "help": "配置合规检查",
    },
    "cost": {
        "module": cost,
        "help": "资源成本估算",
    },
    "health": {
        "module": health,
        "help": "运行稳定性评估",
    },
}


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _capture_json(module, argv: list[str]) -> dict | list | None:
    """执行模块 main(argv) 并捕获其 stdout JSON 输出。

    返回解析后的 dict/list，失败返回 None。
    """
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    try:
        module.main(argv)
    except SystemExit:
        pass  # 某些模块在错误时 raise SystemExit
    finally:
        sys.stdout = old_stdout

    raw = buffer.getvalue().strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------

def _render_summary_table(results: dict[str, dict | list | None]) -> str:
    """渲染顶部摘要表。"""
    lines = [
        "| 模块 | 状态 | 关键指标 |",
        "|------|------|---------|",
    ]
    for name, data in results.items():
        if data is None:
            lines.append(f"| {name} | ⚠️ 未执行 | - |")
            continue

        status, metric = _summarize_module(name, data)
        lines.append(f"| {name} | {status} | {metric} |")

    return "\n".join(lines)


def _summarize_module(name: str, data: dict | list) -> tuple[str, str]:
    """从模块 JSON 中提取摘要指标。"""
    if name == "diagnose":
        if isinstance(data, dict):
            apps = data.get("apps", [])
            critical = sum(
                1 for a in apps
                if a.get("severity") in ("critical", "high")
            )
            return ("🔴" if critical else "🟢"), f"{len(apps)} apps, {critical} critical/high"
        if isinstance(data, list):
            critical = sum(
                1 for a in data
                if a.get("severity") in ("critical", "high")
            )
            return ("🔴" if critical else "🟢"), f"{len(data)} apps, {critical} critical/high"

    elif name == "compliance":
        if isinstance(data, dict):
            risks = data.get("risks", data.get("results", []))
            if isinstance(risks, list):
                high = sum(1 for r in risks if r.get("severity") in ("high", "critical"))
                return ("🔴" if high else "🟢"), f"{len(risks)} rules, {high} high/critical"
        if isinstance(data, list):
            high = sum(1 for r in data if r.get("severity") in ("high", "critical"))
            return ("🔴" if high else "🟢"), f"{len(data)} rules, {high} high/critical"

    elif name == "cost":
        if isinstance(data, dict):
            total = data.get("total_cost", data.get("estimated_cost", "N/A"))
            return "💰", f"est. ${total}"
        if isinstance(data, list) and data:
            total = sum(item.get("estimated_cost", 0) for item in data if isinstance(item, dict))
            return "💰", f"est. ${total:.2f}"

    elif name == "health":
        if isinstance(data, dict):
            score = data.get("score", data.get("health_score", "N/A"))
            return ("🟢" if isinstance(score, (int, float)) and score >= 80 else "🟡"), f"score: {score}"
        if isinstance(data, list) and data:
            avg = sum(
                item.get("score", item.get("health_score", 0))
                for item in data if isinstance(item, dict)
            ) / len(data)
            return ("🟢" if avg >= 80 else "🟡"), f"avg score: {avg:.1f}"

    return "ℹ️", "-"


def _render_section(name: str, data: dict | list | None) -> str:
    """渲染单个模块的 Markdown 章节。"""
    lines = [f"## {name}", ""]

    if data is None:
        lines.append("> ⚠️ 该模块未执行或无输出")
        return "\n".join(lines)

    lines.append(_truncate_json_block(data, max_items=50))
    return "\n".join(lines)


def _truncate_json_block(data: dict | list, max_items: int = 50) -> str:
    """将 JSON 数据转为 Markdown 代码块，超过 max_items 项时截断。"""
    if isinstance(data, list) and len(data) > max_items:
        truncated = data[:max_items]
        body = json.dumps(truncated, ensure_ascii=False, indent=2)
        return f"```json\n{body}\n```\n\n> ... 共 {len(data)} 项，仅展示前 {max_items} 项"
    return f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"


def _compose_markdown(
    results: dict[str, dict | list | None],
    project: str | None = None,
) -> str:
    """将多模块结果合成为完整 Markdown 报告。"""
    parts: list[str] = []

    title = "ArgoCD 综合报告"
    if project:
        title += f" — {project}"
    parts.append(f"# {title}")
    parts.append("")

    parts.append(f"> 生成时间: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    parts.append("")

    parts.append(_render_summary_table(results))
    parts.append("")

    for name, data in results.items():
        parts.append(_render_section(name, data))
        parts.append("")

    return "\n".join(parts)


def _compose_json(
    results: dict[str, dict | list | None],
    project: str | None = None,
) -> dict:
    """将多模块结果合成为 JSON 输出。"""
    return {
        "report": {
            "title": f"ArgoCD 综合报告{f' — {project}' if project else ''}",
            "generated_at": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "project": project,
        },
        "modules": {name: data for name, data in results.items()},
    }


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def compose_report(
    includes: list[str],
    project: str | None = None,
    output_format: str = "markdown",
    push: bool = False,
    webhook_url: str = "",
    channel: str = "",
    title: str = "ArgoCD 综合报告",
) -> tuple[str, dict[str, dict | list | None]]:
    """合成报告主函数。

    Args:
        includes: 要包含的模块名称列表
        project: 项目过滤（部分模块支持）
        output_format: "markdown" 或 "json"
        push: 是否推送
        webhook_url: 推送 webhook URL
        channel: 推送渠道
        title: 推送消息标题

    Returns:
        (report_text, results_dict)
    """
    results: dict[str, dict | list | None] = {}

    for name in includes:
        if name not in MODULES:
            results[name] = None
            continue

        mod_entry = MODULES[name]
        argv = ["--output", "json"]
        if project and name in ("diagnose", "health"):
            argv += ["--project", project]
        argv += mod_entry.get("extra_args", [])

        data = _capture_json(mod_entry["module"], argv)
        results[name] = data

    if output_format == "json":
        report = _compose_json(results, project)
        report_text = json.dumps(report, ensure_ascii=False, indent=2)
    else:
        report_text = _compose_markdown(results, project)

    if push and webhook_url:
        effective_channel = channel
        if not effective_channel:
            effective_channel = _detect_channel(webhook_url) or "feishu"

        ok, err = push_report(
            report_text,
            title=title,
            channel=effective_channel,
            webhook_url=webhook_url,
        )
        if ok:
            print(f"✓ 报告已推送到 {effective_channel}", file=sys.stderr)
        else:
            print(f"✗ 推送失败: {err}", file=sys.stderr)

    return report_text, results


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="argocd-insight report-compose",
        description="合成多模块报告（diagnose + compliance + cost + health）",
    )
    p.add_argument(
        "--include",
        default="diagnose,compliance,cost,health",
        help="逗号分隔的模块列表（默认: 全部）",
    )
    p.add_argument("--project", help="项目过滤（传递给 diagnose/health）")
    p.add_argument(
        "--output",
        choices=["markdown", "json"],
        default="markdown",
        help="输出格式（默认: markdown）",
    )
    p.add_argument("--push", action="store_true", help="合成后自动推送")
    p.add_argument("--webhook", dest="webhook_url", default="", help="Webhook URL（推送时必填）")
    p.add_argument(
        "--channel",
        choices=["feishu", "dingtalk", "slack"],
        default="",
        help="推送渠道（留空则自动检测）",
    )
    p.add_argument("--title", default="ArgoCD 综合报告", help="推送消息标题")

    args = p.parse_args(argv)

    includes = [s.strip() for s in args.include.split(",") if s.strip()]
    invalid = [s for s in includes if s not in MODULES]
    if invalid:
        print(
            f"错误：未知模块 {invalid}（可用: {', '.join(MODULES)}）",
            file=sys.stderr,
        )
        return 1

    if args.push and not args.webhook_url:
        print("错误：--push 需要配合 --webhook 使用", file=sys.stderr)
        return 1

    report_text, _ = compose_report(
        includes=includes,
        project=args.project,
        output_format=args.output,
        push=args.push,
        webhook_url=args.webhook_url,
        channel=args.channel,
        title=args.title,
    )

    print(report_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
