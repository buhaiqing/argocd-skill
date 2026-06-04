# Application Manifest 转换示例

> 示例 1-5 基于内部生产 `argoapp` 仓库真实 YAML 提取，覆盖三大层级（业务/运维/Root/基础设施）与多源边界。

## 应用层级速查

| 示例 | 层级 | 真实占比 | 是否含 labels | 是否含 automated | CLI 是否完全可表达 |
|-----|------|--------|--------------|----------------|------------------|
| 1 | 业务应用（Kustomize 单源） | 76% | 是 | 否 | ✅ |
| 2 | 运维组件（Kustomize 单源 + CreateNamespace=false） | 18% | 否 | 否 | ✅ |
| 3 | Root 聚合入口（含 automated） | 5% | 否 | 是 | ✅ |
| 4 | 基础设施层 Root（精简 automated 写法） | <1% | 否 | 是（精简） | ⚠️ 含字段省略 |
| 5 | 多源 Helm + $values（CLI 边界） | 3% | 否 | 否 | ⚠️ argocd CLI 走 `app create -f` 而非 flag |
| 6 | 含 Kustomize transformer 的完整应用 | 假设场景 | 是 | 是 | ✅ |
| 7 | 含 patches/components 的应用（边界） | 假设场景 | 是 | 否 | ⚠️ patches 字段需保留 YAML |

---

## 示例 1：业务应用（最常见模式，76% 场景）

**输入 YAML（基于 `argo-apps/dly/production/k8s_mas/dly3-mas-user-service.yaml`）：**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: production-mas-user-service
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
  labels:
    project: dly
    profile: production
    stack: dly3
    app: mas-user-service
spec:
  destination:
    name: ''
    namespace: 'production'
    server: https://kubernetes.default.svc
  source:
    path: mas-user-service/overlays/production/production
    repoURL: https://github-argocd.hd123.com/qianfanops/toolset_dly.git
    targetRevision: k8s_mas
    kustomize:
      version: v4.1.3
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
```

**输出命令：**

```bash
argocd app create production-mas-user-service \
  --app-namespace argocd \
  --set-finalizer \
  --label project=dly \
  --label profile=production \
  --label stack=dly3 \
  --label app=mas-user-service \
  --project default \
  --repo https://github-argocd.hd123.com/qianfanops/toolset_dly.git \
  --revision k8s_mas \
  --path mas-user-service/overlays/production/production \
  --kustomize-version v4.1.3 \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace production \
  --sync-option PruneLast=true
```

> **说明：** 业务应用必含 labels 四件套 `project/profile/stack/app`，syncOptions 只有 `PruneLast=true`，**无 automated**（业务变更需运维显式触发 sync）。

---

## 示例 2：运维组件（含 CreateNamespace=false，约 17.5% 场景）

**输入 YAML（基于 `argo-apps/dly/production/k8s_ops/dl1h-prometheus.yaml`）：**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prometheus
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    name: ''
    namespace: 'ops'
    server: 'https://kubernetes.default.svc'
  source:
    path: prometheus/overlays/dly-prd/dl1h
    repoURL: 'https://github-argocd.hd123.com/qianfanops/toolset_dly.git'
    targetRevision: k8s_ops
    kustomize:
      version: v4.1.3
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
      - CreateNamespace=false
```

**输出命令：**

```bash
argocd app create prometheus \
  --app-namespace argocd \
  --set-finalizer \
  --project default \
  --repo https://github-argocd.hd123.com/qianfanops/toolset_dly.git \
  --revision k8s_ops \
  --path prometheus/overlays/dly-prd/dl1h \
  --kustomize-version v4.1.3 \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace ops \
  --sync-option PruneLast=true \
  --sync-option CreateNamespace=false
```

> **说明：** 运维组件 94% 无 labels；`CreateNamespace=false` 是生产规范（namespace 由 initns 单独 Application 管理），**勿误转为 `CreateNamespace=true`**。

---

## 示例 3：Root 聚合入口（App-of-Apps 模式，5% 场景）

**输入 YAML（基于 `argo-apps/dly/production/dly-production-k8s_ops.yaml`）：**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: dly-production-k8s-ops
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    name: ''
    namespace: 'argo-root'
    server: https://kubernetes.default.svc
  source:
    path: argo-apps/dly/production/k8s_ops
    repoURL: https://github-argocd.hd123.com/qianfanops/argoapp.git
    targetRevision: dly_prd
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
    automated:
      prune: true
      selfHeal: true
```

**输出命令：**

```bash
argocd app create dly-production-k8s-ops \
  --app-namespace argocd \
  --set-finalizer \
  --project default \
  --repo https://github-argocd.hd123.com/qianfanops/argoapp.git \
  --revision dly_prd \
  --path argo-apps/dly/production/k8s_ops \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace argo-root \
  --sync-policy automated \
  --auto-prune \
  --self-heal \
  --sync-option PruneLast=true
```

> **说明：** Root YAML 特征——`destination.namespace=argo-root`、`metadata.name` 含 `_` 已替换为 `-`（源分支 `dly_prd` 中的 `_` 不在 name 字段无需处理）、`automated.prune+selfHeal` 必含、**无 Kustomize 子字段**（聚合 root 通常是纯目录引用）。

---

## 示例 4：基础设施层 Root（管理 root 的 root）

**输入 YAML（基于 `argoapp/projects/projects.yaml`）：**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: projects
spec:
  project: default
  source:
    repoURL: https://github-argocd.hd123.com/qianfanops/argoapp.git
    targetRevision: dly_prd
    path: projects/projects
  destination:
    name: ''
    server: https://kubernetes.default.svc
    namespace: argo-root
  syncPolicy:
    automated: {}
```

**输出命令：**

```bash
argocd app create projects \
  --project default \
  --repo https://github-argocd.hd123.com/qianfanops/argoapp.git \
  --revision dly_prd \
  --path projects/projects \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace argo-root \
  --sync-policy automated
  # ⚠️ 注意源 YAML 省略了 metadata.namespace 和 finalizers
  #    若需保持一致请手动 kubectl 创建；CLI 默认会带 finalizer 与 argocd namespace
```

> **说明：** 这是"管理 root 的 root"特殊层级，结构精简：
> 1. **省略 `metadata.namespace`** 与 `finalizers`（由 ArgoCD 默认值兜底）
> 2. **`automated: {}` 简写**——不开 prune/selfHeal，仅自动检测同步状态
> 3. CLI 无法完全表达这种"省略字段"语义。若必须保持完全一致，**保留 YAML + `kubectl apply -n argocd` 创建**

---

## 示例 5：多源 Helm + Git $values（约 3% 场景，CLI 边界）

**输入 YAML（基于 `argo-apps/dly/production/k8s_ops/loki.yaml`）：**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: loki
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  destination:
    name: ''
    namespace: 'loki'
    server: 'https://kubernetes.default.svc'
  sources:
    - repoURL: 'https://helm-charts.itboon.top/grafana'
      chart: loki
      targetRevision: 6.5.2
      helm:
        valueFiles:
        - $values/loki/overlays/dly-prd/values-scalable-s3.yaml
    - repoURL: 'https://github-argocd.hd123.com/qianfanops/toolset_dly.git'
      targetRevision: k8s_ops
      ref: values
  project: default
  syncPolicy:
    syncOptions:
      - PruneLast=true
      - CreateNamespace=false
```

**输出（推荐 `argocd app create -f`，保持 argocd CLI 工具栈一致）：**

argocd CLI 不能用 flag 描述多源，但 `argocd app create -f <yaml>` 接受任意
Application manifest，由服务端解析多源 spec。本 skill 据此把多源 Helm 应用归入
`MULTI_SOURCE_HELM` 层级，自动产出 `40_workloads_helm.sh` 与 `helm-apps/loki.yaml`：

```bash
argocd app create loki \
  -f helm-apps/loki.yaml \
  --upsert
```

`helm-apps/loki.yaml` 就是原 manifest 整体（保留 `spec.sources` 与 `$values` 引用不变）。
`40_workloads_helm.sh` 在执行前 `cd "$(dirname "$0")"`，保证相对路径解析到位。
dry-run 副本：

```bash
argocd app create --dry-run -o yaml \
  loki \
  -f helm-apps/loki.yaml \
  --upsert
```

> **关键边界：** 多源场景常用于 **Helm chart 与 values 文件分仓库**。`$values` 是 ArgoCD
> 多源专属语法，没有等价 CLI flag，但 `argocd app create -f` 可整段提交。
> 仅当多源不是 chart+ref 组合（如多个 git path、自定义 plugin）时，才回退到
> `kubectl -n argocd apply -f 99_multisource_fallback.yaml`。

---

## 示例 6：含 Kustomize Transformer 的完整应用（含 retry，假设场景）

**输入 YAML：**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: prod-api
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
spec:
  project: default
  source:
    repoURL: https://github-argocd.hd123.com/qianfanops/toolset_lsym.git
    targetRevision: main
    path: api/overlays/stable
    kustomize:
      version: v4.1.3
      namePrefix: stable-
      images:
        - my-app:ghcr.io/myorg/api:v3.0.0
      commonLabels:
        env: stable
        component: api
  destination:
    server: https://kubernetes.default.svc
    namespace: api-ns
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - PruneLast=true
    retry:
      limit: 3
      backoff:
        duration: 10s
        factor: 2
        maxDuration: 2m
```

**输出命令：**

```bash
argocd app create prod-api \
  --app-namespace argocd \
  --set-finalizer \
  --project default \
  --repo https://github-argocd.hd123.com/qianfanops/toolset_lsym.git \
  --revision main \
  --path api/overlays/stable \
  --kustomize-version v4.1.3 \
  --kustomize-nameprefix stable- \
  --kustomize-image my-app:ghcr.io/myorg/api:v3.0.0 \
  --kustomize-common-label env=stable \
  --kustomize-common-label component=api \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace api-ns \
  --sync-policy automated \
  --auto-prune \
  --self-heal \
  --sync-option PruneLast=true \
  --sync-retry-limit 3 \
  --sync-retry-backoff-duration 10s \
  --sync-retry-backoff-factor 2 \
  --sync-retry-backoff-max-duration 2m
```

> **说明：** 这是理论支持但生产几乎不通过 CLI 传递的字段集合——argoapp 仓库 97 个 YAML 中**未出现过 retry 字段**，namePrefix/images/commonLabels 也均由 `kustomization.yaml` 内部处理。

---

## 示例 7：含不支持字段的 Manifest（patches，边界处理示范）

**输入 YAML：**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: payment-svc
  namespace: argocd
  finalizers:
  - resources-finalizer.argocd.argoproj.io
  labels:
    project: payment
    profile: production
    stack: payment-api
    app: payment-svc
spec:
  project: default
  source:
    repoURL: https://github-argocd.hd123.com/qianfanops/toolset_lsym.git
    targetRevision: release/v2
    path: payment/overlays/prod
    kustomize:
      version: v4.1.3
      replicas:
        - name: payment-api
          count: 3
      patches:
        - target:
            kind: Deployment
            name: payment-api
          patch: |-
            - op: replace
              path: /spec/template/spec/containers/0/resources
              value:
                requests:
                  cpu: 500m
                  memory: 512Mi
  destination:
    server: https://kubernetes.default.svc
    namespace: payment-prod
  syncPolicy:
    syncOptions:
      - PruneLast=true
```

**输出命令：**

```bash
argocd app create payment-svc \
  --app-namespace argocd \
  --set-finalizer \
  --label project=payment \
  --label profile=production \
  --label stack=payment-api \
  --label app=payment-svc \
  --project default \
  --repo https://github-argocd.hd123.com/qianfanops/toolset_lsym.git \
  --revision release/v2 \
  --path payment/overlays/prod \
  --kustomize-version v4.1.3 \
  --kustomize-replicas payment-api=3 \
  --dest-server https://kubernetes.default.svc \
  --dest-namespace payment-prod \
  --sync-option PruneLast=true
  # ⚠️ spec.source.kustomize.patches: CLI 无直接对应 flag
  #    建议将 patches 写入 overlays 的 kustomization.yaml 或使用 YAML 方式管理
```

---

## 命名转换规则（实操要点）

转换时必须处理：

1. **`metadata.name` 含下划线** → 必须替换为 `-`
   - 例：源数据 `dly_production_k8s_mas` → CLI 中 `dly-production-k8s-mas`
2. **源 YAML 的 `targetRevision`（git 分支名）保留下划线**，**不要替换**
   - 例：`--revision k8s_mas`、`--revision dly_prd` 保持原样
3. **`metadata.namespace` 必须是 `argocd`**：CLI 用 `--app-namespace argocd`
4. **`destination.name: ''` 空字符串**：CLI 可省略 `--dest-name`
