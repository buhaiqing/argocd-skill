"""会话结束触发（P3.5-7）— 通过 atexit 注册轻量级分析钩子。

启用方式：
    export ARGOCD_SKILL_SESSION_HOOK=1

设计原则：
- 默认**不启用**：仅当 ARGOCD_SKILL_SESSION_HOOK=1/true/yes 时才注册 atexit 钩子，
  避免对未开启 trace 的会话产生副作用。
- 仅分析最近 1 天：会话结束钩子面向"刚结束的会话"，时间窗设为 1 天，
  避免重复分析历史会话。
- 始终 dry-run：会话结束钩子只做**只读分析**，不写回经验文件，
  防止异常退出时污染知识库。
- 输出到 stderr：分析摘要打印到 stderr，不干扰 stdout 的正常输出。
- 异常不抛出（ponytail）：钩子内任何异常都捕获并打印 error 行，
  绝不影响宿主进程的退出码。
"""
from __future__ import annotations

import atexit
import os
import sys
from typing import Callable

from .base import get_trace_dir, run_pipeline

__all__ = ["is_hook_enabled", "install_session_end_hook"]

_HOOK_INSTALLED = False


def is_hook_enabled() -> bool:
    """检查 ARGOCD_SKILL_SESSION_HOOK 是否启用。

    环境变量值为 1/true/yes（忽略大小写与首尾空白）时返回 True，
    未设置或其他值返回 False。
    """
    raw = os.environ.get("ARGOCD_SKILL_SESSION_HOOK", "")
    return raw.strip().lower() in ("1", "true", "yes")


def install_session_end_hook() -> Callable[[], None] | None:
    """幂等注册 atexit 会话结束钩子。

    仅当 is_hook_enabled() 为 True 时调用 atexit.register。
    多次调用只注册一次（幂等）。始终返回 _session_end_handler 函数对象
    （用于测试断言非 None）；未启用时不注册，但仍返回 handler 对象。
    """
    global _HOOK_INSTALLED
    if not _HOOK_INSTALLED and is_hook_enabled():
        atexit.register(_session_end_handler)
        _HOOK_INSTALLED = True
    return _session_end_handler


def _session_end_handler() -> None:
    """atexit 回调 — 运行轻量级分析管道，异常不抛出。

    运行 run_pipeline(trace_dir, since_days=1, extract=True, evolve=False,
    dry_run=True)；若 sessions_analyzed > 0，打印摘要到 stderr。
    任何异常都捕获并打印 error 行，不影响宿主进程退出码。
    """
    try:
        results = run_pipeline(
            get_trace_dir(),
            since_days=1,
            extract=True,
            evolve=False,
            dry_run=True,
        )
        sessions = results.get("sessions_analyzed", 0)
        if sessions > 0:
            events = results.get("total_events", 0)
            insights = len(results.get("insights", []))
            print(
                f"[trace-hook] {sessions} sessions, {events} events, "
                f"{insights} insights",
                file=sys.stderr,
            )
    except Exception as e:
        print(f"[trace-hook] error: {e}", file=sys.stderr)
