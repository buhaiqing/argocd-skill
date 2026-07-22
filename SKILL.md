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

# ArgoCD CLI Skill（黄金技能重构版）

## 一、适用边界（什么场景用，什么场景不用）

### ✅ 适用场景
- 用户明确提到 "argocd"、"ArgoCD"、"argo" 相关操作
- 需要安装/升级/配置 argocd CLI 二进制
- 将自然语言操作意图转换为具体 CLI 命令
- 将 ArgoCD Application YAML 转换为 `argocd app create` 命令
- 批量处理 manifest 目录（≥5 个 YAML 文件）
- CLI 命令执行失败，需要 HTTP API 回退
- OutOfSync 诊断、版本漂移检测、健康评估等运维分析
- 批量 sync/rollback/refresh 操作
- 配置合规检查、成本估算、自动修复
- 执行轨迹记录、分析经验提炼、自进化写回、离线触发（定时/阈值/会话结束）
- 历史轨迹分析、性能瓶颈识别、参数优化建议

### ❌ 不适用场景
- 用户要求操作 **Kubernetes 原生资源**（Deployment/Service 等）但**未提及 ArgoCD** → 让路给 k8s skill
- 用户要求 **Helm 直接操作**（helm install/upgrade）而非通过 ArgoCD → 让路给 helm skill
- 用户要求 **Kustomize 本地构建**（kustomize build）而非 ArgoCD 应用 → 让路给 kustomize skill
- 用户要求 **编写 Application YAML** 而非转换为 CLI 命令 → 这是 YAML 编写任务，非本 Skill 核心
- 用户要求 **ArgoCD 服务端安装/配置**（argocd-server 部署）→ 这是集群安装，非 CLI 操作
- 用户要求 **修改 ArgoCD 系统配置**（ConfigMap/CRD 级别）→ 需要集群管理员权限，超出 CLI 范围

---

## 二、已知死法（失败机制编码）

### 死法 1：CLI 命令未登录就执行
- **触发条件**：`argocd app create/sync/rollback/delete` 等操作前未执行 `argocd login`
- **失败表现**：`FATA[0000] rpc error: code = Unauthenticated desc = no session information`
- **根因**：argocd CLI 需要有效 token/session，不像 kubectl 有 kubeconfig
- **避免策略**：每次会话首条命令前执行开机自检协议（见第三节）

### 死法 2：应用名包含下划线 `_`
- **触发条件**：YAML 中 `metadata.name: my_app` 或用户输入 `app_name=my_app`
- **失败表现**：`FATA[0000] application name "my_app" contains invalid character '_'`
- **根因**：ArgoCD 应用名只允许 `[a-z0-9.-]`，下划线是非法字符
- **避免策略**：**强制替换逻辑**：所有 `metadata.name` 在传入 CLI 前必须 `s/_/-/g`

### 死法 3：混淆 Kustomize 和 Helm 参数
- **触发条件**：YAML 中是 Kustomize 配置，但 CLI 用了 `--helm-set`；或反之
- **失败表现**：参数不生效，或 `--helm-set` 报错（非 Helm 应用）
- **根因**：`spec.source.kustomize` 和 `spec.source.helm` 是两个独立分支，flag 前缀不同
- **避免策略**：**先判定 source 类型**：
  - 若 `spec.source.kustomize` 存在 → 使用 `--kustomize-*` 前缀
  - 若 `spec.source.helm` 存在 → 使用 `--helm-*` 前缀
  - **严禁混用**

### 死法 4：automated 和 prune/self-heal 关系错误
- **触发条件**：用了 `--auto-prune` 或 `--self-heal` 但没加 `--sync-policy automated`
- **失败表现**：prune/self-heal 不生效，或命令报错
- **根因**：prune/self-heal 只在 automated 模式下有意义
- **避免策略**：**级联检查**：若 `--auto-prune` 或 `--self-heal` 出现，必须同时出现 `--sync-policy automated`

### 死法 5：强行将多源 `spec.sources` 转 CLI
- **触发条件**：YAML 包含 `spec.sources`（数组）而非 `spec.source`（单对象），且含 `$values` 引用
- **失败表现**：CLI 无法表达多源间的 `$values` 依赖关系，转换结果丢失关键配置
- **根因**：argocd CLI `app create` 只支持单源 `--repo-url`，多源只能用 `kubectl apply`
- **避免策略**：**检测到 `spec.sources` 时**：
  - 若长度=1 → 降级为单源处理
  - 若长度>1 → **立即停止转换**，输出 `kubectl apply -f <file>` 作为兜底方案

### 死法 6：运维组件错误开启 CreateNamespace
- **触发条件**：k8s_ops 目录下的 YAML 被转成 CLI 时加了 `--sync-option CreateNamespace=true`
- **失败表现**：namespace 冲突，或覆盖 initns 预配置的 namespace 设置
- **根因**：运维组件的 namespace 由基础设施 Root 单独管理（initns），不应由应用创建
- **避免策略**：**namespace 判定逻辑**：
  - 若 `destination.namespace` 是 `ops`/`loki`/`kube-system` 等运维 ns → **强制 `--sync-option CreateNamespace=false`**
  - 只有业务应用才允许 `CreateNamespace=true`

### 死法 7：业务应用错误开启 automated
- **触发条件**：业务应用 YAML（`destination.namespace` 非 `argo-root`，非运维 ns）被加上 `--sync-policy automated`
- **失败表现**：生产环境应用自动同步，可能引入未经审核的变更
- **根因**：业务应用生产规范要求手动触发 sync，Root 层才开 automated
- **避免策略**：**automated 判定逻辑**：
  - 若 `destination.namespace == "argo-root"` → 允许 automated
  - 若 `destination.namespace` 是业务 ns → **禁止 automated**，只保留 `PruneLast=true`

### 死法 8：CLI 失败时未自动回退 HTTP API
- **触发条件**：`argocd login` 因 context path / insecure 失败，或 `argocd app` 命令超时
- **失败表现**：Agent 直接报错停止，未尝试替代方案
- **根因**：部分环境 CLI 不可用，但 HTTP API `/api/v1` 仍可访问
- **避免策略**：**双通道原则**：CLI 失败后必须自动尝试 `python -m argocd_api` 回退（见第三节）

### 死法 9：敏感信息泄露
- **触发条件**：`ARGOCD_AUTH_TOKEN`、`ARGOCD_PASSWORD` 被回显或写入日志
- **失败表现**：凭证泄露到屏幕或文件，安全风险
- **根因**：Agent 未对敏感变量做脱敏处理
- **避免策略**：**强制脱敏**：所有输出中 `ARGOCD_AUTH_TOKEN` 和 `ARGOCD_PASSWORD` 必须替换为 `***`

### 死法 10：afix/fix 操作未确认直接执行
- **触发条件**：`argocd_insight.autofix` 或合规修复建议被自动执行
- **失败表现**：未经用户确认直接修改生产配置
- **根因**：Agent 未区分 dry-run 和实际执行
- **避免策略**：**两步确认**：所有修复操作必须先展示 dry-run 结果，**明确询问用户"是否继续"**，获得肯定答复后才执行

---

## 三、原子级 SOP（零抽象，全动词指令）

### 3.1 会话开机自检协议（首条命令前强制执行）

> **认证优先级（所有 ArgoCD 工具共享）**：
> `ARGOCD_AUTH_TOKEN`（推荐）→ `ARGOCD_USERNAME` + `ARGOCD_PASSWORD` → `~/.config/argocd/config`
> 支持 `.env` 文件自动检测（skill 根目录或当前目录）。

**Step 1: 加载环境变量**
```bash
# 检查 .env 文件是否存在
if [ -f .env ]; then export $(cat .env | grep -v '^#' | xargs); fi
```

**Step 2: 检测凭证优先级**
- 检查 `ARGOCD_AUTH_TOKEN` → 若存在，标记为「token 模式」
- 检查 `ARGOCD_USERNAME` + `ARGOCD_PASSWORD` → 若存在，标记为「密码模式」
- 检查 `~/.config/argocd/config` → 若存在，标记为「已有 session」
- 以上全无 → 进入「交互式 login」分支

**Step 3: 验证 CLI 可用性**
```bash
argocd version --client
```
- 返回 0 → CLI 可用，跳 Step 5
- 返回非 0 → 进入 Step 4

**Step 4: CLI 不可用时安装**
- 执行能力一：CLI 安装（见 3.2）

**Step 5: 验证登录状态**
```bash
argocd account get-user-info --server $ARGOCD_SERVER
```
- 返回 0 → 已登录，自检完成
- 返回非 0 → 执行登录：
  - token 模式：`argocd login --auth-token $ARGOCD_AUTH_TOKEN --server $ARGOCD_SERVER`
  - 密码模式：`argocd login --username $ARGOCD_USERNAME --password $ARGOCD_PASSWORD --server $ARGOCD_SERVER`
  - 交互模式：提示用户执行 `argocd login --server <server>`

**Step 6: 记录会话状态（内存中复用）**
- 保存 `ARGOCD_SERVER`、`app_name`、`namespace`、`project`、`repo_url`、`revision` 到会话上下文
- 后续命令缺省时自动沿用，**必须在输出开头标注「复用：key=value」**

---

### 3.2 能力一：CLI 安装（原子步骤）

**触发条件**：用户说"安装 argocd"、"升级 CLI"、或开机自检发现 CLI 不存在

**Step 1: 确定目标版本**
- 若用户指定版本（如 "v3.4.2"）→ 使用指定值
- 若用户未指定 → 调用 GitHub API 获取 latest release tag
- **强制补 v 前缀**：若版本号不以 "v" 开头，添加 "v"

**Step 2: 确定目标平台**
- 执行 `uname -s` → 获取 OS（Linux/Darwin/Windows）
- 执行 `uname -m` → 获取 ARCH（x86_64→amd64, arm64→arm64）
- 组合为 `argocd-<OS>-<ARCH>`（如 `argocd-linux-amd64`）

**Step 3: 构建下载 URL**
```
https://github.com/argoproj/argo-cd/releases/download/<version>/argocd-<OS>-<ARCH>
```

**Step 4: 执行下载**
```bash
curl -sSL -o /usr/local/bin/argocd <download_url>
chmod +x /usr/local/bin/argocd
```

**Step 5: 验证安装**
```bash
argocd version --client
```
- 返回 0 → 安装成功
- 返回非 0 → 检查 PATH，或重试 sudo 安装

---

### 3.3 能力二：自然语言生成 CLI 命令（原子步骤）

**触发条件**：用户描述操作意图（如"创建一个应用"、"同步 my-app"、"回滚到上一个版本"）

**Step 1: 意图关键词匹配（精确到动词）**
| 用户输入包含 | 映射命令 |
|-------------|---------|
| "创建"、"create"、"新建" | `argocd app create` |
| "同步"、"sync"、"部署" | `argocd app sync` |
| "回滚"、"rollback"、"回退" | `argocd app rollback` |
| "删除"、"delete"、"移除" | `argocd app delete` |
| "列出"、"list"、"查看所有" | `argocd app list` |
| "获取"、"get"、"查看详情" | `argocd app get` |
| "历史"、"history"、"版本记录" | `argocd app history` |
| "差异"、"diff"、"对比" | `argocd app diff` |
| "登录"、"login"、"认证" | `argocd login` |
| "项目"、"project" | `argocd proj` |
| "仓库"、"repo"、"git" | `argocd repo` |
| "集群"、"cluster" | `argocd cluster` |

**Step 2: 提取必备参数（一次问齐）**
- `app_name`：从输入提取，或询问「应用名称是什么？」
- `repo_url`：从输入提取，或询问 "Git 仓库地址？"
- `revision`：从输入提取，默认 "HEAD"
- `path`：从输入提取，询问 "manifest 在仓库中的路径？"
- `dest_server`：从输入提取，默认 "https://kubernetes.default.svc"
- `dest_namespace`：从输入提取，询问 "部署到哪个 namespace？"
- `project`：从输入提取，默认 "default"

**Step 3: 危险命令二次确认**
- 若命令是 `argocd app delete`、`argocd app terminate-op`、`argocd cluster rm`、`argocd repo rm`、`argocd proj delete` → **必须要求用户重复确认目标名称**
- 输出格式："⚠️ 危险操作：将删除 `<resource_name>`。请重复输入名称以确认："
- 用户输入与目标名称完全匹配 → 继续执行
- 不匹配 → 终止操作

**Step 4: 构建命令字符串**
```bash
argocd app create <app_name> \
  --repo <repo_url> \
  --revision <revision> \
  --path <path> \
  --dest-server <dest_server> \
  --dest-namespace <dest_namespace> \
  --project <project>
```

**Step 5: 附加 syncPolicy（依据层级判定）**
- 若 `dest_namespace == "argo-root"` → 追加 `--sync-policy automated --auto-prune --self-heal`
- 若 `dest_namespace` 是运维 ns（`ops`/`loki`/`kube-system`）→ 追加 `--sync-option CreateNamespace=false`
- 若 `dest_namespace` 是业务 ns → 追加 `--sync-option CreateNamespace=true`，**不追加 automated**

**Step 6: 输出命令并标注复用字段**
```
复用：app_name=<app_name>, namespace=<dest_namespace>, project=<project>, repo_url=<repo_url>, revision=<revision>

生成的命令：
<command>
```

---

### 3.4 能力三：YAML 反向生成 CLI（原子步骤）

**触发条件**：用户提供 ArgoCD Application YAML 文本或文件

**Step 1: 分流判定**
- 输入是单个 YAML 文本块，或 ≤4 个分散片段 → 走 **3.4.1 内联转换**
- 输入是目录路径，或 ≥5 个文件，或提到"批量/整个/全部" → 走 **3.4.2 批量工具**

#### 3.4.1 单 YAML 内联转换（Agent 直接处理）

**Step 1: 读取 YAML 内容**
- 解析 `metadata.name` → `app_name`
- 解析 `spec.project` → `project`（默认 "default"）

**Step 2: 检测多源（关键判定点）**
- 若 `spec.sources` 存在且长度 > 1 → **立即停止**，输出：
  ```
  ⚠️ 检测到多源配置（spec.sources），ArgoCD CLI 不支持。
  请使用兜底方案：
  kubectl apply -f <original.yaml>
  ```
- 若 `spec.sources` 长度 == 1 → 降级为单源处理，取 `spec.sources[0]`
- 若 `spec.source` 存在 → 正常使用

**Step 3: 提取 source 配置**
- `repo_url` = `spec.source.repoURL`
- `revision` = `spec.source.targetRevision`（默认 "HEAD"）
- `path` = `spec.source.path`
- `chart` = `spec.source.chart`（Helm 时存在）

**Step 4: 提取 destination 配置**
- `dest_server` = `spec.destination.server`（默认 "https://kubernetes.default.svc"）
- `dest_namespace` = `spec.destination.namespace`

**Step 5: 判定 source 类型（Kustomize vs Helm）**
- 若 `spec.source.kustomize` 存在 → 标记为 Kustomize 类型
- 若 `spec.source.helm` 存在 → 标记为 Helm 类型
- 若 `spec.source.chart` 存在 → 标记为 Helm 类型
- 否则 → 标记为原生类型

**Step 6: 转换 Kustomize 参数（仅 Kustomize 类型）**
| YAML 字段 | CLI Flag |
|----------|----------|
| `kustomize.namePrefix` | `--kustomize-name-prefix` |
| `kustomize.nameSuffix` | `--kustomize-name-suffix` |
| `kustomize.images` | `--kustomize-image`（数组项转多个 flag）|
| `kustomize.commonLabels` | `--kustomize-common-label`（key=value 格式）|
| `kustomize.commonAnnotations` | `--kustomize-common-annotation` |

**Step 7: 转换 Helm 参数（仅 Helm 类型）**
| YAML 字段 | CLI Flag |
|----------|----------|
| `helm.valueFiles` | `--values` |
| `helm.parameters` | `--helm-set`（name=value 格式）|
| `helm.releaseName` | `--helm-release-name` |
| `helm.apiVersions` | `--helm-api-versions` |

**Step 8: 转换 syncPolicy**
- 若 `spec.syncPolicy.automated` 存在 → 追加 `--sync-policy automated`
- 若 `automated.prune` == true → 追加 `--auto-prune`
- 若 `automated.selfHeal` == true → 追加 `--self-heal`
- 若 `spec.syncPolicy.syncOptions` 包含 `CreateNamespace=true` → 追加 `--sync-option CreateNamespace=true`

**Step 9: 应用名净化（强制替换下划线）**
```python
app_name = app_name.replace('_', '-')
```

**Step 10: 组装命令并输出**
```bash
argocd app create <app_name> \
  --repo <repo_url> \
  --revision <revision> \
  --path <path> \
  --dest-server <dest_server> \
  --dest-namespace <dest_namespace> \
  --project <project> \
  [<kustomize_flags>] \
  [<helm_flags>] \
  [<syncPolicy_flags>]
```

#### 3.4.2 批量转换（调用 Python 工具）

**Step 1: 确认输入路径（必须是绝对路径）**
- 若用户提供相对路径 → 转换为绝对路径：`$(pwd)/<relative_path>`
- 验证路径存在：`test -d <input_path>`

**Step 2: 执行批量工具**
```bash
python -m argocd_cli_gen \
  --input <absolute_input_path> \
  --output <output_dir> \
  --upsert \
  --emit-dry-run
```

**Step 3: 读取并展示报告**
- 读取 `<output_dir>/report.md`
- 提取关键信息：总文件数、成功转换数、fallback 数、Top 3 警告
- 展示给用户

**Step 4: 输出 run_all.sh 路径**
```
批量转换完成。
执行脚本：`<output_dir>/run_all.sh`
预检脚本：`<output_dir>/00_preflight.sh`
多源兜底：`<output_dir>/99_multisource_fallback.yaml`（若存在）
```

---

### 3.5 CLI 运行时回退协议（CLI 失败时强制执行）

**触发条件**：任何 `argocd` 命令返回非 0 退出码

**Step 1: 分析失败原因**
- 错误包含 "Unauthenticated" / "no session" → 认证问题
- 错误包含 "connection refused" / "timeout" → 网络问题
- 错误包含 "unknown flag" / "invalid syntax" → 命令语法问题
- 其他 → 未知问题

**Step 2: 认证/网络问题 → HTTP API 回退**
输出以下命令供用户执行：
```bash
# 先获取 token（若未设置 ARGOCD_AUTH_TOKEN）
export ARGOCD_TOKEN=$(curl -s -X POST "$ARGOCD_SERVER/api/v1/session" \
  -d "{\"username\":\"$ARGOCD_USERNAME\",\"password\":\"$ARGOCD_PASSWORD\"}" \
  | jq -r .token)

# 使用 HTTP API 执行等效操作
python -m argocd_api <operation> <app_name> [args...]
```

**Step 3: 语法问题 → 修正命令**
- 检查 flag 名称是否正确（`--kustomize-*` vs `--helm-*`）
- 检查参数顺序是否符合规范
- 重新生成命令

**Step 4: 未知问题 → 记录并上报**
- 记录完整错误输出
- 建议用户使用 `kubectl apply -f` 作为最终兜底

---

## 四、绝对禁区（高风险行动黑名单）

### 🚫 禁区 1：死循环重试
- **禁止**：CLI 命令失败后，不分析原因就无限重试
- **强制**：每次失败后必须执行「回退协议」（见 3.5），最多 3 次尝试（CLI → HTTP API → kubectl）

### 🚫 禁区 2：未经确认的危险操作
- **禁止**：直接执行 `argocd app delete`、`argocd cluster rm` 等删除类命令
- **强制**：必须执行「二次确认」流程（见 3.3 Step 3）

### 🚫 禁区 3：敏感信息泄露
- **禁止**：在输出中回显 `ARGOCD_AUTH_TOKEN`、`ARGOCD_PASSWORD` 的值
- **强制**：所有敏感字段必须替换为 `***`

### 🚫 禁区 4：跨会话状态持久化
- **禁止**：将会话中的 `app_name`、`namespace` 等写入文件或长期记忆
- **强制**：状态仅在**当前 LLM 会话内存**中复用，新会话必须重新询问

### 🚫 禁区 5：dry-run 模式下执行实际变更
- **禁止**：当用户或命令包含 `--dry-run` 时，执行任何实际修改
- **强制**：dry-run 模式下**只输出预览，不下发命令**

### 🚫 禁区 6：强行转换不支持的 YAML 特性
- **禁止**：将 `spec.sources` 多源（长度>1）、`kustomize.patches`、`kustomize.components` 等强行转为 CLI
- **强制**：检测到不支持特性时，**立即回退到 `kubectl apply -f`**

### 🚫 禁区 7：臆造不存在的配置
- **禁止**：为业务应用臆造 labels（project/profile/stack/app）
- **禁止**：为运维组件臆造 automated 或 labels
- **强制**：严格遵循「4-tier 生产模型」（见附录 A），只使用 YAML 中存在的配置

### 🚫 禁区 8：跨 skill 越权处理
- **禁止**：处理纯 Kubernetes 操作（kubectl apply deployment）时自称 argocd skill
- **禁止**：处理纯 Helm 操作（helm install）时自称 argocd skill
- **强制**：检测到不适用的场景时，**明确告知用户应使用其他 skill**

---

## 附录 A：4-Tier 生产模型（决策依据）

| 层级 | namespace 特征 | automated | CreateNamespace | labels |
|------|---------------|-----------|-----------------|--------|
| 基础设施 Root | `argo-root` | — | — | — |
| 聚合入口 Root | `argo-root` | **required** | true | — |
| 业务应用 | 业务 ns（非 argo-root、非运维 ns） | **NO** | true | **required** |
| 运维组件 | `ops`/`loki`/`kube-system` 等 | NO | **false** | — |

**判定流程（代码化逻辑）**：
```python
if namespace == "argo-root":
    # 进一步检测：若 name 包含 "project" 或 "repo" → 基础设施 Root
    # 否则 → 聚合入口 Root（需要 automated）
    tier = "infra_root" if is_infra_name(name) else "app_root"
elif namespace in ["ops", "loki", "kube-system", "monitoring"]:
    tier = "ops"
else:
    tier = "business"
```

---

## 附录 B：字段映射速查表

### Kustomize → CLI Flag
| YAML 字段 | CLI Flag | 值格式 |
|----------|----------|--------|
| `namePrefix` | `--kustomize-name-prefix` | 字符串 |
| `nameSuffix` | `--kustomize-name-suffix` | 字符串 |
| `images` | `--kustomize-image` | 可重复，数组每项一个 flag |
| `commonLabels` | `--kustomize-common-label` | `key=value`，可重复 |
| `commonAnnotations` | `--kustomize-common-annotation` | `key=value`，可重复 |

### Helm → CLI Flag
| YAML 字段 | CLI Flag | 值格式 |
|----------|----------|--------|
| `valueFiles` | `--values` | 可重复，数组每项一个 flag |
| `parameters` | `--helm-set` | `name=value`，可重复 |
| `releaseName` | `--helm-release-name` | 字符串 |
| `apiVersions` | `--helm-api-versions` | 可重复 |

### syncPolicy → CLI Flag
| YAML 字段 | CLI Flag | 依赖关系 |
|----------|----------|----------|
| `automated` | `--sync-policy automated` | 无 |
| `automated.prune` | `--auto-prune` | **依赖 automated** |
| `automated.selfHeal` | `--self-heal` | **依赖 automated** |
| `syncOptions.CreateNamespace` | `--sync-option CreateNamespace=true/false` | 无 |
| `syncOptions.PruneLast` | `--sync-option PruneLast=true` | 无 |

---

## 附录 C：参考资料

### 内部 Runbooks
| 文档 | 内容 |
|------|------|
| [references/cli-installation.md](references/cli-installation.md) | CLI 安装详细步骤 |
| [references/cli-commands.md](references/cli-commands.md) | 20+ 命令详解、危险命令清单 |
| [references/kustomize-mapping.md](references/kustomize-mapping.md) | 完整字段映射表 |
| [references/kustomize-examples.md](references/kustomize-examples.md) | 真实 YAML 转换示例 |
| [references/batch-conversion-design.md](references/batch-conversion-design.md) | 批量工具设计文档 |
| [references/argocd-insight-commands.md](references/argocd-insight-commands.md) | 诊断工具集使用手册 |

### 外部文档
- [ArgoCD CLI 安装文档](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- [ArgoCD CLI 命令参考](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd/)
- [GitHub Release 页面](https://github.com/argoproj/argo-cd/releases)
