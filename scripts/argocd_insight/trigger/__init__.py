"""trigger 包：离线触发机制（定时 / 阈值 / 会话结束）。

共享工具函数在 base.py 中实现，三个触发模式各自提供独立入口点。
"""
from .base import run_pipeline, list_sessions, count_events, get_trace_dir

__all__ = ["run_pipeline", "list_sessions", "count_events", "get_trace_dir"]
