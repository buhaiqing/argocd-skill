# CLI 命令映射表与示例

## 完整命令参考

### 认证

```bash
argocd login <ARGOCD_SERVER> --username <USER> --password <PASS> [--insecure]
```

### 创建应用

**从 Git 源（标准模式）：**

```bash
argocd app create APPNAME \
  --repo <URL> \
  --path <PATH> \
  --revision <REV> \
  --dest-server <CLUSTER> \
  --dest-namespace <NS> \
  --project default
```

**带 Kustomize 参数：**

```bash
argocd app create APPNAME \
  --repo <URL> --path <PATH> --dest-server <CLUSTER> --dest-namespace <NS> \
  --kustomize-nameprefix PREFIX \
  --kustomize-image IMG1 --kustomize-image IMG2 \
  --kustomize-common-label KEY=VAL
```

### 同步（生产常用模式）

```bash
argocd app sync APPNAME --prune
```

> 生产实践中常配合 `--sync-option PruneLast=true` 使用（与内部 argocd.py 中 `sync_application` 的 body 逻辑一致）。

### 查询

```bash
argocd app get APPNAME                                  # 详情
argocd app list [-l LABEL_SELECTOR]                     # 列表
argocd app history APPNAME                              # 历史
argocd app diff APPNAME                                 # 差异对比
argocd app manifests APPNAME [--revision REV]           # Manifest
```

### 修改 syncPolicy

```bash
argocd app set APPNAME \
  --sync-policy automated \
  --auto-prune \
  --self-heal
```

### 回滚

```bash
argocd app rollback APPNAME [HISTORY_ID]
```

### 删除

```bash
argocd app delete APPNAME [--cascade]
```

### 等待同步

```bash
argocd app wait APPNAME [--health] [--suspended] [--timeout N]
```

### 仓库/集群/项目管理

```bash
argocd repo add <URL> --username <USER> --password <PASS>
argocd repo list
argocd cluster add <KUBE_CONTEXT>
argocd cluster list
argocd proj create <NAME>
```

## 操作场景处理规则

| 场景 | 规则 |
|------|------|
| 用户缺少关键参数 | 输出带 `<占位符>` 的模板命令，说明必填项 |
| 复合意图（"创建并同步"） | 拆分多条命令，按序输出 |
| 认证前置操作 | 同步/回滚/删除前提示 "请确保已执行 argocd login" |
| syncPolicy 组合 | 常用模板：automated + prune + selfHeal |
| 多步操作 | 创建→设置参数→同步，按步骤编号输出 |
| Kustomize 多个参数 | 每个参数用独立 flag，--kustomize-image 可重复 |

## 生产模式参考（来自 argoapp/script/argocd.py）

内部运维脚本 `argocd.py` 封装了 ArgoCD REST API 调用，其模式可直接映射为 CLI 命令：

| argocd.py 方法 | 对应 CLI 命令 |
|---------------|--------------|
| `get_application_by_name(name)` | `argocd app get <name>` |
| `sync_application()` | `argocd app sync <name> --prune` + `--sync-option PruneLast=true` |
| `get_application_health()` | `argocd app get <name> -o json | jq '.status.health.status'` |
| `check_application_is_healthy()` | `argocd app wait <app> --health --timeout N` |
| `refresh_application()` | `argocd app refresh <name>` |
| `get_applications(project)` | `argocd app list -l project=<project>` |
| `get_application_manifests()` | `argocd app manifests <name>` |
| `get_application_resource_tree()` | `argocd app get <name> -o json`（资源树在 status 中） |
| `get_application_events()` | `kubectl get events -n argocd --field-selector involvedObject.name=<app>` |

## 参数推断规则（默认补全与提示）

Agent 在生成命令前应按下表做默认补全；用户未提供但属于安全默认时直接补入，需用户决策时才提示。

1. `argocd app sync <name>` → 默认追加 `--prune --sync-option PruneLast=true`（来自 argocd.py `sync_application` 模式，生产 100% 标配）。
2. `argocd app create <name>` → `--dest-server` 默认 `https://kubernetes.default.svc`（in-cluster，生产 95% 即此值）；用户若指定外部集群可覆盖。
3. `argocd app create <name>` → 用户未指定 `--revision` 时，提示「建议显式指定 branch/tag/SHA，避免跟踪默认分支漂移」。
4. `argocd app create <name>` → 用户未指定 `--project` 时，提示「生产 100% 用 `default`，但部分团队会按 AppProject 隔离，请确认」。
5. `argocd app set <name> --sync-policy automated` → **必须**同时存在 `--auto-prune`（任一缺失则报错提示：prune 只能在 automated 模式下使用）。
6. `argocd app rollback <name>` → 未指定 HISTORY_ID 时默认回上一版本；提示「用 `argocd app history <name>` 先查 ID 再回滚更稳」。
7. `argocd app get <name> -o json | jq ...` → 推荐用 jq 路径提取 `.status.health.status`（健康态）和 `.status.sync.status`（同步态）。
8. `argocd repo add` / `argocd cluster add` → 必须先 `argocd login`；凭证可通过 `--auth-token "$ARGOCD_AUTH_TOKEN"` 注入（**绝不回显**）。
9. `argocd app wait <name> --timeout N` → N 单位秒；生产建议 `300`（5 分钟），CI 可缩到 `60`。
10. `argocd app manifests <name> --revision <rev>` → rev 必须是 Git SHA/branch/tag；`HEAD` 默认当前 main，仅调试用。

## 复合意图编排（4 套固定模板）

### 「创建 + 同步 + 等就绪」

```bash
argocd app create <name> \
  --repo <url> --path <p> --revision <rev> \
  --dest-namespace <ns> --project default \
  --upsert

argocd app sync <name> --prune
argocd app wait <name> --health --timeout 300
argocd app get <name> -o json | jq '{health: .status.health.status, sync: .status.sync.status}'
```

### 「创建 + 开自愈」

> ⚠️ **前置警告**：automated 一旦开启，集群状态会被 ArgoCD 持续协调（drift 检测 + 自愈）。务必确认这是 Root 入口或业务确实需要自愈，否则不要打开。

```bash
argocd app create <name> \
  --repo <url> --path <p> --revision <rev> \
  --dest-namespace <ns> --project default \
  --upsert

argocd app set <name> \
  --sync-policy automated \
  --auto-prune \
  --self-heal
```

### 「同步 + 等就绪」

```bash
argocd app sync <name> --prune
argocd app wait <name> --health --timeout 300
argocd app get <name> -o json | jq '{health: .status.health.status, sync: .status.sync.status}'
```

### 「回滚 + 验证」

```bash
argocd app history <name>
argocd app rollback <name> <HISTORY_ID>
argocd app wait <name> --health --timeout 300
argocd app get <name> -o json | jq '.status.sync.status'
```

## 危险命令清单（必须二次确认）

下表命令的破坏半径超出「读 + 单 App 操作」范围，Agent 必须在用户**完整复述标识符**后才生成/执行命令。

| 命令 | 风险 | 确认话术 |
|------|------|---------|
| `argocd app delete <name>` | 删 Application，但保留托管资源（除非加 `--cascade`） | 「请完整复述 app name」 |
| `argocd app delete <name> --cascade` | 删 Application + 所有托管资源（**不可逆**） | 「请完整复述 app name + 明确 `--cascade` 意图」 |
| `argocd app terminate-op <name>` | 强杀正在进行的 sync / rollback 操作 | 「请复述 app name + 说明为何 terminate」 |
| `argocd cluster rm <ctx>` | 移除集群 context，影响所有依赖该集群的应用 | 「请复述 context + 确认无应用依赖」 |
| `argocd repo rm <url>` | 移除仓库凭证，依赖该仓库的应用会报 sync 错 | 「请复述 URL + 确认无应用依赖」 |
| `argocd proj delete <name>` | 删 AppProject，project 下所有应用级联失败 | 「请复述 name + 提示此操作不可逆」 |
| `argocd app set --sync-policy automated --self-heal` | 开自愈，ArgoCD 会持续覆盖集群漂移 | 「这是 Root 入口或业务确实需要自愈吗？」 |

## 开机自检（会话开头）

每个会话处理第一条命令前，Agent 在内部（不在用户输出中）先做凭证自检。未通过则提示用户补全，不直接报错退出。

**自检项：**

1. `ARGOCD_AUTH_TOKEN` 是否已 export？未设 → 提示「请先 `export ARGOCD_AUTH_TOKEN=***`（或运行 `argocd login`）」。
2. `ARGOCD_SERVER` 是否已 export 或有默认值？未设 → 提示「请先 `export ARGOCD_SERVER=argocd.example.com`」。
3. `argocd` CLI 是否在 PATH？未设 → 提示安装（参考能力一）。

**Agent 内部参考的 bash 片段（不要直接 echo 给用户）：**

```bash
: "${ARGOCD_AUTH_TOKEN:?need ARGOCD_AUTH_TOKEN env var}"
: "${ARGOCD_SERVER:=argocd.hd123.com}"
```

**与批量工具的对齐：** `python -m argocd_cli_gen` 生成的 `00_preflight.sh` 实现了同样的自检逻辑（env 检查 + `argocd version --client` + `argocd login --auth-token --grpc-web` + `argocd account get-user-info`）。能力 2（单条命令生成）走 LLM 提示阶段，能力 3.2 走 shell 落地阶段，**两阶段自检项必须一致**。

**凭证处理硬性约束：**

- `ARGOCD_AUTH_TOKEN` 永远**不回显**、**不写日志**、**不传非加密通道**；Agent 输出中一律 mask 为 `***`。
- `ARGOCD_SERVER` 永远不让用户在内联命令里以明文粘贴（用户已经在 env 里 export 过）；Agent 引用时写 `$ARGOCD_SERVER`。
- `argocd login --username ... --password ...` 仅在交互场景使用；CI / 脚本场景一律走 `--auth-token "$ARGOCD_AUTH_TOKEN"`。
