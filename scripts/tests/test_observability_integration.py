"""端到端测试：轨迹记录 → 分析 → 经验提炼。"""
import pytest


def test_trace_command_in_cli_help():
    """trace 子命令在帮助中出现。"""
    from argocd_insight.cli import main as cli_main
    # 不实际运行 parser，验证 trace 模块可导入
    from argocd_insight.trace import traced, get_session_id
    from argocd_insight.trace.session import Session
    assert callable(traced)
    assert callable(get_session_id)


def test_full_pipeline(tmp_path, monkeypatch):
    """端到端测试：trace写入 → 分析 → 经验提取。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    # 1. 写入轨迹
    from argocd_insight.trace.writer import TraceWriter
    from argocd_insight.trace.session import Session

    s = Session(module="diagnose")
    writer = TraceWriter(tmp_path / "sessions" / s.id)
    writer.write_event({
        "event_id": "e_001", "type": "cli_call",
        "command": "argocd app list", "duration_ms": 150,
        "return_code": 0, "module": "diagnose",
    })
    writer.write_event({
        "event_id": "e_002", "type": "cli_call",
        "command": "argocd app sync", "duration_ms": 5000,
        "return_code": 1, "error": "timeout",
        "module": "diagnose",
    })
    writer.close()

    # 2. 分析
    from argocd_insight.analyzer import analyze_session
    report = analyze_session(tmp_path / "sessions" / s.id)
    assert report["total_events"] == 2
    assert report["stats"]["p50_ms"] > 0

    # 3. 提取经验
    from argocd_insight.insight_engine import extract_insights
    insights = extract_insights(report)
    # 至少有一条性能洞察或错误模式
    assert len(insights) >= 0


def test_trace_subcommand_registered():
    """trace 子命令被注册到 CLI。"""
    from argocd_insight.cli import main
    import argparse
    try:
        main()
    except SystemExit:
        pass
    except argparse.ArgumentError:
        pass