# 测试指南 (Testing Guide)

## 测试执行流程

```
功能代码实现完成
  ↓
主 agent 委托子 agent 运行全量测试套件
  ↓
子 agent 返回结果 → 主 agent 判断
  ↓
测试通过率 = 100%？ ─── 否 → 主 agent 定位 + 修复 → 重新委托
  ↓ 是
自审代码质量（类型安全 / 死代码 / 注释清理）
  ↓
主 agent 委托子 agent 运行性能基准
  ↓
提交并合并到 main
```

## 测试执行委托规则

**所有单元测试的执行必须委托给子 agent**，主 agent 不直接运行 pytest。规则如下：

1. **主 agent** 负责编写/修改测试代码，但**不执行**测试命令
2. **子 agent**（`task(category="quick")` 或 `task(subagent_type="deep")`）负责执行测试并返回结果
3. 主 agent 根据子 agent 返回的结果决定下一步（通过 → 提交；失败 → 修复后重新委托）
4. 测试执行的超时、重试、环境准备均由子 agent 管理

委托示例：
```python
task(
    category="quick",
    description="run argocd-insight tests",
    prompt="cd /Users/bohaiqing/opensource/git/argocd-skill/scripts && python3 -m pytest tests/ -v --tb=short 2>&1 | tail -50",
    run_in_background=False,
)
```

**例外**：单文件 < 5 行的 typo 修复可跳过委托，直接用 `lsp_diagnostics` 验证。

## 测试命令

```bash
# 推荐：从 scripts/ 目录运行（pytest 自动发现 tests/）
cd scripts/
python3 -m pytest tests/ -v

# 并行执行（需安装 pytest-xdist）
python3 -m pytest tests/ -v -n auto

# 仅运行新增/修改模块的测试
python3 -m pytest tests/test_<module>.py -v

# 带覆盖率（可选）
python3 -m pytest tests/ -v --cov=argocd_insight --cov-report=term-missing
```

## 测试质量标准

| 维度 | 要求 |
|---|---|
| **外部依赖** | 所有外部服务（ArgoCD API / K8s API / HTTP）必须通过 mock 隔离；禁止依赖 live 连接 |
| **临时目录** | 使用 pytest `tmp_path` fixture，禁止 `tempfile.mkdtemp()`（自动清理 + 线程安全） |
| **Mock 粒度** | mock 到具体模块路径（如 `unittest.mock.patch('argocd_insight.module.func')`），禁止过度 mock |
| **覆盖范围** | 每个公开函数至少 1 个正向 + 1 个异常/边界测试；CLI 入口必须测试 |
| **断言具体** | 禁止 `assert result`（无信息量）；使用 `assert result["key"] == expected_value` |
| **测试隔离** | 测试间无状态共享；fixture 作用域默认 `function`（除非明确需要 `session`） |

## Hypothesis 属性测试

对于具有确定性输入→输出映射的纯函数模块，**推荐**使用 [Hypothesis](https://hypothesis.readthedocs.io/) 进行属性测试：

| 适用模块 | 属性测试示例 |
|---|---|
| `parser.py` (4-tier 分类) | 输入任意 namespace + name → 输出固定 tier ∈ {root, root_entry, business, ops} |
| `mapper.py` (字段→flag 映射) | 输入任意 Kustomize 字段路径 → 输出对应的 CLI flag |
| `trend.py` (统计计算) | 输入任意 delta → pct_change == (last - first) / first × 100 |
| `report_composer.py` (截断) | 任意输入文本 → len(output) ≤ max_lines |

不适用场景：需要外部 IO、非纯函数、简单组合逻辑（如 `_summarize_module`）。

Hypothesis 用法示例：
```python
from hypothesis import given, strategies as st

@given(st.floats(min_value=0, max_value=1_000_000), st.floats(min_value=0, max_value=1_000_000))
def test_pct_change_property(first, last):
    result = compute_delta([make_snapshot(first), make_snapshot(last)], "metric")
    if first > 0:
        assert result["pct_change"] == pytest.approx((last - first) / first * 100)
```

## Explorer Testing 五轮法

单元测试验证"代码是否按设计工作"，Explorer Testing 验证"用户用自然语言驱动时，端到端流程是否跑通"。适用于集成测试、端到端验收、新功能上线前。

### 五轮流程

| 轮次 | 目标 | 方法 | 验证标准 |
|------|------|------|----------|
| R1 意图识别 | 自然语言 → intent → params | 用真实用户措辞测试 IntentClassifier | 意图正确、置信度 > 0.5 |
| R2 API 实时查询 | 认证 / CRUD 全链路 | subprocess 调用 argocd_api，只读操作 | exit code 0、JSON 可解析 |
| R3 诊断工具 | health / compliance / diagnose | 调用 insight 子命令，验证实时数据 | 返回具体数值（非空、非 error） |
| R4 端到端管线 | Snapshot → Trend → Compare → Report | 串联多个工具完成完整工作流 | 每步输出作为下一步输入，最终产出报告 |
| R5 边界条件 | 空输入 / 噪声 / 降级 / 错误处理 | 故意传入异常参数 | 优雅降级，不 crash |

### 执行要点

- **R1 用中文自然语言**，不要用英文关键词测试（目标用户是中文运维）
- **R2 只用只读操作**，不用 `sync` / `delete` / `create` 等变更操作
- **R3 的 `predict` 工具需要离线 JSON 文件**，不同设计于其他 live-query 工具——这是预期行为
- **R4 每步输出需 JSON 可解析**，否则管线中断
- **R5 空输入必须返回结构化错误**，不能返回 None 或抛异常

### 与单元测试的关系

```
单元测试 (pytest)          Explorer Testing
  ↓ 红绿重构                  ↓ 五轮法
  ↓ mock 隔离                 ↓ 真实 API / subprocess
  ↓ 验证代码逻辑               ↓ 验证用户流程
  ↓ 快速反馈 (< 10s)          ↓ 深度验证 (1-2 min)
```

两者互补，不可替代。

## 性能回归保护

测试套件的执行时间本身也是质量指标：

| 基线 | 阈值 |
|---|---|
| 97-YAML 全样本处理 | < 1s |
| 500-app 批量处理 | < 5s |
| 完整测试套件（pytest -v） | < 10s |

若测试时间显著增加，需检查是否有：
- 未 mock 的外部 IO
- 过大的测试数据 fixture
- 重复的 setup/teardown 开销
