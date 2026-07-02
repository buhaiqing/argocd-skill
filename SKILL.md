---
name: argocd-skill
description: |
 ArgoCD CLI 全流程技能。Use when the user wants to:
 (1) 安装 / 升级 argocd CLI（含跨平台 Linux/macOS/Windows/Docker、指定版本、离线包）；
 (2) 用自然语言生成 argocd CLI 命令（app create / sync / rollback / get / list / login 等 20 个高频操作）；
 (3) 把 1 个 ArgoCD Application YAML 翻译成等价的 `argocd app create` 命令；
 (4) 把整个 manifest 目录批量反向生成 shell 脚本，调用 `python -m argocd_cli_gen`；
 (5) 处理 ArgoCD CLI 不支持的边界（多源 $values、kustomize.patches/components 等），回退到 `kubectl apply -f` 兜底；
 (6) 通过 HTTP API（`/api/v1`）执行 ArgoCD 操作，适用于 CLI 失败时的自动回退；
 (7) 诊断分析 / 漂移检测 / 健康评估 / 成本估算 / 合规检查 / 批量自动修复 / 变更影响分析 / 批量操作 / 配置模板生成 / Git 源健康检查 / 报告推送，调用 `python -m argocd_insight` 系列工具。
 Trigger keywords: argocd, ArgoCD, app of apps, App-of-Apps, Application YAML, manifest 转 CLI, argocd app create, kustomize, multi-source, 多源, 反向生成, 批量转换, 迁移 ArgoCD, GitOps, kubectl apply 兜底, HTTP API, argocd 回退, 诊断分析, 问题 App, OutOfSync, 根因归因, 漂移检测, 版本漂移, 健康评估, 稳定性, 多维度打分, 改进建议, argocd-insight, 部署频率, 部署统计, Git 源健康, repo 健康, 仓库健康, repo-health, 合规检查, syncPolicy 风险, automated, self-heal, 配置合规, 成本估算, 资源成本, 成本报告, CPU, Memory, 运行成本, Top 10, 成本分析, 自动修复, 批量修复, autofix, 变更影响, 影响分析, impact, 操作前预览, 批量操作, 批量同步, 并发执行, batch, scaffold, 配置模板, 生成模板, Scaffold.
allowed-tools: [Read, Write, Bash, Grep, Glob]
---

# ArgoCD CLI Skill

## 概述

为运维智能体提供 ArgoCD CLI 的核心能力：CLI 安装、自然语言→CLI 命令生成、Application YAML→CLI 反向生成（含批量工具）、HTTP API 回退、诊断分析工具集（diagnose/drift/health/repo-health/compliance/cost/autofix/impact/batch/scaffold/report-push）。

## 何时使用

- 用户说"装一下 argocd"、"帮我安装 ArgoCD CLI"
- 用户描述操作意图（"创建一个应用"、"同步"、"回滚"等）需要生成对应 CLI 命令
- 用户给了一个 ArgoCD Application YAML 需要转换为 CLI 命令
- **用户给了一个 manifest 目录**，要批量反向生成 shell 脚本
- 用户需要诊断分析、版本漂移检测、健康评估、成本估算、合规检查、批量修复等运维操作
- 用户编写 CI/CD 脚本中需要 argocd 命令

## 行为准则（执行前必读）— 🚫 强制遵守

> 源自 Andrej Karpathy 对 LLM 编程陷阱的观察。**本 skill 所有 Agent 必须无例外遵守。**
>
> 完整内容（准则一~五）已移入 [references/agent-protocols.md](references/agent-protocols.md#一行为准则执行前必读) 第**一**节。**Agent 读取本行后必须跳转到该文件展开执行。**

## 会话开机自检协议（跨能力通用）

> 完整内容（0.1 `.env` 加载 → 0.2 凭证检测 → 0.3 CLI 可用性 → 0.4 HTTP API 回退 → 0.5 状态复用 → 0.6 运行时 CLI 回退协议）已移入 [references/agent-protocols.md](references/agent-protocols.md#二会话开机自检协议跨能力通用会话首条命令前执行) 第**二**节。**Agent 读取本行后必须跳转到该文件展开执行。**

## 能力清单

### 能力一：CLI 安装

从 GitHub Release 统一入口下载 argocd CLI 单文件二进制，支持跨平台（Linux/macOS/Windows/Docker）和指定版本。

**详见：** [references/cli-installation.md](references/cli-installation.md)

### 能力二：自然语言生成 CLI 命令

将用户的操作描述映射为正确的 argocd CLI 命令，覆盖 20 个高频操作。本能力由五个子协议驱动：必备参数一次问齐、复合意图编排模板、危险命令二次确认、会话内状态复用、命令吐出前自检。

**详见：** [references/cli-commands.md](references/cli-commands.md)（含完整命令表、参数推断规则、危险命令清单）

### 能力三：Application Manifest 反向生成

**分流决策（必须先做）：**

| 用户输入形态 | 应当走的子能力 |
|---|---|
| 粘贴 1 个 YAML 文本块 / `≤4` 个分散 YAML 片段 | **3.1 内联转换** |
| 给一个目录路径、`≥5` 个文件、说"整个/批量/全部" | **3.2 批量工具** |
| 提到"迁移 / 重建 / 备份 / 灾备 / 新集群" | **3.2 批量工具** |
| 单个 YAML 含 `spec.sources` 多源 | **3.1 + 回退到 `kubectl apply`** |

**子能力 3.1：单 YAML 内联转换** — Agent 自己读 YAML，按字段映射表输出 `argocd app create ...`，无外部依赖。

**完整字段映射表：** [references/kustomize-mapping.md](references/kustomize-mapping.md)
**真实模式转换示例：** [references/kustomize-examples.md](references/kustomize-examples.md)

**子能力 3.2：目录批量转换（推荐用于 5 个以上 YAML）：**

```bash
python -m argocd_cli_gen \
  --input  /abs/path/to/argo-apps/dly/production \
  --output ./out \
  --upsert \
  --emit-dry-run
```

**输出结构：** `out/00_preflight.sh` → `05_infra_roots.sh` → `10_app_roots.sh` → `20_workloads_ops.sh` → `30_workloads_business.sh` → `99_multisource_fallback.yaml` + `report.json` / `report.md` / `run_all.sh`

**工具使用手册：** [scripts/README.md](scripts/README.md)
**工具方案设计：** [references/batch-conversion-design.md](references/batch-conversion-design.md)

### 能力四~十五：诊断与运维工具集

全部调用 `python -m argocd_insight` 系列工具（或 `argocd_deploy_stats`）。

**详见：** [references/argocd-insight-commands.md](references/argocd-insight-commands.md)（含每个能力的调用方式、输出示例、触发短语三段式）

快速索引：

| 能力 | 工具模块 | 主要功能 |
|------|---------|---------|
| 四 | `argocd_deploy_stats.oos_analyzer` | OutOfSync 根因归因（Git漂移/手动漂移/孤儿资源） |
| 五 | `argocd_insight.batch` | 批量 sync/rollback/refresh，支持并发控制 |
| 六 | `argocd_insight.drift` | 版本漂移检测（跨集群/跨环境） |
| 七 | `argocd_insight.health` | 8 维度稳定性评估打分 |
| 八 | `argocd_insight.repo_health` | Git 仓库连接状态检查 |
| 九 | `argocd_insight.compliance` | syncPolicy 风险合规检查 |
| 十 | `argocd_insight.cost` | 资源成本估算（CPU/Memory） |
| 十一 | `argocd_insight.autofix` | 基于诊断结果的批量自动修复 |
| 十二 | `argocd_insight.impact` | sync/rollback 前影响范围预览 |
| 十三 | `argocd_insight.multi_cluster` | 多集群 App 配置/资源对比 |
| 十四 | `argocd_insight.report_push` | 报告推送（飞书/钉钉/Slack） |
| 十五 | `argocd_insight.scaffold` | 4-tier 模型 Application YAML+CLI 生成 |

**提示词示例（全部迁移至）：** [references/argocd-prompts.md](references/argocd-prompts.md)

## App-of-Apps 与层级分布（基于 argoapp 仓库 97 YAML 全样本）

| 层级 | 真实占比 | YAML 示例 | namespace | automated | CreateNamespace | labels |
|------|---------|----------|-----------|-----------|-----------------|--------|
| 基础设施 Root | <1% | `projects.yaml`、`repos.yaml`、`initns/namespace.yaml` | `argo-root` | — | — | — |
| 聚合入口 Root | 5% | `{project}-{profile}-{git_branch}.yaml` | `argo-root` | **required** | true | — |
| 业务应用 | 76% | `{stack}-{app}.yaml` | 业务 ns | **NO** | true | **required** (project/profile/stack/app) |
| 运维组件 | 18% | `prometheus.yaml`、`loki.yaml` | `ops`/`loki`/etc. | NO | **false** | — |

**关键约束：**
- `metadata.name` 含 `_` 必须替换为 `-`（`--revision k8s_mas` 等 git 分支名保留下划线）
- 业务应用的 `metadata.name` 与文件命名都不允许 `_`
- 聚合 Root 必含 `syncPolicy.automated.prune+selfHeal`；业务/运维通常只有 `PruneLast=true`，**不开 automated**
- 运维组件多含 `CreateNamespace=false`（namespace 由 initns 单独管理）

## 常见错误

| 错误 | 正确处理 |
|------|---------|
| 缺少 --dest-server | 必须指定目标集群地址，不可省略 |
| 用 --helm-set 处理 Kustomize 参数 | Kustomize 用 `--kustomize-*`，Helm 用 `--helm-*`，不可混用 |
| 版本号不带 v 前缀 | GitHub Release tag 需要 v 前缀（v3.4.2），不指定则自动补全 |
| 未先 login 就操作 | 同步/回滚/删除等操作前要求用户先 `argocd login` |
| `--auto-prune` 缺少 `--sync-policy automated` | prune 只能在 automated 模式下使用，需同时指定 |
| 强行将 `spec.sources` 多源 YAML 转 CLI | argocd CLI 不支持多源 `$values` 引用；**回退到 `kubectl apply -f`** |
| `metadata.name` 含下划线直接传入 CLI | argocd 应用名不允许 `_`，需替换为 `-` |
| Root 入口漏 `automated` | `destination.namespace=argo-root` 必含 `--sync-policy automated --auto-prune --self-heal` |
| 运维组件错加 labels | k8s_ops 下 94% 应用无 labels，禁止臆造四件套 |
| 业务应用错开 automated | 业务应用生产规范是手动触发 sync，**勿臆加 automated** |
| 把 `CreateNamespace=false` 转成 `=true` | 运维组件 namespace 由 initns 单独管理，必须保持 `false` |
| `argocd login` 因 context path / insecure 失败 | **不回退放弃**，改用 HTTP API `/api/v1/session` 获取 token + `python -m argocd_api` |
| 运行时 CLI 命令失败仅报错、不自动回退 API | Agent **必须**自动输出等价的 `python -m argocd_api` 命令重试 |
| OutOfSync 分析时 `argocd app diff` 执行超时 | 默认 timeout=30s，可追加 `--concurrency 2` 降低并发 |
| compliance 修复命令直接自动执行 | 合规修复建议**仅作为输出展示**，不自动执行 |
| autofix 在 dry-run 模式下执行了实际操作 | **禁止**：带 `--dry-run` 时只预览、不下发 |
| impact 分析依赖缺失导致分析不完整 | 变更影响分析需要当前 context 能访问目标 App 的 K8s 资源，先验证权限 |
| autofix 直接执行诊断结果而未让用户确认 | **必须先展示 dry-run 结果，询问用户是否继续** |

## 参考资料

### 内部 Runbooks（`references/`）

| Runbook | 适用场景 |
|---------|---------|
| [cli-installation.md](references/cli-installation.md) | argocd CLI 跨平台安装、指定版本、离线包 |
| [cli-commands.md](references/cli-commands.md) | 20+ CLI 命令详解、参数推断规则、危险命令清单 |
| [agent-protocols.md](references/agent-protocols.md) | 行为准则（Karpathy 五则）+ 会话开机自检协议 |
| [argocd-app-lifecycle.md](references/argocd-app-lifecycle.md) | App 创建 → 同步 → 回滚 → 删除全生命周期 |
| [argocd-appproject-guide.md](references/argocd-appproject-guide.md) | AppProject / repo / cluster 多租户边界 |
| [argocd-sync-policy-deep-dive.md](references/argocd-sync-policy-deep-dive.md) | automated / selfHeal / PruneLast / 4-tier 矩阵 |
| [argocd-appset-guide.md](references/argocd-appset-guide.md) | ApplicationSet Generator 与批量 App 模板 |
| [argocd-troubleshooting.md](references/argocd-troubleshooting.md) | 按症状分流：OutOfSync / Degraded / 认证 / 仓库 |
| [kustomize-mapping.md](references/kustomize-mapping.md) | Kustomize 字段 → CLI flag 映射表（与 `mapper.py` 同源） |
| [kustomize-examples.md](references/kustomize-examples.md) | 真实 YAML 转换示例（含多源边界 + 命名规范） |
| [batch-conversion-design.md](references/batch-conversion-design.md) | `argocd_cli_gen` 方案设计 + 可行性论证 |
| [argocd-insight-commands.md](references/argocd-insight-commands.md) | 能力 4~15 的调用方式 + 输出示例 + 触发短语（完整三段式） |
| [argocd-prompts.md](references/argocd-prompts.md) | 全部提示词示例（从 SKILL.md 迁移至此） |
| [testing-guide.md](references/testing-guide.md) | 测试标准、委托规则、Hypothesis 属性测试 |
| [performance-guide.md](references/performance-guide.md) | 性能复盘流程、检查清单、基准指标 |

### 外部文档

- [ArgoCD CLI 安装文档](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- [ArgoCD CLI 命令参考](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd/)
- [ArgoCD Application CRD 规范](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/)
- [GitHub Release 页面](https://github.com/argoproj/argo-cd/releases)
