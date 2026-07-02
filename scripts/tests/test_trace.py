"""Tests for trace module (轨迹记录核心)."""
import pytest
from pathlib import Path
from argocd_insight.trace.session import Session, get_session_id
from argocd_insight.trace.writer import TraceWriter


def test_session_id_format():
    s = Session(module="diagnose")
    assert s.id.startswith("s_")
    assert len(s.id) > 10


def test_session_meta():
    s = Session(module="diagnose")
    assert s.module == "diagnose"
    assert s.start_time is not None


def test_traced_decorator(tmp_path, monkeypatch):
    """@traced 装饰器记录调用轨迹。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))
    from argocd_insight.trace.decorator import traced

    call_log = []

    @traced(module="diagnose", operation="app_list")
    def my_command():
        call_log.append("executed")
        return "ok"

    result = my_command()

    assert result == "ok"
    assert call_log == ["executed"]
    # 检查轨迹文件是否生成
    trace_files = list(tmp_path.glob("sessions/*/trace_*.jsonl"))
    assert len(trace_files) == 1


def test_get_trace_dir_default(monkeypatch):
    """env 未设置时，默认为 <CWD>/.runtime/argocd-skill"""
    monkeypatch.delenv("ARGOCD_SKILL_RUNTIME_DIR", raising=False)
    import os
    from argocd_insight.trace.decorator import get_trace_dir

    expected = Path.cwd() / ".runtime" / "argocd-skill"
    assert get_trace_dir() == expected.resolve()
    assert get_trace_dir().name == "argocd-skill"
    assert get_trace_dir().parent.name == ".runtime"


def test_get_trace_dir_relative_to_cwd(monkeypatch, tmp_path):
    """相对路径相对于当前工作目录（CWD）解析。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", ".runtime/argocd-skill")
    from argocd_insight.trace.decorator import get_trace_dir

    expected = Path.cwd() / ".runtime" / "argocd-skill"
    assert get_trace_dir() == expected.resolve()


def test_get_trace_dir_absolute(monkeypatch, tmp_path):
    """绝对路径直接使用，不受 CWD 影响。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path / "custom" / "runtime"))
    from argocd_insight.trace.decorator import get_trace_dir

    assert get_trace_dir() == (tmp_path / "custom" / "runtime").resolve()


def test_writer_jsonl_format(tmp_path):
    writer = TraceWriter(tmp_path)
    writer.write_event({
        "event_id": "e_001",
        "type": "cli_call",
        "command": "argocd app list",
        "duration_ms": 100,
        "return_code": 0,
    })
    assert (tmp_path / "trace_000.jsonl").exists()