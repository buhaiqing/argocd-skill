# AppProject 管理 Runbook

> AppProject 是 ArgoCD 的多租户边界：限制哪些 Git 仓库、哪些集群/命名空间可被 Application 使用。
>
> **关联文档：** [cli-commands.md](cli-commands.md) · [argocd-app-lifecycle.md](argocd-app-lifecycle.md)

---

## 概念模型

```
┌──────────────── AppProject ────────────────┐
│  metadata.name: my-project                 │
│  spec:                                     │
│    sourceRepos: []      ← 允许的 Git 仓库   │
│    destinations: []     ← 允许的目标集群+NS  │
│    clusterResourceWhitelist / blacklist      │
│    namespaceResourceWhitelist / blacklist  │
│    roles: []            ← RBAC 策略         │
└────────────────────────────────────────────┘
         ▲
         │ spec.project 引用
┌────────┴────────┐
│  Application    │
│  my-app         │
└─────────────────┘
```

**默认项目：** 新集群通常有 `default` AppProject，生产环境应拆分为按团队/环境隔离的 Project。

---

## 常用 CLI 命令

### 列表与详情

```bash
argocd proj list
argocd proj get my-project
argocd proj get my-project -o yaml
```

### 创建

```bash
argocd proj create my-project \
  --description "Production ecommerce apps"

# 允许的来源仓库（可多次指定）
argocd proj add-source my-project https://github.com/org/apps.git
argocd proj add-source my-project https://github.com/org/infra.git

# 允许的目标（cluster + namespace）
argocd proj add-destination my-project \
  https://kubernetes.default.svc \
  production

argocd proj add-destination my-project \
  https://kubernetes.default.svc \
  staging
```

### 修改与删除

```bash
# 移除 source / destination
argocd proj remove-source my-project https://github.com/org/old-repo.git
argocd proj remove-destination my-project https://kubernetes.default.svc ops

# 删除 Project — 危险操作，需用户复述项目名
argocd proj delete my-project
```

---

## YAML 模板（基础设施 Root 场景）

典型放在 `argo-root` namespace，由 init Root App 管理：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: ecommerce-prd
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  description: E-commerce production workloads
  sourceRepos:
    - https://github.com/org/toolset_*.git
    - https://github.com/org/argoapp.git
  destinations:
    - namespace: production
      server: https://kubernetes.default.svc
    - namespace: argo-root
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: "*"
      kind: "*"
  namespaceResourceWhitelist:
    - group: "*"
      kind: "*"
```

**CLI 等价（简化版）：**

```bash
kubectl -n argocd apply -f appproject-ecommerce-prd.yaml
# 或
argocd proj create -f appproject-ecommerce-prd.yaml
```

---

## 与 Application 的绑定

创建 App 时必须指定 `--project`，且需满足 Project 的 source/destination 约束：

```bash
argocd app create order-service \
  --repo https://github.com/org/toolset_mas.git \
  --path order/overlays/prd/mas \
  --revision k8s_mas \
  --dest-namespace production \
  --dest-server https://kubernetes.default.svc \
  --project ecommerce-prd
```

**典型报错：**

| 错误信息 | 原因 | 修复 |
|---------|------|------|
| `repository not permitted` | repo 不在 `sourceRepos` | `proj add-source` |
| `destination not permitted` | cluster/ns 不在 `destinations` | `proj add-destination` |
| `resource X not allowed` | 资源类型被 blacklist | 调整 whitelist/blacklist |

---

## 集群注册（跨集群部署前置）

AppProject 的 `destinations.server` 必须是已注册集群：

```bash
argocd cluster list
argocd cluster add <context-name> --name prod-cluster

# 查看集群详情
argocd cluster get https://kubernetes.default.svc
```

---

## 仓库注册

Project 允许某 URL 模式，但 ArgoCD 还需能连接该仓库：

```bash
argocd repo list
argocd repo add https://github.com/org/private.git \
  --username git --password "$GIT_TOKEN"
# SSH
argocd repo add git@github.com:org/private.git --ssh-private-key-path ~/.ssh/id_rsa
```

**健康检查：**

```bash
python -m argocd_insight repo-health
```

---

## RBAC 角色（spec.roles）

AppProject 可定义项目级 RBAC（配合 ArgoCD Casbin 策略）：

```yaml
spec:
  roles:
    - name: developer
      description: Read-only + sync dev apps
      policies:
        - p, proj:ecommerce-prd:developer, applications, get, ecommerce-prd/*, allow
        - p, proj:ecommerce-prd:developer, applications, sync, ecommerce-prd/dev-*, allow
      groups:
        - github:org:team-dev
```

CLI 管理 roles 较繁琐，复杂策略推荐 **YAML + kubectl apply**。

---

## 生产检查清单

| 检查项 | 命令 / 方法 |
|--------|------------|
| 每个业务 App 非 default project | `argocd app list -o json \| jq '.[].spec.project' \| sort -u` |
| sourceRepos 无 `*` 通配（除非刻意） | `argocd proj get <name> -o yaml` |
| destinations 不含 kube-system 等业务 ns（除非运维 Project） | 合规工具 |
| orphaned repos 已清理 | `argocd repo list` |

```bash
python -m argocd_insight compliance --severity high
```

---

## 危险操作

| 命令 | 二次确认 |
|------|---------|
| `argocd proj delete <name>` | 用户复述项目名 + 提示不可逆 |
| `argocd cluster rm <ctx>` | 用户复述 + 提示影响所有关联 App |
| `argocd repo rm <url>` | 用户复述 URL |

---

## 外部参考

- [Projects](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/)
- [Security](https://argo-cd.readthedocs.io/en/stable/operator-manual/security/)
