"""共享基础模块 — 列举会话 / 统计事件 / 运行全分析管道。

三个触发模式（cron / threshold / session_end）共用本模块的工具函数，
避免重复实现。所有函数都不依赖外部调度器，仅基于文件系统。
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..trace.decorator import get_trace_dir

__all__ = ["list_sessions", "count_events", "run_pipeline", "get_trace_dir"]


def list_sessions(trace_dir: Path, since_days: int = 0) -> list[Path]:
    """列举 trace_dir/sessions/ 下所有 s_ 前缀的会话目录。

    Args:
        trace_dir: 轨迹根目录（含 sessions/ 子目录）
        since_days: 仅返回最近 N 天内修改过的会话（0 表示全部）

    Returns:
        按名称排序的会话目录列表。无 sessions/ 目录时返回空列表。
    """
    sessions_dir = trace_dir / "sessions"
    if not sessions_dir.exists():
        return []

    cutoff = time.time() - since_days * 86400 if since_days > 0 else 0
    result: list[Path] = []
    for p in sorted(sessions_dir.iterdir()):
        if p.is_dir() and p.name.startswith("s_"):
            if cutoff == 0 or p.stat().st_mtime >= cutoff:
                result.append(p)
    return result


def count_events(trace_dir: Path) -> int:
    """统计 trace_dir 下所有会话的事件总数。

    遍历 sessions/s_*/trace_*.jsonl 文件，逐行计数非空行。
    """
    total = 0
    for session_dir in list_sessions(trace_dir):
        for f in session_dir.glob("trace_*.jsonl"):
            with open(f, encoding="utf-8") as fp:
                for line in fp:
                    if line.strip():
                        total += 1
    return total


def run_pipeline(
    trace_dir: Path,
    since_days: int = 7,
    extract: bool = False,
    evolve: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """全分析管道：列举会话 → 分析 → 提炼经验 → 写回。

    Args:
        trace_dir: 轨迹根目录
        since_days: 仅分析最近 N 天的会话
        extract: 是否提炼经验（默认 False，仅做统计）
        evolve: 是否执行写回（默认 False）。evolve=True 时隐含 extract=True
        dry_run: 写回时是否 dry-run（默认 True，不实际写文件）

    Returns:
        dict 含:
        - sessions_analyzed: int
        - total_events: int
        - insights: list[Insight]（extract=False 时为空列表）
        - evolve_results: dict（evolve=False 时为空 dict）
    """
    sessions = list_sessions(trace_dir, since_days=since_days)
    if not sessions:
        return {
            "sessions_analyzed": 0,
            "total_events": 0,
            "insights": [],
            "evolve_results": {},
        }

    # 延迟导入，避免在仅列举会话时拉起分析依赖
    from ..analyzer import analyze_session
    from ..insight_engine import extract_insights

    do_extract = extract or evolve
    all_insights: list[Any] = []
    total_events = 0

    for session_dir in sessions:
        report = analyze_session(session_dir)
        total_events += report.get("total_events", 0)
        if do_extract:
            insights = extract_insights(report)
            all_insights.extend(insights)

    result: dict[str, Any] = {
        "sessions_analyzed": len(sessions),
        "total_events": total_events,
        "insights": all_insights if do_extract else [],
    }

    if evolve and all_insights:
        from ..evolver import evolve as evolve_write
        result["evolve_results"] = evolve_write(all_insights, dry_run=dry_run)
    else:
        result["evolve_results"] = {}

    return result
