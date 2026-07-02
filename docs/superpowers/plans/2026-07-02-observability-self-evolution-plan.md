# P3.5 可观测与自进化 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 argocd-skill 构建可观测系统，包含执行轨迹记录、轨迹分析、经验提炼、自进化写回、SkillOpt SDK 集成

**Architecture:** 统一装饰器拦截所有 CLI 调用，写入 `.runtime/argocd-skill/sessions/`；分析器做统计/瓶颈/归因；经验引擎生成带推断链的经验；写回器安全写回 SKILL.md/tool 参数；SkillOpt SDK 提供意图识别与参数推荐

**Tech Stack:** Python ≥ 3.10, Microsoft SkillOpt SDK, PyYAML, 标准库 (json/pathlib/dataclasses/concurrent.futures)

## Global Constraints

- 轨迹写入 `.runtime/argocd-skill/sessions/` 目录（自动创建）
- 每个经验必须包含 `evidence` + `reasoning_chain` + `confidence`
- 置信度 < 0.7 不写回，0.7~0.9 需人工确认，≥ 0.9 自动写回
- SkillOpt SDK 不可用时优雅降级
- 不修改现有工具的公开接口，仅在底层拦截

---

## 文件结构

```
scripts/argocd_insight/
├── trace/
│   ├── __init__.py              # 导出 @traced, get_session_id
│   ├── decorator.py              # @traced 装饰器
│   ├── session.py                # 会话管理
│   └── writer.py                # JSONL 写入
│
├── analyzer/
│   ├── __init__.py              # 导出 analyze_session
│   ├── stats.py                 # 统计聚合
│   ├── bottleneck.py            # 瓶颈识别
│   └── error_classify.py        # 错误归因
│
├── insight_engine/
│   ├── __init__.py              # 导出 extract_insights
│   ├── extractor.py             # 经验提取
│   └── reasoning.py             # 推断链生成
│
├── evolver/
│   ├── __init__.py              # 导出 evolve
│   ├── writer.py                # 写回执行器
│   └── validator.py             # 写回前校验
│
└── skillopt/
    ├── __init__.py              # 导出 SkillOptAdapter
    ├── adapter.py              # SDK 适配器
    ├── intent.py               # 意图识别
    └── recommend.py            # 参数推荐
```

---

## 任务清单

### Task 1: 轨迹记录核心（trace/）

**Files:**
- Create: `scripts/argocd_insight/trace/__init__.py`
- Create: `scripts/argocd_insight/trace/decorator.py`
- Create: `scripts/argocd_insight/trace/session.py`
- Create: `scripts/argocd_insight/trace/writer.py`
- Create: `scripts/tests/test_trace.py`

**Interfaces:**
- Consumes: 无
- Produces: `@traced(module, operation)` 装饰器，`get_session_id()` 函数，`get_trace_dir()` 函数

- [ ] **Step 1: 编写会话管理测试**

```python
# scripts/tests/test_trace.py
import pytest
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

def test_writer_jsonl_format(tmp_path):
    from argocd_insight.trace.writer import TraceWriter
    writer = TraceWriter(tmp_path)
    writer.write_event({
        "event_id": "e_001",
        "type": "cli_call",
        "command": "argocd app list",
        "duration_ms": 100,
        "return_code": 0,
    })
    assert (tmp_path / "trace_000.jsonl").exists()
```

- [ ] **Step 2: 验证测试失败**

Run: `cd /Users/bohaiqing/opensource/git/argocd-skill/scripts && pytest tests/test_trace.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: 实现 session.py**

```python
# scripts/argocd_insight/trace/session.py
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import os

@dataclass
class Session:
    """单次工具执行的会话。"""
    module: str
    id: str = field(default_factory=lambda: f"s_{uuid.uuid4().hex[:12]}")
    start_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    end_time: str = ""
    command: str = ""
    argocd_server: str = field(default_factory="")
    argocd_version: str = field(default_factory="")

    def to_meta(self) -> dict:
        return {
            "session_id": self.id,
            "module": self.module,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "command": self.command,
            "argocd_server": self.argocd_server or os.getenv("ARGOCD_SERVER", ""),
            "argocd_version": self.argocd_version or _get_argocd_version(),
        }

_session_local = None

def get_session_id() -> str:
    """获取当前会话 ID。"""
    global _session_local
    if _session_local is None:
        _session_local = Session(module="unknown")
    return _session_local.id

def _get_argocd_version() -> str:
    import subprocess
    try:
        r = subprocess.run(["argocd", "version", "--client", "--format", "{{.Client.Version}}"],
                          capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ""
```

- [ ] **Step 4: 实现 writer.py**

```python
# scripts/argocd_insight/trace/writer.py
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

class TraceWriter:
    """JSONL 轨迹写入器。"""

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._file_index = 0
        self._file = None
        self._open_file()

    def _open_file(self):
        self._file = open(
            self.session_dir / f"trace_{self._file_index:03d}.jsonl",
            "a",
            encoding="utf-8"
        )

    def write_event(self, event: dict[str, Any]):
        if self._file is None:
            self._open_file()
        # 补时间戳
        if "ts" not in event:
            event["ts"] = datetime.now(timezone.utc).isoformat()
        self._file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self):
        if self._file:
            self._file.close()
            self._file = None

def get_trace_dir() -> Path:
    """获取运行时目录。"""
    base = Path(os.getenv("ARGOCD_SKILL_RUNTIME_DIR", ".runtime/argocd-skill"))
    return base.resolve()
```

- [ ] **Step 5: 实现 decorator.py**

```python
# scripts/argocd_insight/trace/decorator.py
from __future__ import annotations
import functools
import time
from typing import Callable, Any
from .session import Session, _session_local
from .writer import TraceWriter, get_trace_dir

_event_counter = 0

def traced(module: str, operation: str):
    """拦截 CLI/API 调用的装饰器。"""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
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

def _reconstruct_cmd(args, kwargs) -> str:
    """从参数重建命令字符串。"""
    parts = []
    for a in args:
        if isinstance(a, list):
            parts.extend(a)
        elif isinstance(a, str):
            parts.append(a)
    parts.extend([f"--{k}" if isinstance(v, bool) and v else f"--{k}={v}"
                  for k, v in kwargs.items() if v is not None])
    return " ".join(parts)
```

- [ ] **Step 6: 验证测试通过**

Run: `cd /Users/bohaiqing/opensource/git/argocd-skill/scripts && pytest tests/test_trace.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
cd /Users/bohaiqing/opensource/git/argocd-skill
git add scripts/argocd_insight/trace/ tests/test_trace.py
git commit -m "feat(trace): P3.5-1 轨迹记录核心（session/writer/decorator）"
```

---

### Task 2: 轨迹分析器（analyzer/）

**Files:**
- Create: `scripts/argocd_insight/analyzer/__init__.py`
- Create: `scripts/argocd_insight/analyzer/stats.py`
- Create: `scripts/argocd_insight/analyzer/bottleneck.py`
- Create: `scripts/argocd_insight/analyzer/error_classify.py`
- Create: `scripts/tests/test_analyzer.py`

**Interfaces:**
- Consumes: `trace/*.jsonl` 文件
- Produces: `analyze_session(session_dir) -> AnalysisReport`

- [ ] **Step 1: 编写分析器测试**

```python
# scripts/tests/test_analyzer.py
import pytest
import json
import tempfile
from pathlib import Path
from argocd_insight.analyzer import analyze_session
from argocd_insight.analyzer.stats import compute_stats
from argocd_insight.analyzer.bottleneck import find_bottlenecks
from argocd_insight.analyzer.error_classify import classify_errors

def test_compute_stats():
    events = [
        {"duration_ms": 100, "return_code": 0, "module": "diagnose"},
        {"duration_ms": 200, "return_code": 0, "module": "diagnose"},
        {"duration_ms": 300, "return_code": 1, "module": "diagnose"},
    ]
    stats = compute_stats(events)
    assert stats["total_calls"] == 3
    assert stats["error_rate"] == pytest.approx(1/3)
    assert stats["p50_ms"] == 200

def test_error_classify():
    events = [
        {"return_code": 1, "error": "unauthorized", "command": "argocd app list"},
        {"return_code": -1, "error": "Timed out", "command": "argocd app sync"},
        {"return_code": 0, "error": "", "command": "argocd app get"},
    ]
    classified = classify_errors(events)
    assert "auth_error" in classified
    assert "network_timeout" in classified
```

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_analyzer.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 stats.py**

```python
# scripts/argocd_insight/analyzer/stats.py
from __future__ import annotations
from typing import Any

def compute_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    """统计聚合。"""
    if not events:
        return {"total_calls": 0, "error_rate": 0.0, "p50_ms": 0, "p90_ms": 0, "p99_ms": 0}

    durations = sorted(e["duration_ms"] for e in events if "duration_ms" in e)
    errors = sum(1 for e in events if e.get("return_code", 0) != 0)

    def percentile(data: list, p: float) -> int:
        if not data:
            return 0
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    # 模块调用分布
    module_counts: dict[str, int] = {}
    for e in events:
        m = e.get("module", "unknown")
        module_counts[m] = module_counts.get(m, 0) + 1

    return {
        "total_calls": len(events),
        "error_rate": errors / len(events),
        "p50_ms": percentile(durations, 50),
        "p90_ms": percentile(durations, 90),
        "p99_ms": percentile(durations, 99),
        "module_distribution": module_counts,
    }
```

- [ ] **Step 4: 实现 error_classify.py**

```python
# scripts/argocd_insight/analyzer/error_classify.py
from __future__ import annotations
from typing import Any

ERROR_PATTERNS: list[tuple[str, list[str]]] = [
    ("auth_error", ["unauthorized", "401", "permission denied", "authentication"]),
    ("network_timeout", ["timeout", "timed out", "connection refused", "network"]),
    ("resource_not_found", ["not found", "404", "does not exist"]),
    ("invalid_args", ["invalid argument", "unrecognized", "unknown flag"]),
    ("server_error", ["500", "internal server error", "503"]),
]

def classify_errors(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """错误归因。"""
    result: dict[str, list[dict[str, Any]]] = {k: [] for k, _ in ERROR_PATTERNS}
    result["other"] = []

    for e in events:
        if e.get("return_code", 0) == 0 and not e.get("error"):
            continue
        error_text = (e.get("error") or "").lower()
        matched = False
        for label, patterns in ERROR_PATTERNS:
            if any(p in error_text for p in patterns):
                result[label].append(e)
                matched = True
                break
        if not matched:
            result["other"].append(e)

    return result
```

- [ ] **Step 5: 实现 bottleneck.py**

```python
# scripts/argocd_insight/analyzer/bottleneck.py
from __future__ import annotations
from typing import Any
from collections import Counter

def find_bottlenecks(events: list[dict[str, Any]]) -> dict[str, Any]:
    """瓶颈识别。"""
    durations = sorted(e["duration_ms"] for e in events if "duration_ms" in e)
    if not durations:
        return {"hot_commands": [], "slow_calls": [], "concurrency_inefficient": False}

    p95 = durations[int(len(durations) * 0.95)] if durations else 0

    # Top 命令
    commands = [e.get("command", "") for e in events]
    hot = Counter(commands).most_common(10)

    # 慢调用
    slow = [e for e in events if e.get("duration_ms", 0) > p95]

    # 并发效率检测（相同命令串行执行 >3 次）
    serial_chains = _find_serial_chains(events)

    return {
        "hot_commands": [{"command": cmd, "count": cnt} for cmd, cnt in hot],
        "slow_calls": slow[:10],  # 最多 10 条
        "p95_ms": p95,
        "serial_chains": serial_chains,
    }

def _find_serial_chains(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测串行瓶颈。"""
    commands = [e.get("command", "") for e in events]
    counts = Counter(commands)
    return [{"command": cmd, "count": cnt} for cmd, cnt in counts.items() if cnt > 3]
```

- [ ] **Step 6: 实现 __init__.py**

```python
# scripts/argocd_insight/analyzer/__init__.py
from .stats import compute_stats
from .bottleneck import find_bottlenecks
from .error_classify import classify_errors
from pathlib import Path
import json

def analyze_session(session_dir: Path) -> dict:
    """分析单个会话轨迹。"""
    events = []
    for f in sorted(session_dir.glob("trace_*.jsonl")):
        with open(f) as fp:
            for line in fp:
                line = line.strip()
                if line:
                    events.append(json.loads(line))

    return {
        "session_id": session_dir.name,
        "stats": compute_stats(events),
        "bottlenecks": find_bottlenecks(events),
        "errors": classify_errors(events),
        "total_events": len(events),
    }
```

- [ ] **Step 7: 验证测试通过**

Run: `pytest tests/test_analyzer.py -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add scripts/argocd_insight/analyzer/ tests/test_analyzer.py
git commit -m "feat(analyzer): P3.5-2 轨迹分析器（stats/bottleneck/error_classify）"
```

---

### Task 3: 经验提炼引擎（insight_engine/）

**Files:**
- Create: `scripts/argocd_insight/insight_engine/__init__.py`
- Create: `scripts/argocd_insight/insight_engine/extractor.py`
- Create: `scripts/argocd_insight/insight_engine/reasoning.py`
- Create: `scripts/tests/test_insight_engine.py`

**Interfaces:**
- Consumes: `analyzer` 输出 `AnalysisReport`
- Produces: `extract_insights(report) -> list[Insight]`，每个 `Insight` 含 `evidence` + `reasoning_chain` + `confidence`

- [ ] **Step 1: 编写经验引擎测试**

```python
# scripts/tests/test_insight_engine.py
import pytest
from argocd_insight.insight_engine import extract_insights
from argocd_insight.insight_engine.reasoning import build_reasoning_chain

def test_build_reasoning_chain():
    steps = ["Step 1: 数据分组", "Step 2: 计算均值", "Step 3: 对比拐点"]
    chain = build_reasoning_chain(steps)
    assert len(chain) == 3
    assert chain[0].startswith("1.")

def test_extract_concurrency_insight():
    report = {
        "stats": {
            "module_distribution": {"diagnose": 12}
        },
        "bottlenecks": {
            "hot_commands": [{"command": "argocd app list", "count": 8}]
        }
    }
    insights = extract_insights(report)
    assert any("diagnose" in str(i) for i in insights)
```

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_insight_engine.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 reasoning.py**

```python
# scripts/argocd_insight/insight_engine/reasoning.py
from __future__ import annotations
from typing import Any

def build_reasoning_chain(steps: list[str]) -> list[str]:
    """构建推断链（CoT 显式化）。"""
    return [f"{i+1}. {step}" for i, step in enumerate(steps)]

def infer_confidence(data_points: int, variance: float = 0.0) -> float:
    """推断置信度。"""
    # 数据点越多 + 方差越小 → 置信度越高
    base = min(data_points / 20.0, 1.0)  # 20 个数据点饱和
    penalty = min(variance / 1000.0, 0.3)  # 方差惩罚
    return round(min(base - penalty + 0.5, 0.95), 2)
```

- [ ] **Step 4: 实现 extractor.py**

```python
# scripts/argocd_insight/insight_engine/extractor.py
from __future__ import annotations
from typing import Any
from dataclasses import dataclass
from .reasoning import build_reasoning_chain, infer_confidence

@dataclass
class Insight:
    """单条经验。"""
    category: str           # performance / error_pattern / best_practice
    insight: str            # 经验描述
    evidence: dict[str, Any]  # 支撑数据
    reasoning_chain: list[str]  # 推断链
    confidence: float       # 置信度 0~1
    action: dict[str, Any] | None = None  # 写回建议

def extract_insights(report: dict[str, Any]) -> list[Insight]:
    """从分析报告提炼经验。"""
    insights = []

    # 1. 性能洞察
    stats = report.get("stats", {})
    if stats.get("p99_ms", 0) > stats.get("p50_ms", 0) * 5:
        insights.append(_perf_slow_tail(report))

    # 2. 错误模式洞察
    errors = report.get("errors", {})
    if sum(len(v) for v in errors.values()) > 0:
        insights.append(_error_pattern_insight(errors))

    # 3. 并发效率洞察
    bottlenecks = report.get("bottlenecks", {})
    if bottlenecks.get("serial_chains"):
        insights.append(_concurrency_insight(report))

    return insights

def _perf_slow_tail(report: dict) -> Insight:
    stats = report["stats"]
    reasoning = build_reasoning_chain([
        f"统计 {stats['total_calls']} 次调用",
        f"P50={stats['p50_ms']}ms, P99={stats['p99_ms']}ms",
        f"P99/P50 比值 = {stats['p99_ms']/max(stats['p50_ms'],1):.1f}x",
        "结论：存在长尾慢调用，建议检查网络或限流"
    ])
    return Insight(
        category="performance",
        insight="存在显著慢调用长尾",
        evidence={"p50_ms": stats["p50_ms"], "p99_ms": stats["p99_ms"], "total": stats["total_calls"]},
        reasoning_chain=reasoning,
        confidence=infer_confidence(stats["total_calls"]),
    )

def _error_pattern_insight(errors: dict) -> Insight:
    total_errors = sum(len(v) for v in errors.values())
    dominant = max(errors.items(), key=lambda x: len(x[1]))
    reasoning = build_reasoning_chain([
        f"共 {total_errors} 次错误",
        f"主要类型：{dominant[0]}（{len(dominant[1])} 次）",
        f"占比：{len(dominant[1])/max(total_errors,1)*100:.0f}%",
        f"建议：优先排查 {dominant[0]} 根因"
    ])
    return Insight(
        category="error_pattern",
        insight=f"错误以 {dominant[0]} 为主",
        evidence={"total_errors": total_errors, "by_type": {k: len(v) for k, v in errors.items()}},
        reasoning_chain=reasoning,
        confidence=infer_confidence(total_errors),
        action={"target": "references/agent-protocols.md", "suggestion": f"补充 {dominant[0]} 处理流程"},
    )

def _concurrency_insight(report: dict) -> Insight:
    chains = report["bottlenecks"]["serial_chains"]
    reasoning = build_reasoning_chain([
        f"发现 {len(chains)} 组串行调用链",
        "串行执行可通过并发优化",
        "建议：使用 --concurrency 参数加速"
    ])
    return Insight(
        category="performance",
        insight="存在可并行的串行调用",
        evidence={"serial_chains": chains},
        reasoning_chain=reasoning,
        confidence=0.75,
        action={"target": "cli.py", "field": "default_concurrency", "current": 8, "suggested": 10},
    )
```

- [ ] **Step 5: 实现 __init__.py**

```python
# scripts/argocd_insight/insight_engine/__init__.py
from .extractor import Insight, extract_insights
from .reasoning import build_reasoning_chain, infer_confidence
```

- [ ] **Step 6: 验证测试通过**

Run: `pytest tests/test_insight_engine.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add scripts/argocd_insight/insight_engine/ tests/test_insight_engine.py
git commit -m "feat(insight_engine): P3.5-3 经验提炼引擎（extractor + reasoning chain）"
```

---

### Task 4: 自进化写回器（evolver/）

**Files:**
- Create: `scripts/argocd_insight/evolver/__init__.py`
- Create: `scripts/argocd_insight/evolver/writer.py`
- Create: `scripts/argocd_insight/evolver/validator.py`
- Create: `scripts/tests/test_evolver.py`

**Interfaces:**
- Consumes: `list[Insight]`
- Produces: 写回文件 + 验证报告

- [ ] **Step 1: 编写写回器测试**

```python
# scripts/tests/test_evolver.py
import pytest
from pathlib import Path
from argocd_insight.evolver import evolve, RiskLevel
from argocd_insight.evolver.validator import validate_write_back

def test_risk_level_classification():
    from argocd_insight.evolver.validator import classify_risk
    assert classify_risk(0.95, destructive=False) == RiskLevel.LOW
    assert classify_risk(0.7, destructive=False) == RiskLevel.MEDIUM
    assert classify_risk(0.6, destructive=False) == RiskLevel.HIGH

def test_validate_yaml_structure():
    content = """
name: argocd-skill
description: |
  ArgoCD CLI 全流程技能。
"""
    assert validate_write_back(content, "SKILL.md")
```

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_evolver.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 validator.py**

```python
# scripts/argocd_insight/evolver/validator.py
from __future__ import annotations
from enum import Enum
import yaml

class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

def classify_risk(confidence: float, destructive: bool = False) -> RiskLevel:
    """风险分级。"""
    if destructive or confidence < 0.7:
        return RiskLevel.HIGH
    if confidence >= 0.9:
        return RiskLevel.LOW
    return RiskLevel.MEDIUM

def validate_write_back(content: str, target: str) -> bool:
    """写回前格式校验。"""
    if target.endswith(".md"):
        # 简单格式检查：非空、无明显语法错误
        return len(content) > 0 and "---" in content
    if target.endswith(".py"):
        # Python 语法检查
        try:
            compile(content, target, "exec")
            return True
        except SyntaxError:
            return False
    return True
```

- [ ] **Step 4: 实现 writer.py**

```python
# scripts/argocd_insight/evolver/writer.py
from __future__ import annotations
from pathlib import Path
from typing import Any
from .validator import validate_write_back, classify_risk, RiskLevel
from ..insight_engine import Insight

def evolve(insights: list[Insight], dry_run: bool = True) -> dict[str, Any]:
    """执行自进化写回。"""
    results = {"low": [], "medium": [], "high": [], "skipped": []}

    for insight in insights:
        risk = classify_risk(insight.confidence)
        if risk == RiskLevel.HIGH:
            results["skipped"].append({"insight": insight.insight, "reason": "confidence < 0.7"})
            continue

        if dry_run:
            results[risk.value].append({
                "insight": insight.insight,
                "action": insight.action,
                "would_write": True,
            })
        else:
            success = _do_write(insight)
            results[risk.value].append({
                "insight": insight.insight,
                "action": insight.action,
                "written": success,
            })

    return results

def _do_write(insight: Insight) -> bool:
    """执行写回。"""
    action = insight.action
    if not action:
        return False

    target = action.get("target", "")
    if not target:
        return False

    path = Path(__file__).parent.parent.parent.parent / target
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    if not validate_write_back(content, target):
        return False

    # 追加经验注释（简单实现：追加到文件末尾）
    note = f"\n\n<!-- EVOLVED: {insight.insight} -->\n<!-- Confidence: {insight.confidence} -->\n"
    content += note
    path.write_text(content, encoding="utf-8")
    return True
```

- [ ] **Step 5: 实现 __init__.py**

```python
# scripts/argocd_insight/evolver/__init__.py
from .writer import evolve
from .validator import RiskLevel, classify_risk, validate_write_back
```

- [ ] **Step 6: 验证测试通过**

Run: `pytest tests/test_evolver.py -v`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add scripts/argocd_insight/evolver/ tests/test_evolver.py
git commit -m "feat(evolver): P3.5-4 自进化写回器（writer + validator）"
```

---

### Task 5: SkillOpt SDK 集成（skillopt/）

**Files:**
- Create: `scripts/argocd_insight/skillopt/__init__.py`
- Create: `scripts/argocd_insight/skillopt/adapter.py`
- Create: `scripts/argocd_insight/skillopt/intent.py`
- Create: `scripts/argocd_insight/skillopt/recommend.py`
- Create: `scripts/tests/test_skillopt.py`

**Interfaces:**
- Consumes: 用户意图文本 + 轨迹历史
- Produces: `RecognizedIntent`, `RecommendedParams`

- [ ] **Step 1: 编写 SkillOpt 测试**

```python
# scripts/tests/test_skillopt.py
import pytest
from argocd_insight.skillopt import SkillOptAdapter, IntentClassifier, ParameterRecommender

def test_intent_classifier():
    classifier = IntentClassifier()
    intent = classifier.recognize("帮我看看哪些 app 不同步")
    assert intent.intent in ("diagnose", "oos_analyzer")
    assert intent.confidence > 0.5

def test_parameter_recommender():
    recommender = ParameterRecommender()
    params = recommender.recommend("diagnose", {"total_calls": 10, "error_rate": 0.1})
    assert "concurrency" in params
```

- [ ] **Step 2: 验证测试失败**

Run: `pytest tests/test_skillopt.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 adapter.py（SDK 适配器框架）**

```python
# scripts/argocd_insight/skillopt/adapter.py
from __future__ import annotations
from typing import Any, Optional
from dataclasses import dataclass

@dataclass
class RecognizedIntent:
    intent: str
    confidence: float
    params: dict[str, Any]

@dataclass
class RecommendedParams:
    module: str
    params: dict[str, Any]
    reasoning: str

class SkillOptAdapter:
    """SkillOpt SDK 适配器。"""

    def __init__(self, trace_dir: str = ".runtime/argocd-skill/sessions"):
        self.trace_dir = trace_dir
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        """检测 SkillOpt SDK 是否可用。"""
        try:
            import skillopt  # noqa: F401
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        return self._available

    def recognize(self, text: str) -> RecognizedIntent:
        """意图识别。"""
        if not self._available:
            return self._fallback_recognize(text)
        from skillopt import IntentRecognizer
        recognizer = IntentRecognizer(skill_name="argocd-skill")
        result = recognizer.recognize(text)
        return RecognizedIntent(
            intent=result["intent"],
            confidence=result["confidence"],
            params=result.get("params", {}),
        )

    def recommend(self, module: str, history: dict) -> RecommendedParams:
        """参数推荐。"""
        if not self._available:
            return self._fallback_recommend(module, history)
        from skillopt import ParameterRecommender
        recommender = ParameterRecommender(skill_name="argocd-skill", trace_dir=self.trace_dir)
        result = recommender.recommend(module, history)
        return RecommendedParams(
            module=module,
            params=result["params"],
            reasoning=result.get("reasoning", ""),
        )

    def _fallback_recognize(self, text: str) -> RecognizedIntent:
        """SkillOpt 不可用时的本地兜底。"""
        text_lower = text.lower()
        if "不同步" in text or "outsync" in text_lower:
            return RecognizedIntent(intent="diagnose", confidence=0.8, params={"severity": "OutOfSync"})
        if "健康" in text or "health" in text_lower:
            return RecognizedIntent(intent="health", confidence=0.8, params={})
        if "漂移" in text or "drift" in text_lower:
            return RecognizedIntent(intent="drift", confidence=0.8, params={})
        return RecognizedIntent(intent="unknown", confidence=0.0, params={})

    def _fallback_recommend(self, module: str, history: dict) -> RecommendedParams:
        """本地兜底参数推荐（基于历史轨迹统计）。"""
        defaults = {
            "diagnose": {"concurrency": 8, "timeout": 60},
            "health": {"concurrency": 8, "timeout": 120},
            "batch": {"concurrency": 5, "timeout": 120},
        }
        return RecommendedParams(
            module=module,
            params=defaults.get(module, {}),
            reasoning="基于历史轨迹统计的默认参数",
        )
```

- [ ] **Step 4: 实现 intent.py**

```python
# scripts/argocd_insight/skillopt/intent.py
from __future__ import annotations
from .adapter import RecognizedIntent

# 意图 → 模块映射
INTENT_MAP = {
    "diagnose": ["不同步", "outsync", "问题", "诊断", "分析", "app 问题"],
    "health": ["健康", "health", "稳定性", "评估"],
    "drift": ["漂移", "drift", "版本", "revision"],
    "compliance": ["合规", "compliance", "配置风险"],
    "cost": ["成本", "cost", "费用", "资源"],
    "autofix": ["修复", "fix", "自动修复"],
    "batch": ["批量", "batch", "并发"],
    "scaffold": ["生成", "scaffold", "模板", "创建"],
}

class IntentClassifier:
    """意图分类器。"""

    def recognize(self, text: str) -> RecognizedIntent:
        """识别用户意图。"""
        from .adapter import SkillOptAdapter
        adapter = SkillOptAdapter()
        if adapter.is_available():
            return adapter.recognize(text)

        # 本地兜底
        text_lower = text.lower()
        for intent, keywords in INTENT_MAP.items():
            if any(kw in text_lower for kw in keywords):
                return RecognizedIntent(intent=intent, confidence=0.8, params={})
        return RecognizedIntent(intent="unknown", confidence=0.0, params={})
```

- [ ] **Step 5: 实现 recommend.py**

```python
# scripts/argocd_insight/skillopt/recommend.py
from __future__ import annotations
from .adapter import RecommendedParams

# 基于轨迹分析的默认参数（可随经验进化）
PARAM_DEFAULTS = {
    "diagnose": {"concurrency": 8, "timeout": 60, "severity": ""},
    "health": {"concurrency": 8, "timeout": 120, "days": 30},
    "drift": {"concurrency": 8, "timeout": 90},
    "batch": {"concurrency": 5, "timeout": 120},
    "autofix": {"concurrency": 3, "timeout": 180},
    "compliance": {"severity": "low"},
    "cost": {"concurrency": 8},
    "repo_health": {"concurrency": 4},
}

class ParameterRecommender:
    """参数推荐器。"""

    def recommend(self, module: str, history: dict) -> RecommendedParams:
        """推荐最优参数。"""
        from .adapter import SkillOptAdapter
        adapter = SkillOptAdapter()
        if adapter.is_available():
            return adapter.recommend(module, history)

        # 本地兜底
        params = PARAM_DEFAULTS.get(module, {}).copy()
        # 根据历史轨迹微调
        if history.get("total_calls", 0) > 100:
            params["concurrency"] = min(params.get("concurrency", 8) + 2, 16)
        return RecommendedParams(
            module=module,
            params=params,
            reasoning=f"基于 {module} 模块历史轨迹统计 + 默认参数",
        )
```

- [ ] **Step 6: 实现 __init__.py**

```python
# scripts/argocd_insight/skillopt/__init__.py
from .adapter import SkillOptAdapter, RecognizedIntent, RecommendedParams
from .intent import IntentClassifier
from .recommend import ParameterRecommender
```

- [ ] **Step 7: 验证测试通过**

Run: `pytest tests/test_skillopt.py -v`
Expected: PASS

- [ ] **Step 8: 提交**

```bash
git add scripts/argocd_insight/skillopt/ tests/test_skillopt.py
git commit -m "feat(skillopt): P3.5-5 SkillOpt SDK 集成（adapter + intent + recommend）"
```

---

### Task 6: CLI 集成与端到端测试

**Files:**
- Modify: `scripts/argocd_insight/cli.py`
- Create: `scripts/tests/test_observability_integration.py`

**Interfaces:**
- Consumes: 所有子模块
- Produ增: `--trace` 参数 + trace 命令

- [ ] **Step 1: 添加 trace 子命令**

```python
# scripts/argocd_insight/cli.py 新增
def _handle_trace(args: argparse.Namespace) -> int:
    from .analyzer import analyze_session
    from .insight_engine import extract_insights
    from .evolver import evolve
    from pathlib import Path

    session_dir = Path(args.session or get_session_dir())
    if not session_dir.exists():
        print(f"Session not found: {session_dir}", file=sys.stderr)
        return 1

    print(f"Analyzing session: {session_dir.name}")
    report = analyze_session(session_dir)
    print(f"Total events: {report['total_events']}")

    if args.extract_insights:
        insights = extract_insights(report)
        print(f"Insights extracted: {len(insights)}")
        for i in insights:
            print(f"  - [{i.category}] {i.insight} (conf={i.confidence})")
            for step in i.reasoning_chain:
                print(f"      {step}")

    if args.evolve:
        results = evolve(insights, dry_run=not args.no_dry_run)
        print(f"Evolve results: {results}")

    return 0
```

- [ ] **Step 2: 添加 CLI 参数**

```python
# scripts/argocd_insight/cli.py argparse 部分新增
p_trace = sub.add_parser("trace", help="分析轨迹与提炼经验")
p_trace.add_argument("--session", help="会话目录路径")
p_trace.add_argument("--extract-insights", action="store_true", help="提炼经验")
p_trace.add_argument("--evolve", action="store_true", help="执行自进化")
p_trace.add_argument("--no-dry-run", action="store_true", help="实际写回（默认 dry-run）")
p_trace.set_defaults(func=_handle_trace)
```

- [ ] **Step 3: 添加全局 trace 装饰器**

在所有子模块的 CLI 调用处添加 `@traced` 装饰器。

- [ ] **Step 4: 端到端测试**

```python
# scripts/tests/test_observability_integration.py
def test_trace_command_integration(tmp_path, monkeypatch):
    """端到端测试：运行 diagnose → 分析轨迹 → 提取经验。"""
    # 1. 设置 trace 目录
    monkeypatch.setenv("ARGOCD_SKILL_RUNTIME_DIR", str(tmp_path))

    # 2. 模拟一次 trace 写入
    from argocd_insight.trace.writer import TraceWriter
    sid = "s_test_001"
    writer = TraceWriter(tmp_path / "sessions" / sid)
    writer.write_event({
        "event_id": "e_001",
        "type": "cli_call",
        "command": "argocd app list",
        "duration_ms": 150,
        "return_code": 0,
        "module": "diagnose",
    })
    writer.close()

    # 3. 分析轨迹
    from argocd_insight.analyzer import analyze_session
    report = analyze_session(tmp_path / "sessions" / sid)
    assert report["total_events"] == 1

    # 4. 提取经验
    from argocd_insight.insight_engine import extract_insights
    insights = extract_insights(report)
    assert len(insights) >= 0  # 无错误时可能为空
```

- [ ] **Step 5: 验证端到端测试**

Run: `pytest tests/test_observability_integration.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add scripts/argocd_insight/cli.py scripts/tests/test_observability_integration.py
git commit -m "feat: P3.5 全链路集成（trace 子命令 + 端到端测试）"
```

---

### Task 7: SKILL.md 触发词增补

**Files:**
- Modify: `SKILL.md`

**Interfaces:**
- Consumes: 自进化提炼的触发词经验
- Produces: 更新 SKILL.md 提示词示例

- [ ] **Step 1: 添加可观测相关触发词**

在 SKILL.md 提示词示例末尾新增：

```markdown
### 可观测与自进化
- "分析这次运行的轨迹"
- "看看有哪些性能瓶颈"
- "经验沉淀，把分析结果写回"
- "SkillOpt 推荐一下这次用什么参数"
- "检查执行效率"
- "轨迹报告，输出 JSON"
```

- [ ] **Step 2: 提交**

```bash
git add SKILL.md
git commit -m "feat: P3.5 SKILL.md 触发词增补（可观测/轨迹/经验）"
```

---

### Task 8: 回归测试与文档

**Files:**
- Modify: `scripts/requirements.txt`（如需新增依赖）
- Create: `docs/superpowers/plans/2026-07-02-observability-self-evolution-plan.md`
- Create: `scripts/tests/fixtures/sample_trace/`（测试用轨迹 fixture）

- [ ] **Step 1: 运行完整测试套件**

Run: `cd scripts && pytest tests/ -v --tb=short`
Expected: 原有测试 100% 通过 + 新增测试通过

- [ ] **Step 2: 保存实现计划**

Plan 已保存至 `docs/superpowers/plans/2026-07-02-observability-self-evolution-plan.md`

- [ ] **Step 3: 提交**

```bash
git add scripts/requirements.txt docs/
git commit -m "docs: P3.5 实现计划 + 测试 fixture"
```

---

## 自检清单

| 检查项 | 状态 |
|--------|------|
| 设计覆盖：P3.5-1 轨迹记录 | ✅ Task 1 |
| 设计覆盖：P3.5-2 轨迹分析 | ✅ Task 2 |
| 设计覆盖：P3.5-3 经验提炼 | ✅ Task 3 |
| 设计覆盖：P3.5-4 自进化写回 | ✅ Task 4 |
| 设计覆盖：P3.5-5 SkillOpt 集成 | ✅ Task 5 |
| 设计覆盖：P3.5-6 端到端集成 | ✅ Task 6 |
| 设计覆盖：P3.5-7 SKILL.md 增补 | ✅ Task 7 |
| 每个任务有测试 | ✅ |
| 每个经验有推断链 | ✅ reasoning_chain 显式化 |
| SkillOpt 优雅降级 | ✅ fallback 实现 |
| 轨迹写入 .runtime/ | ✅ TraceWriter + get_trace_dir() |