"""trace 包：会话管理 + JSONL 写入 + 装饰器。"""
from .session import Session as Session, get_session_id as get_session_id
from .writer import TraceWriter as TraceWriter
from .decorator import traced as traced, get_trace_dir as get_trace_dir