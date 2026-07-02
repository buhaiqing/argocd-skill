---
name: argocd-skill
description: |
  ArgoCD CLI 全流程技能。Use when the user wants to:
  (1) 安装 / 升级 argocd CLI（含跨平台 Linux/macOS/Windows/Docker、指定版本、离线包）；
  (2) 用自然语言生成 argocd CLI 命令（app create / sync / rollback / get / list / login 等 20 个高频操作）；
  (3) 把 1 个 ArgoCD Application YAML（spec.source / spec.sources / kustomize / helm / syncPolicy / App-of-Apps Root）翻译成等价的 `argocd app create` 命令；
  (4) 把整个 manifest 目录（如 argoapp 仓库、argo-apps/dly/production 等）批量反向生成 shell 脚本（迁移 / 重建 / 备份 / 灾备 / 新集群初始化 / GitOps 配置脚本化场景），调用内置工具 `python -m argocd_cli_gen`；
  (5) 处理 ArgoCD CLI 不支持的边界（多源 spec.sources $values、kustomize.patches/components 等），引导用户回退到 `kubectl apply -f` 兜底方案；
  (6) 通过 HTTP API（`/api/v1`）执行 ArgoCD 操作，适用于 CLI（含 login 及运行时命令）因 context path / insecure / grpc-web 失败时的自动回退，支持 `python -m argocd_api` 查询/操作应用、Pod、资源树。
  (7) 诊断分析：批量识别有问题的 App（OutOfSync / Degraded / Error / Missing），多维度诊断（资源层 / diff 层 / 事件层 / 历史层），输出根因 + 严重级别（critical/high/medium/low）+ 具体 action 命令，调用内置工具 `python -m argocd_insight diagnose`；
  (8) 版本漂移检测：比对两个 ArgoCD 集群（或同一集群两个环境）同名 App 的 revision，输出漂移率、仅源端/目标端存在的 App，调用内置工具 `python -m argocd_insight drift`；
  (9) 运行稳定性评估：8 维度打分（App 健康率 / 同步率 / 错误率 / 部署频率 / 自动化覆盖率 / 聚合入口完整性 / 多源冗余度 / 漂移复发率），输出总分 + 薄弱项 + 具体改进建议，调用内置工具 `python -m argocd_insight health`。
  (10) Git 源健康检查：检查 ArgoCD 所有仓库的连接状态（ArgoCD server 侧）、分支可达性，输出健康报告，调用内置工具 `python -m argocd_insight repo-health` 或 `python -m argocd_deploy_stats.stats`（部署频率统计）。
  (11) 配置合规检查：检查 App syncPolicy 风险（automated 无 retry / 无 self-heal / 无 prune）、namespace 风险，输出风险数 + 严重级别 + 具体修复命令，调用内置工具 `python -m argocd_insight compliance`。
  (12) 资源成本估算：查询 ArgoCD App 的部署资源（CPU/Memory requests），估算运行成本，输出成本概览 + Top 10 高成本 App，调用内置工具 `python -m argocd_insight cost`。
  (13) 批量自动修复：基于诊断结果自动修复问题 App（sync OutOfSync / rollback Degraded），支持 dry-run 预览，调用内置工具 `python -m argocd_insight autofix`。
  (14) 变更影响分析：操作前预览 sync/rollback 会影响哪些资源、依赖关系、风险评估，调用内置工具 `python -m argocd_insight impact`。
   (15) 批量操作：对指定 App 列表或筛选条件（project/label/status）批量并发执行 sync/rollback/refresh，支持 dry-run 预览和并发度控制，调用内置工具 `python -m argocd_insight batch`。
   (16) Application 配置模板生成：基于 4-tier 模型从零生成 ArgoCD Application YAML 和等价 CLI 命令，支持 tier 自动设置默认参数（sync-policy / CreateNamespace / labels），调用内置工具 `python -m argocd_insight scaffold`。
  Trigger keywords: argocd, ArgoCD, app of apps, App-of-Apps, Application YAML, manifest 转 CLI, argocd app create, kustomize, multi-source, 多源, 反向生成, 批量转换, 迁移 ArgoCD, GitOps, kubectl apply 兜底, HTTP API, argocd 回退, pod 查询, .env 加载, 诊断分析, 问题 App, OutOfSync, 根因归因, 漂移检测, 版本漂移, 健康评估, 稳定性, 多维度打分, 改进建议, argocd-insight, 部署频率, 部署统计, Git 源健康, repo 健康, 仓库健康, repo-health, 合规检查, syncPolicy 风险, automated, self-heal, 配置合规, 成本估算, 资源成本, 成本报告, CPU, Memory, 运行成本, Top 10, 成本分析, 自动修复, 批量修复, autofix, 变更影响, 影响分析, impact, 操作前预览, 批量操作, 批量同步, 并发执行, batch, scaffold, 配置模板, 生成模板, Scaffold.
allowed-tools: [Read, Write, Bash, Grep, Glob]
---

# ArgoCD CLI Skill

## 概述

为运维智能体提供 ArgoCD CLI 的三项核心能力。

## 行为准则（执行前必读）— 🚫 强制遵守，不可违背

> 源自 Andrej Karpathy 对 LLM 编程陷阱的观察。**本 skill 所有 Agent 必须无例外遵守，不得以任何理由绕过。**
>
> 完整内容（准则一~五）已移入 [references/agent-protocols.md](references/agent-protocols.md#一行为准则执行前必读) 第**一**节。**Agent 读取本行后必须跳转到该文件展开执行。**

## 何时使用

- 用户说"装一下 argocd"、"帮我安装 ArgoCD CLI"
- 用户描述操作意图（"创建一个应用"、"同步"、"回滚"等）需要生成对应 CLI 命令
- 用户给了一个 ArgoCD Application YAML 需要转换为 CLI 命令
- **用户给了一个 manifest 目录**，要批量反向生成 shell 脚本（迁移、备份、重建场景）
- 用户编写 CI/CD 脚本中需要 argocd 命令

## 会话开机自检协议（跨能力通用，会话首条命令前执行）

> 完整内容（0.1 `.env` 加载 → 0.2 凭证检测 → 0.3 CLI 可用性 → 0.4 HTTP API 回退 → 0.5 状态复用 → 0.6 运行时 CLI 回退协议）已移入 [references/agent-protocols.md](references/agent-protocols.md#二会话开机自检协议跨能力通用会话首条命令前执行) 第**二**节。**Agent 读取本行后必须跳转到该文件展开执行。**

## 能力清单

### 能力一：CLI 安装

从 GitHub Release 统一入口下载 argocd CLI 单文件二进制，支持跨平台（Linux/macOS/Windows/Docker）和指定版本。

**实现逻辑详见：** [references/cli-installation.md](references/cli-installation.md)

### 能力二：自然语言生成 CLI 命令

将用户的操作描述映射为正确的 argocd CLI 命令。覆盖 20 个高频操作。
本能力由五个子协议驱动：必备参数一次问齐、复合意图编排模板、危险命令二次确认、会话内状态复用、命令吐出前自检。任何 20 个高频命令都必须经过这五步才能输出。

**完整命令表和示例详见：** [references/cli-commands.md](references/cli-commands.md)

#### 2.1 必备参数收集协议（一次问完）

收到不完整描述时，**禁止立刻吐占位符命令**。必须按命令→必填字段清单一次性问齐，避免来回三轮往返。下面是 5 个最高频命令的必填字段表：

| 命令 | 必填字段 | 可选字段 | 默认推断 |
|---|---|---|---|
| `argocd app create APPNAME` | `APPNAME` / `--repo` / `--path` / `--dest-namespace` / `--project` | `--revision`（建议显式指定）/`--dest-server` | `--dest-server https://kubernetes.default.svc` |
| `argocd app sync APPNAME` | `APPNAME` | `--revision` / `--timeout` | 追加 `--prune --sync-option PruneLast=true`（生产规范） |
| `argocd app rollback APPNAME [HISTORY_ID]` | `APPNAME` | `HISTORY_ID`（省略则回上一版本） | — |
| `argocd app set APPNAME` | `APPNAME` / `--sync-policy` | `--auto-prune` / `--self-heal`（与 `--sync-policy automated` 配对） | 三者同时给齐 |
| `argocd app delete APPNAME` | `APPNAME` | `--cascade` | **必须二次确认（见 2.3）** |
| `argocd app delete-resource APPNAME` | `APPNAME` / `--kind` / `--resource-name` / `--namespace` | `--force` / `--orphan` | **必须确认资源类型和标识符**（见 2.3） |
| `argocd app refresh APPNAME` | `APPNAME` | `--hard`（强制硬刷新） | — |
| `argocd app unset APPNAME` | `APPNAME` / 参数名 | — | **关闭自动化时必须确认**（见 2.3） |
| `argocd app edit APPNAME` | `APPNAME` | — | 交互式编辑 |
| `argocd app terminate-op APPNAME` | `APPNAME` | — | **必须二次确认**（见 2.3） |
| `argocd app logs APPNAME` | `APPNAME` | `--follow` / `--tail` / `--kind` / `--name` / `--namespace` / `--container` | — |
| `argocd app events APPNAME` | `APPNAME` | — | — |
| `argocd app diff APPNAME` | `APPNAME` | `--namespace` | — |
| `argocd app history APPNAME` | `APPNAME` | — | 输出 sync 历史 |
| `argocd app wait APPNAME` | `APPNAME` | `--health` / `--suspended` / `--timeout` | 等 App 就绪 |
| `argocd proj list/get/create/delete` | `PROJECT` | — | **delete 必须二次确认** |
| `argocd proj add-source/remove-source` | `PROJECT` / `REPO_URL` | — | — |
| `argocd proj add-destination/remove-destination` | `PROJECT` / `CLUSTER` / `NS` | — | — |
| `argocd appset list/get` | `APPSET` | — | — |
| `argocd appset delete` | `APPSET` | — | **必须二次确认** |
| `argocd appset generate` | `APPSET` | — | 干跑生成所有 App |
| `argocd account get-user-info` | — | — | 当前用户信息 |
| `argocd account generate-token` | — | `--account` | 生成认证 token |
| `argocd repo get/rm` | `URL` | — | **rm 必须二次确认** |
| `argocd cluster get/rm` | `NAME` | — | **rm 必须二次确认** |
| `argocd app list --output json` | — | `--project` / `-l label` | 输出 JSON 供后续分析 |

**一次问完的提问模板**（针对 `app create`）：

> "请一次性提供以下信息：1) 应用名 2) Git 仓库 URL（含 https/ssh）3) 仓库内路径 4) 目标命名空间 5) revision（分支/tag/HEAD）6) AppProject 名（默认 `default`）"

#### 2.2 复合意图编排模板（命中即用）

复合意图（用户用一句话表达多步操作）必须按下列固定模板输出，不要临场拼接：

**「创建并同步」：**

```bash
argocd app create <name> \
  --repo <url> --path <p> --revision <rev> \
  --dest-namespace <ns> --project default --upsert

argocd app sync <name> --prune --sync-option PruneLast=true
argocd app wait <name> --health --timeout 300
```

**「创建并设置自愈」（仅 Root 入口或明确需要时）：**

```bash
argocd app create <name> \
  --repo <url> --path <p> --revision <rev> \
  --dest-namespace <ns> --project default --upsert

# ⚠️ 警告：--sync-policy automated 开启后，ArgoCD 会持续协调集群状态。
# 仅当这是 Root 入口（destination.namespace=argo-root）或业务方明确
# 要求自愈时才执行；普通业务应用生产规范是手动触发 sync。
argocd app set <name> --sync-policy automated --auto-prune --self-heal
```

**「同步并等就绪」：**

```bash
argocd app sync <name> --prune --sync-option PruneLast=true
argocd app wait <name> --health --timeout 300
argocd app get <name> -o json | jq '.status.health.status, .status.sync.status'
```

**「回滚并验证」：**

```bash
argocd app history <name>
argocd app rollback <name>          # 省略 HISTORY_ID = 回上一版本
argocd app wait <name> --health --timeout 300
```

#### 2.3 危险命令二次确认（不可跳过）

下列 5 类命令属于"不可逆 / 影响范围大"的危险操作，**必须**在用户完整复述资源标识符后才生成命令：

| 危险命令 | 二次确认要求 |
|---|---|
| `argocd app delete <name>` / `argocd app delete --cascade` | 用户**完整复述** `<name>` 一次（大小写敏感） |
| `argocd app terminate-op <name>` | 同上 |
| `argocd cluster rm <ctx>` / `argocd repo rm <url>` / `argocd proj delete <name>` | 完整复述 + 显式提示「**此操作不可逆**」 |
| `argocd app set <name> --sync-policy automated --self-heal` | 询问「**这是 Root 入口（argo-root）或业务方真的需要自愈吗？**」避免误开 |
| 任何带 `--prune` / `--cascade` 标志的命令 | 询问影响范围（哪些资源会被回收） |

> **逐行展开版**（按命令一行的完整清单）见 `references/cli-commands.md` 的「危险命令清单」章节——本节是按"风险类型"归并的 5 类视图，两边数量差是合并粒度不同，不是遗漏。

**凭证约束（与 AGENTS.md 变量表一致）**：

- `ARGOCD_AUTH_TOKEN` 永远**不回显**到命令、错误信息、stdout/stderr；缺失时直接 fail 并提示"请先 `argocd login` 或 export `ARGOCD_AUTH_TOKEN`"
- `ARGOCD_SERVER` 同样**不要求用户明文粘贴**（应从 env 读，缺失则 fail）

#### 2.4 会话内状态复用（短期 in-memory）

在同一会话内，下列变量可在多条命令间自动复用（与 AGENTS.md 变量表的 `{{user.*}}` 占位符对齐）：

| 变量 | 来源 | 复用范围 |
|---|---|---|
| `app_name` | 用户首次提供的 APPNAME | 后续所有 `argocd app <verb> <app_name>` 命令 |
| `namespace` / `dest_namespace` | 首次 `app create` 的 `--dest-namespace` | 后续 `app create` / `app set` |
| `project` | 首次 `app create` 的 `--project` | 后续所有命令 |
| `repo_url` | 首次 `--repo` | 后续同仓库 `app create` |
| `revision` | 首次 `--revision` | 后续 `app sync --revision` / `app rollback` |
| `dest_server` | 首次 `--dest-server` | 后续所有命令（in-cluster 默认 `https://kubernetes.default.svc`） |

**复用规则**：

- 上条命令出现过的字段，下条命令省略时**自动沿用**
- 输出命令时**首行标注**：「复用：app_name=my-app, namespace=production」
- 跨会话**不持久**：下一会话用户必须重述（除非使用 sub-agent 跨会话传递）
- 命中 2.3 危险命令时**不复用** APPNAME——必须重新复述确认

> 完整协议与冲突优先原则见 `AGENTS.md`「会话内状态复用（短期 in-memory）」子节（含 5 条规则与凭证屏蔽边界说明）。本节是该协议在能力二的前台摘要。

#### 2.5 命令吐出前自检 checklist（11 项，来自错误表）

每条命令吐出前，**Agent 内部**必须对照下列 11 项跑一遍自检（这是给 agent 看的清单，不是给用户看的）。**任一项不通过 → 不输出命令，先修正**：

- [ ] **必填未缺**：`--dest-server` / `--repo` / `--path` / `--dest-namespace` / `--revision` 不缺失
- [ ] **Kustomize/Helm 不混用**：Kustomize 字段用 `--kustomize-*`，Helm 字段用 `--helm-*`，不可交叉
- [ ] **GitHub 版本号带 v 前缀**：未指定时自动补 `v`（如 `v3.4.2`）
- [ ] **前置 login 已确认**：`$ARGOCD_AUTH_TOKEN` / `$ARGOCD_SERVER` 已 export，否则提示 `argocd login`
- [ ] **prune 不裸用**：出现 `--auto-prune` 时**必须同时**有 `--sync-policy automated`
- [ ] **多源不强行转 CLI**：`spec.sources` 非 Helm+`$values` 模式时，回退 `kubectl apply -f`
- [ ] **下划线已替换**：`metadata.name` 含 `_` 已替换为 `-`（git 分支名 `--revision k8s_mas` 除外）
- [ ] **Root 入口必含 automated**：`destination.namespace=argo-root` 时必含 `--sync-policy automated --auto-prune --self-heal`
- [ ] **运维组件不臆加 labels**：`k8s_ops/*` 94% 无 labels，禁止补 project/profile/stack/app 四件套
- [ ] **业务应用不臆开 automated**：业务应用生产规范是手动 sync，**不主动加** `--sync-policy automated`
- [ ] **CreateNamespace 保持原值**：运维组件多为 `CreateNamespace=false`（namespace 由 initns 管理），禁止转成 `true`

> **与 cli-commands.md 的关系**：本 checklist 是「行为规则」（agent 内部约束），cli-commands.md 的「参数推断规则」是「输出规则」（命令字面如何补全）。两者**互不替代**——必须先过本 checklist，再按 cli-commands.md 补默认 flag。

### 能力三：Application Manifest 反向生成

> **分流决策（必须先做）**
>
> | 用户输入形态 | 应当走的子能力 |
> |---|---|
> | 粘贴 1 个 YAML 文本块 / `≤4` 个分散 YAML 片段 | **3.1 内联转换** |
> | 给一个目录路径、git 仓子目录、`≥5` 个文件、说"整个/批量/全部" | **3.2 批量工具** |
> | 提到"迁移 / 重建 / 备份 / 灾备 / 新集群 / 全量 / 反向生成" | **3.2 批量工具** |
> | 单个 YAML 但含 `spec.sources` 多源 | **3.1 + 回退到 `kubectl apply`** |
>
> 子能力定义：
> - **3.1 单 YAML 内联转换**：Agent 自己读 YAML，按字段映射表输出 `argocd app create ...`，无外部依赖
> - **3.2 目录批量转换**：调用 `scripts/argocd_cli_gen` 工具批量生成分层 shell 脚本 + JSON/MD 报告 + 多源回退 YAML

#### 子能力 3.1：单 YAML 内联转换

**转换前先判定层级**（决定 labels/automated/CreateNamespace 取值）：

```
源 YAML 含 spec.sources?
├─ 是 → 多源（Helm chart + Git $values 模式，约 3%）
│       → CLI 不支持，回退到 kubectl apply -f 保留 YAML
└─ 否 → 单源 Kustomize（97%）
       │
       ├─ destination.namespace == "argo-root"?
       │    └→ Root 入口（5%）：含 automated.prune+selfHeal，不含 labels
       │
       ├─ 路径或分支命中 k8s_ops/运维组件?
       │    └→ 运维组件（18%）：常含 CreateNamespace=false，多数无 labels
       │
       └─ 其他 → 业务应用（76%）：必含 labels 四件套（project/profile/stack/app），无 automated
```

**完整字段映射表：** [references/kustomize-mapping.md](references/kustomize-mapping.md)
**真实模式转换示例（含多源边界 + 命名规范）：** [references/kustomize-examples.md](references/kustomize-examples.md)

#### 子能力 3.2：目录批量转换（推荐用于 5 个以上 YAML）

调用打包好的 Python 工具，把整个 manifest 目录反向生成为可执行的 shell 脚本集合。

**首次安装依赖（一次性）：**
```bash
cd /path/to/agent_skills/skills/argocd-skill/scripts
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

**实际调用（建议 `--input` 用绝对路径，可在任意工作目录执行）：**
```bash
python -m argocd_cli_gen \
  --input  /abs/path/to/argo-apps/dly/production \
  --output ./out \
  --upsert \
  --emit-dry-run
```

**常用变体：**
```bash
# 仅匹配某个 stack 的 YAML
python -m argocd_cli_gen --input /abs/path/to/argo-apps --include "**/k8s_mas/**.yaml"

# 不生成 dry-run 副本（脚本更精简）
python -m argocd_cli_gen --input /abs/path --no-emit-dry-run

# 严格模式：有 fallback 即返回 exit 1
python -m argocd_cli_gen --input /abs/path --fail-on warning

# 每条命令间插入 sleep，避免对 argocd-server 限流
python -m argocd_cli_gen --input /abs/path --sleep 0.5
```

**输出结构（按依赖顺序）：**
```
out/
├── 00_preflight.sh                # argocd 登录与连通性校验
├── 05_infra_roots.sh              # 基础设施 root（projects/repos/initns）
├── 10_app_roots.sh                # 聚合 Root 应用
├── 20_workloads_ops.sh            # 运维组件
├── 30_workloads_business.sh       # 业务应用
├── *.dry-run.sh                   # 每个脚本对应的 --dry-run -o yaml 副本
├── 99_multisource_fallback.yaml   # CLI 不支持的多源 → kubectl apply 兜底
├── report.json                    # 机器可读报告
├── report.md                      # 人读报告（统计表 + 警告明细 + 后续操作指引）
└── run_all.sh                     # 串联入口
```

**何时调用：**
- 用户说"把这个目录的 manifest 全部转成 CLI 脚本"
- 用户说"我有一堆 ArgoCD YAML，能批量生成脚本吗"
- 用户给一个目录路径或 git 仓库子目录
- 单 YAML 数量 ≥ 5 时优先用工具而非内联转换

**工具使用手册：** [scripts/README.md](scripts/README.md)
**工具方案设计与可行性论证：** [references/batch-conversion-design.md](references/batch-conversion-design.md)

**退出码语义：**
- `0`：全部成功 → 可直接 `bash run_all.sh`
  - 注：**默认 `--fail-on=error`** 下，即便存在多源回退也是 exit 0（提示在 stderr 与 `report.md` 中），原因是回退不影响主脚本可用性
- `1`：有 fallback 且使用 `--fail-on=warning` 时 → 主脚本仍可用，额外执行 `kubectl apply -f 99_multisource_fallback.yaml`
- `2`：YAML 解析致命错误 / 输入目录下未发现任何 Application → 检查输入修复后重试
- `3`：CLI 参数错误（路径不存在、`--sleep` 为负等）

### 能力四：诊断分析（OutOfSync 根因归因）

批量扫描所有 ArgoCD Application，筛选 OutOfSync 状态 App，通过 diff 分析自动归因：

| 归因维度 | CLI 命令 | 判断依据 |
|----------|---------|---------|
| Git 新增/未部署 | `argocd app diff` | diff 中出现 `+` / `>` 行（Git 有，集群无） |
| 手动漂移（集群多出） | `argocd app diff` | diff 中出现 `-` / `<` 行（集群有，Git 无） |
| 内容不一致 | `argocd app diff` | 同时有新增和删除行 |
| 孤儿资源 | `argocd app resources` | Orphaned 列值为 Yes |

**调用方式：**
```bash
# 全量分析
python -m argocd_deploy_stats.oos_analyzer

# 只看最近 7 天 OutOfSync 的
python -m argocd_deploy_stats.oos_analyzer --days 7

# 指定项目
python -m argocd_deploy_stats.oos_analyzer --project default

# JSON 输出（供后续分析）
python -m argocd_deploy_stats.oos_analyzer --output json
```

**输出示例（Markdown）：**
```
# ArgoCD OutOfSync 根因分析

总 App 数：102，OutOfSync：12

## 归因汇总
| 原因 | 数量 |
|------|------|
| 手动漂移（集群多出 Git 没有的资源） | 7 |
| Git 新增/未部署 | 3 |
| 内容不一致 | 2 |

### 手动漂移（7 个）
- `app-1`（手动漂移; 孤儿: Pod/stale-pod）
- `app-2`
```

**工具位置：** `scripts/argocd_deploy_stats/oos_analyzer.py`
**依赖：** 仅 argocd CLI（无 Python 第三方依赖）

**归因输出字段说明：**
- `app` — 应用名称
- `cause` — 归因结果（None 表示已 Sync）
- `hasAdditions` — 是否有新增行
- `hasDeletions` — 是否有删除行
- `orphaned` — 孤儿资源列表
- `diffRc` — diff 命令退出码

> ⚠️ 注意：该工具每次运行时对每个 OOS App 执行 `argocd app resources` + `argocd app diff` 各一次（共 2 次 CLI 调用）。
> 566 App 环境按 ~10% OOS 率计，约 110 次调用，预估耗时 ~2 分钟。若 ArgoCD server 吞吐有限，可通过 `--concurrency 2` 降低并发。

### 能力五：批量操作（Batch Operations）

对指定 App 列表或筛选条件（project/label/status）批量并发执行 sync/rollback/refresh，支持 dry-run 预览和并发度控制。

**调用方式：**
```bash
# 按项目过滤并同步
python -m argocd_insight batch sync --project my-project

# 按标签过滤并回滚 Degraded 应用
python -m argocd_insight batch rollback --label env=production

# 按状态过滤并刷新
python -m argocd_insight batch refresh --status Degraded

# 操作所有应用（dry-run 预览）
python -m argocd_insight batch sync --all --dry-run

# 指定应用列表
python -m argocd_insight batch sync --apps app1 app2 app3

# 控制并发度
python -m argocd_insight batch rollback --status Degraded --concurrency 10

# JSON 输出
python -m argocd_insight batch sync --project prod --output json
```

**支持的操作：** `sync` / `rollback` / `refresh`

**筛选条件：** `--project` / `--label` / `--status` / `--apps` / `--all`（至少指定一个）

**可选参数：**
- `--dry-run` — 预览操作，不实际执行
- `--concurrency N` — 并发数（默认 5）
- `--timeout N` — 单个操作超时秒数（默认 120）
- `--output markdown|json` — 输出格式

**输出示例（Markdown）：**
```
# Batch Operation Summary

**Operation:** sync
**Total:** 15
**Succeeded:** 14
**Failed:** 1

## ✅ Succeeded
- app-1 (2.3s): sync succeeded
- app-2 (1.8s): sync succeeded

## ❌ Failed
- app-3: sync failed: timeout
```

**工具位置：** `scripts/argocd_insight/batch.py`
**依赖：** 仅 argocd CLI（无 Python 第三方依赖）

### 能力六：版本漂移检测 (Drift)

比对两个 ArgoCD 集群（或同一集群两个环境）同名 App 的 revision 差异，识别版本漂移、仅源端/目标端独有的 App。

**调用方式：**
```
python -m argocd_insight drift
python -m argocd_insight drift --from prod --to staging
python -m argocd_insight drift --project default --output json
```

**参数：**
- `--from`/`--to` — 源端/目标端标签（报告显示用）
- `--from-server`/`--to-server` — 指定 ArgoCD server URL（留空用当前 context）
- `--project` — 按项目过滤
- `--output markdown|json`

**输出维度：**
- `matched`：两端都存在的 App，按 revision 一致/漂移分组
- `sourceOnly`：仅源端有的 App
- `targetOnly`：仅目标端有的 App
- `summary`：漂移统计（总数/一致/漂移/漂移率）

**示例输出：**
```
## 漂移检测报告：源端(prod) vs 目标端(staging)

| 匹配状态 | 数量 |
|---------|------|
| revision 一致 | 42 |
| 漂移 | 8 |
| 仅源端 | 3 |
| 仅目标端 | 2 |
| 漂移率 | 16.0% |

### 漂移 App 列表
- order-service (prod: v1.2 → staging: v1.1)
- payment-gateway (prod: v2.0 → staging: v1.9)
...
```

**工具位置：** `scripts/argocd_insight/drift.py`
**依赖：** 仅 argocd CLI（无 Python 第三方依赖）

### 能力七：运行稳定性评估 (Health)

从 8 个维度对 ArgoCD 集群做全维度健康评估：App 健康率 / 同步率 / 错误率 / 部署频率 / 自动化覆盖率 / 聚合入口完整性 / 多源冗余度 / 漂移复发率，输出总分、薄弱项和改进建议。

**评分矩阵：**

| 维度 | 权重 | 数据来源 |
|------|------|---------|
| D1 App 健康率 | 20% | `argocd app list` 各 App health.status |
| D2 同步率 | 20% | `argocd app list` sync.status |
| D3 错误率 | 15% | `argocd app get` 最近事件 |
| D4 部署频率 | 10% | 最近 N 天 sync 操作计数 |
| D5 自动化覆盖 | 10% | `argocd app get` syncPolicy.automated |
| D6 聚合入口完整性 | 10% | 检查 Root App 的 automated 配置 |
| D7 多源冗余度 | 5% | spec.sources 数量分布 |
| D8 漂移复发率 | 10% | 连续同步后漂移复发的 App 比例 |

**调用方式：**
```
python -m argocd_insight health
python -m argocd_insight health --project default
python -m argocd_insight health --output json
python -m argocd_insight health --detail
```

**输出：** 总分 + 等级（critical/warning/info）+ 各维度评分 + 薄弱项分析 + 改进建议汇总

**示例输出：**
```
## ArgoCD 稳定性评估报告

**总分：72/100 — Warning**

| 维度 | 得分 | 状态 |
|------|------|------|
| D1 App 健康率 | 85 | ✅ Good |
| D2 同步率 | 90 | ✅ Good |
| D3 错误率 | 60 | ⚠️ Warning |
| D4 部署频率 | 45 | ❌ Critical |
| D5 自动化覆盖 | 70 | ⚠️ Warning |
| D6 聚合入口完整性 | 80 | ✅ Good |
| D7 多源冗余度 | 90 | ✅ Good |
| D8 漂移复发率 | 65 | ⚠️ Warning |

### 薄弱项详细分析
...
```

**工具位置：** `scripts/argocd_insight/health.py`
**依赖：** 仅 argocd CLI（无 Python 第三方依赖）

### 能力八：Git 源健康检查 (Repo Health)

检查 ArgoCD 所有注册仓库的连接状态（ArgoCD server 侧连接 + Agent 侧 git ls-remote 可达性），统计分支使用情况，输出健康报告。

**检查维度：**
- ArgoCD server 侧连接状态（`connectionState`）
- Agent 侧 git ls-remote 可达性（区分凭证不可达与真正不可达）
- 仓库按 App 使用统计（关联 App 数、使用中的 revision 列表）

**调用方式：**
```
python -m argocd_insight.repo_health
python -m argocd_insight.repo_health --output json
python -m argocd_insight.repo_health --project default
```

**输出：** 仓库健康总览表（仓库名、App 数、连接状态、Agent 可达性、备注）

**示例输出：**
```
## Repo 健康检查报告

| 仓库 | App 数 | Server 连接 | Agent 可达性 | 备注 |
|------|--------|-------------|-------------|------|
| github.com/team/apps.git | 23 | ✅ Connected | ✅ Reachable | |
| gitlab.internal/platform.git | 5 | ✅ Connected | ❌ Unreachable | 凭证可能过期 |
| bitbucket.org/legacy.git | 2 | ❌ Disconnected | ❌ Unreachable | 仓库已归档 |
| gitea.dev/tools.git | 8 | ✅ Connected | ⚠️ Partial | 部分分支不存在 |
```

**工具位置：** `scripts/argocd_insight/repo_health.py`
**依赖：** 仅 argocd CLI + git CLI（无 Python 第三方依赖）

### 能力九：配置合规检查 (Compliance)

检查 ArgoCD App 的配置风险点：automated 无 retry、automated 无 self-heal、automated 无 PruneLast、部署到系统 namespace 等，输出风险数 + 严重级别 + 具体修复命令。

**检查规则：**

| 规则 | 严重级别 | 说明 | 修复命令 |
|------|---------|------|---------|
| automated-no-retry | medium | 开了 automated 但没有 retry | `argocd app set <app> --sync-policy automated --sync-option Retry` |
| automated-no-selfheal | high | 开了 automated 但没有 self-heal | `argocd app set <app> --auto-prune --self-heal` |
| automated-no-prune | low | 开了 automated 但没有 auto-prune | `argocd app set <app> --auto-prune` |
| prune-last-not-automated | low | PruneLast=true 但非 automated | 配置矛盾，建议对齐 |
| system-namespace | high | 部署到系统 namespace | `argocd app set <app> --dest-namespace <business-ns>` |

**调用方式：**
```
python -m argocd_insight.compliance
python -m argocd_insight.compliance --severity high
python -m argocd_insight.compliance --output json
```

**参数：** `--severity` — 最低严重级别（默认 low），`--output markdown|json`

**输出：** 按严重级别分组的风险列表 + 每个违规 App 的详细风险 + 具体修复命令

**示例输出：**
```
## Config Compliance Report

| 严重级别 | 违规数 | App 列表 |
|---------|--------|---------|
| 🔴 High | 4 | payment-gateway, order-svc, auth-svc, notification-svc |
| 🟡 Medium | 7 | user-svc, inventory-svc, ... |
| 🟢 Low | 12 | ... |

### 🔴 High: automated-no-selfheal (4 apps)
- payment-gateway → `argocd app set payment-gateway --auto-prune --self-heal`
- order-svc → `argocd app set order-svc --auto-prune --self-heal`
...
```

**工具位置：** `scripts/argocd_insight/compliance.py`
**依赖：** 仅 argocd CLI（无 Python 第三方依赖）

### 能力十：批量自动修复 (Autofix)

基于诊断分析结果（diagnose 输出的 JSON），自动执行 sync/rollback 修复可修复的问题 App，支持 dry-run 预览和严重级别过滤。

**自动修复逻辑：**
- OutOfSync → `argocd app sync --prune`
- Degraded → `argocd app rollback`（回滚到上版本）
- Missing → 跳过（需人工确认）
- Unknown → 跳过

**调用方式：**
```
python -m argocd_insight autofix diagnosis.json
python -m argocd_insight autofix diagnosis.json --dry-run
python -m argocd_insight autofix diagnosis.json --severity high
```

**参数：**
- `diagnosis` — 诊断结果 JSON 文件路径
- `--dry-run` — 预览修复，不实际执行
- `--severity` — 最低修复级别（critical/high/medium/low）

**输出：** 修复汇总（成功数、跳过数、失败数）+ 每个 App 的修复详情

**示例输出：**
```
## Autofix 结果汇总

| 状态 | 数量 |
|------|------|
| ✅ 修复成功 | 5 |
| ⏭️ 跳过 | 3 |
| ❌ 修复失败 | 1 |

### ✅ 修复成功
- payment-gateway: sync succeeded (2.3s)
- order-svc: sync succeeded (1.8s)
- auth-svc: rollback to v3 succeeded (2.1s)
...

### ❌ 修复失败
- notification-svc: sync failed — timeout
  建议手动检查：`argocd app get notification-svc`
```

**工具位置：** `scripts/argocd_insight/autofix.py`
**依赖：** 仅 argocd CLI（无 Python 第三方依赖）

### 能力十一：变更影响分析 (Impact)

执行 sync/rollback 前预览操作影响范围：资源列表、依赖关系、风险评估、预计耗时。属于只读操作，不修改任何状态。

**调用方式：**
```
python -m argocd_insight impact my-app sync
python -m argocd_insight impact my-app rollback 3
python -m argocd_insight impact my-app sync --output json
```

**参数：**
- `app` — 应用名称（位置参数）
- `operation` — 操作类型（sync/rollback，位置参数）
- `history_id` — 回滚历史 ID（rollback 操作可指定，位置参数）
- `--output markdown|json`

**输出维度：**
- 当前应用状态（health/sync/revision）
- 受影响资源列表（kind/name/namespace/risk）
- 依赖关系（parent/child App，含跨 namespace 依赖）
- 风险评估（高风险项警告）
- 操作建议 + 预计耗时

**示例输出：**
```
## 变更影响分析：payment-gateway — sync

### 当前状态
- Health: Healthy
- Sync: OutOfSync
- Revision: v2.0

### 受影响资源（共 12 个）
| Kind | Name | Namespace | Risk |
|------|------|-----------|------|
| Deployment | payment-gateway | production | low |
| Service | payment-gateway-svc | production | low |
| ConfigMap | payment-gateway-config | production | medium |
| Secret | db-credentials | production | high |

### 依赖关系
- ⬆ parent: infra-root → ecommerce-production-root
- ⬇ child apps: order-svc (depends on payment-gateway:ready)

### 风险评估
- 🔴 Secret `db-credentials` 即将更新 — 确认不含破坏性变更
- ⚠️ order-svc 有部署依赖 — sync 完成后再触发 order-svc sync

### 建议
预计耗时：30-60s。建议先 sync 后观察 2 分钟再操作 order-svc。
```

**工具位置：** `scripts/argocd_insight/impact.py`
**依赖：** 仅 argocd CLI（无 Python 第三方依赖）

## App-of-Apps 与层级分布（基于 argoapp 仓库 97 YAML 全样本）

生产环境常用 App-of-Apps 多级架构管理大量应用：

| 层级 | 真实占比 | YAML 示例 | 用途 | namespace |
|------|---------|----------|------|-----------|
| 基础设施 Root（管理 root 的 root） | <1% | `projects.yaml`、`repos.yaml`、`initns/namespace.yaml` | 自启动初始化 | `argo-root` |
| 聚合入口 Root | 5% | `{project}-{profile}-{git_branch}.yaml` | 指向子目录，聚合子应用 | `argo-root` |
| 业务应用 | 76% | `{stack}-{app}.yaml` | 每个微服务一个文件 | 业务命名空间（如 `production`） |
| 运维组件 | 18% | `prometheus.yaml`/`loki.yaml`/`redis.yaml` | 监控/日志/中间件 | `ops`/`loki`/`kube-system` 等 |

**关键约束：**
- 业务应用的 `metadata.name` 与文件命名都不允许 `_`，需替换为 `-`（但 `targetRevision` 的 git 分支名保留原样）
- 聚合 Root 必含 `syncPolicy.automated.prune+selfHeal`；业务/运维通常**只有 `PruneLast=true`**，**不开 automated**
- 运维组件多含 `CreateNamespace=false`（namespace 由 initns 单独管理）

## 提示词示例

### 安装相关
- "帮我装一下 argocd CLI"
- "安装 ArgoCD 3.4.2 到这台机器上"
- "在 Docker 容器里安装最新版本的 argocd"
- "我要给 CI runner 装一个 argocd 客户端"
- "离线环境怎么装 argocd CLI"

### 命令生成相关（自然语言 → CLI）
- "帮我创建一个 ArgoCD 应用 my-app，从 main 分支部署到 prod 命名空间"
- "同步一下 my-app"
- "把 my-app 回滚到上一个版本"
- "看看 my-app 有没有同步"
- "给我写一个自动同步 ArgoCD 应用的脚本"
- "帮我查一下所有 ArgoCD 应用列表"
- "argocd login 怎么用 token 登录"
- "怎么删除一个 ArgoCD 应用还顺便清理资源"

### 子能力 3.1：单 YAML 内联转换（粘贴 1 个 YAML）

**A. 通用触发短语**
- "把这个 ArgoCD YAML 转成 CLI 命令"
- "这段 ArgoCD manifest 怎么用命令行重建？"
- "我有个 Application 资源描述，给我等价的 argocd CLI"
- "粘贴的这段 YAML 转 CLI"
- "argocd app create 怎么写？我贴 YAML 给你"
- "把下面这个 Application 资源对应的 argocd 命令打出来"
- "这个 YAML 怎么用命令行创建应用？"
- "看一下我这个 spec.source 翻译成 argocd 命令是什么样"

**B. 按层级特化**
- "这是个 root 入口 / 聚合应用 YAML，转一下 CLI" → 必含 `--sync-policy automated --auto-prune --self-heal`
- "App-of-Apps 入口 Application 怎么转命令"
- "把这个 `projects.yaml` / `repos.yaml` 转 CLI"（基础设施 Root，namespace=`argo-root`）
- "业务应用 YAML 转命令，我贴给你"（必含 labels 四件套，无 automated）
- "k8s_ops 下面的 prometheus.yaml / loki.yaml 怎么转 CLI"（运维组件，多含 `CreateNamespace=false`）

**C. 按 kustomize 特性**
- "这个 YAML 的 `kustomize.images` 怎么映射到 CLI flag"
- "kustomize.commonLabels / nameSuffix / replicas 怎么转命令"
- "kustomize.patches / components 字段 CLI 支持吗？怎么转？" → **回退到 `kubectl apply -f`**

**D. 多源边界**
- "这个 loki / tempo / grafana YAML 怎么转 CLI"（`spec.sources` 多源）
- "这个应用是多源 Helm + `$values` 模式，CLI 写不出来怎么办" → **回退方案 + 解释原因**
- "我这个 Application 里有 `spec.sources`，argocd CLI 怎么写？"

### 子能力 3.2：目录批量转换（整目录 / 多文件 → shell 脚本）

**A. 直接给目录**
- "把 `argo-apps/dly/production` 整个目录的 manifest 转成 CLI 脚本"
- "我给你一个 ArgoCD app 目录，反向生成 shell 脚本"
- "把这个 git 仓库子目录的 ArgoCD YAML 全部生成 argocd app create 命令"
- "我有一堆 ArgoCD Application YAML，能批量转吗？"
- "我有 30+ 个 Application YAML，逐个写太累，能批量？"
- "整目录反向生成 argocd app create 脚本"
- "把 `/path/to/argoapp/` 下面所有 manifest 跑一遍生成命令"

**B. 场景化触发（迁移 / 灾备 / 备份）**
- "集群迁移：把现存所有 ArgoCD 应用 manifest 转成命令脚本"
- "灾备重建 ArgoCD 应用：从 YAML 目录生成命令"
- "新集群初始化：跑一遍历史所有 Application 创建命令"
- "ArgoCD 配置脚本化 / 导出 shell"
- "把 GitOps 仓库的 Application 反向生成 CLI 脚本"
- "运维交接：把 ArgoCD 应用配置 dump 成可执行命令"
- "把 prd / staging / 多套环境的 Application 一键生成创建脚本"

**C. 期望明确产物**
- "我想要 `run_all.sh` 串联入口 + 每个层级一个脚本"
- "生成脚本要带 dry-run 副本，能灰度跑一遍再上"
- "顺便给我一份转换报告 / report.md"

**任一上述触发 → Agent 应直接调用：**
```bash
python -m argocd_cli_gen --input <dir> --output ./out --upsert --emit-dry-run
```
然后向用户展示 `report.md` 摘要、回退条目数，以及 `run_all.sh` 的使用方法。

### 能力四：诊断分析（OutOfSync 根因归因）

**触发短语：**
- "哪些 App 是 OutOfSync 的？什么原因？"
- "帮我批量分析 OutOfSync 根因"
- "看看有没有漂移的 App"
- "OutOfSync 归因，按原因分类"
- "有没有手动漂移的 App 和孤儿资源？"
- "哪些 App Git 有但集群没有？"
- "分析一下 production 项目的 OOS 情况"
- "给我一份 OutOfSync 诊断报告（JSON 格式）"
- "批量查所有 OutOfSync 的 App 是什么原因导致的"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_deploy_stats.oos_analyzer [--project <name>] [--days N] [--output json]
```
然后向用户展示归因汇总表 + 每种原因的 App 列表。

### 能力五：资源成本估算

查询 ArgoCD App 的部署资源（CPU/Memory requests），估算运行成本。

**调用方式：**
```bash
# 全量估算
python -m argocd_insight cost

# 按项目过滤
python -m argocd_insight cost --project prod

# JSON 输出
python -m argocd_insight cost --output json
```

**输出示例（Markdown）：**
```
# ArgoCD 资源成本估算报告

生成时间：2026-07-01T12:00:00+00:00
成本模型：CPU $0.042/vCPU-hr，Memory $0.0047/GiB-hr

## 总览

| 指标 | 值 |
|------|-----|
| App 总数 | 50 |
| CPU 总量 | 32.5 cores |
| Memory 总量 | 64.2 GiB |
| 副本总数 | 128 |
| **每小时成本** | **$48.72** |
| **预估月成本** | **$35,118.24** |

## Top 10 高成本 App

| 排名 | App | Project | CPU (cores) | Memory (GiB) | 副本 | 月成本 |
|------|-----|---------|-------------|--------------|------|--------|
| 1 | payment-service | prod | 8.0 | 16.0 | 12 | $2,880.00 |
| 2 | order-service | prod | 4.0 | 8.0 | 8 | $1,440.00 |
```

**工具位置：** `scripts/argocd_insight/cost.py`
**依赖：** 仅 argocd CLI（无 Python 第三方依赖）

**触发短语：**
- "帮我看看 ArgoCD 里部署的资源成本"
- "估算一下 production 环境的运行成本"
- "哪些 App 消耗资源最多？"
- "给我一份资源成本报告"
- "CPU 和 Memory 用了多少？"
- "成本估算，按项目分组"
- "哪个服务最烧钱？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight cost [--project <name>] [--output json]
```
然后向用户展示成本概览 + Top 10 高成本 App 列表。

### 能力六：多集群对比报告

比对两个 ArgoCD 集群的 App 配置、资源、健康状态差异。

**调用方式：**
```bash
# 全量对比
python -m argocd_insight multi-cluster --from-server <server-a> --to-server <server-b>

# 按项目过滤
python -m argocd_insight multi-cluster --from-server <a> --to-server <b> --project prod

# JSON 输出
python -m argocd_insight multi-cluster --from-server <a> --to-server <b> --output json
```

**对比维度：**
- App 存在性：只在 A / 只在 B / 两边都有
- 版本漂移：revision 是否一致
- 健康状态：Healthy / Degraded / Missing
- 同步状态：Synced / OutOfSync
- 资源配置：CPU/Memory requests 差异

**触发短语：**
- "对比一下 prod 和 staging 两个集群的 App"
- "多集群对比，看看哪些 App 不一致"
- "检查两个环境的配置差异"
- "prod 和 staging 的资源差异"
- "哪些 App 只在一个集群有？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight multi-cluster --from-server <a> --to-server <b> [--project <name>] [--output json]
```
然后向用户展示对比概览 + 漂移/差异详情。

### 能力七：报告推送（飞书 / 钉钉 / Slack）

将诊断、成本、对比等报告推送到即时通讯渠道。

**调用方式：**
```bash
# 管道输入（推荐）：将其他命令的输出直接推送
python -m argocd_insight cost --output json | python -m argocd_insight report-push --webhook <url>

# 文件输入
python -m argocd_insight report-push --file report.md --webhook <url>

# 指定渠道（自动检测）
python -m argocd_insight report-push --file report.md --channel feishu --webhook <url>

# 自定义标题
python -m argocd_insight cost --output json | python -m argocd_insight report-push --webhook <url> --title "生产环境成本报告"
```

**注意事项：**
- 不指定 `--channel` 时自动从 Webhook URL 检测渠道（feishu/dingtalk/slack）
- 不指定 `--file` 时从 stdin 读入
- 支持 Markdown / JSON 两种消息样式

**触发短语：**
- "把这个报告推送到飞书"
- "把成本报告发到钉钉"
- "推送诊断报告到 Slack"
- "把对比报告结果通知给我"
- "把报告通过管道发给 Webhook"
- "推送报告，自动检测渠道"
- "报告发到群机器人"
- "帮我定时把成本报告推送到飞书"

**任一触发 → Agent 应直接执行（推荐管道模式）：**
```bash
python -m argocd_insight cost --output json | python -m argocd_insight report-push --webhook <url>
```
或使用文件输入：
```bash
python -m argocd_insight report-push --file report.md --webhook <url>
```

**工具位置：** `scripts/argocd_insight/report_push.py`
**依赖：** 仅 Python 标准库（urllib + json）

### 能力八：批量操作（Batch Operations）

**触发短语：**
- "批量同步所有 OutOfSync 的 App"
- "把所有 Degraded 的应用回滚到上一版本"
- "刷新 production 项目下所有 App"
- "把 label 为 env=production 的 App 全部同步"
- "批量操作，先 dry-run 预览一下"
- "并发执行 sync，控制并发数为 10"
- "给我一份批量操作报告（JSON 格式）"
- "按项目过滤，批量回滚"
- "把状态为 Missing 的应用全部刷新"
- "给指定列表的 App 批量执行 sync"

**任一触发 → Agent 应直接调用：**
```bash
# 常用变体
python -m argocd_insight batch sync --status OutOfSync
python -m argocd_insight batch rollback --status Degraded
python -m argocd_insight batch refresh --all --dry-run
python -m argocd_insight batch sync --project prod --concurrency 10 --output json
```
然后向用户展示批量操作汇总结果（成功数 / 失败数 / 详情列表）。

### 能力九：Application 配置模板生成（Scaffold）

> **注意：** 本能力是**从零生成** YAML+CLI（正向），区别于子能力 3.1 的**从已有 YAML 反向生成** CLI。
> 适合新 App 创建、快速原型、以及 CI/CD Pipeline 中的模板化创建。

从零快速生成 ArgoCD Application YAML 和等价 CLI 命令，基于 4-tier 模型自动填充最佳实践默认值。

**调用方式：**
```bash
# 业务应用（手动 sync，自动 CreateNamespace=true）
python -m argocd_insight scaffold my-app \
  --tier business --namespace production --project default \
  --repo https://github.com/org/repo.git --path apps/my-app

# Root 聚合入口（auto sync + auto-prune + self-heal）
python -m argocd_insight scaffold my-root \
  --tier root --namespace argo-root \
  --repo https://github.com/org/repo.git --path apps/root

# 运维组件（CreateNamespace=false）
python -m argocd_insight scaffold prometheus \
  --tier ops --namespace ops \
  --repo https://github.com/org/repo.git --path monitoring/prometheus

# Helm 源（--source-type helm + --helm-chart + --helm-values）
python -m argocd_insight scaffold nginx \
  --tier business --namespace web --repo https://charts.nginx.org \
  --source-type helm --helm-chart nginx-ingress \
  --helm-values values/prod.yaml

# 列出可用层级
python -m argocd_insight scaffold --list-tiers

# JSON 输出
python -m argocd_insight scaffold my-app --tier business \
  --repo https://github.com/org/repo.git --path apps/my-app \
  --output json
```

**4-tier 模型：**
| Tier | 说明 | 默认 Namespace | Sync Policy | CreateNamespace | Labels |
|------|------|---------------|-------------|-----------------|--------|
| root | 聚合入口 Root | argo-root | automated | true | - |
| business | 业务应用 | 需指定 | manual | true | project, profile, stack, app |
| ops | 运维组件 | ops | manual | false | - |
| infra_root | 基础设施 Root | argo-root | manual | false | - |

**触发短语：**
- "帮我生成一个业务 ArgoCD 应用模板，名字叫 my-app"
- "用 scaffold 创建一个 ArgoCD 应用，从 main 到 prod"
- "创建一个 Root 聚合入口的 Application YAML"
- "生成一个运维组件模板，比如 Prometheus"
- "scaffold 一个 Helm 源的应用"
- "看下 4-tier 模型有哪些层级"
- "scaffold 一个 my-app，输出 JSON"
- "帮我生成个 ArgoCD 应用，用 scaffold --tier business"
- "我要快速创建个新 App，走 scaffold"
- "scaffold 支持哪些层级？--list-tiers 看看"
- "生成一个带 labels 业务应用模板"
- "创建一个 infra_root 基础设施模板，namespace 设 argo-root"

**任一触发 → Agent 应直接调用：**
```bash
# 确定 tier + 必填参数后调用
python -m argocd_insight scaffold <name> --tier <tier> --repo <url> [--path <path>] [--output json]
```
然后向用户展示生成的 YAML + CLI 命令。如果有警告（tier 参数不匹配等），一并提示。

**工具位置：** `scripts/argocd_insight/scaffold.py`
**依赖：** 仅 Python 标准库（无第三方依赖）

### 能力十：版本漂移检测 (Drift)

**触发短语：**
- "比对一下 prod 和 staging 集群的版本漂移"
- "看看哪些 App 在不同环境 revision 不一致"
- "版本漂移检测，对比源端和目标端"
- "哪些 App 漂移了？漂移率多少？"
- "检查两个 ArgoCD 集群的版本一致性"
- "多集群灾备检查：revision 对比"
- "drift 检测：看下 staging 跟 prod 的差异"
- "帮我做版本漂移对比，输出 JSON"
- "只有源端集群有的 App 有哪些？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight drift [--from <label>] [--to <label>] [--project <name>] [--output json]
```
然后向用户展示漂移统计概览（整体漂移率）+ 漂移 App 列表 + 仅源端/目标端 App 列表。

### 能力十一：运行稳定性评估 (Health)

**触发短语：**
- "帮我看看 ArgoCD 集群整体健康度"
- "运行稳定性评估，8 维度打分"
- "ArgoCD 健康检查，哪些维度有问题？"
- "评估一下生产环境的 ArgoCD 稳定性"
- "看看自动化覆盖率和聚合入口完整性"
- "稳定性评估，输出薄弱项和改进建议"
- "ArgoCD 健康度打分，总分多少？"
- "部署频率统计，哪些 App 长期不部署？"
- "health 检查，给个总分和具体建议"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight health [--project <name>] [--output json]
```
然后向用户展示总分 + 各维度评分表 + 薄弱项详细分析 + 改进建议汇总。若输出为 markdown，直接展示表格；若为 JSON，用表格呈现再附注原始数据。

### 能力十二：Git 源健康检查 (Repo Health)

**触发短语：**
- "检查一下 Git 仓库连接状态"
- "Git 源健康检查，哪些仓库有问题？"
- "repo 健康检查：连接状态和分支可达性"
- "看看 ArgoCD 注册的仓库都健康吗"
- "仓库健康报告，哪些仓库不可达？"
- "repo-health 检查，输出 JSON"
- "检查所有 repo 的连通性"
- "Git 仓库认证是否正常？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight.repo_health [--project <name>] [--output json]
```
然后向用户展示仓库健康总览表（仓库名、App 数、连接状态、Agent 可达性）。对不可达仓库给出排查建议。

### 能力十三：配置合规检查 (Compliance)

**触发短语：**
- "检查 ArgoCD App 配置合规性"
- "合规检查：哪些 App 开了 automated 但没有 retry？"
- "看看哪些 App 没有配 self-heal"
- "配置风险检查，只看高风险项"
- "syncPolicy 风险分析"
- "哪些 App 部署到了系统 namespace？"
- "compliance 检查，输出 JSON"
- "帮我检查一下配置有没有风险"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight.compliance [--severity high] [--output json]
```
然后向用户展示风险总览（按严重级别分组）+ 每类风险的 App 列表 + 具体修复命令。若用户想修复，转交能力十四 autofix。

### 能力十四：批量自动修复 (Autofix)

**触发短语：**
- "帮我自动修复诊断出来的问题 App"
- "基于诊断结果自动修复 OutOfSync 的 App"
- "自动修复：先 dry-run 看看会动哪些"
- "autofix：修复 low/medium 风险的问题"
- "批量修复诊断结果，只看 high 以上的"
- "诊断完以后自动修复一下"
- "自动修复 diagnosis.json，干跑预览"
- "修复所有 OutOfSync 和 Degraded 的 App"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight autofix <diagnosis.json> [--dry-run] [--severity high]
```
然后向用户展示修复汇总（成功数、跳过数、失败数）+ 每个 App 的修复详情。若用户未提供 diagnosis.json，先用 `python -m argocd_insight diagnose --output json > diagnosis.json` 生成。

### 能力十五：变更影响分析 (Impact)

**触发短语：**
- "先看看 sync my-app 会影响哪些资源"
- "操作前预览：rollback my-app 的风险"
- "变更影响分析，做之前先评估"
- "impact 分析：sync 这个 App 会动到什么？"
- "执行前检查：哪些依赖会被影响？"
- "预览一下 sync 操作的影响范围"
- "rollback 到版本 3 的影响分析"
- "风险评估：当前操作有什么风险？"
- "这个操作预计需要多久？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight impact <app> <sync|rollback> [history_id] [--output json]
```
然后向用户展示操作影响分析：当前状态 → 受影响资源 → 依赖关系 → 风险评估 → 操作建议。

### 可观测与自进化
- "分析这次运行的轨迹"
- "看看有哪些性能瓶颈"
- "经验沉淀，把分析结果写回"
- "SkillOpt 推荐一下这次用什么参数"
- "检查执行效率"
- "轨迹报告，输出 JSON"

## 常见错误

| 错误 | 正确处理 |
|------|---------|
| 缺少 --dest-server | 必须指定目标集群地址，不可省略 |
| 用 --helm-set 处理 Kustomize 参数 | Kustomize 用 `--kustomize-*`，Helm 用 `--helm-*`，不可混用 |
| 版本号不带 v 前缀 | GitHub Release tag 需要 v 前缀（v3.4.2），不指定则自动补全 |
| 未先 login 就操作 | 同步/回滚/删除等操作前要求用户先 `argocd login` |
| `--auto-prune` 缺少 `--sync-policy automated` | prune 只能在 automated 模式下使用，需同时指定 |
| 强行将 `spec.sources` 多源 YAML 转 CLI | argocd CLI 不支持多源 `$values` 引用；**回退到 `kubectl apply -f`** 保留 YAML |
| `metadata.name` 含下划线直接传入 CLI | argocd 应用名不允许 `_`，转换时需替换为 `-`（但 `--revision k8s_mas` 等 git 分支名保留下划线） |
| Root 入口漏 `automated` | `destination.namespace=argo-root` 必含 `--sync-policy automated --auto-prune --self-heal` |
| 运维组件错加 labels | k8s_ops 下 94% 应用无 labels，转换时不应臆造四件套 |
| 业务应用错开 automated | 业务应用生产规范是手动触发 sync，**勿臆加 automated** |
| 把 `CreateNamespace=false` 转成 `=true` | 运维组件 namespace 由 initns 单独 Application 管理，必须保持 `false` |
| `argocd login` 因 context path / insecure 失败 | **不回退放弃**，改用 HTTP API `/api/v1/session` 获取 token + `python -m argocd_api` 执行操作（见 0.4） |
| 运行时 CLI 命令失败仅报错、不自动回退 API | Agent **必须**自动输出等价的 `python -m argocd_api` 命令重试。同步失败 → `python -m argocd_api sync`，查看失败 → `python -m argocd_api get`，以此类推（见 0.6） |
| OutOfSync 分析时 `argocd app diff` 执行超时 | 默认 timeout=30s，可追加 `--concurrency 2` 降低并发；diff 输出为空时归因为"未知差异" |
| 孤儿资源检测基于 tabular 输出列尾 `Yes` | 若 ArgoCD 版本升级后 Orphaned 列格式变化，改为解析 `argocd app resources --output json` 的 orphaned 字段 |
| 漂移对比时两个 server 地址均未设 | `--from-server` 和 `--to-server` 至少设一个；均留空时默认用当前 context 做单向对比 |
| 漂移检测的 `--from` 和 `--to` 标签颠倒 | 标签仅用于报告显示，不影响对比逻辑，但会误导用户阅读。**按约定**：`--from` 为源端（参考基准），`--to` 为目标端（被比较方） |
| health 评估结果被误解为"集群"健康 | 评估对象是 ArgoCD 集群的 App 运行状况，**非 K8s 集群本身**。不覆盖 node/pod/etcd 等基础设施层 |
| repo_health 的 Agent 侧 git ls-remote 失败直接报错 | git ls-remote 失败可能是凭证问题（SSH key 过期 / token 失效），**先检查凭证再报不可达**。输出注明可能原因 |
| compliance 修复命令直接自动执行 | 合规修复建议**仅作为输出展示**，不自动执行。如需自动修复，转交 autofix 能力并让用户显式确认 |
| autofix 在 dry-run 模式下执行了实际操作 | **禁止**：带 `--dry-run` 时只预览、不下发。生产环境 `--dry-run` 是默认行为，用户确认后才移除 |
| impact 分析依赖缺失导致分析不完整 | 变更影响分析需要当前 context 能访问目标 App 的 K8s 资源。**先验证权限**，如果 `argocd app get` 不可用则提示受限模式 |
| autofix 直接执行诊断结果而未让用户确认 | **必须先展示 dry-run 结果，询问用户是否继续。** 直接执行可能造成业务中断 |

## 参考资料

- [ArgoCD CLI 安装文档](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- [ArgoCD CLI 命令参考](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd/)
- [ArgoCD Application CRD 规范](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/)
- [GitHub Release 页面](https://github.com/argoproj/argo-cd/releases)
