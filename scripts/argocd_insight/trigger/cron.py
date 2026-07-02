"""定时触发入口 — 适合 crontab 调用。

crontab 使用示例:
    # 每天凌晨 2 点分析最近 7 天的会话（dry-run）
    0 2 * * * cd /path/to/scripts && python3 -m argocd_insight.trigger.cron --since 7

    # 每周一凌晨 3 点提炼经验并写回
    0 3 * * 1 cd /path/to/scripts && python3 -m argocd_insight.trigger.cron --since 7 --evolve --no-dry-run

    # 每小时输出 JSON 格式报告
    0 * * * * cd /path/to/scripts && python3 -m argocd_insight.trigger.cron --since 1 --output json
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .base import get_trace_dir, run_pipeline

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    """构造 cron CLI 的参数解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m argocd_insight.trigger.cron",
        description="定时触发离线分析管道（适合 crontab 调用）。",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=7,
        help="分析最近 N 天的会话（默认 7）。",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="提炼经验（仅生成 Insight，不写回）。",
    )
    parser.add_argument(
        "--evolve",
        action="store_true",
        help="执行写回（默认 dry-run，需配合 --no-dry-run 才会实际写文件）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="显式声明 dry-run（no-op，因默认即为 dry-run；保留以兼容调用方）。",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="关闭 dry-run，实际写回文件（与 --dry-run 互斥，同时出现时本项优先）。",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="输出格式（默认 text）。",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 入口，返回 0 表示成功。

    Args:
        argv: 命令行参数列表（None 时读取 sys.argv[1:]）。
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    dry_run = not args.no_dry_run
    results = run_pipeline(
        get_trace_dir(),
        since_days=args.since,
        extract=args.evolve or args.extract,
        evolve=args.evolve,
        dry_run=dry_run,
    )

    if args.output == "json":
        print(json.dumps(results, ensure_ascii=False, default=str))
    else:
        print(f"Sessions analyzed: {results['sessions_analyzed']}")
        print(f"Total events: {results['total_events']}")
        insights = results.get("insights") or []
        if insights:
            print(f"Insights: {len(insights)}")
        evolve_results = results.get("evolve_results") or {}
        if evolve_results:
            low = len(evolve_results.get("low", []))
            medium = len(evolve_results.get("medium", []))
            skipped = len(evolve_results.get("skipped", []))
            print(f"Evolve: low={low}, medium={medium}, skipped={skipped}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
