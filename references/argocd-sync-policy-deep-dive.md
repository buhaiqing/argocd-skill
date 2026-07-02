# syncPolicy 深度解析 Runbook

> 解释 `syncPolicy.automated` / `selfHeal` / `prune` / `syncOptions` 的组合语义，以及 4-tier 生产模型下的推荐配置。
>
> **关联文档：** [kustomize-mapping.md](kustomize-mapping.md) · [argocd-app-lifecycle.md](argocd-app-lifecycle.md) · [cli-commands.md](cli-commands.md)

---

## 字段速查

| YAML 字段 | CLI 等价 | 作用 |
|-----------|---------|------|
| `syncPolicy.automated` | `--sync-policy automated` | 检测到 Git 变更自动 sync |
| `syncPolicy.automated.selfHeal` | `--self-heal` | 集群被手动改动时自动拉回 Git 状态 |
| `syncPolicy.automated.prune` | `--auto-prune` | 删除 Git 中已移除的资源 |
| `syncPolicy.syncOptions[]` | `--sync-option KEY=VAL` | 细粒度 sync 行为 |
| （无 automated） | `--sync-policy none` 或 `unset` | 手动 sync |

**铁律：** `--auto-prune` 只能在 `--sync-policy automated` 下使用。

---

## syncOptions 常用项

| syncOption | 含义 | 生产样本占比 |
|------------|------|-------------|
| `CreateNamespace=true` | 目标 ns 不存在则创建 | 业务 App ~100%；运维组件常 **false** |
| `PruneLast=true` | 先 apply 新资源，最后再 prune 旧资源 | 业务/运维 Root 常见 |
| `ApplyOutOfSyncOnly=true` | 仅 apply OutOfSync 资源（加速大 App） | 大 manifest 可选 |
| `ServerSideApply=true` | 使用 SSA 合并字段 | 冲突多时可开 |
| `RespectIgnoreDifferences=true` | 尊重 ignoreDifferences 配置 | 与 ignoreDifferences 配合 |

**CLI 示例：**

```bash
argocd app create my-app \
  ... \
  --sync-option CreateNamespace=true \
  --sync-option PruneLast=true
```

---

## 4-tier 推荐矩阵（基于 argoapp 97 YAML 样本）

| 层级 | automated | selfHeal | prune | CreateNamespace | PruneLast |
|------|-----------|----------|-------|-----------------|-----------|
| 基础设施 Root | ❌ manual | — | — | false | — |
| **聚合 Root**（argo-root） | ✅ **必须** | ✅ | ✅ | true | true |
| **业务应用** | ❌ **manual** | ❌ | ❌ | true | ✅ 常见 |
| **运维组件** | ❌ manual | ❌ | ❌ | **false** | ✅ 常见 |

### 聚合 Root 入口（5% 样本）

```bash
argocd app create dly-prd-k8s_mas \
  --repo https://github.com/org/argoapp.git \
  --path argo-apps/dly/production/k8s_mas \
  --revision dly_prd \
  --dest-namespace argo-root \
  --dest-server https://kubernetes.default.svc \
  --project default \
  --sync-policy automated \
  --auto-prune \
  --self-heal \
  --sync-option CreateNamespace=true \
  --sync-option PruneLast=true
```

### 业务应用（76% 样本）

```bash
argocd app create mas-order-service \
  ... \
  --sync-option CreateNamespace=true \
  --sync-option PruneLast=true
# 注意：不加 --sync-policy automated
```

### 运维组件（18% 样本）

```bash
argocd app create prometheus \
  ... \
  --sync-option CreateNamespace=false \
  --sync-option PruneLast=true
```

---

## automated 三件套语义

```
Git 变更 ──→ automated sync ──→ 集群更新
                    │
手动 kubectl edit ──┼──→ selfHeal ──→ 拉回 Git（若开启）
                    │
Git 删资源 ─────────┼──→ prune ──→ 删集群资源（若开启）
```

| 组合 | 风险 | 适用 |
|------|------|------|
| automated only | 中：自动部署但集群漂移不回收 | 不推荐单独使用 |
| automated + selfHeal | 高：任何手动 hotfix 会被覆盖 | **仅 Root 入口** |
| automated + prune + selfHeal | 最高：全自动 GitOps | **仅聚合 Root** |
| manual + PruneLast | 低：人工 gate + 安全 prune 顺序 | **业务 App 生产规范** |

⚠️ 对业务 App 开启 `automated + selfHeal` 前必须询问用户：「这是 Root 入口还是业务方真的需要自愈？」

---

## retry 与 backoff

YAML（CLI 对 retry 支持有限，复杂策略用 YAML）：

```yaml
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  retry:
    limit: 5
    backoff:
      duration: 5s
      factor: 2
      maxDuration: 3m
```

**合规检查：**

```bash
python -m argocd_insight compliance --severity medium
```

常见违规：`automated-no-retry` / `automated-no-selfheal`（Root 层）/ `automated-no-prune`。

---

## ignoreDifferences（减少假 OutOfSync）

Deployment 副本数被 HPA 改变时，可忽略：

```yaml
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/replicas
```

CLI 创建后通常通过 `kubectl edit` 或 patch 追加；批量场景保留 YAML + `kubectl apply`。

---

## 修改已有 App 的 syncPolicy

```bash
# 开启自动化（危险 — 需确认）
argocd app set my-root --sync-policy automated --auto-prune --self-heal

# 关闭自动化
argocd app unset my-app --sync-policy

# 追加 sync-option（需 get 现有 options 后合并，或 patch YAML）
argocd app set my-app --sync-option PruneLast=true
```

---

## 决策树（Agent 用）

```
用户要配置 syncPolicy？
├─ destination.namespace == argo-root 且是聚合入口？
│   └─ YES → automated + prune + selfHeal + CreateNamespace=true
├─ 业务微服务 App？
│   └─ YES → manual sync + CreateNamespace=true + PruneLast=true + labels 四件套
├─ k8s_ops / 运维组件？
│   └─ YES → manual + CreateNamespace=false + PruneLast=true
└─ 不确定？
    └─ 问用户层级，默认 manual（安全侧）
```

---

## 常见错误

| 错误 | 修复 |
|------|------|
| `--auto-prune` 无 `--sync-policy automated` | 两者同时指定 |
| 业务 App 误开 selfHeal | `argocd app unset APP --sync-policy` |
| Root 漏 automated | `app set --sync-policy automated --auto-prune --self-heal` |
| 运维 App CreateNamespace=true | 改为 false（ns 由 initns 管理） |
| PruneLast 但 manual sync | 允许；PruneLast 只影响 sync 时 prune 顺序 |

---

## 外部参考

- [Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
- [Automated Sync Policy](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
