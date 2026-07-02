# P3.5 可观测与自进化 — 设计文档

**版本：** v0.5.0
**日期：** 2026-07-02
**状态：** 设计中

---

## 一、目标

为 argocd-skill 构建完整的可观测系统，包含：
1. **执行轨迹记录**：所有 CLI/API 调用写入 `.runtime/argocd-skill/sessions/`
2. **轨迹分析**：统计、瓶颈识别、错误归因
3. **经验沉淀**：从轨迹提炼经验，带自解释推断链
4. **自进化**：经验写回 SKILL.md / references / tool 参数
5. **SkillOpt 集成**：本地 SDK 接入，增强意图识别与参数推断

---

## 二、整体架构

### 2.1 数据流程图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              在线流程（实时）                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   用户操作 ──→ @traced 装饰器 ──→ trace_*.jsonl                             │
│                              (会话目录)                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                              离线流程（事后）                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   trace_*.jsonl ──→ analyzer/ ──→ insight_engine/ ──→ evolver/ ──→ 写回    │
│        │              │              │                  │                   │
│        │              │              │                  │                   │
│        ▼              ▼              ▼                  ▼                   │
│   会话结束后       统计/瓶颈/      经验提炼+         风险分级                │
│   手动/定时触发    错误归因        推断链生成        → SKILL.md              │
│                                                     → references/           │
│                                                     → cli.py 参数            │
│                                                                             │
│   skillopt/ ← 基于历史轨迹学习，增强意图识别与参数推荐（可离线独立运行）        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

```
python -m argocd_insight <command>
         │
         ├── trace/              # 统一拦截层（装饰器）
         │       └── .runtime/argocd-skill/sessions/{session_id}/trace_{ts}.jsonl
         │
         ├── analyzer/           # 轨迹分析器
         │       └── stats.py    # 统计聚合
         │       └── bottleneck.py # 瓶颈识别
         │       └── error_classify.py # 错误归因
         │
         ├── insight_engine/     # 经验提炼引擎
         │       └── extractor.py # 从分析结果提炼经验
         │       └── reasoning.py # 推断链生成（CoT 显式化）
         │
         ├── evolver/            # 自进化写回器
         │       └── writer.py   # 写回 SKILL.md / references / tool
         │       └── validator.py # 写回前校验
         │
         └── skillopt/           # SkillOpt SDK 集成
                 └── adapter.py  # SDK 适配器
                 └── intent.py   # 意图识别
                 └── recommend.py # 参数推荐
```

---

## 三、执行时机

### 3.1 在线流程（实时）

**触发时机**：用户每次操作时自动执行，无需手动干预。

- `@traced` 装饰器拦截所有 CLI/API 调用
- 轨迹写入当前会话目录 `.runtime/argocd-skill/sessions/{session_id}/`

### 3.2 离线流程（事后）

**触发时机**（三种方式，按需选择）：

| 触发方式 | 命令 | 说明 |
|---------|------|------|
| 手动触发 | `python -m argocd_insight analyze --session <id>` | 分析指定会话 |
| 定时触发 | `python -m argocd_insight analyze --all --since 7d` | 每天/每周定时分析 |
| 单会话结束 | 会话结束时自动分析当前会话 | 可选配置 |

**离线流程内部顺序**：

```
analyzer/（统计/瓶颈/归因）
    ↓
insight_engine/（经验提炼 + 推断链）
    ↓
evolver/（置信度检查 → 风险分级 → 写回）
```

**SkillOpt 独立运行**：SkillOpt 可在离线流程之外独立执行，基于全量历史轨迹重新训练或推理推荐，不需要等待特定会话结束。

---

## 四、轨迹记录（Trace）

### 3.1 统一装饰器

```python
from argocd_insight.trace import traced, get_session_id

@traced(module="diagnose", operation="list_apps")
def list_apps(project: str, concurrency: int) -> list[dict]:
    ...
```

### 3.2 轨迹文件结构

```
.runtime/argocd-skill/
└── sessions/
    └── s_20260702_abc123/
        ├── meta.json           # 会话元信息
        │   ├── session_id, start_time, end_time
        │   ├── command, module
        │   └── argocd_server, argocd_version
        ├── trace_000.jsonl     # 调用轨迹（每行一条）
        └── report.json         # 本次会话分析报告
```

### 3.3 轨迹事件格式（JSONL）

```json
{
  "event_id": "e_001",
  "type": "cli_call",
  "command": "argocd app list --project default --output json",
  "args": ["app", "list", "--project", "default", "--output", "json"],
  "start": "2026-07-02T10:00:00.123Z",
  "end": "2026-07-02T10:00:00.456Z",
  "duration_ms": 333,
  "return_code": 0,
  "stdout_size": 4096,
  "stderr": "",
  "context": {
    "module": "diagnose",
    "phase": "list_apps",
    "concurrency": 8
  }
}
```

### 3.4 上下文变量（复用规则）

| 变量 | 来源 | 复用范围 |
|---|---|---|
| `app_name` | 用户首次提供 | 同一会话后续命令 |
| `namespace` | 首次 `app create` | 同一会话 |
| `project` | 首次 `--project` | 同一会话 |
| `repo_url` | 首次 `--repo` | 同一会话 |

---

## 五、轨迹分析（Analyzer）

### 4.1 统计聚合（stats.py）

- **CLI 调用频率**：每类命令的调用次数、占比
- **耗时分布**：P50/P90/P99 平均耗时
- **错误率**：按 return_code、stderr 关键词聚合
- **并发效率**：不同 concurrency 下的吞吐量对比

### 4.2 瓶颈识别（bottleneck.py）

- **热点命令**：调用次数最多的 Top 10 CLI 命令
- **慢调用**：单次耗时 > P95 的调用
- **串行瓶颈**：可并行但被串行执行的调用链
- **API 限流**：连续 429 响应检测

### 4.3 错误归因（error_classify.py）

| 错误类型 | 判断规则 | 归因标签 |
|---------|---------|---------|
| 认证失败 | stderr 含 `unauthorized` / `401` | `auth_error` |
| 网络超时 | return_code=-1 / stderr 含 `timeout` | `network_timeout` |
| 资源不存在 | return_code=1 + stderr 含 `not found` | `resource_not_found` |
| 参数错误 | stderr 含 `invalid argument` | `invalid_args` |
| 服务端错误 | stderr 含 `500` / `Internal server error` | `server_error` |

---

## 六、经验提炼（Insight Engine）

### 5.1 核心原则：自解释推断链

**每个经验必须包含：**
1. `evidence`：支撑结论的原始数据（轨迹 ID、数据点数量、具体数值）
2. `reasoning_chain`：推断步骤列表，每步可独立验证
3. `confidence`：置信度（0~1），基于数据量与一致性

### 5.2 推断链示例

```python
{
  "insight": "diagnose 模块默认并发度 8 接近最优",
  "evidence": {
    "data_points": 12,
    "sessions": ["s_xxx", "s_yyy", ...],
    "avg_duration_ms": {
      "concurrency_2": 892,
      "concurrency_8": 234,
      "concurrency_16": 301
    }
  },
  "reasoning_chain": [
    "Step 1: 筛选 12 次 diagnose 运行记录，按 concurrency 分组",
    "Step 2: 计算每组平均耗时并对比",
    "Step 3: 并发 8 时耗时最短（234ms），16 时因竞争退化（301ms）",
    "Step 4: 结论：并发 8 为拐点，建议保留当前值或微调至 10"
  ],
  "confidence": 0.85,
  "action": {
    "target": "scripts/argocd_insight/cli.py",
    "field": "default_concurrency",
    "current": 8,
    "suggested": 8
  }
}
```

### 5.3 经验类型

| 类型 | 触发条件 | 写回目标 |
|------|---------|---------|
| 性能优化 | 某参数多次影响耗时 | `cli.py` 默认参数 |
| 错误模式 | 某类错误重复出现 | `references/agent-protocols.md` |
| 最佳实践 | 某操作方式成功率更高 | `references/cli-commands.md` |
| 新触发词 | 用户意图与执行结果映射 | `SKILL.md` 提示词示例 |

---

## 七、自进化写回（Evolver）

### 6.1 写回类型

| 类型 | 目标文件 | 验证要求 |
|------|---------|---------|
| 参数调优 | `cli.py` 的 `default_concurrency` 等 | 回归测试通过 |
| 协议补充 | `references/agent-protocols.md` | Agent 重新读取并验证 |
| 触发词增补 | `SKILL.md` 提示词示例 | 人工确认 |
| 最佳实践 | `references/cli-commands.md` | 专家确认 |

### 6.2 写回流程

```
经验生成 → 置信度检查（≥0.7 才写回）→ 人工确认（高风险）→ 写回 → 回归测试
```

### 6.3 风险分级

| 级别 | 条件 | 处理方式 |
|------|------|---------|
| Low | 置信度 ≥ 0.9，无破坏性变更 | 自动写回 + 日志记录 |
| Medium | 置信度 0.7~0.9 | 通知用户确认后写回 |
| High | 置信度 < 0.7 或有破坏性变更 | 仅记录，不写回 |

---

## 八、SkillOpt SDK 集成

### 7.1 集成目标

通过 Microsoft SkillOpt SDK 本地运行，增强：
- **意图识别**：理解用户模糊描述，映射到具体命令
- **参数推荐**：基于历史轨迹推荐最优参数
- **异常预测**：提前预警可能的错误

### 7.2 集成方式

```python
from skillopt import SkillOpt, IntentClassifier, ParameterRecommender

skillopt = SkillOpt(
    skill_name="argocd-skill",
    trace_dir=".runtime/argocd-skill/sessions",
    model="local"
)

# 意图识别
intent = skillopt.recognize("帮我看看有哪些 app 不同步")
# → {"intent": "diagnose", "confidence": 0.92, "params": {"severity": "OutOfSync"}}

# 参数推荐
params = skillopt.recommend("diagnose", history_trace)
# → {"concurrency": 10, "timeout": 60, "severity": "high"}
```

### 7.3 数据接口

SkillOpt SDK 需要：
- 训练数据：`.runtime/argocd-skill/sessions/` 轨迹文件
- 推理输入：用户意图文本 / 历史轨迹
- 推理输出：意图分类 / 参数推荐 / 异常预测

---

## 九、文件清单

```
argocd-skill/
├── .runtime/argocd-skill/          # 运行时目录（自动创建）
│   └── sessions/
│       └── {session_id}/
│           ├── meta.json
│           ├── trace_*.jsonl
│           └── report.json
│
├── scripts/argocd_insight/
│   ├── trace/                      # 新增：轨迹记录模块
│   │   ├── __init__.py
│   │   ├── decorator.py            # @traced 装饰器
│   │   ├── session.py              # 会话管理
│   │   └── writer.py               # JSONL 写入
│   │
│   ├── analyzer/                   # 新增：轨迹分析模块
│   │   ├── __init__.py
│   │   ├── stats.py                # 统计聚合
│   │   ├── bottleneck.py           # 瓶颈识别
│   │   └── error_classify.py       # 错误归因
│   │
│   ├── insight_engine/             # 新增：经验提炼模块
│   │   ├── __init__.py
│   │   ├── extractor.py            # 经验提取
│   │   └── reasoning.py            # 推断链生成
│   │
│   ├── evolver/                    # 新增：自进化模块
│   │   ├── __init__.py
│   │   ├── writer.py               # 写回执行器
│   │   └── validator.py            # 写回前校验
│   │
│   └── skillopt/                   # 新增：SkillOpt 集成
│       ├── __init__.py
│       ├── adapter.py              # SDK 适配器
│       ├── intent.py               # 意图识别
│       └── recommend.py            # 参数推荐
│
├── docs/superpowers/specs/
│   └── 2026-07-02-observability-self-evolution-design.md
│
├── SKILL.md                        # 触发词可能增补
└── TODO.md                         # P3.5 已列入
```

---

## 十、测试策略

| 模块 | 测试方式 | 覆盖率目标 |
|------|---------|-----------|
| trace | 单元测试：装饰器拦截正确 | 90% |
| analyzer | 集成测试：使用 fixture 轨迹数据 | 85% |
| insight_engine | 属性测试：推断链完整性 | 80% |
| evolver | 集成测试：写回后 SKILL.md 格式正确 | 100% |
| skillopt | 集成测试：SDK 适配器正确调用 | 90% |

---

## 十一、依赖

- Python ≥ 3.10
- Microsoft SkillOpt SDK（待确认版本）
- PyYAML（写回 SKILL.md 时需要）
- 标准库：json, pathlib, dataclasses, concurrent.futures

---

## 十二、风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 轨迹数据量大 | 定期归档 + 压缩，按 session 打包 |
| 写回破坏 SKILL.md | 写回前备份 + 格式校验 |
| SkillOpt SDK 不可用 | 优雅降级：关闭 SkillOpt，本地经验引擎继续工作 |
| 推断链质量差 | 置信度门槛 0.7，高风险项人工确认 |