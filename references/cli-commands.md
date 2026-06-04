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
