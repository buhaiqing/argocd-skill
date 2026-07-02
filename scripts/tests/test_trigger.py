"""Tests for trigger module (P3.5-5~7 离线触发)."""
import os
import time
from pathlib import Path

import pytest

from argocd_insight.trigger.base import list_sessions, count_events, run_pipeline


# ---------- Task 1: base.py ----------

def test_list_sessions_finds_dirs(tmp_path):
    (tmp_path / "sessions" / "s_abc").mkdir(parents=True)
    (tmp_path / "sessions" / "s_def").mkdir(parents=True)
    (tmp_path / "sessions" / "other").mkdir()

    sessions = list(list_sessions(tmp_path))
    assert len(sessions) == 2
    assert all(s.name.startswith("s_") for s in sessions)


def test_list_sessions_empty(tmp_path):
    sessions = list(list_sessions(tmp_path))
    assert sessions == []


def test_list_sessions_since_filter(tmp_path):
    old = tmp_path / "sessions" / "s_old"
    old.mkdir(parents=True)
    old_ts = time.time() - 8 * 86400
    os.utime(old, (old_ts, old_ts))

    new = tmp_path / "sessions" / "s_new"
    new.mkdir(parents=True)

    sessions = list(list_sessions(tmp_path, since_days=7))
    assert len(sessions) == 1
    assert sessions[0].name == "s_new"


def test_count_events(tmp_path):
    from argocd_insight.trace.writer import TraceWriter

    sess = tmp_path / "sessions" / "s_test"
    writer = TraceWriter(sess)
    writer.write_event({"event_id": "e_001", "type": "cli_call"})
    writer.write_event({"event_id": "e_002", "type": "cli_call"})
    writer.close()

    assert count_events(tmp_path) == 2


def test_run_pipeline_no_sessions(tmp_path):
    """无会话时优雅返回空结果。"""
    results = run_pipeline(tmp_path, since_days=7)
    assert results["sessions_analyzed"] == 0
    assert results["total_events"] == 0
    assert results["insights"] == []
    assert results["evolve_results"] == {}


def test_run_pipeline_integration(tmp_path, monkeypatch):
    """全管道:列举 → 分析 → 提取(不写回)。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_pipe"
    writer = TraceWriter(sess)
    writer.write_event({
        "event_id": "e_001", "type": "cli_call",
        "command": "argocd app list", "duration_ms": 150,
        "return_code": 0, "module": "diagnose",
    })
    writer.close()

    results = run_pipeline(tmp_path, since_days=7, extract=True, evolve=False, dry_run=True)
    assert results["sessions_analyzed"] >= 1
    assert "insights" in results
    assert "evolve_results" in results


def test_run_pipeline_extract_path(tmp_path, monkeypatch):
    """extract 路径真实覆盖:构造能触发 insight 的事件(p99>p50*5 + errors>0)。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_extract"
    writer = TraceWriter(sess)
    # 5 个事件:4 个正常(150ms) + 1 个慢调用(5000ms 触发 p99>p50*5) + 1 个错误
    for i in range(4):
        writer.write_event({
            "event_id": f"e_{i:03d}", "type": "cli_call",
            "command": "argocd app list", "duration_ms": 150,
            "return_code": 0, "module": "diagnose",
        })
    writer.write_event({
        "event_id": "e_slow", "type": "cli_call",
        "command": "argocd app sync slow-app", "duration_ms": 5000,
        "return_code": 0, "module": "diagnose",
    })
    writer.write_event({
        "event_id": "e_err", "type": "cli_call",
        "command": "argocd app get missing", "duration_ms": 100,
        "return_code": -1, "module": "diagnose",
    })
    writer.close()

    results = run_pipeline(tmp_path, since_days=7, extract=True, evolve=False, dry_run=True)
    assert results["sessions_analyzed"] >= 1
    assert len(results["insights"]) >= 1, "extract 路径应产生至少 1 条 insight"


def test_run_pipeline_evolve_dry_run(tmp_path, monkeypatch):
    """evolve=True 路径覆盖:dry-run 不写文件,断言 evolve_results 非空。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_evolve"
    writer = TraceWriter(sess)
    for i in range(4):
        writer.write_event({
            "event_id": f"e_{i:03d}", "type": "cli_call",
            "command": "argocd app list", "duration_ms": 150,
            "return_code": 0, "module": "diagnose",
        })
    writer.write_event({
        "event_id": "e_slow", "type": "cli_call",
        "command": "argocd app sync slow-app", "duration_ms": 5000,
        "return_code": 0, "module": "diagnose",
    })
    writer.close()

    results = run_pipeline(tmp_path, since_days=7, extract=False, evolve=True, dry_run=True)
    assert results["sessions_analyzed"] >= 1
    assert len(results["insights"]) >= 1, "evolve=True 隐含 extract,应有 insights"
    assert results["evolve_results"], "evolve_results 不应为空"


# ---------- Task 2: cron.py ----------

def test_cron_cli_help():
    """cron 模块可作为 CLI 调用。"""
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "argocd_insight.trigger.cron", "--help"],
        capture_output=True, text=True,
        cwd="/Users/bohaiqing/opensource/git/argocd-skill/scripts",
    )
    assert result.returncode == 0
    assert "--since" in result.stdout


def test_cron_dry_run(tmp_path, monkeypatch):
    """cron 模式下 dry-run 不写回文件。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_cron"
    writer = TraceWriter(sess)
    writer.write_event({
        "event_id": "e_001", "type": "cli_call",
        "duration_ms": 100, "return_code": 0, "module": "diagnose",
    })
    writer.close()

    from argocd_insight.trigger.cron import main as cron_main
    exit_code = cron_main(["--since", "30", "--dry-run"])
    assert exit_code == 0


def test_cron_dry_run_no_evolve_output(tmp_path, monkeypatch, capsys):
    """cron dry-run 不传 --evolve/--extract 时,不打印 Insights/Evolve 行。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_cron2"
    writer = TraceWriter(sess)
    writer.write_event({
        "event_id": "e_001", "type": "cli_call",
        "duration_ms": 100, "return_code": 0, "module": "diagnose",
    })
    writer.close()

    from argocd_insight.trigger.cron import main as cron_main
    cron_main(["--since", "30", "--dry-run"])
    out = capsys.readouterr().out
    assert "Sessions analyzed: 1" in out
    assert "Total events: 1" in out
    assert "Insights:" not in out
    assert "Evolve:" not in out


def test_cron_evolve_dry_run_prints_evolve(tmp_path, monkeypatch, capsys):
    """cron --evolve --dry-run 打印 Insights 与 Evolve 行(Evolve 值为 int 数量)。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_cron_evolve"
    writer = TraceWriter(sess)
    # 4 个正常 + 1 个慢调用,触发 p99>p50*5 产生 insight
    for i in range(4):
        writer.write_event({
            "event_id": f"e_{i:03d}", "type": "cli_call",
            "command": "argocd app list", "duration_ms": 150,
            "return_code": 0, "module": "diagnose",
        })
    writer.write_event({
        "event_id": "e_slow", "type": "cli_call",
        "command": "argocd app sync slow-app", "duration_ms": 5000,
        "return_code": 0, "module": "diagnose",
    })
    writer.close()

    from argocd_insight.trigger.cron import main as cron_main
    cron_main(["--since", "30", "--evolve", "--dry-run"])
    out = capsys.readouterr().out
    assert "Insights:" in out
    assert "Evolve:" in out
    # Evolve 行应为数量(int),不是 list repr
    for line in out.splitlines():
        if line.startswith("Evolve:"):
            # 形如 "Evolve: low=1, medium=0, skipped=0"
            assert "[" not in line, f"Evolve 行打印了 list 而非数量: {line}"


def test_cron_output_json(tmp_path, monkeypatch, capsys):
    """--output json 输出合法 JSON 且含必要字段。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_cron_json"
    writer = TraceWriter(sess)
    writer.write_event({
        "event_id": "e_001", "type": "cli_call",
        "duration_ms": 100, "return_code": 0, "module": "diagnose",
    })
    writer.close()

    import json
    from argocd_insight.trigger.cron import main as cron_main
    cron_main(["--since", "30", "--dry-run", "--output", "json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["sessions_analyzed"] == 1
    assert payload["total_events"] == 1
    assert "insights" in payload
    assert "evolve_results" in payload


# ---------- Task 3: threshold.py ----------

def test_threshold_cli_help():
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "argocd_insight.trigger.threshold", "--help"],
        capture_output=True, text=True,
        cwd="/Users/bohaiqing/opensource/git/argocd-skill/scripts",
    )
    assert result.returncode == 0


def test_threshold_below_does_not_trigger(tmp_path, monkeypatch):
    """事件数未达阈值时不触发分析。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_thr"
    writer = TraceWriter(sess)
    writer.write_event({"event_id": "e_001", "type": "cli_call"})
    writer.close()

    from argocd_insight.trigger.threshold import main as thr_main
    exit_code = thr_main(["--threshold", "10", "--dry-run"])
    assert exit_code == 1  # 未触发


def test_threshold_meets_triggers(tmp_path, monkeypatch):
    """事件数达到阈值时触发分析。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_thr2"
    writer = TraceWriter(sess)
    for i in range(3):
        writer.write_event({
            "event_id": f"e_{i:04d}", "type": "cli_call",
            "duration_ms": 100, "return_code": 0, "module": "diagnose",
        })
    writer.close()

    from argocd_insight.trigger.threshold import main as thr_main
    exit_code = thr_main(["--threshold", "3", "--dry-run"])
    assert exit_code == 0  # 触发成功


# ---------- Task 4: session_end.py ----------

def test_session_end_hook_registers():
    """安装钩子返回非 None（注册了 atexit）。"""
    from argocd_insight.trigger.session_end import install_session_end_hook
    hook = install_session_end_hook()
    assert hook is not None


def test_session_end_env_disabled(monkeypatch):
    """未设置环境变量时不启用。"""
    monkeypatch.delenv("ARGOCD_SKILL_SESSION_HOOK", raising=False)
    from argocd_insight.trigger.session_end import is_hook_enabled
    assert not is_hook_enabled()


def test_session_end_env_enabled(monkeypatch):
    """设置环境变量时启用。"""
    monkeypatch.setenv("ARGOCD_SKILL_SESSION_HOOK", "1")
    from argocd_insight.trigger.session_end import is_hook_enabled
    assert is_hook_enabled()


@pytest.mark.parametrize("val", ["1", "true", "yes", "TRUE", "Yes", " 1 ", " TRUE "])
def test_session_end_env_truthy_values(monkeypatch, val):
    """1/true/yes（含大小写、首尾空白）均启用。"""
    monkeypatch.setenv("ARGOCD_SKILL_SESSION_HOOK", val)
    from argocd_insight.trigger.session_end import is_hook_enabled
    assert is_hook_enabled()


@pytest.mark.parametrize("val", ["0", "false", "no", "", "random"])
def test_session_end_env_falsy_values(monkeypatch, val):
    """0/false/no/空字符串/其他值均不启用。"""
    monkeypatch.setenv("ARGOCD_SKILL_SESSION_HOOK", val)
    from argocd_insight.trigger.session_end import is_hook_enabled
    assert not is_hook_enabled()


def test_session_end_handler_prints_summary(tmp_path, monkeypatch, capsys):
    """有会话时 handler 打印 [trace-hook] 摘要到 stderr。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_hook"
    writer = TraceWriter(sess)
    writer.write_event({
        "event_id": "e_001", "type": "cli_call",
        "duration_ms": 100, "return_code": 0, "module": "diagnose",
    })
    writer.close()

    from argocd_insight.trigger.session_end import _session_end_handler
    _session_end_handler()

    captured = capsys.readouterr()
    assert "[trace-hook]" in captured.err
    assert "1 sessions" in captured.err


def test_session_end_handler_no_sessions_silent(tmp_path, monkeypatch, capsys):
    """无会话时 handler 不输出。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    from argocd_insight.trigger.session_end import _session_end_handler
    _session_end_handler()

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_session_end_handler_exception_ponytail(monkeypatch, capsys):
    """run_pipeline 抛异常时 handler 不抛出，打印 error 到 stderr。"""
    from argocd_insight.trigger import session_end

    def boom(*args, **kwargs):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(session_end, "run_pipeline", boom)

    # 不应抛出
    session_end._session_end_handler()

    captured = capsys.readouterr()
    assert "[trace-hook] error:" in captured.err
    assert "pipeline exploded" in captured.err


def test_session_end_install_idempotent(monkeypatch):
    """多次调用 install_session_end_hook 返回同一对象（幂等）。"""
    monkeypatch.setenv("ARGOCD_SKILL_SESSION_HOOK", "1")
    from argocd_insight.trigger.session_end import install_session_end_hook
    h1 = install_session_end_hook()
    h2 = install_session_end_hook()
    assert h1 is h2
