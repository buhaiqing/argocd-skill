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

**完整命令表和示例详见：** [references/cli-commands.md](references/cli-commands.md)

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
