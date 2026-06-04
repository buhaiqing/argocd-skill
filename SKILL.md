---
name: argocd-skill
description: |
  ArgoCD CLI 全流程技能。Use when the user wants to:
  (1) 安装 / 升级 argocd CLI（含跨平台 Linux/macOS/Windows/Docker、指定版本、离线包）；
  (2) 用自然语言生成 argocd CLI 命令（app create / sync / rollback / get / list / login 等 20 个高频操作）；
  (3) 把 1 个 ArgoCD Application YAML（spec.source / spec.sources / kustomize / helm / syncPolicy / App-of-Apps Root）翻译成等价的 `argocd app create` 命令；
  (4) 把整个 manifest 目录（如 argoapp 仓库、argo-apps/dly/production 等）批量反向生成 shell 脚本（迁移 / 重建 / 备份 / 灾备 / 新集群初始化 / GitOps 配置脚本化场景），调用内置工具 `python -m argocd_cli_gen`；
  (5) 处理 ArgoCD CLI 不支持的边界（多源 spec.sources $values、kustomize.patches/components 等），引导用户回退到 `kubectl apply -f` 兜底方案。
  Trigger keywords: argocd, ArgoCD, app of apps, App-of-Apps, Application YAML, manifest 转 CLI, argocd app create, kustomize, multi-source, 多源, 反向生成, 批量转换, 迁移 ArgoCD, GitOps, kubectl apply 兜底.
allowed-tools: [Read, Write, Bash, Grep, Glob]
---

# ArgoCD CLI Skill

## 概述

为运维智能体提供 ArgoCD CLI 的三项核心能力。

## 何时使用

- 用户说"装一下 argocd"、"帮我安装 ArgoCD CLI"
- 用户描述操作意图（"创建一个应用"、"同步"、"回滚"等）需要生成对应 CLI 命令
- 用户给了一个 ArgoCD Application YAML 需要转换为 CLI 命令
- **用户给了一个 manifest 目录**，要批量反向生成 shell 脚本（迁移、备份、重建场景）
- 用户编写 CI/CD 脚本中需要 argocd 命令

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

## 参考资料

- [ArgoCD CLI 安装文档](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- [ArgoCD CLI 命令参考](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd/)
- [ArgoCD Application CRD 规范](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/)
- [GitHub Release 页面](https://github.com/argoproj/argo-cd/releases)
