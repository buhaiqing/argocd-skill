---
name: argocd-skill
description: |
  ArgoCD CLI 全流程技能。Use when: (1) argocd CLI 安装/升级；(2) 自然语言生成 argocd CLI 命令（20+ 操作）；(3) Application YAML 反向转 `argocd app create`；(4) 批量 manifest 转换（argocd_cli_gen）；(5) 批量操作（batch）；(6) 变更影响分析（impact）；(7) 诊断/漂移/健康/合规/成本/自动修复；(8) 部署频率/OOS 统计；(9) Git 源健康（repo_health）；(10) 多集群对比；(11) 报告推送/配置模板；(12) HTTP API 回退 + Pod 操作（ulw）；(13) ArgoCD Rollouts 渐进式交付：Deployment→Rollout 转换、Canary/BlueGreen/Analysis 配置生成、kubectl argo rollouts 命令生成、Rollout 状态与 AnalysisRun 归因诊断（argocd_insight rollouts diagnose）。
  Trigger keywords: argocd, ArgoCD, argocd app, app of apps, App-of-Apps, kustomize, 多源, 反向生成, 批量转换, GitOps, kubectl apply, HTTP API, 诊断, OutOfSync, 漂移, 健康, 合规, 成本, 自动修复, 批量, 配置模板, 部署频率, 自进化, 离线触发, argocd_insight, argocd_deploy_stats, ulw, 孤儿 Pod, batch, impact, repo_health, multi-cluster, report-push, scaffold, rollouts, Rollout, kubectl argo rollouts, Deployment 转 Rollout, 渐进式交付, canary, bluegreen, AnalysisRun, 金丝雀, 蓝绿, 灰度发布, app actions, resource actions, 资源操作, 重启 Pod.
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

### 死法 11：Deployment 直接替换 Rollout 时丢失 strategy/Service
- **触发**：把 Deployment 的 `spec` 平移到 Rollout 但漏掉 `strategy` 与 Service 关联
- **表现**：Rollout 退化为 basic（一次性全量替换，无金丝雀/蓝绿），或 controller 报错 "no service defined"
- **避免**：3.6.1 转换必须补 `strategy` 字段 + `service` 引用；输出前提示 Service 需预存在
- **友好提示**：⚠️ Rollout 转换缺 strategy/Service → 详见附录 A 格式

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
| 资源 Action / 重启 / 执行操作 | `argocd app actions list/run` |
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

### 3.6 能力四：ArgoCD Rollouts 渐进式交付

> 完整指南见 [references/argocd-rollouts-guide.md](references/argocd-rollouts-guide.md)。
> 运行态只读诊断：`python -m argocd_insight rollouts diagnose <name> -n <ns>`

ArgoCD Rollouts 是独立于核心 ArgoCD Application 的渐进式交付控制器，
用 `Rollout` CRD（替代 Deployment）实现 Canary / BlueGreen / Analysis 驱动的发布。

**典型场景（agent 应主动设想并引导）**：

| 场景 | 用户意图 | agent 动作 |
|------|----------|-----------|
| Deployment → Rollout 改造 | "把这个 Deployment 改成灰度发布" | 提取 `spec.template` / `selector` / `replicas`，生成等价 `Rollout` 骨架（strategy 留空待选） |
| 金丝雀发布 | "用金丝雀，5%→25%→50%→100%" | 生成 canary `steps`：`setWeight` + `pause{duration}` 阶梯 + 末步 `analysis` |
| 蓝绿切换 | "蓝绿发布，验证通过再切流量" | 生成 blueGreen：`previewService`/`activeService` + `autoPromotionSeconds` 或手动 `promote` |
| 分析卡点 | "发布卡住了，帮我看为什么" | `argocd_insight rollouts diagnose` → 输出 paused/aborted/analysis 失败归因 |
| 命令生成 | "查看 rollout 状态 / 手动推进 / 回滚" | 生成 `kubectl argo rollouts get/promote/abort/undo/set image` |

**分流规则**：

1. 用户给的是 **Deployment YAML** → 走 3.6.1 转换流程，输出 `Rollout` YAML（不强行用 CLI）。
2. 用户问 **状态/卡点/失败归因** → 走诊断工具（只读，不写）。
3. 用户要 **CLI 命令** → 生成 `kubectl argo rollouts` 子命令。

**3.6.1 Deployment → Rollout 转换**

- `spec.replicas` / `spec.selector` / `spec.template` 原样平移到 `Rollout.spec`。
- **必须**新增 `service` 引用（Rollout 通过 `spec.strategy.canary/blueGreen` 关联 Service）。
- **必须**新增 `strategy` 字段（canary / blueGreen），否则 Rollout 退化为 basic 无渐进能力。
- 应用名净化遵循 `s/_/-/g`（与死法 2 一致）。
- 输出后提示用户：Rollout 需集群已安装 `argo-rollouts` controller，且 Service 需预先存在。

**3.6.2 诊断调用**

```bash
python -m argocd_insight rollouts diagnose <name> -n <ns> --output json
```

返回 `RolloutDiagnosis`（paused/aborted/Progressing 归类 + 严重级别 + action 列表）
与关联 `AnalysisRun` 归因（metric 阈值未达标 / run 未完成）。

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
