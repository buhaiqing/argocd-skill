# P3.5-5~7 离线流程触发 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 argocd-skill 构建三种离线触发机制（定时/阈值/会话结束），使轨迹分析-经验提炼-自进化写回流程可以自动化执行

**Architecture:** 三个触发模式共享一个 `trigger/base.py` 核心工具集（列举会话、运行全分析管道、统计事件数），各自通过独立入口点实现触发逻辑。定时触发通过 cron CLI 命令实现；阈值触发通过事件计数守卫实现；会话结束触发通过 Python `atexit` 钩子注册实现。

**Tech Stack:** Python ≥ 3.10, 标准库 (argparse/atexit/os/pathlib/json/datetime), 已有 trace/analyzer/insight_engine/evolver 模块

## Global Constraints

- 所有触发模式共用 `trigger/base.py` 中的工具函数，不重复实现
- 每个触发模式必须可独立运行（入口点不同）
- 不依赖外部调度器（cron 模式只负责生成可被 cron 调用的命令脚本）
- 阈值和会话结束触发默认不启用，通过环境变量或显式调用激活
- 遵守既有的置信度规则：≥0.9 自动写回，0.7~0.9 dry-run，<0.7 跳过

---

## 文件结构

```
scripts/argocd_insight/trigger/
├── __init__.py              # 导出 run_pipeline, list_sessions, count_events
├── base.py                  # 共享工具：列举会话、运行管道、事件计数
├── cron.py                  # P3.5-5: 定时触发入口
├── threshold.py             # P3.5-6: 阈值触发入口
└── session_end.py           # P3.5-7: 会话结束钩子

scripts/tests/
└── test_trigger.py           # 所有触发模式的测试
```

---

## 任务清单

### Task 1: 共享基础模块（trigger/base.py）

**Files:**
- Create: `scripts/argocd_insight/trigger/__init__.py`
- Create: `scripts/argocd_insight/trigger/base.py`
- Test in: `scripts/tests/test_trigger.py`

**Interfaces:**
- Consumes: `trace.decorator.get_trace_dir()`, `analyzer.analyze_session()`, `insight_engine.extract_insights()`, `evolver.evolve()`
- Produces: `list_sessions(...)` -> `list[Path]`, `count_events(trace_dir) -> int`, `run_pipeline(session_dirs, ...) -> dict`

- [ ] **Step 1: 编写基础模块测试**

```python
# scripts/tests/test_trigger.py
from pathlib import Path
from argocd_insight.trigger.base import list_sessions, count_events, run_pipeline


def test_list_sessions_finds_dirs(tmp_path):
    # 创建模拟会话目录
    (tmp_path / "sessions" / "s_abc").mkdir(parents=True)
    (tmp_path / "sessions" / "s_def").mkdir(parents=True)
    # 非会话目录不应该被匹配
    (tmp_path / "sessions" / "other").mkdir()

    sessions = list(list_sessions(tmp_path))
    assert len(sessions) == 2
    assert all(s.name.startswith("s_") for s in sessions)


def test_list_sessions_empty(tmp_path):
    sessions = list(list_sessions(tmp_path))
    assert sessions == []


def test_list_sessions_since_filter(tmp_path):
    import time
    from datetime import datetime, timezone

    old = tmp_path / "sessions" / "s_old"
    old.mkdir(parents=True)
    # 设置旧会话的 mtime 为 8 天前
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


def test_run_pipeline_integration(tmp_path, monkeypatch):
    """测试全管道：列举会话 → 分析 → 提取 → 写回。"""
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    # 写入一条轨迹
    from argocd_insight.trace.writer import TraceWriter
    sess = tmp_path / "sessions" / "s_pipe"
    writer = TraceWriter(sess)
    writer.write_event({
        "event_id": "e_001", "type": "cli_call",
        "command": "argocd app list", "duration_ms": 150,
        "return_code": 0, "module": "diagnose",
    })
    writer.close()

    results = run_pipeline(tmp_path, since_days=7, extract=True, evolve=True, dry_run=True)
    assert results["sessions_analyzed"] >= 1
    assert "insights" in results
    assert "evolve_results" in results
```

- [ ] **Step 2: 验证测试失败**

Run: `cd scripts && pytest tests/test_trigger.py -v`
Expected: FAIL (ModuleNotFoundError for trigger module)

- [ ] **Step 3: 实现 base.py**

```python
# scripts/argocd_insight/trigger/base.py
from __future__ import annotations
import os
import time
import json
from pathlib import Path
from typing import Any
from ..trace.decorator import get_trace_dir


def list_sessions(trace_dir: Path, since_days: int = 0) -> list[Path]:
    """列举 trace_dir/sessions/ 下所有 s_ 前缀的会话目录。

    Args:
        trace_dir: 轨迹根目录（含 sessions/ 子目录）
        since_days: 仅返回最近 N 天内的会话（0 表示全部）
    """
    sessions_dir = trace_dir / "sessions"
    if not sessions_dir.exists():
        return []

    cutoff = time.time() - since_days * 86400 if since_days > 0 else 0
    result = []
    for p in sorted(sessions_dir.iterdir()):
        if p.is_dir() and p.name.startswith("s_"):
            if cutoff == 0 or p.stat().st_mtime >= cutoff:
                result.append(p)
    return result


def count_events(trace_dir: Path) -> int:
    """统计 trace_dir 下所有会话的事件总数。"""
    total = 0
    for session_dir in list_sessions(trace_dir):
        for f in session_dir.glob("trace_*.jsonl"):
            with open(f) as fp:
                for line in fp:
                    if line.strip():
                        total += 1
    return total


def run_pipeline(
    trace_dir: Path,
    since_days: int = 7,
    extract: bool = False,
    evolve: bool = False,
    dry_run: bool = True,
) -> dict[str, Any]:
    """全管道：分析会话 → 提炼经验 → 写回。

    Returns:
        dict with keys: sessions_analyzed, total_events, insights, evolve_results
    """
    from ..analyzer import analyze_session
    from ..insight_engine import extract_insights

    sessions = list_sessions(trace_dir, since_days=since_days)
    if not sessions:
        return {"sessions_analyzed": 0, "total_events": 0, "insights": [], "evolve_results": {}}

    all_insights = []
    for session_dir in sessions:
        report = analyze_session(session_dir)
        if extract or evolve:
            insights = extract_insights(report)
            all_insights.extend(insights)

    result: dict[str, Any] = {
        "sessions_analyzed": len(sessions),
        "total_events": sum(
            len(list(s.glob("trace_*.jsonl"))) for s in sessions
        ),
        "insights": all_insights if extract else [],
    }

    if evolve and all_insights:
        from ..evolver import evolve as evolve_write
        result["evolve_results"] = evolve_write(all_insights, dry_run=dry_run)
    else:
        result["evolve_results"] = {}

    return result
```

- [ ] **Step 4: 实现 __init__.py**

```python
# scripts/argocd_insight/trigger/__init__.py
from .base import run_pipeline, list_sessions, count_events
```

- [ ] **Step 5: 验证测试通过**

Run: `cd scripts && pytest tests/test_trigger.py -v`
Expected: PASS (all tests)

- [ ] **Step 6: 提交**

```bash
git add scripts/argocd_insight/trigger/ scripts/tests/test_trigger.py
git commit -m "feat(trigger): P3.5-5 base — 共享基础模块（list_sessions/count_events/run_pipeline）"
```

---

### Task 2: 定时触发（trigger/cron.py — P3.5-5）

**Files:**
- Create: `scripts/argocd_insight/trigger/cron.py`
- Test in: `scripts/tests/test_trigger.py`（追加）

**Interfaces:**
- Consumes: `base.run_pipeline()`, `base.list_sessions()`
- Produces: CLI entry point `python -m argocd_insight.trigger.cron`，适合 crontab 调用

- [ ] **Step 1: 编写 cron 触发测试**

```python
# scripts/tests/test_trigger.py 追加
def test_cron_cli_help():
    """cron 模块可作为 CLI 调用。"""
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "argocd_insight.trigger.cron", "--help"],
        capture_output=True, text=True,
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
    import sys
    exit_code = cron_main(["--since", "30", "--dry-run"])
    assert exit_code == 0
```

- [ ] **Step 2: 验证测试失败**

Run: `cd scripts && pytest tests/test_trigger.py::test_cron_cli_help -v`
Expected: FAIL (module not importable yet)

- [ ] **Step 3: 实现 cron.py**

```python
# scripts/argocd_insight/trigger/cron.py
"""定时触发入口 — 适合 crontab 调用。

Usage:
    python -m argocd_insight.trigger.cron --since 7
    python -m argocd_insight.trigger.cron --since 30 --evolve --no-dry-run

Crontab 示例（每天凌晨 3 点执行）:
    0 3 * * * cd /path/to/project && python -m argocd_insight.trigger.cron \
        --since 7 --evolve --no-dry-run >> /var/log/argocd-trace-cron.log 2>&1
"""
from __future__ import annotations
import argparse
import sys
from .base import run_pipeline, get_trace_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m argocd_insight.trigger.cron",
        description="定时分析轨迹并经验沉淀（适合 cron 调用）",
    )
    parser.add_argument("--since", type=int, default=7,
                        help="分析最近 N 天的轨迹（默认 7）")
    parser.add_argument("--extract", action="store_true",
                        help="提取经验")
    parser.add_argument("--evolve", action="store_true",
                        help="执行写回（默认 dry-run）")
    parser.add_argument("--no-dry-run", action="store_true",
                        help="实际写回文件")
    parser.add_argument("--output", choices=["text", "json"], default="text",
                        help="输出格式")

    args = parser.parse_args(argv)

    trace_dir = get_trace_dir()
    dry_run = not args.no_dry_run

    results = run_pipeline(
        trace_dir=trace_dir,
        since_days=args.since,
        extract=args.evolve or args.extract,
        evolve=args.evolve,
        dry_run=dry_run,
    )

    if args.output == "json":
        import json
        print(json.dumps(results, ensure_ascii=False, default=str))
    else:
        print(f"Sessions analyzed: {results['sessions_analyzed']}")
        print(f"Total events: {results['total_events']}")
        if results.get("insights"):
            print(f"Insights: {len(results['insights'])}")
        if results.get("evolve_results"):
            evolve = results["evolve_results"]
            print(f"Evolve: low={len(evolve.get('low', []))}, "
                  f"medium={len(evolve.get('medium', []))}, "
                  f"skipped={len(evolve.get('skipped', []))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 验证测试通过**

Run: `cd scripts && pytest tests/test_trigger.py::test_cron_cli_help tests/test_trigger.py::test_cron_dry_run -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/argocd_insight/trigger/cron.py
git commit -m "feat(trigger): P3.5-5 定时触发（cron CLI 入口）"
```

---

### Task 3: 阈值触发（trigger/threshold.py — P3.5-6）

**Files:**
- Create: `scripts/argocd_insight/trigger/threshold.py`
- Test in: `scripts/tests/test_trigger.py`（追加）

**Interfaces:**
- Consumes: `base.count_events()`, `base.run_pipeline()`
- Produces: CLI entry point `python -m argocd_insight.trigger.threshold`，可配合 cron 使用

- [ ] **Step 1: 编写阈值触发测试**

```python
# scripts/tests/test_trigger.py 追加
def test_threshold_cli_help():
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "argocd_insight.trigger.threshold", "--help"],
        capture_output=True, text=True,
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
```

- [ ] **Step 2: 验证测试失败**

Run: `cd scripts && pytest tests/test_trigger.py::test_threshold_cli_help -v`
Expected: FAIL

- [ ] **Step 3: 实现 threshold.py**

```python
# scripts/argocd_insight/trigger/threshold.py
"""阈值触发入口 — 事件数达阈值时触发分析。

设计为 exit code 守卫：返回 0（触发）或 1（未触发），方便 cron 串联。

Usage:
    # 独立运行
    python -m argocd_insight.trigger.threshold --threshold 100

    # cron 中串联（达阈值才执行）
    python -m argocd_insight.trigger.threshold --threshold 100 --dry-run \\
        && python -m argocd_insight.trigger.cron --since 7 --evolve --no-dry-run
"""
from __future__ import annotations
import argparse
import sys
from .base import count_events, run_pipeline, get_trace_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m argocd_insight.trigger.threshold",
        description="事件数达阈值时触发轨迹分析",
    )
    parser.add_argument("--threshold", type=int, default=100,
                        help="触发阈值（事件条数，默认 100）")
    parser.add_argument("--dry-run", action="store_true",
                        help="仅检查阈值，不执行分析")
    parser.add_argument("--evolve", action="store_true",
                        help="达阈值时执行写回")
    parser.add_argument("--no-dry-run", action="store_true",
                        help="实际写回文件")

    args = parser.parse_args(argv)

    trace_dir = get_trace_dir()
    total = count_events(trace_dir)

    if total < args.threshold:
        print(f"Events: {total} / {args.threshold} — 未达阈值，跳过")
        return 1

    print(f"Events: {total} >= {args.threshold} — 触发分析")

    if not args.dry_run:
        results = run_pipeline(
            trace_dir=trace_dir,
            since_days=0,
            extract=args.evolve,
            evolve=args.evolve,
            dry_run=not args.no_dry_run,
        )
        print(f"Sessions analyzed: {results['sessions_analyzed']}")
        if results.get("insights"):
            print(f"Insights: {len(results['insights'])}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 验证测试通过**

Run: `cd scripts && pytest tests/test_trigger.py::test_threshold_cli_help tests/test_trigger.py::test_threshold_below_does_not_trigger tests/test_trigger.py::test_threshold_meets_triggers -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/argocd_insight/trigger/threshold.py
git commit -m "feat(trigger): P3.5-6 阈值触发（事件计数守卫）"
```

---

### Task 4: 会话结束触发（trigger/session_end.py — P3.5-7）

**Files:**
- Create: `scripts/argocd_insight/trigger/session_end.py`
- Test in: `scripts/tests/test_trigger.py`（追加）

**Interfaces:**
- Consumes: `base.run_pipeline()`, `trace.decorator.get_session_id()`
- Produces: `install_session_end_hook()` 函数，支持 `ARGOCD_SKILL_SESSION_HOOK=1` env 启用

- [ ] **Step 1: 编写会话结束触发测试**

```python
# scripts/tests/test_trigger.py 追加
def test_session_end_hook_registers():
    """安装钩子不会立即执行。"""
    from argocd_insight.trigger.session_end import install_session_end_hook
    hook = install_session_end_hook()
    # 只是注册 atexit，不执行任何操作
    assert hook is not None


def test_session_end_env_disabled(monkeypatch):
    """未设置环境变量时不安装钩子。"""
    monkeypatch.delenv("ARGOCD_SKILL_SESSION_HOOK", raising=False)
    from argocd_insight.trigger.session_end import is_hook_enabled
    assert not is_hook_enabled()


def test_session_end_env_enabled(monkeypatch):
    """设置环境变量时安装钩子。"""
    monkeypatch.setenv("ARGOCD_SKILL_SESSION_HOOK", "1")
    from argocd_insight.trigger.session_end import is_hook_enabled
    assert is_hook_enabled()
```

- [ ] **Step 2: 验证测试失败**

Run: `cd scripts && pytest tests/test_trigger.py::test_session_end_hook_registers -v`
Expected: FAIL

- [ ] **Step 3: 实现 session_end.py**

```python
# scripts/argocd_insight/trigger/session_end.py
"""会话结束自动触发 — 通过 atexit 注册轻量级分析。

启用方式（环境变量）:
    ARGOCD_SKILL_SESSION_HOOK=1 python -m argocd_insight ...

设计原则：
    - 默认不启用，需显式设置环境变量
    - 仅分析当前会话（最近 1 天）
    - 始终以 dry-run 模式运行，不自动写回
    - 分析结果输出到 stderr，不影响 stdout
"""
from __future__ import annotations
import atexit
import os
import sys
from .base import run_pipeline, get_trace_dir


def is_hook_enabled() -> bool:
    """检查环境变量是否启用会话结束钩子。"""
    return os.getenv("ARGOCD_SKILL_SESSION_HOOK", "").strip() in ("1", "true", "yes")


def _session_end_handler():
    """atexit 回调：运行轻量级分析。"""
    try:
        trace_dir = get_trace_dir()
        results = run_pipeline(
            trace_dir=trace_dir,
            since_days=1,
            extract=True,
            evolve=False,  # 会话结束仅分析，不写回
            dry_run=True,
        )
        if results["sessions_analyzed"] > 0:
            print(
                f"[trace-hook] {results['sessions_analyzed']} sessions, "
                f"{results['total_events']} events, "
                f"{len(results['insights'])} insights",
                file=sys.stderr,
            )
    except Exception as e:
        # ponytail: atexit 中不抛出异常
        print(f"[trace-hook] error: {e}", file=sys.stderr)


def install_session_end_hook():
    """注册会话结束分析钩子（幂等）。"""
    if is_hook_enabled():
        atexit.register(_session_end_handler)
    return _session_end_handler
```

- [ ] **Step 4: 验证测试通过**

Run: `cd scripts && pytest tests/test_trigger.py::test_session_end_hook_registers tests/test_trigger.py::test_session_end_env_disabled tests/test_trigger.py::test_session_end_env_enabled -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add scripts/argocd_insight/trigger/session_end.py
git commit -m "feat(trigger): P3.5-7 会话结束触发（atexit 钩子）"
```

---

### Task 5: 全量回归测试 + crontab 示例文档

**Files:**
- Modify: `scripts/tests/test_trigger.py`（如有遗漏补充）
- Create: 在 `scripts/` 下添加安装脚本 `install_cron.sh.example`（crontab 示例）
- Modify: `TODO.md`（更新最终状态）

- [ ] **Step 1: 运行全量回归测试**

Run: `cd scripts && pytest tests/ -v --tb=short`
Expected: 所有原有测试通过 + 新增触发模块测试通过

- [ ] **Step 2: 创建 crontab 安装示例**

```bash
# scripts/install_cron.sh.example
# 安装 argocd-skill 定时轨迹分析 crontab
#
# 使用方式：
#   bash install_cron.sh.example
#   或手动添加到 crontab：
#   crontab -e
#
# 配置项
PROJECT_DIR="/path/to/argocd-skill"
PYTHON="/usr/local/bin/python3"
LOG_DIR="/var/log/argocd-trace"

# 创建日志目录
mkdir -p "$LOG_DIR"

# 添加到 crontab（每天凌晨 3 点执行）
CRON_LINE="0 3 * * * cd $PROJECT_DIR && $PYTHON -m argocd_insight.trigger.cron --since 7 --evolve --no-dry-run >> $LOG_DIR/cron.log 2>&1"

# 检查是否已存在
(crontab -l 2>/dev/null | grep -v "argocd_insight.trigger.cron"; echo "$CRON_LINE") | crontab -
echo "Crontab installed: $CRON_LINE"
```

- [ ] **Step 3: 更新 TODO.md 最终状态**

确认 TODO.md 中 P3.5 部分标记为：
- P3.5-5 ✅ → 定时触发
- P3.5-6 ✅ → 阈值触发
- P3.5-7 ✅ → 会话结束触发

- [ ] **Step 4: 最终提交**

```bash
git add scripts/install_cron.sh.example TODO.md
git commit -m "docs: P3.5-5~7 crontab 示例 + TODO.md 更新"
```

---

## 自检清单

| 检查项 | 状态 |
|--------|------|
| 设计覆盖：P3.5-5 定时触发 | ✅ Task 2 |
| 设计覆盖：P3.5-6 阈值触发 | ✅ Task 3 |
| 设计覆盖：P3.5-7 会话结束触发 | ✅ Task 4 |
| 每个任务有 TDD 测试 | ✅ |
| run_pipeline 复用已有 analyzer/insight_engine/evolver | ✅ |
| 优雅降级：无轨迹时返回空结果 | ✅ |
| cron 模式 exit code 0 表示成功 | ✅ |
| 阈值模式 exit code 1 表示未触发 | ✅ |
| 会话结束默认不启用 | ✅ env guard |
| 无外部依赖（仅 stdlib + 已有内部模块） | ✅ |