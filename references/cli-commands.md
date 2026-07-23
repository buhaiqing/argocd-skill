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
argocd app diff APPNAME                                 # 差异对比（干跑）
argocd app manifests APPNAME [--revision REV]           # Manifest（输出多文档 JSON，以 --- 分隔，非单个 JSON 数组）
argocd app resources APPNAME                            # 资源树（kind/name/namespace/健康态）
argocd app get-resource APPNAME --kind Pod              # Pod 运行时详情（phase/IP/node/containerStatuses）
argocd app logs APPNAME [--follow] [--tail N]          # Pod 日志
argocd app events APPNAME                              # 应用事件
```

#### P0-1.5：Pod 运行时状态查询（get-resource）

> 触发词：「hdops-mcp 有几个 Pod」「查看 Pod 状态」「Pod 在哪个节点」「Pod IP」「容器是否 Ready」「Pod 重启次数」

```bash
# 查看 App 内所有 Pod 的运行时状态（phase / IP / node / Ready / restartCount）
argocd app get-resource APPNAME --kind Pod

# 查看指定 Pod 的完整 manifest（含 spec/status/containerStatuses）
argocd app get-resource APPNAME --kind Pod --resource-name my-pod-xxx

# 只看关键字段（phase / podIP / hostIP / Ready / restartCount / node）
argocd app get-resource APPNAME --kind Pod \
  --filter-fields status.phase,status.podIP,status.hostIP,status.conditions[?type=="Ready"].status,status.containerStatuses[:1].restartCount

# 查看特定 Pod 的容器状态（容器名 / Ready / restartCount / image / containerID）
argocd app get-resource APPNAME --kind Pod --resource-name my-pod-xxx \
  --filter-fields status.containerStatuses[:1].name,status.containerStatuses[:1].ready,status.containerStatuses[:1].restartCount,status.containerStatuses[:1].image

# 格式化输出（json / yaml / wide）
argocd app get-resource APPNAME --kind Pod -o json
argocd app get-resource APPNAME --kind Pod -o yaml

# Python API 等价（无 ArgoCD CLI 时）
python -m argocd_api resource-tree APPNAME          # 概览（含 Pod phase/IP）
python -m argocd_api resource APPNAME Pod <pod-name> --ns <namespace>  # 完整规格
```

#### P0-2：Pod / Container 日志

> 触发词：「查看日志」「看 Pod 日志」「App 里的容器日志」「events」

```bash
# 查看应用所有关联 Pod 的日志
argocd app logs APPNAME

# 实时跟踪日志（类似 tail -f）
argocd app logs APPNAME --follow

# 只看最近 N 行
argocd app logs APPNAME --tail 100

# 指定特定资源
argocd app logs APPNAME \
  --kind Pod \
  --namespace my-ns \
  --name my-pod-xxx \
  --container my-container

# 查看 App 相关的事件
argocd app events APPNAME

# 直接查 Kubernetes 事件（ArgoCD 无法覆盖时）
kubectl get events -n <namespace> \
  --field-selector involvedObject.name=<app-name>,involvedObject.namespace=<namespace> \
  --sort-by=.lastTimestamp
```

#### P0-3：App diff（干跑对比）

> 触发词：「App diff」「看差异」「本地和集群有什么不同」「哪些资源有漂移」

```bash
# 查看 App 的完整差异（Git vs 集群）
argocd app diff APPNAME

# 只看某个 namespace 的 diff
argocd app diff APPNAME --namespace my-ns

# 导出 diff 结果（用于自动化检查）
# exit code: 0=无差异, 1=有差异, 2=错误
argocd app diff APPNAME; echo "exit code: $?"

# 提取 OutOfSync 资源列表
argocd app get APPNAME -o json | \
  python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d.get('status',{}).get('resources',[]):
    if r.get('status') not in ('Synced',''):
        print(r['kind']+'/'+r['name']+' ['+r['status']+']')
"
```

#### P0-5：全量 App 健康报告

> 触发词：「所有 App 健康状况」「App 报告」「哪些 App 有问题」

```bash
# 生成全量健康报告（按 health/sync/project 分组）
argocd app list --output json | \
  python3 -c "
import json,sys
apps=json.load(sys.stdin)
ok=[a for a in apps if a.get('status',{}).get('health',{}).get('status')=='Healthy']
err=[a for a in apps if a.get('status',{}).get('health',{}).get('status') not in('Healthy','Missing','')]
unk=[a for a in apps if not a.get('status',{}).get('health',{}).get('status')]
oos=[a for a in apps if a.get('status',{}).get('sync',{}).get('status')=='OutOfSync']
print('总 App 数：'+str(len(apps)))
print('Healthy: '+str(len(ok))+' | 异常: '+str(len(err))+' | 未知: '+str(len(unk)))
print('Synced: '+str(len(apps)-len(oos))+' | OutOfSync: '+str(len(oos)))
for a in err: print('  [异常] '+a['metadata']['name']+': '+a['status']['health']['status'])
for a in oos: print('  [OutOfSync] '+a['metadata']['name'])
"

# 按 project 分组统计
argocd app list --output json | \
  python3 -c "
import json,sys
from collections import defaultdict
apps=json.load(sys.stdin)
by_proj=defaultdict(list)
for a in apps:
    p=a.get('spec',{}).get('project','unknown')
    by_proj[p].append(a)
for p,as_ in sorted(by_proj.items()):
    print(p+': '+str(len(as_))+' App')
"
```

### 修改 syncPolicy（已有）

```bash
argocd app set APPNAME \
  --sync-policy automated \
  --auto-prune \
  --self-heal
```

#### P0-4：修改 App 参数（set / patch）

> 触发词：「修改 App 参数」「改 revision」「改 namespace」「改 sync-policy」「把 App 改成手动同步」

**常用参数（`argocd app set`）：**
```bash
# 修改 Git revision（切换分支/tag/SHA）
argocd app set APPNAME --revision <branch-or-sha>

# 修改目标 namespace
argocd app set APPNAME --dest-namespace <namespace>

# 修改 sync-policy（关闭自动化 → 手动模式）
argocd app set APPNAME --sync-policy none

# 开启自动化同步（Root 入口或明确需要自愈的业务 App）
argocd app set APPNAME --sync-policy automated --auto-prune --self-heal

# 调整 Kustomize 参数
argocd app set APPNAME --kustomize-nameprefix <prefix> --kustomize-image <img>

# 修改 Helm 参数
argocd app set APPNAME --param key=value

# 查看当前所有参数
argocd app get APPNAME -o json | jq '.spec'
```

**patch 场景（修改 YAML 子字段）：**
```bash
# 对 App 内的某个资源打 patch（如改副本数）
argocd app patch-resource APPNAME \
  --kind Deployment \
  --name my-deploy \
  --namespace my-ns \
  --patch '{"spec":{"replicas":3}}' \
  --patch-type application/strategic-merge-patch
```

### 回滚

```bash
argocd app rollback APPNAME [HISTORY_ID]
```

### 补充 App 操作（refresh / unset / edit / terminate-op / 多源）

```bash
# 强制刷新：强制 ArgoCD 重新从 Git 拉取并对账（解决 cache 不一致）
argocd app refresh APPNAME

# 取消已设置的参数（如取消 automated syncPolicy / 取消 kustomize namePrefix）
argocd app unset APPNAME --sync-policy
argocd app unset APPNAME --kustomize-nameprefix

# 交互式编辑：打开 $EDITOR 编辑 app spec（等价 UI 点「Edit」按钮）
argocd app edit APPNAME

# 终止正在运行的 sync / rollback 操作
argocd app terminate-op APPNAME

# 多源管理：增/删 App 的 source
argocd app add-source APPNAME --repo <url> --path <path> --revision <rev>
argocd app remove-source APPNAME --repo <url>
```

### 删除 Application（整应用）

```bash
argocd app delete APPNAME [--cascade]
```

### 删除 Application 内的单个 Resource

> ⚠️ **副作用说明**：删除后 App 进入 OutOfSync 状态，ArgoCD 下次 Reconciliation 会从 Git 源重建该资源。如需立即恢复，执行 `argocd app sync APPNAME --prune`。

```bash
# 标准删除（安全：留 orphans 让 Git 接管）
argocd app delete-resource APPNAME \
  --kind <Kind> \
  --resource-name <NAME> \
  --namespace <NS>

# 强制删除（跳过 finalizer 等保护）
argocd app delete-resource APPNAME \
  --kind <Kind> \
  --resource-name <NAME> \
  --namespace <NS> \
  --force

# 删除并清理 orphans（等同于 sync --prune 行为）
argocd app delete-resource APPNAME \
  --kind <Kind> \
  --resource-name <NAME> \
  --namespace <NS> \
  --orphan
```

**完整操作示例（删 Service + 确认恢复）：**
```bash
# 1. 删除
argocd app delete-resource my-app \
  --kind Service \
  --resource-name my-service \
  --namespace my-namespace

# 2. 验证 App 状态（应为 OutOfSync）
argocd app get my-app -o json | jq '{sync: .status.sync.status, health: .status.health.status}'

# 3. 从 Git 重建（可选）
argocd app sync my-app --prune
```

### 对 App 内 Resource 执行 Action

> ArgoCD 支持对 App 管理的 K8s 资源执行内置或自定义 Action（如重启 Deployment、缩容/扩容等）。

```bash
# 列出 App 内所有资源可用的 Action
argocd app actions list APPNAME

# 列出指定 kind 的可用 Action
argocd app actions list APPNAME --kind Deployment

# 对 App 内某个资源执行 Action（按 kind + name 定位）
argocd app actions run APPNAME restart \
  --kind Deployment \
  --resource-name my-deployment \
  --namespace production

# 对 App 内所有匹配的同类资源批量执行 Action
argocd app actions run APPNAME restart \
  --kind Deployment \
  --namespace production \
  --all

# 列出 App 内所有资源（含过滤参数）
argocd app actions list APPNAME --kind Deployment -o yaml
```

**使用场景：** 无需 kubectl，手动触发 Pod 重启、HPA 调整、ConfigMap reload 等。Action 必须是 K8s 资源上已定义的 Action（通常是 `kind` 级联动作如 restart）。

### 等待同步

```bash
argocd app wait APPNAME [--health] [--suspended] [--timeout N]
```

### 仓库/集群/项目管理

```bash
argocd repo add <URL> --username <USER> --password <PASS>
argocd repo list
argocd repo get <URL>                       # 查单个仓库详情
argocd repo rm <URL>                        # ⚠️ 必须确认无应用依赖
argocd cluster add <KUBE_CONTEXT>
argocd cluster list
argocd cluster get <NAME>                    # 查集群详情
argocd cluster rm <NAME>                    # ⚠️ 必须确认无应用依赖
```

#### Project 管理

> 触发词：「创建项目」「删除项目」「给项目加仓库」「项目里允许哪些 namespace」

```bash
# 增删查改
argocd proj create <PROJECT>                              # 创建
argocd proj list                                          # 列表
argocd proj get <PROJECT>                                # 详情
argocd proj delete <PROJECT>                             # ⚠️ 必须二次确认
argocd proj edit <PROJECT>                               # 交互式编辑（打开 $EDITOR）

# 源管理
argocd proj add-source <PROJECT> <REPO_URL> [--path <path>] [--revision <rev>]
argocd proj remove-source <PROJECT> <REPO_URL>

# 目标管理（哪些集群+namespace 该 project 下的 App 可以部署到）
argocd proj add-destination <PROJECT> <CLUSTER> <NAMESPACE>
argocd proj remove-destination <PROJECT> <CLUSTER> <NAMESPACE>

# Sync Windows
argocd proj windows list <PROJECT>
# （sync window 完整操作用 argocd proj windows --help）

# 参数设置
argocd proj set <PROJECT> --allow-namespaced-resource <KIND>   # 允许某类 namespaced 资源
argocd proj set <PROJECT> --deny-namespaced-resource <KIND>    # 拒绝某类 namespaced 资源
```

#### ApplicationSet 管理

> 触发词：「查看 ApplicationSet」「删除 ApplicationSet」「生成 ApplicationSet 的 app」

```bash
argocd appset list                                      # 列表
argocd appset get <APPSETNAME>                         # 详情
argocd appset create <FILE.yaml>                        # 从 YAML 创建
argocd appset delete <APPSETNAME>                      # ⚠️ 必须二次确认
argocd appset generate <APPSETNAME>                     # 干跑：生成会被创建的所有 App
```

#### Account / Token 管理

> 触发词：「生成 token」「查看用户信息」「删除 token」

```bash
argocd account list                                      # 列出所有账号
argocd account get-user-info                             # 当前登录用户信息
argocd account generate-token --account <NAME>          # 为指定账号生成 token
argocd account delete-token --token <TOKEN>             # 删除某个 token
argocd account update-password                           # 交互式改密码
argocd account can-i sync applications '*'              # 权限检查
```

## 删除单个 Resource 的完整流程

当用户说「删掉 App 里的某个资源 / 删除 xxx Pod / 删掉某个 Service」时：

1. **识别目标**：用 `argocd app resources APPNAME` 找到资源的 kind / name / namespace
2. **执行删除**：`argocd app delete-resource APPNAME --kind X --resource-name Y --namespace Z`
3. **显式告知副作用**：告知用户 App 会变成 OutOfSync，下次 Reconcile（或手动 sync）会重建
4. **主动建议恢复**：如果用户未明确说「不要重建」，默认给出 `argocd app sync APPNAME --prune` 命令

**危险等级判断**：
| 资源类型 | 风险 | 确认要求 |
|---------|------|---------|
| Pod / Deployment / StatefulSet | 高（影响业务） | 必须用户复述资源标识 |
| Service / ConfigMap / Ingress | 中（可快速恢复）| 提示确认即可 |
| Secret | 高（凭证风险）| 必须用户复述 + 明确说明 |
| CRD / ClusterRole / Namespace | 极高（影响范围大）| 拒绝 + 说明边界 |



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
| `get_application_manifests()` | `argocd app manifests <name>`（多文档 JSON，`---` 分隔） |
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
| `argocd appset delete <name>` | 删 ApplicationSet，所有由它生成的 App 也会被清理 | 「请复述 AppSet name」 |
| `argocd app terminate-op <name>` | 强杀正在进行的 sync/rollback 操作，可能导致中间状态 | 「请复述 app name + 说明为何 terminate」 |
| `argocd app unset <name> --sync-policy` | 关闭 automated syncPolicy，App 停止自愈/自动同步 | 「确认要关闭该 App 的自动化同步吗？」 |
| `argocd repo rm <url>` | 移除仓库凭证，依赖该仓库的应用会报 sync 错 | 「请复述 URL + 确认无应用依赖」 |
| `argocd cluster rm <ctx>` | 移除集群 context，影响所有依赖该集群的应用 | 「请复述 context + 确认无应用依赖」 |
| `argocd account delete-token <token>` | 吊销某个认证令牌，可能导致依赖它的自动化脚本失效 | 「请复述 token 前 8 位确认」 |
| `argocd app set --sync-policy automated --self-heal` | 开自愈，ArgoCD 会持续覆盖集群漂移 | 「这是 Root 入口或业务确实需要自愈吗？」 |

## P1 智能诊断（聚合分析层）

### 诊断工具集入口

```bash
# 一级入口
python -m argocd_insight diagnose          # 问题 App 诊断
python -m argocd_insight drift             # 版本漂移检测
python -m argocd_insight health            # 稳定性评估
python -m argocd_insight repo-health       # Git 源健康检查
python -m argocd_insight compliance       # 配置合规检查

# 或直接调用单个工具
python -m argocd_deploy_stats.oos_analyzer  # OutOfSync 根因归因
python -m argocd_deploy_stats.stats           # 部署频率统计
```



> 触发词：「所有 App 健康报告」「哪些 App 有问题」「部署频率」「谁部署最多」「最近部署了多少次」

### 部署频率统计工具

使用 `scripts/argocd_deploy_stats/stats.py`，依赖 Python 标准库（`concurrent.futures` 并发拉 history）：

```bash
# 最近 30 天部署频率统计（全量 566 App，约 3 分钟）
python -m argocd_deploy_stats.stats --days 30

# 只看最近 7 天（更快）
python -m argocd_deploy_stats.stats --days 7

# 只看某项目（更快）
python -m argocd_deploy_stats.stats --project default --days 7

# JSON 输出（供下游集成）
python -m argocd_deploy_stats.stats --days 30 --output json

# 调高并发（server 允许时加快）
python -m argocd_deploy_stats.stats --days 30 --concurrency 20
```

**输出内容：**
- 总 App 数 / 总部署次数
- 按触发者（自动化 / 各用户名）部署次数
- 最近 50 次部署详情（App / 时间 / 触发者 / Revision）

---

## 开机自检（会话开头）

每个会话处理第一条命令前，Agent 在内部（不在用户输出中）先做凭证自检。未通过则提示用户补全，不直接报错退出。

### 步骤 1：加载 `.env`（如果存在）

Agent 应优先检查 skill 仓库根目录下的 `.env` 文件并自动 `source`：

```bash
ENV_FILE="<skill-root>/.env"   # 例如：argocd-skill/.env
test -f "$ENV_FILE" && set -a; source "$ENV_FILE"; set +a
```

`.env` 中定义的变量优先级低于 shell env 中已 export 的同名变量（shell 的 `set -a` 不会覆盖已设变量）。`.env.example` 是模板，**不会被自动加载**。

### 步骤 2：认证凭证检测（4 层优先级）

| 优先级 | 来源 | 说明 |
|--------|------|------|
| **1** | Shell env 的 `ARGOCD_AUTH_TOKEN` | `argocd login --auth-token`，最高优先级 |
| **2** | `~/.config/argocd/config` | 本地已保存的 token + server 配置（含 `grpc-web-root-path` / `insecure`） |
| **3** | `.env` 中的 `ARGOCD_USERNAME` + `ARGOCD_PASSWORD` | 走 HTTP API `/api/v1/session` 获取 token（见步骤 5） |
| **4** | `.env` 中的 `ARGOCD_AUTH_TOKEN` | `.env` 中的 token，最低优先级 |

### 步骤 3：`ARGOCD_SERVER` 与 CLI 可用性

1. `command -v argocd` → 未找到则提示安装（参考「能力一：CLI 安装」）。
2. `ARGOCD_SERVER` 是否已设 → 未设则提示用户提供。

### 步骤 4：CLI login

```bash
argocd login "$ARGOCD_SERVER" \
  --username "$ARGOCD_USERNAME" \
  --password "$ARGOCD_PASSWORD"
```

如果成功 → 继续执行后续命令。

### 步骤 5：CLI login 失败 → HTTP API 回退（Python 模块）

当 `argocd login` 失败时（常见原因：context path `/dnet-int` 导致 gRPC-web 代理解析失败、`insecure` 证书、proxy 连接错误），**不阻塞退出**，改用内置的 Python HTTP API 客户端：

```bash
# 测试认证（自动从 .env / config / env 获取凭证）
python -m argocd_api login

# 查询应用
python -m argocd_api list
python -m argocd_api get hdops-mcp
python -m argocd_api resource-tree hdops-mcp

# Pod 操作
python -m argocd_api find-pod hdops-mcp-66f64bb8c9-7tw6n
python -m argocd_api resource hdops-mcp Pod hdops-mcp-66f64bb8c9-7tw6n --ns ops

# 同步 / 刷新
python -m argocd_api sync hdops-mcp
python -m argocd_api refresh hdops-mcp

# 删除资源（需二次确认）
python -m argocd_api delete-resource hdops-mcp Pod hdops-mcp-xxx --ns ops

# 查看渲染清单
python -m argocd_api manifests hdops-mcp
```

`.env` 文件自动从 `argocd-skill/.env` 加载，无需手动指定 `--env-file`。凭证优先级：
1. Shell env 的 `ARGOCD_AUTH_TOKEN`
2. `~/.config/argocd/config` 中匹配的 token
3. `.env` 中的 `ARGOCD_USERNAME` + `ARGOCD_PASSWORD` → API login

**常用 API 端点映射表（`python -m argocd_api` 底层调用）：**

| 操作 | CLI 命令 | Python CLI | HTTP API |
|------|----------|------------|----------|
| 登录（获取 token） | `argocd login` | `python -m argocd_api login` | `POST /api/v1/session` |
| 应用列表 | `argocd app list` | `python -m argocd_api list` | `GET /api/v1/applications` |
| 应用详情 | `argocd app get <name>` | `python -m argocd_api get <name>` | `GET /api/v1/applications/{name}` |
| 资源树（Pod 状态） | `argocd app wait --health` | `python -m argocd_api resource-tree <name>` | `GET /api/v1/applications/{name}/resource-tree` |
| 查找 Pod | `kubectl get pod -A \| grep` | `python -m argocd_api find-pod <pod>` | 遍历所有 App 的 resource-tree |
| Pod 详细规格 | `kubectl get pod -o yaml` | `python -m argocd_api resource <app> Pod <name> --ns <ns>` | `GET /api/v1/applications/{name}/resource` |
| 删除 Pod | `kubectl delete pod` | `python -m argocd_api delete-resource <app> Pod <name> --ns <ns>` | `DELETE /api/v1/applications/{name}/resource` |
| 同步 | `argocd app sync <name>` | `python -m argocd_api sync <name>` | `POST /api/v1/applications/{name}/sync` |
| 创建应用 | `argocd app create` | （暂不支持，需 CLI） | `POST /api/v1/applications` |

**与批量工具的对齐：** `python -m argocd_cli_gen` 生成的 `00_preflight.sh` 实现了同样的自检逻辑（env 检查 + `argocd version --client` + `argocd login --auth-token --grpc-web` + `argocd account get-user-info`）。能力 2（单条命令生成）走 LLM 提示阶段，能力 3.2 走 shell 落地阶段，**两阶段自检项必须一致**。

**凭证处理硬性约束：**

- `ARGOCD_AUTH_TOKEN` / `ARGOCD_PASSWORD` 永远**不回显**、**不写日志**、**不传非加密通道**；Agent 输出中一律 mask 为 `***`。
- `ARGOCD_SERVER` 永远不让用户在内联命令里以明文粘贴（用户已经在 env 里 export 过）；Agent 引用时写 `$ARGOCD_SERVER`。
- `argocd login --username ... --password ...` 仅在交互场景使用；CI / 脚本场景一律走 `--auth-token "$ARGOCD_AUTH_TOKEN"`。
