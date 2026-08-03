# ArgoCD 重启 Pod Runbook

## 1. 两种重启范式对比

| 范式 | 命令 | 影响范围 | ArgoCD Action 定义位置 |
|------|------|---------|----------------------|
| **Deployment Action** | `argocd app actions run <app> restart --kind Deployment --resource-name <name>` | **整个 Deployment（所有 Pod）** | Deployment 级别 |
| **ulw / argocd_api 单 Pod** | `python -m ulw delete-pod <pod>` | **仅单个 Pod**（Deployment 自愈拉起） | 无需 ArgoCD Action |

## 2. 范式一：Deployment 级别 restart

**适用场景**：需要重启整个 Deployment 的所有 Pod。

```bash
# 查看可用 Action
argocd app actions list <app> --server <server>

# 执行 restart（重启所有 Pod）
argocd app actions run <app> restart \
  --kind Deployment \
  --resource-name <deployment-name> \
  --server <server>
```

**示例**（hdops-mcp）：
```bash
source .env && argocd app actions run hdops-mcp restart \
  --kind Deployment \
  --resource-name hdops-mcp \
  --server "argocd.hd123.com"
```

**⚠️ 注意**：restart action 定义在 **Deployment 级别**，不是 Pod 级别。执行后 Deployment 下所有 Pod 都会被重启。

## 3. 范式二：单个 Pod 重启（推荐 ulw）

**适用场景**：只需要重启某个特定的 Pod，无需 kubectl 凭证。

### 3.1 首选：ulw

```bash
# 1. 查找 Pod 归属的 App（会扫描所有 Application）
python -m ulw find-pod <pod-name>

# 2. 删除 Pod（交互式确认后，Deployment 自愈拉起新 Pod）
python -m ulw delete-pod <pod-name>
# → 输入 "yes" 确认
# → ArgoCD API 调用 delete_application_resource
# → Deployment 检测到 Pod 缺失 → 自动重建 Pod
```

**实测**（hdops-mcp-7b8cc44dd8-mdp97）：
```bash
$ python -m ulw delete-pod hdops-mcp-7b8cc44dd8-mdp97
[ulw] delete Pod hdops-mcp-7b8cc44dd8-mdp97 via App hdops-mcp? Type 'yes': yes
[ulw] delete result: {}
# → Deployment 状态：Healthy → Progressing → 新 Pod 拉起
```

### 3.2 替代：argocd_api（直接调用 API）

```python
from argocd_api.client import ArgoCDClient
client = ArgoCDClient.from_env()
client.delete_application_resource(
    app_name='hdops-mcp',
    kind='Pod',                 # ⚠️ kind 必须在 namespace 之前
    name='hdops-mcp-7b8cc44dd8-mdp97',
    namespace='ops',
)
```

**⚠️ 重要陷阱**：参数顺序错误会导致 400 "Pod not found as part of application"。
`scripts/ulw/commands.py:delete_pod()` 是正确的实现参考。

### 3.3 kubectl 兜底（如果有集群凭证）

```bash
kubectl delete pod <pod-name> -n <namespace>
```

## 4. 工具支持详解

### 4.1 ulw（ArgoCD HTTP API）✅ **首选**

```bash
# 子命令
python -m ulw find-pod <pod-name>      # 查找 Pod 归属 App
python -m ulw delete-pod <pod-name>    # 删除 Pod（需交互式确认）

# 实现流程
# 1. find_pod 遍历所有 Application，用 get_application_pods 定位 Pod 归属的 App
#    （get_application_pods 先打 /applications/<app>/pods，404 再回退 /resource-tree 筛 kind==Pod）
# 2. delete_pod 调用 client.delete_application_resource 删除 Pod
# 3. Deployment 通过 ReplicaSet 控制器自动重建 Pod
```

`find_pod` 可以定位 Pod（经 `/pods` 或 `/resource-tree` 回退）。注意
`managed-resources` 接口本身不返回 Pod，但 `get_application_pods` 用
`/pods` 端点规避了此限制，故 `find-pod` / `delete-pod` 均可用。
详见 [ulw 重启 Pod runbook](ulw-restart-pod.md)。

### 4.2 argocd_api（HTTP API）

```bash
# 完整调用链（参数顺序是关键）
python3 << 'EOF'
from argocd_api.client import ArgoCDClient
client = ArgoCDClient.from_env()
result = client.delete_application_resource(
    app_name='hdops-mcp',
    kind='Pod',
    name='hdops-mcp-7b8cc44dd8-mdp97',
    namespace='ops',
)
print(result)
EOF
```

### 4.3 ArgoCD CLI

```bash
# argocd CLI 无 "delete pod" 子命令
# 只能查 Application 信息，或执行 Deployment 级别 restart
```

### 4.4 argocd_insight

无 Pod 操作能力（仅 Application 级别：diagnose/drift/health/batch/sync/rollback/refresh）。

## 5. 危险操作确认

无论哪种范式，执行前必须：
1. **确认目标 Pod 名称**（避免误删其他 Pod）
2. **确认 namespace**（避免误操作其他环境）
3. **确认影响范围**（Deployment restart 影响所有 Pod）
4. **确认无持久化问题**（本地存储 Pod 被删除后数据丢失）

## 6. 触发短语

- "重启 my-app 里的某个 Pod"
- "只重启一个 Pod，不要动其他的"
- "Pod 临时卡住了，帮我删掉它"
- "Deployment 级别的 restart 和单个 Pod 重启有什么区别"
- "用 ulw 删这个 Pod"
- "用 ArgoCD API 重启 Pod"
