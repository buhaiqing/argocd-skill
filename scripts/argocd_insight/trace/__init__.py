"""trace 包：会话管理 + JSONL 写入 + 装饰器。"""
from .session import Session, get_session_id
from .writer import TraceWriter
from .decorator import traced, get_trace_dir