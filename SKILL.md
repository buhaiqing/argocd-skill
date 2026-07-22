---
name: argocd-skill
description: |
  ArgoCD CLI 全流程技能。Use when the user wants to:
  (1) 安装 / 升级 argocd CLI（含跨平台 Linux/macOS/Windows/Docker、指定版本、离线包）；
  (2) 用自然语言生成 argocd CLI 命令（app create / sync / rollback / get / list / login 等 20 个高频操作）；
  (3) 把 1 个 ArgoCD Application YAML 翻译成等价的 `argocd app create` 命令；
  (4) 把整个 manifest 目录批量反向生成 shell 脚本，调用 `python -m argocd_cli_gen`；
  (5) 处理 ArgoCD CLI 不支持的边界（多源 $values、kustomize.patches/components 等），回退到 `kubectl apply -f` 兜底；
  (6) 通过 HTTP API（`/api/v1`）执行 ArgoCD 操作，适用于 CLI 失败时的自动回退，调用 `python -m argocd_api`；
  (7) 诊断分析 / 漂移检测 / 健康评估 / 成本估算 / 合规检查 / 批量自动修复 / 变更影响分析 / 批量操作 / 配置模板生成 / Git 源健康检查 / 报告推送，调用 `python -m argocd_insight` 系列工具；
  (8) 部署频率统计 / OutOfSync 分析，调用 `python -m argocd_deploy_stats.stats` / `python -m argocd_deploy_stats.oos_analyzer`；
  (9) 通过 HTTP API 直接操作 Pod（查找/删除孤儿 Pod），调用 `python -m ulw`；
  (10) 可观测与自进化：执行轨迹记录、轨迹分析、经验提炼、自进化写回（自动优化参数与配置）、SkillOpt 参数推荐、离线触发（定时/阈值/会话结束），调用 `python -m argocd_insight trace` / `python -m argocd_insight.trigger.cron` 等工具。
  Trigger keywords: argocd, ArgoCD, app of apps, App-of-Apps, Application YAML, manifest 转 CLI, argocd app create, kustomize, multi-source, 多源, 反向生成, 批量转换, 迁移 ArgoCD, GitOps, kubectl apply 兜底, HTTP API, argocd 回退, 诊断分析, 问题 App, OutOfSync, 根因归因, 漂移检测, 版本漂移, 健康评估, 稳定性, 多维度打分, 改进建议, argocd-insight, 部署频率, 部署统计, Git 源健康, repo 健康, 仓库健康, repo-health, 合规检查, syncPolicy 风险, automated, self-heal, 配置合规, 成本估算, 资源成本, 成本报告, CPU, Memory, 运行成本, Top 10, 成本分析, 自动修复, 批量修复, autofix, 变更影响, 影响分析, impact, 操作前预览, 批量操作, 批量同步, 并发执行, batch, scaffold, 配置模板, 生成模板, Scaffold, argocd_deploy_stats, 部署频率, OOS 分析, ulw, Pod 操作, 孤儿 Pod, 可观测, 轨迹, 经验提炼, 自进化, 写回, 离线触发, cron, threshold, session_end, trace, analyzer, insight_engine, evolver, skillopt, trigger.
allowed-tools: [Read, Write, Bash, Grep, Glob]
---

# ArgoCD CLI Skill

## 一、适用边界

### ✅ 适用场景
- 用户明确提到 "argocd"、"ArgoCD"、"argo" 相关操作
- 安装/升级 argocd CLI、生成 CLI 命令、反向生成 Application YAML
- 批量处理 manifest 目录（≥5 个文件）、CLI 失败时 HTTP API 回退
- OutOfSync 诊断、版本漂移检测、健康评估、配置合规、成本估算、自动修复
- 执行轨迹记录、经验提炼、自进化写回、离线触发

### ❌ 不适用场景
- 操作 Kubernetes 原生资源但**未提及 ArgoCD** → 让路给 k8s skill
- 直接操作 Helm / Kustomize 而非通过 ArgoCD → 让路给对应 skill
- 编写 Application YAML（而非转换为 CLI）→ 非本 Skill 核心
- ArgoCD 服务端安装/配置、修改系统 ConfigMap/CRD → 超出 CLI 范围

---

## 二、已知死法（失败机制编码）

### 死法 1：CLI 命令未登录就执行
- **触发**：`argocd app create/sync/delete` 前未执行 `argocd login`
- **表现**：`FATA[0000] rpc error: code = Unauthenticated desc = no session information`
- **避免**：会话首条命令前执行 3.1 开机自检协议
- **友好提示**：❌ 认证失败 → 详见附录 A 格式

### 死法 2：应用名包含下划线 `_`
- **触发**：`metadata.name: my_app`
- **表现**：`application name "my_app" contains invalid character '_'`
- **避免**：所有 `metadata.name` 传入 CLI 前必须 `s/_/-/g`
- **友好提示**：❌ 应用名非法 → 详见附录 A 格式

### 死法 3：混淆 Kustomize 和 Helm 参数
- **触发**：YAML 是 Kustomize 配置但用了 `--helm-set`
- **避免**：先判定 source 类型，`kustomize` 用 `--kustomize-*`，`helm` 用 `--helm-*`
- **友好提示**：❌ 参数类型不匹配 → 详见附录 A 格式

### 死法 4：automated 和 prune/self-heal 关系错误
- **触发**：用了 `--auto-prune` / `--self-heal` 但没加 `--sync-policy automated`
- **避免**：若出现 `--auto-prune` / `--self-heal`，必须同时出现 `--sync-policy automated`
- **深度参考**：[references/argocd-sync-policy-deep-dive.md](references/argocd-sync-policy-deep-dive.md)（automated/prune/selfHeal 完整解析）
- **友好提示**：❌ 参数缺少必需配置 → 详见附录 A 格式

### 死法 5：强行将多源 `spec.sources` 转 CLI
- **触发**：`spec.sources` 长度 > 1
- **避免**：长度 > 1 → **立即停止**，输出 `kubectl apply -f` 兜底
- **友好提示**：⚠️ 多源不支持 CLI → 详见附录 A 格式

### 死法 6：运维组件错误开启 CreateNamespace
- **触发**：k8s_ops 目录 YAML 加了 `--sync-option CreateNamespace=true`
- **避免**：`destination.namespace` 是 `ops`/`loki`/`kube-system` 等 → **强制 `CreateNamespace=false`**
- **友好提示**：❌ 运维组件不应创建 namespace → 详见附录 A 格式

### 死法 7：业务应用错误开启 automated
- **触发**：业务应用 YAML 被加上 `--sync-policy automated`
- **避免**：`namespace` 是业务 ns → **禁止 automated**，只保留 `PruneLast=true`
- **深度参考**：[references/argocd-sync-policy-deep-dive.md](references/argocd-sync-policy-deep-dive.md)（automated 业务规范完整解析）
- **友好提示**：⚠️ 生产应用不应开启自动同步 → 详见附录 A 格式

### 死法 8：CLI 失败时未自动回退 HTTP API
- **触发**：`argocd login` 失败或 `argocd app` 命令超时
- **避免**：CLI 失败后必须自动尝试 `python -m argocd_api`（见 3.5）
- **友好提示**：⚠️ CLI 失败，尝试 HTTP API → 详见附录 A 格式

### 死法 9：敏感信息泄露
- **触发**：`ARGOCD_AUTH_TOKEN` / `ARGOCD_PASSWORD` 被回显或写入日志
- **避免**：所有输出中敏感字段必须替换为 `***`
- **友好提示**：🔒 敏感信息保护 → 详见附录 A 格式

### 死法 10：修复操作未确认直接执行
- **触发**：`autofix` 或合规修复建议被自动执行
- **避免**：所有修复必须先展示 dry-run，明确询问用户"是否继续"
- **友好提示**：⚠️ 修复操作需确认 → 详见附录 A 格式

---

## 三、原子级 SOP

### 3.1 会话开机自检协议（首条命令前强制执行）

> **认证优先级（所有 ArgoCD 工具共享）**：
> `ARGOCD_AUTH_TOKEN`（推荐）→ `ARGOCD_USERNAME + ARGOCD_PASSWORD` → `~/.config/argocd/config`
> 支持 `.env` 文件自动检测（skill 根目录或当前目录）。

**Step 1: 加载环境变量**
```bash
if [ -f .env ]; then export $(cat .env | grep -v '^#' | xargs); fi
```

**Step 2: 检测凭证** → token 模式 / 密码模式 / 已有 session / 交互式 login

**Step 3: 验证 CLI 可用性** → `argocd version --client`，非 0 则进入 Step 4

**Step 4: CLI 不可用时安装** → 执行 3.2

**Step 5: 验证登录状态** → `argocd account get-user-info --server $ARGOCD_SERVER`
- token 模式：`argocd login --auth-token $ARGOCD_AUTH_TOKEN --server $ARGOCD_SERVER`
- 密码模式：`argocd login -u $ARGOCD_USERNAME -p $ARGOCD_PASSWORD --server $ARGOCD_SERVER`
- 交互模式：提示用户执行 `argocd login --server <server>`

**Step 6: 记录会话状态** → 后续命令缺省时自动沿用，输出开头标注「复用：key=value」
> 完整协议详见 [references/agent-protocols.md](references/agent-protocols.md)（开机预检 / CLI 回退 / 认证优先级）

---

### 3.2 能力一：CLI 安装

**触发**：用户说"安装 argocd"、"升级 CLI"、或开机自检发现 CLI 不存在

**Step 1**: 确定版本 → 用户指定 / GitHub API latest（强制补 v 前缀）
**Step 2**: 确定平台 → `uname -s` + `uname -m`
**Step 3**: 下载 → `curl -sSL -o /usr/local/bin/argocd <url>` + `chmod +x`
**Step 4**: 验证 → `argocd version --client`

---

### 3.3 能力二：自然语言生成 CLI

**Step 1: 意图关键词匹配**
| 关键词 | 命令 |
|--------|------|
| 创建/create/新建 | `argocd app create` |
| 同步/sync/部署 | `argocd app sync` |
| 回滚/rollback | `argocd app rollback` |
| 删除/delete/移除 | `argocd app delete` |
| 列出/list/查看所有 | `argocd app list` |
| 获取/get/查看详情 | `argocd app get` |
| 历史/history | `argocd app history` |
| 差异/diff | `argocd app diff` |
| 登录/login | `argocd login` |
| 项目/project | `argocd proj` |
| 仓库/repo | `argocd repo` |
| 集群/cluster | `argocd cluster` |

**Step 2: 提取必备参数**（一次问齐）→ `app_name`、`repo_url`、`revision`(默认 HEAD)、`path`、`dest_server`(默认 kubernetes.default.svc)、`dest_namespace`、`project`(默认 default)

**Step 3: 危险命令二次确认** → `delete/terminate-op/cluster rm/repo rm/proj delete` 必须用户重复确认目标名称
> AppProject 管理详见 [references/argocd-appproject-guide.md](references/argocd-appproject-guide.md)

**Step 4: 构建命令**
**Step 5: 附加 syncPolicy**（依据 4-tier 层级）
- `namespace == argo-root` → `--sync-policy automated --auto-prune --self-heal`
- 运维 ns → `--sync-option CreateNamespace=false`
- 业务 ns → `--sync-option CreateNamespace=true`（禁止 automated）

**Step 6: 输出命令并标注复用字段**

---

### 3.4 能力三：YAML 反向生成 CLI

**分流**：单个 YAML 文本块 / ≤4 个片段 → 3.4.1；目录路径 / ≥5 个文件 → 3.4.2
> ApplicationSet 管理详见 [references/argocd-appset-guide.md](references/argocd-appset-guide.md)

#### 3.4.1 单 YAML 内联转换

**Step 1**: 解析 `metadata.name`、`spec.project`
**Step 2**: 检测多源 → `spec.sources` 长度 > 1 立即回退 `kubectl apply -f`
**Step 3**: 提取 source（`repoURL`/`targetRevision`/`path`/`chart`）
**Step 4**: 提取 destination（`server`/`namespace`）
**Step 5**: 判定类型 → Kustomize / Helm / 原生
**Step 6**: 转换参数 → 字段映射表见 [references/kustomize-mapping.md](references/kustomize-mapping.md)
**Step 7**: 转换 syncPolicy
**Step 8**: 应用名净化 → `s/_/-/g`
**Step 9**: 组装命令并输出

#### 3.4.2 批量转换
```bash
python -m argocd_cli_gen --input <absolute_path> --output <out_dir> --upsert --emit-dry-run
```
读取 `report.md` 展示结果。

---

### 3.5 CLI 运行时回退协议

**触发**：任何 `argocd` 命令返回非 0 退出码

**Step 1: 分析原因**
- "Unauthenticated"/"no session" → 认证问题
- "connection refused"/"timeout" → 网络问题
- "unknown flag"/"invalid syntax" → 语法问题
- 其他 → 未知

**Step 2: 认证/网络问题** → HTTP API 回退：`python -m argocd_api <op> <app>`
**Step 3: 语法问题** → 修正 flag 名称（`--kustomize-*` vs `--helm-*`）
> CLI 回退协议详见 [references/agent-protocols.md](references/agent-protocols.md)
**Step 4: 未知问题** → `kubectl apply -f` 兜底

---

## 四、绝对禁区

- 🚫 死循环重试：最多 3 次（CLI → HTTP API → kubectl）
- 🚫 危险操作未经二次确认就执行
- 🚫 敏感信息（`AUTH_TOKEN`/`PASSWORD`）泄露
- 🚫 跨会话状态持久化
- 🚫 dry-run 模式下执行实际变更
- 🚫 强行转换不支持的 YAML 特性（`spec.sources` 多源、`kustomize.patches` 等）
- 🚫 臆造 labels / automated
- 🚫 跨 skill 越权处理

---

## 附录 A：用户友好错误输出规范

**格式**（遇到错误时必须遵守）：
```
<❌/⚠️/🔒/ℹ️> <错误分类>

<一句话说明问题>

<根因说明（如有）>

<自助排查步骤>
  1. ...
  2. ...

<兜底方案>
  兜底：<替代命令>
```

**图标含义**：`❌` 失败、`⚠️` 警告需确认、`🔒` 安全凭证、`ℹ️` 提示

**必须包含**：问题说明 + 可执行排查步骤 + 兜底方案
**禁止**：原始错误堆栈、只说"失败"不解释原因、泄露 `AUTH_TOKEN` 明文

详见 `references/argocd-troubleshooting.md`（按症状分流的完整排查指南）。

## 附录 B：4-Tier 生产模型

| 层级 | namespace | automated | CreateNamespace | labels |
|------|-----------|-----------|----------------|--------|
| 基础设施 Root | `argo-root` | — | — | — |
| 聚合入口 Root | `argo-root` | **required** | true | — |
| 业务应用 | 业务 ns | **NO** | true | **required** |
| 运维组件 | `ops`/`loki`/`kube-system` | NO | **false** | — |

详见 `references/argocd-app-lifecycle.md`。

## 附录 C：字段映射速查表（完整版）

完整映射见 [references/kustomize-mapping.md](references/kustomize-mapping.md)，本附录仅列核心条目：

**Kustomize**：namePrefix/nameSuffix/images → `--kustomize-name-prefix`/`--kustomize-image` 等
**Helm**：valueFiles/parameters/releaseName → `--values`/`--helm-set`/`--helm-release-name`
**syncPolicy**：automated / prune / selfHeal / CreateNamespace → 见 [references/kustomize-mapping.md](references/kustomize-mapping.md)

## 附录 D：参考资料

| 文档 | 内容 |
|------|------|
| [references/cli-installation.md](references/cli-installation.md) | CLI 安装详细步骤 |
| [references/cli-commands.md](references/cli-commands.md) | 20+ 命令详解 |
| [references/kustomize-mapping.md](references/kustomize-mapping.md) | **完整字段映射表** |
| [references/kustomize-examples.md](references/kustomize-examples.md) | 真实 YAML 转换示例 |
| [references/batch-conversion-design.md](references/batch-conversion-design.md) | 批量工具设计 |
| [references/argocd-troubleshooting.md](references/argocd-troubleshooting.md) | 按症状分流的故障排查 |
| [references/argocd-insight-commands.md](references/argocd-insight-commands.md) | 诊断工具集使用手册 |
| [references/argocd-app-lifecycle.md](references/argocd-app-lifecycle.md) | App 全生命周期管理 |
| [references/argocd-appproject-guide.md](references/argocd-appproject-guide.md) | AppProject 管理 |
| [references/argocd-appset-guide.md](references/argocd-appset-guide.md) | ApplicationSet 管理 |
| [references/argocd-sync-policy-deep-dive.md](references/argocd-sync-policy-deep-dive.md) | syncPolicy 深度解析 |
| [references/agent-protocols.md](references/agent-protocols.md) | 开机预检 / CLI 回退协议 |
| [references/argocd-prompts.md](references/argocd-prompts.md) | 提示词示例 |
| [references/performance-guide.md](references/performance-guide.md) | 性能指南与基准 |
| [references/testing-guide.md](references/testing-guide.md) | 测试标准与用例 |

外部：[ArgoCD CLI 安装](https://argo-cd.readthedocs.io/en/stable/cli_installation/) · [命令参考](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd/) · [GitHub Release](https://github.com/argoproj/argo-cd/releases)
