"""阈值触发模式 — 事件数累计达阈值时触发分析。

CLI 入口：``python -m argocd_insight.trigger.threshold``

典型用法（cron 串联，与 cron.py 配合）：

.. code-block:: bash

    # 每小时检查一次，事件数达 100 触发分析
    0 * * * * cd /path/to/scripts && \\
        python3 -m argocd_insight.trigger.threshold \\
            --threshold 100 --dry-run && \\
        python3 -m argocd_insight.trigger.cron --since 7 --dry-run

退出码约定：
- 0 = 已触发分析（达阈值）
- 1 = 未触发（事件数未达阈值）
"""
from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .base import count_events, get_trace_dir, run_pipeline

__all__ = ["main", "build_parser"]


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
    parser = argparse.ArgumentParser(
        prog="python -m argocd_insight.trigger.threshold",
        description="阈值触发：事件数达阈值时触发分析。",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=100,
        help="触发阈值（事件总数，默认 100）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅检查阈值，不执行分析",
    )
    parser.add_argument(
        "--evolve",
        action="store_true",
        help="达阈值时执行写回（evolve）",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="实际写回文件（关闭 run_pipeline 的 dry_run）",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI 主入口。

    Args:
        argv: 命令行参数（None 时取 sys.argv[1:]）

    Returns:
        0 = 触发；1 = 未触发
    """
    args = build_parser().parse_args(argv)

    trace_dir = get_trace_dir()
    total = count_events(trace_dir)
    threshold = args.threshold

    if total < threshold:
        print(f"Events: {total} / {threshold} — 未达阈值，跳过")
        return 1

    print(f"Events: {total} >= {threshold} — 触发分析")

    if args.dry_run:
        return 0

    results = run_pipeline(
        trace_dir,
        since_days=0,
        extract=args.evolve,
        evolve=args.evolve,
        dry_run=not args.no_dry_run,
    )
    print(f"Sessions analyzed: {results.get('sessions_analyzed', 0)}")
    insights = results.get("insights", [])
    if insights:
        print(f"Insights: {len(insights)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
