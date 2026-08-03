# ulw 重启 ArgoCD 管理的 Pod — 专项 Runbook

> 工具实现：`scripts/ulw/ulw.py`（CLI 层）+ `scripts/ulw/commands.py`（业务层）。
> 相关文档：[argocd-restart-pod-guide.md](argocd-restart-pod-guide.md)（单 Pod vs Deployment 两种重启范式对比）、
> [SKILL.md § 3.5 CLI 运行时回退协议](../SKILL.md)。

## 1. 概述

「重启一个 ArgoCD 管理的 Pod」的本质是**删掉旧 Pod，让控制器重建**。
本 Runbook 描述的 `python3 -m ulw delete-pod` 走 **ArgoCD Application 资源 API**
（`delete_application_resource`），而不是裸 `kubectl delete pod`。

**为什么优先走 ulw：**

| 维度 | `python3 -m ulw delete-pod` | 裸 `kubectl delete pod` |
|------|------------------------------|--------------------------|
| 凭证 | 只需 `ARGOCD_SERVER` + ArgoCD 凭证 | 需要 kubeconfig / 集群凭证 |
| 真相源 | 经 ArgoCD，操作记录在 App 事件里，贴近 GitOps 真相源 | 绕过 ArgoCD，ArgoCD 视角看不到这次操作 |
| 安全护栏 | **删除前强制校验** App 的 `spec.syncPolicy.automated`，非 automated 直接拒绝 | 无任何校验，非 auto-sync 的 App 删完 Pod 可能不重建 |
| 等待重建 | `--wait-ready` 内置轮询（含 StatefulSet 同名 Pod 判定） | 需自行 `kubectl wait` |

**适用场景**：单个 Pod 卡住 / OOM 后需要重来 / 想清掉某个副本重新调度。
**不适用**：要重启整个 Deployment 的所有 Pod → 走 `argocd app actions run <app> restart --kind Deployment`
（见 [argocd-restart-pod-guide.md § 2](argocd-restart-pod-guide.md)）。

## 2. 前置条件

### 2.1 环境变量

`.env` 文件（默认路径 `<repo>/.env`，即 `scripts/ulw/` 的上两级；可用 `--env-file` 覆盖）
至少需要：

```bash
export ARGOCD_SERVER=https://argocd.example.com
# 二选一（推荐前者）
export ARGOCD_AUTH_TOKEN=***
# 或
export ARGOCD_USERNAME=***
export ARGOCD_PASSWORD=***
```

> ⚠️ `.env` 中变量**必须带 `export` 前缀**，否则子进程读不到。
> 验证：`source .env && echo $ARGOCD_SERVER` 应输出值（不要 echo token）。

### 2.2 认证优先级与自动回退（`scripts/argocd_api/client.py:from_env`）

1. shell env `ARGOCD_AUTH_TOKEN`
2. `~/.config/argocd/config` 里的 token
3. `.env` 的 `ARGOCD_USERNAME` + `ARGOCD_PASSWORD` → 调 API login
4. `.env` 的 `ARGOCD_AUTH_TOKEN`

**token 过期是正常路径，不是错误**。你会在 stderr 看到：

```
[argocd-api] shell env token expired, trying next priority...
[argocd-api] config token expired, auto-fallback to username+password...
```

只要最终拿到 session 就继续执行，**不要**把这两行当失败上报给用户。
若四级全部失败，客户端抛 `ValueError`，`ulw` 打印
`[ulw] configuration error: ...` 并返回 **1**。

## 3. 操作步骤

> 所有命令从仓库的 `scripts/` 目录执行（`python3 -m ulw` 需要 `ulw` 包在
> import 路径上）。

### 步骤 A：定位 Pod 归属的 Application

```bash
cd /path/to/argocd-skill/scripts
python3 -m ulw find-pod <pod-name>
```

成功时 stdout 输出五行键值（可直接被 shell 消费）：

```
APP_NAME=hdops-mcp
NAMESPACE=ops
KIND=Pod
GROUP=
VERSION=v1
```

实现说明（`commands.py:find_pod`）：遍历**所有** Application，对每个 App 调
`get_application_pods()` —— 优先打 `/applications/<app>/pods`（ArgoCD 1.9+），
404 时回退到 `/resource-tree` 里筛 `kind == "Pod"` 的节点。
找不到时 stderr 打印 `pod=<name> not found in any ArgoCD Application`，退出码 **1**。

> App 数量多时全量扫描较慢；已知归属就用步骤 B 的 `--app-name` + `--namespace` 快捷键跳过。

### 步骤 B：删除（=重启）Pod

```bash
python3 -m ulw delete-pod <pod-name> --yes
```

#### 安全护栏（核心，`commands.py:_assert_automated`）

删除**之前**先 `get_application(app_name)` 读 `spec.syncPolicy.automated`：

- 只有当 `automated` 是 **dict**（包括空 dict `{}`，意为「全默认的 automated」）才放行 —— 白名单策略；
- 任何非 dict 值（`None` / `false` / 字符串 `"false"` / `0` / `""`）视为**手动同步**，
  删了 Pod 也不会被 ArgoCD 重建 → 抛 `BlockedError`；
- App **读不到**（网络 / 权限 / 不存在）同样抛 `BlockedError` —— 宁可拒绝，不猜测。

被拒绝时 Pod **不会被删除**，stderr 打印 `[ulw] BLOCKED: ...`（消息里已含替代方案），
退出码 **2**。

> `--yes` 只跳过交互确认，**不跳过**安全护栏。护栏无 CLI 开关可绕过。

#### 常用参数

| 参数 | 作用 |
|------|------|
| `--yes` | 跳过交互确认（`Type 'yes':`）。非 TTY（CI / cron / 管道）下不加此参数会因 `EOFError` 直接中止，退出码 1 |
| `--app-name <app>` + `--namespace <ns>` | 跳过全量扫描直接定位。**两个必须同时给**，只给其一会退回全量扫描 |
| `--wait-ready` | 删除后轮询直到替代 Pod Running |
| `--wait-timeout N` | `--wait-ready` 超时秒数，默认 **120**，必须为正整数 |
| `--wait-interval N` | 轮询间隔秒数，默认 **5**，必须为正整数 |
| `--env-file PATH` | 指定 `.env`，文件不存在会在参数解析阶段报错 |

完整用法：

```bash
python3 -m ulw delete-pod hdops-mcp-7b8cc44dd8-mdp97 \
  --app-name hdops-mcp --namespace ops \
  --yes --wait-ready --wait-timeout 180 --wait-interval 5
```

#### `--wait-ready` 判定逻辑（`commands.py:wait_pod_ready`）

成功需**同时**满足「旧 Pod 已消失或已被原地重建」+「有一个 Running/Healthy 的 Pod」：

- **Deployment / ReplicaSet**：新 Pod 名字变了 → 旧名从列表消失，另一个 Pod Running 即成功；
- **StatefulSet**：成员 Pod 名字**不变**（如 `mysql-0`），靠首轮轮询记下的
  `metadata.resourceVersion` 基线，后续同名 Pod 的 `resourceVersion` 变化即证明被重建；
- Running 判定兼容两种数据源：`/resource-tree` 节点的 `health.status`（`Healthy`）
  与 `/pods` 的 `status.phase`（`Running`）；
- 轮询期间的 API 报错只打日志并重试，不中断等待；
- 超时返回 False → `ulw` 提示 `check argocd app get <app>`，退出码 **1**
  （**Pod 已经删了**，只是没等到新 Pod Running）。

### 步骤 C：验证

```bash
# 方式一：旧 Pod 应已消失（Deployment/ReplicaSet 场景）
python3 -m ulw find-pod <old-pod-name>   # 期望：not found，退出码 1

# 方式二：看 App 与 Pod 整体状态
argocd app get <app-name>
```

> StatefulSet 场景下 Pod 同名重建，`find-pod` **仍会找到**同名 Pod——这不代表失败。
> 该场景请以 `--wait-ready` 的结果或 `argocd app get` 的健康状态为准。

## 4. 退出码

| 码 | 含义 | 典型 stderr |
|----|------|-------------|
| **0** | 成功（含 `--wait-ready` 已等到替代 Pod Running） | `[ulw] replacement Pod is running: <name>` |
| **1** | Pod 未找到 / 用户中止 / 非 TTY 未加 `--yes` / `--wait-ready` 超时 / 配置错误 | `cannot delete: pod not found`、`aborted`、`no TTY for confirmation; pass --yes to proceed`、`timeout after Ns`、`configuration error: ...` |
| **2** | 安全门禁拒绝（`BlockedError`，App 非 automated 或读不到）——**Pod 未被删除** | `[ulw] BLOCKED: App '<app>' has no spec.syncPolicy.automated ...` |

区分 1 和 2 很重要：**2 表示什么都没动**，1 里的「超时」表示 **Pod 已删但没等到新 Pod**。

## 5. 遇到 rc=2（非 automated）怎么办

工具拒绝说明该 App 是手动同步，删掉 Pod 后 ArgoCD **不会**帮你重建。按需二选一：

```bash
# 方案 1（推荐）：让工作负载控制器滚动重启，不依赖 ArgoCD 同步
kubectl rollout restart deployment/<deployment-name> -n <namespace>

# 方案 2：先让 App 回到期望状态，再考虑删 Pod
argocd app sync <app-name>
```

> 本项目的 4-tier 模型中，**业务应用禁止 automated**（见 SKILL.md 附录 B、死法 7）。
> 因此对业务 App 执行 `ulw delete-pod` 被拒是**预期行为**，不要为了删 Pod 去
> 给业务 App 加 `automated`。

## 6. 兜底：直接用 kubectl

仅在以下情况使用：

- Pod **不由 ArgoCD 管理**（`find-pod` 找不到，且确认它是裸 K8s 工作负载）；
- App 已是 automated，但你不想经过 ArgoCD API（例如 ArgoCD server 不可达）。

```bash
kubectl delete pod <pod-name> -n <namespace>
```

前提是本机有 kubeconfig。删除前务必确认 Pod 名与 namespace，
并注意使用本地存储的 Pod 删除后数据会丢失。

## 7. 注意点

- **只读监控类 MCP（如 hdops-mcp 相关只读工具）不能重启 Pod**。它们只提供指标 /
  日志 / 告警查询，没有写通道。要真正执行重启，**必须**走 `python3 -m ulw delete-pod`
  或 `kubectl`。不要把「查到了 Pod 状态」误当成「可以重启它」。
- `delete-pod` 只删 Pod，**不动** Deployment / ReplicaSet / StatefulSet 本身。
- 单 Pod 重启 ≠ Deployment 重启。用户说「重启 Pod」时先按
  [SKILL.md § 3.3.x restart Pod 决策树](../SKILL.md) 追问意图。
- 敏感字段（`ARGOCD_AUTH_TOKEN` / `ARGOCD_PASSWORD`）任何输出中都必须以 `***` 呈现。

## 8. 交叉引用

| 文档 | 内容 |
|------|------|
| [SKILL.md](../SKILL.md) | § 3.3.x restart Pod 决策树、§ 3.5 CLI 运行时回退协议、附录 B 4-Tier 模型 |
| [argocd-restart-pod-guide.md](argocd-restart-pod-guide.md) | 单 Pod vs Deployment 两种重启范式对比、argocd_api 直调示例 |
| [agent-protocols.md](agent-protocols.md) | 开机预检协议、认证优先级 |
| [argocd-sync-policy-deep-dive.md](argocd-sync-policy-deep-dive.md) | `syncPolicy.automated` / prune / selfHeal 完整解析 |
