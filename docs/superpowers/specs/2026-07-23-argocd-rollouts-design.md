# 设计文档：在 argocd-skill 中并入 ArgoCD Rollouts 能力

- 日期：2026-07-23
- 状态：已批准（用户认可方案）
- 关联 skill：argocd-skill（仓库根目录单 skill）
- 关联工具：argocd_insight（诊断框架复用）

## 1. 背景与目标

当前 `argocd-skill` 只覆盖核心 ArgoCD（Application、AppProject、ApplicationSet、
syncPolicy、CLI、HTTP API、insight 诊断）。ArgoCD Rollouts 是 Argo 生态中负责
**渐进式交付**的平行项目（`Rollout` CRD + `kubectl argo rollouts` CLI），与
Application 是两套独立资源。

本设计在**不拆分单 skill 结构**的前提下，为现有 skill 增加 Rollouts 维度：

1. 文档 runbook：Rollout 字段→CLI 映射、常用命令、Canary/BlueGreen/Analysis 配置示例。
2. 诊断工具：并入 `argocd_insight`，提供 rollout 状态诊断 + Analysis 失败归因。

## 2. 范围（已与用户确认）

| 决策点 | 结论 |
|---|---|
| 是否独立新 skill | 否，并入现有 argocd-skill |
| 内容形态 | 文档 runbook + 诊断工具 |
| 诊断覆盖 | 状态诊断 + Analysis 失败归因（仅运行态，需集群访问） |
| 工具位置 | 并入 `argocd_insight`（不新建独立包） |

## 3. 不做的事（YAGNI）

- 不写 Rollout YAML→CLI 的【批量 Python 转换器】（命令生成走文档 + 现有模式）。
- 不做本地 YAML dry-run 校验（用户明确选择纯运行态诊断）。
- 不引入 nested skill 布局，不迁移现有 skill。
- 不新增凭证类型，沿用 `ARGOCD_*` + `kubectl` 上下文。

## 4. 架构与文件变更

### 4.1 SKILL.md

- frontmatter `description` 追加 Rollouts 触发短语（中英双语，保持 ≤1024 字符约束）。
- 新增「能力 N：ArgoCD Rollouts」章节，链接到 `references/argocd-rollouts-guide.md`
  与 `python -m argocd_insight rollouts ...`。
- 「常见错误」表追加至少 1 行 Rollouts 专属失败模式（如 Rollout 与 Deployment
  controller 冲突、`setCanaryScale` 误用、Analysis 卡点无 progression 超时）。

### 4.2 新增 references/argocd-rollouts-guide.md

- Rollout 核心概念：与 Deployment/Application 的关系。
- 字段→CLI 映射表（`kubectl argo rollouts`）：
  `get / list / abort / promote / restart / undo / set image / pause / resume`
- 三种策略配置示例：Canary（steps/setWeight/analysis）、BlueGreen（preview/previewReplicaCount/autoPromotionSeconds）、Analysis（template/inline）。
- AnalysisRun 失败归因思路（对应诊断工具输出）。
- 用户友好错误提示（与 SKILL.md 错误表、AGENTS.md 提示规范一致，引用附录而非硬编码）。

### 4.3 references/argocd-prompts.md

- 追加 Rollouts 触发短语分组（命令生成 / 诊断），与 SKILL.md `description` 同步。

### 4.4 argocd_insight/rollouts/（新增子模块）

复用 `argocd_insight` 的轨迹（`trace`）、`@traced`、报告框架。

- `diagnose.py`：读取 rollout 状态，识别 `paused`/`aborted`/`Progressing` 卡点，
  输出根因摘要（如 analysis 失败、setWeight 卡在 wait、abort 用户操作）。
- `analysis.py`：读取关联 AnalysisRun，归因失败（metric 阈值未达标 / run 未完成 / 无 progression 超时）。
- `__main__.py` 或 CLI 入口扩展：`python -m argocd_insight rollouts diagnose <name> [-n ns]`。
- 调用方式：`kubectl` + `kubectl argo rollouts` 子命令（`get rollout` JSON 输出），
  读取集群状态；不在此工具内写 Rollout（只读诊断）。

### 4.5 scripts/tests/

- 新增 `test_rollouts_diagnose.py` / `test_rollouts_analysis.py`：以 fixture
  （mock 的 rollout/analysisrun JSON）验证诊断逻辑与归因正确性。

## 5. 复用的现有约定（不可破坏）

- 单 skill 在仓库根目录；不触发 nested 布局迁移。
- `argocd_insight` 的 `@traced` / trace writer / 报告格式。
- 不回显 token 的脱敏规则；会话内 `{{user.*}}` 复用规则。
- 错误提示规范：SKILL.md 错误表摘要 + 引用附录 A，不在正文硬编码完整提示。
- 文档交叉引用完整性检查（每个新 references 文件须在 SKILL.md 中被引用）。

## 6. 验证清单（post-change）

1. `python3 -m argocd_insight rollouts --help` 可用。
2. `pytest scripts/tests/ -v` 零失败（含新增 rollouts 测试）。
3. SKILL.md `description` 仍 ≤1024 字符、frontmatter 可解析。
4. 新 references 文件在 SKILL.md 中均有引用（运行 AGENTS.md 的引用完整性检查）。
5. `references/argocd-rollouts-guide.md` 字段映射与文档示例自洽。
6. TODO.md 同步更新迭代记录。

## 7. 成功标准

- Rollouts 能力在 SKILL.md 可见、可触发。
- `argocd-rollouts-guide.md` 提供可操作的命令与配置示例。
- `argocd_insight rollouts diagnose` 对 paused/aborted/analysis 失败场景输出正确归因。
- 全量测试零失败。
