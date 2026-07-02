"""@traced 装饰器。"""
from __future__ import annotations
import functools
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .session import Session, get_session_id
from .writer import TraceWriter


def get_trace_dir() -> Path:
    """获取运行时目录。"""
    base = Path(os.getenv("ARGOCD_SKILL_RUNTIME_DIR"))
    if not base:
        base = Path.home() / ".runtime" / "argocd-skill"
    return base.resolve()


_event_counter = 0


def traced(module: str, operation: str):
    """拦截 CLI/API 调用的装饰器。"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            global _event_counter
            sid = get_session_id()
            event_id = f"e_{_event_counter:04d}"
            _event_counter += 1

            trace_dir = get_trace_dir() / "sessions" / sid
            writer = TraceWriter(trace_dir)

            start = time.perf_counter()
            start_iso = datetime.now(timezone.utc).isoformat()
            return_code = 0
            error_msg = ""

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                return_code = -1
                error_msg = str(e)
                raise
            finally:
                end = time.perf_counter()
                duration_ms = int((end - start) * 1000)

                writer.write_event({
                    "event_id": event_id,
                    "type": "cli_call",
                    "module": module,
                    "operation": operation,
                    "command": _reconstruct_cmd(args, kwargs),
                    "start": start_iso,
                    "duration_ms": duration_ms,
                    "return_code": return_code,
                    "error": error_msg,
                })
                writer.close()

        return wrapper
    return decorator


_MASKED_PARAMS = {"password", "token", "secret", "api_key", "apikey"}


def _reconstruct_cmd(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """从参数重建命令字符串（敏感参数值打码）。"""
    parts: list[str] = []
    for a in args:
        if isinstance(a, list):
            parts.extend(str(x) for x in a)
        elif isinstance(a, str):
            parts.append(a)
    for k, v in kwargs.items():
        if v is None:
            continue
        if k.lower() in _MASKED_PARAMS:
            parts.append(f"--{k}=***")
        elif isinstance(v, bool) and v:
            parts.append(f"--{k}")
        else:
            parts.append(f"--{k}={v}")
    return " ".join(parts)