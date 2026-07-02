"""@traced 装饰器。"""
from __future__ import annotations
import functools
import os
import platform
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .session import Session, get_session_id
from .writer import TraceWriter

def get_trace_dir() -> Path:
    """获取运行时目录。

    优先级：``ARGOCD_SKILL_RUNTIME_DIR`` env > ``<CWD>/.runtime/argocd-skill``。

    - env 值为绝对路径 → 直接使用
    - env 值为相对路径 → 相对于 **当前工作目录（CWD）** 解析
    - env 未设置 → 默认为 ``<CWD>/.runtime/argocd-skill``

    ponytail: 目录不存在时自动创建（mkdir parents），便于 ls 等工具直接检查。
    """
    env_val = os.getenv("ARGOCD_SKILL_RUNTIME_DIR")
    if env_val:
        base = Path(env_val)
        if not base.is_absolute():
            base = Path.cwd() / base
    else:
        base = Path.cwd() / ".runtime" / "argocd-skill"
    resolved = base.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


_event_counter = 0


def traced(module: str, operation: str, interface: str = "cli"):
    """拦截 CLI/API 调用的装饰器。

    Args:
        module: 功能模块名（如 "diagnose", "api"）
        operation: 操作名（如 "app_list", "sync"）
        interface: 调用接口类型，"cli" | "api" | "web"（默认 "cli"）
    """
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
                    "interface": interface,
                    "command": _reconstruct_cmd(args, kwargs),
                    "start": start_iso,
                    "duration_ms": duration_ms,
                    "return_code": return_code,
                    "error": error_msg,
                    "host": platform.node(),
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