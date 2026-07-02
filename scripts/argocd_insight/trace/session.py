"""会话管理。"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Session:
    """单次工具执行的会话。"""
    module: str
    id: str = field(default_factory=lambda: f"s_{uuid.uuid4().hex[:12]}")
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: str = ""
    command: str = ""


_session_local: Session | None = None


def get_session_id() -> str:
    """获取当前会话 ID。"""
    global _session_local
    if _session_local is None:
        _session_local = Session(module="unknown")
    return _session_local.id