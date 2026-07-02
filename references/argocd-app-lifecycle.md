# ArgoCD Application 生命周期 Runbook

> 覆盖 App 从创建到删除的完整操作路径。Agent 收到「创建 / 同步 / 回滚 / 删除 / 等就绪」类意图时，优先按本 runbook 编排命令。
>
> **关联文档：** [cli-commands.md](cli-commands.md) · [kustomize-mapping.md](kustomize-mapping.md) · [argocd-sync-policy-deep-dive.md](argocd-sync-policy-deep-dive.md)

---

## 状态机概览

```
                    ┌─────────────┐
                    │  (不存在)    │
                    └──────┬──────┘
                           │ app create / kubectl apply
                           ▼
                    ┌─────────────┐
         ┌─────────│   Created    │─────────┐
         │         └──────┬──────┘         │
         │ refresh      │ sync           │ delete
         ▼                ▼                ▼
  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
  │  Refreshing │  │   Syncing   │  │  Deleting   │
  └──────┬──────┘  └──────┬──────┘  └─────────────┘
         │                │
         └────────┬───────┘
                  ▼
           ┌─────────────┐
           │ Sync Status │
           ├─────────────┤
           │ Synced      │ ← 期望终态（Git == 集群）
           │ OutOfSync   │ ← 需 diff / sync / 排查漂移
           │ Unknown     │ ← 权限或 API 异常
           └──────┬──────┘
                  │
           ┌──────▼──────┐
           │Health Status│
           ├─────────────┤
           │ Healthy     │
           │ Degraded    │ ← 常配合 rollback / 事件排查
           │ Missing     │ ← 资源未部署或已被删
           │ Progressing │ ← 滚动更新中，用 wait
           └─────────────┘
```

**快速判读：**

| sync.status | health.status | 典型含义 | 首选动作 |
|-------------|---------------|---------|---------|
| Synced | Healthy | 正常 | 无（或例行 refresh） |
| OutOfSync | Healthy | Git 与集群有差异，工作负载仍健康 | `app diff` → `app sync` |
| Synced | Degraded | 已同步但 Pod/Deployment 异常 | `app get` / `app logs` → `rollback` |
| OutOfSync | Degraded | 差异 + 运行异常 | 先 diff 归因，再决定 sync 或 rollback |
| Unknown | * | 控制器无法评估 | 检查 RBAC / repo 凭证 / server 连通 |

---

## Phase 0：前置检查（每次生命周期操作前）

```bash
# 凭证（优先 token，勿在聊天中粘贴）
test -n "$ARGOCD_AUTH_TOKEN" && test -n "$ARGOCD_SERVER" || echo "请先 export ARGOCD_AUTH_TOKEN / ARGOCD_SERVER 或 argocd login"

# CLI 可用
command -v argocd && argocd version --client

# 当前 context（多集群时必查）
argocd context
```

---

## Phase 1：创建（Create）

### 1.1 判定层级（决定 syncPolicy / labels / CreateNamespace）

| 层级 | namespace 特征 | syncPolicy | labels | CreateNamespace |
|------|---------------|------------|--------|-----------------|
| 聚合 Root | `argo-root` | **automated + prune + selfHeal** | 无 | true |
| 业务应用 | 业务 ns | **manual**（生产规范） | project/profile/stack/app 四件套 | true |
| 运维组件 | ops/loki/… | manual | 通常无 | **false** |

详见 [kustomize-mapping.md](kustomize-mapping.md) 与 SKILL.md「App-of-Apps 与层级分布」。

### 1.2 单源 Kustomize（最常见）

```bash
argocd app create my-app \
  --repo https://github.com/org/repo.git \
  --path apps/my-app/overlays/production \
  --revision k8s_mas \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace production \
  --project default \
  --upsert \
  --label project=myproj \
  --label profile=prd \
  --label stack=mas \
  --label app=my-app
```

### 1.3 从已有 YAML 创建（`-f`）

```bash
# 多源 Helm+$values 或复杂 spec 时，整段 YAML 投喂
argocd app create -f application.yaml --upsert
```

多源非 Helm+$values 模式 → **回退** `kubectl -n argocd apply -f application.yaml`（见 SKILL.md 常见错误表）。

### 1.4 创建后验证

```bash
argocd app get my-app -o json | jq '.status.sync.status, .status.health.status, .status.sync.revision'
argocd app diff my-app   # 预期：无差异或仅预期 diff
```

---

## Phase 2：同步（Sync）

### 2.1 手动同步（业务应用生产规范）

```bash
argocd app sync my-app \
  --prune \
  --sync-option PruneLast=true

argocd app wait my-app --health --timeout 300
argocd app get my-app -o json | jq '.status.health.status, .status.sync.status'
```

### 2.2 同步到指定 revision

```bash
argocd app sync my-app --revision abc1234 --prune
```

### 2.3 刷新（不部署，仅重算状态）

```bash
argocd app refresh my-app          # 软刷新
argocd app refresh my-app --hard   # 强制重新拉 Git
```

### 2.4 批量同步

```bash
# 工具化（推荐 ≥5 个 App）
python -m argocd_insight batch sync --status OutOfSync --dry-run
python -m argocd_insight batch sync --status OutOfSync --concurrency 5
```

---

## Phase 3：观察与诊断（Observe）

```bash
# 详情 + 条件
argocd app get my-app
argocd app get my-app -o json | jq '.status.conditions'

# 差异
argocd app diff my-app

# 资源树
argocd app resources my-app

# 历史
argocd app history my-app

# 日志 / 事件
argocd app logs my-app --tail 100
argocd app events my-app
```

**OutOfSync 根因批量分析：**

```bash
python -m argocd_deploy_stats.oos_analyzer --project default
# 或
python -m argocd_insight diagnose --output markdown
```

---

## Phase 4：回滚（Rollback）

```bash
# 查看历史 ID
argocd app history my-app

# 回滚到上一版本（省略 HISTORY_ID）
argocd app rollback my-app

# 回滚到指定历史
argocd app rollback my-app 3

argocd app wait my-app --health --timeout 300
```

**操作前影响预览：**

```bash
python -m argocd_insight impact my-app rollback 3
```

---

## Phase 5：修改配置（Set / Unset）

```bash
# 改 revision / namespace
argocd app set my-app --revision main
argocd app set my-app --dest-namespace staging

# 开启自动化（仅 Root 入口或业务方明确要求）
argocd app set my-app --sync-policy automated --auto-prune --self-heal

# 关闭自动化 → 手动 sync
argocd app unset my-app --sync-policy
```

⚠️ `--auto-prune` 必须配合 `--sync-policy automated`（见 [argocd-sync-policy-deep-dive.md](argocd-sync-policy-deep-dive.md)）。

---

## Phase 6：删除（Delete）— 危险操作

**必须**让用户完整复述 `APPNAME` 后才生成命令。

```bash
# 仅删 Application CR（保留集群资源）
argocd app delete my-app

# 级联删除（回收 Git 管理的资源）
argocd app delete my-app --cascade
```

删除前建议：

```bash
argocd app get my-app -o json | jq '.spec.destination, .status.resources | length'
python -m argocd_insight impact my-app sync   # 了解影响面
```

---

## 复合意图编排模板

### 创建并同步

```bash
argocd app create my-app \
  --repo <url> --path <path> --revision <rev> \
  --dest-namespace production --project default --upsert

argocd app sync my-app --prune --sync-option PruneLast=true
argocd app wait my-app --health --timeout 300
```

### 同步并验证

```bash
argocd app sync my-app --prune --sync-option PruneLast=true
argocd app wait my-app --health --timeout 300
argocd app get my-app -o json | jq '.status.health.status, .status.sync.status'
```

### 回滚并验证

```bash
argocd app history my-app
argocd app rollback my-app
argocd app wait my-app --health --timeout 300
```

---

## 常见陷阱

| 陷阱 | 正确处理 |
|------|---------|
| 未 login 就 sync | 先 `argocd login` 或 export `ARGOCD_AUTH_TOKEN` |
| 业务 App 误开 automated | 生产业务 App 默认手动 sync |
| Root 漏 automated | `dest-namespace=argo-root` 必须 automated+prune+selfHeal |
| `metadata.name` 含 `_` | 应用名改为 `-`（git 分支 revision 可保留下划线） |
| sync 后仍 Out discovery | 用 `app wait --health`，不要只看 sync.status |
| CLI login 失败（context path） | 回退 `python -m argocd_api`（见 agent-protocols.md 0.4） |

---

## 外部参考

- [Application CRD 规范](https://argo-cd.readthedocs.io/en/stable/user-guide/application-specification/)
- [argocd app 命令参考](https://argo-cd.readthedocs.io/en/stable/user-guide/commands/argocd_app/)
