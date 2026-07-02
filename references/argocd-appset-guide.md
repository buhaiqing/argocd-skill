# ApplicationSet Runbook

> ApplicationSet 用 Generator 批量生成 Application CR，适合多集群、多租户、多环境矩阵部署。
>
> **关联文档：** [argocd-app-lifecycle.md](argocd-app-lifecycle.md) · [argocd-appproject-guide.md](argocd-appproject-guide.md) · [cli-commands.md](cli-commands.md)

---

## 何时用 ApplicationSet vs 手写 App

| 场景 | 推荐 |
|------|------|
| 1~4 个固定 App | 手写 YAML 或 `argocd app create` |
| N 集群 × M 环境 × K 服务 | **ApplicationSet** |
| App-of-Apps Root 指向子目录 | Root App + git 目录结构（本仓库 97 样本主流） |
| 动态发现集群/仓库 | ApplicationSet Cluster/Git Generator |

---

## Generator 类型速查

| Generator | 输入 | 典型用途 |
|-----------|------|---------|
| `list` | 静态元素列表 | 固定几个 App 名/参数 |
| `clusters` | ArgoCD 已注册集群 | 每集群一份 App |
| `git` | Git 目录/file 发现 | 仓库子目录即 App |
| `matrix` | 两个 generator 笛卡尔积 | 集群 × 环境 |
| `merge` | 多 generator 合并 | 组合参数 |
| `scmProvider` | GitHub/GitLab org | 按 repo 生成 |
| `clusterDecisionResource` | 外部 ConfigMap | 高级路由 |
| `pullRequest` | PR 事件 | Preview 环境 |

---

## CLI 常用命令

```bash
argocd appset list
argocd appset get my-appset
argocd appset get my-appset -o yaml

# 干跑：预览将生成哪些 Application（不写入）
argocd appset generate my-appset

# 删除 — 危险操作
argocd appset delete my-appset
```

---

## 模板 1：List Generator（固定环境列表）

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: guestbook-envs
  namespace: argocd
spec:
  generators:
    - list:
        elements:
          - env: dev
            namespace: guestbook-dev
          - env: staging
            namespace: guestbook-staging
  template:
    metadata:
      name: 'guestbook-{{env}}'
    spec:
      project: default
      source:
        repoURL: https://github.com/argoproj/argocd-example-apps.git
        targetRevision: HEAD
        path: guestbook
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{namespace}}'
      syncPolicy:
        syncOptions:
          - CreateNamespace=true
```

```bash
kubectl -n argocd apply -f appset-guestbook-envs.yaml
argocd appset generate guestbook-envs
```

---

## 模板 2：Git Generator（目录即 App）

与 App-of-Apps 类似，但由 ApplicationSet 控制器生成子 App：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: cluster-addons
  namespace: argocd
spec:
  generators:
    - git:
        repoURL: https://github.com/org/argo-apps.git
        revision: main
        directories:
          - path: addons/*
  template:
    metadata:
      name: '{{path.basename}}'
    spec:
      project: infra
      source:
        repoURL: https://github.com/org/argo-apps.git
        targetRevision: main
        path: '{{path}}'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{path.basename}}'
      syncPolicy:
        automated:
          prune: true
          selfHeal: true
        syncOptions:
          - CreateNamespace=true
```

---

## 模板 3：Matrix（集群 × 环境）

```yaml
spec:
  generators:
    - matrix:
        generators:
          - clusters:
              selector:
                matchLabels:
                  env: production
          - list:
              elements:
                - app: payment
                - app: order
  template:
    metadata:
      name: '{{name}}-{{app}}'
    spec:
      project: ecommerce-prd
      source:
        repoURL: https://github.com/org/apps.git
        targetRevision: main
        path: '{{app}}/overlays/production'
      destination:
        server: '{{server}}'
        namespace: production
```

---

## 与 4-tier 模型的关系

本仓库生产样本（97 YAML）**主要用 App-of-Apps Root**，而非 ApplicationSet。迁移时注意：

| App-of-Apps | ApplicationSet |
|-------------|----------------|
| Root App 指向 git 子目录 | Git/Cluster generator 自动生成 |
| 子 App YAML 在 git 仓库 | template 渲染 Application |
| 层级由目录结构表达 | 层级由 generator + template 表达 |

**CLI 无法表达 ApplicationSet** — 始终 `kubectl -n argocd apply -f` 或 GitOps 管理 ApplicationSet CR 本身。

---

## 排查

```bash
# 生成的 App 列表
argocd app list -l argocd.argoproj.io/application-set-name=my-appset

# ApplicationSet 状态
kubectl -n argocd get applicationset my-appset -o yaml | yq '.status'

# 控制器日志
kubectl -n argocd logs deploy/argocd-applicationset-controller --tail=100
```

| 症状 | 可能原因 |
|------|---------|
| 无子 App 生成 | generator 无匹配元素 / project 约束 / template 渲染错误 |
| 子 App OutOfSync | template 中 path/revision 错误 |
| 重复 App 名 | template.metadata.name 冲突 |
| 删除 AppSet 后 App 残留 | 检查 `syncPolicy` 与 finalizer；可能需手动 delete |

---

## 危险操作

| 命令 | 说明 |
|------|------|
| `argocd appset delete NAME` | 需用户复述名称；可能影响所有生成的 App |
| template 开 automated+prune | 批量误删风险 — 先 `appset generate` 预览 |

---

## 外部参考

- [ApplicationSet 文档](https://argo-cd.readthedocs.io/en/stable/user-guide/application-set/)
- [Generators](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators/)
