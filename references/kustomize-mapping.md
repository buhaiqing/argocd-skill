# Kustomize Manifest 字段映射表

输入一个 ArgoCD Application YAML，逐项映射为 `argocd app create` CLI flag。

> **优先级标注：** P0 = 真实生产 95% 以上 YAML 必含；P1 = 30%~80% 使用，与层级相关；P2 = 实际生产几乎不通过 CLI 传递（多由 kustomization.yaml 内部处理）。
>
> **数据来源：** 内部 `argoapp` 仓库 97 个真实生产 Application YAML 全样本统计。

## 真实样本结构（用于判断映射场景）

| 应用层级 | 样本数 | 是否含 labels | 是否有 automated | 典型 namespace |
|---------|-------|--------------|----------------|--------------|
| 业务应用（k8s_dly/mas/oas/pluto） | 74 (76%) | 95% 有 | 无 | `production` |
| 运维组件（k8s_ops） | 18 (19%) | 6% 有 | 无 | `ops/loki/kube-system/...` |
| Root 聚合入口 | 5 (5%) | 0% | 100% 有 | `argo-root` |

→ **转换前先识别层级**，再决定 labels / automated / CreateNamespace 取值。

## 元数据字段

| 优先级 | Application CRD 字段 | CLI Flag | 真实生产取值 / 映射说明 |
|--------|----------------------|---------|---------|
| P0 | `metadata.name` | 位置参数 `APPNAME` | 直接取值。**注意**：不允许 `_`，源 YAML 含 `_` 时请改用 `-` |
| P0 | `metadata.namespace` | `--app-namespace` | 生产 100% 为 `argocd` |
| P0 | `metadata.finalizers` | `--set-finalizer` | 生产 100% 含 `resources-finalizer.argocd.argoproj.io` |
| P0/P1 | `metadata.labels` | `--label KEY=VAL` | 业务应用 P0（key：`project`/`profile`/`stack`/`app`）；运维组件 P2（94% 不带 labels） |
| P2 | `metadata.annotations` | `--annotations KEY=VAL` | 生产几乎不用 |

## 源字段 - 单源 spec.source（97% 场景）

| 优先级 | Application CRD 字段 | CLI Flag | 真实生产取值 |
|--------|----------------------|---------|---------|
| P0 | `spec.source.repoURL` | `--repo` | 业务/运维：`https://github-argocd.hd123.com/qianfanops/toolset_*.git`；Root：`.../argoapp.git` |
| P0 | `spec.source.targetRevision` | `--revision` | 业务 `k8s_mas/k8s_dly/k8s_oas/k8s_pluto`；运维 `k8s_ops`；Root `{project}_prd` |
| P0 | `spec.source.path` | `--path` | 业务：`{app}/overlays/{profile}/{stack}`；Root：`argo-apps/{project}/{profile}/{branch}` |

## 源字段 - 多源 spec.sources（3% 场景，CLI 边界）

argocd CLI 不支持用 flag 描述多源（截至 v2.13 仍是"UI/CLI 只识别第一个 source"）。
按多源结构落到两条不同通道：

| 场景识别 | 处置通道 | 工具产物 |
|---------|---------|---------|
| 所有 source 满足 `chart`（Helm 仓库）+ `ref`（values 仓库）；至少含一个 chart 源 → **Helm + $values 模式** | `argocd app create -f <yaml> --upsert`（YAML 整体投喂 argocd 服务端） | `40_workloads_helm.sh` + `helm-apps/<name>.yaml` |
| 其余多源场景（多个 git path、自定义 plugin 等） | `kubectl -n argocd apply -f`（绕过 argocd CLI） | `99_multisource_fallback.yaml` |

| 优先级 | Application CRD 字段 | CLI 表达 | 映射说明 |
|--------|----------------------|---------|---------|
| P1 | `spec.sources[]` | `argocd app create -f` / `kubectl apply -f` | 按上表选择通道，**单条命令 + 整段 YAML** 而非 flag 拼接 |
| - | `spec.sources[].chart` | （YAML 内字段）| Helm chart 名，由服务端解析 |
| - | `spec.sources[].helm.valueFiles` | （YAML 内字段）| 含 `$values/` 变量引用另一个 Git 源 |
| - | `spec.sources[].ref: values` | （YAML 内字段）| 标识 values 仓库；ref 源不得带 `chart` |

## 目标字段（destination）

| 优先级 | Application CRD 字段 | CLI Flag | 真实生产取值 |
|--------|----------------------|---------|---------|
| P0 | `spec.destination.server` | `--dest-server` | 100% 为 `https://kubernetes.default.svc` |
| P0 | `spec.destination.namespace` | `--dest-namespace` | 业务：`production/{profile}`；Root：`argo-root`；运维按服务名 |
| P1 | `spec.destination.name` | `--dest-name` | 生产 95% 为空字符串 `''`，可省略 |

## 同步策略字段（syncPolicy）

| 优先级 | Application CRD 字段 | CLI Flag | 真实占比 / 映射说明 |
|--------|----------------------|---------|---------|
| P0 | `spec.syncPolicy.syncOptions[]` | `--sync-option OPT=VAL` | 每行用独立 flag |
| P1 | `spec.syncPolicy.automated` | `--sync-policy automated` | 6/97 (6%)，**仅 Root 入口含** |
| P1 | `spec.syncPolicy.automated.prune` | `--auto-prune` | 必与 `automated` 同时存在 |
| P1 | `spec.syncPolicy.automated.selfHeal` | `--self-heal` | 同上 |
| P1 | `spec.syncPolicy.automated.allowEmpty` | `--allow-empty` | 同上 |
| P2 | `spec.syncPolicy.retry.limit` | `--sync-retry-limit` | 生产几乎不用 |
| P2 | `spec.syncPolicy.retry.backoff.duration` | `--sync-retry-backoff-duration` | 同上 |
| P2 | `spec.syncPolicy.retry.backoff.factor` | `--sync-retry-backoff-factor` | 同上 |
| P2 | `spec.syncPolicy.retry.backoff.maxDuration` | `--sync-retry-backoff-max-duration` | 同上 |

## syncPolicy.syncOptions 真实频次（97 YAML 全样本）

| syncOption 值 | CLI 参数 | 真实占比 | 何时出现 |
|---------------|---------|-------|---------|
| `PruneLast=true` | `--sync-option PruneLast=true` | **97/97 (100%)** | **强制**模板字段，所有应用必含 |
| `CreateNamespace=false` | `--sync-option CreateNamespace=false` | 17/97 (17.5%) | 运维组件（namespace 已由 initns 单独管理） |
| `CreateNamespace=true` | `--sync-option CreateNamespace=true` | 1/97 (1%) | 极少数 Root 入口，**生产推荐用 initns 显式管理** |
| `ServerSideApply=true` | `--sync-option ServerSideApply=true` | 0/97 | 实际未在 argoapp 中出现 |
| `ApplyOutOfSyncOnly=true` | `--sync-option ApplyOutOfSyncOnly=true` | 0/97 | 同上 |
| `Replace=true` | `--sync-option Replace=true` | 0/97 | 同上 |
| `Validate=false` | `--sync-option Validate=false` | 0/97 | 同上 |

> **规则提取：** 转换时若源 YAML 未显式声明 syncOption，**默认补 `PruneLast=true`**。`CreateNamespace=false` 仅在 `destination.namespace` 命中 namespace 由 initns 管理的清单时显式补；其他场景留空。

## Kustomize 专属字段

| 优先级 | Application CRD 字段 | CLI Flag | 真实生产取值 |
|--------|----------------------|---------|---------|
| P0 | `spec.source.kustomize.version` | `--kustomize-version` | 生产 95% 取值 `v4.1.3` |
| P2 | `spec.source.kustomize.namePrefix` | `--kustomize-nameprefix` | 由 kustomization.yaml 处理 |
| P2 | `spec.source.kustomize.nameSuffix` | `--kustomize-namesuffix` | 同上 |
| P2 | `spec.source.kustomize.images[]` | `--kustomize-image` | 同上，每行用独立 flag |
| P2 | `spec.source.kustomize.commonLabels` | `--kustomize-common-label` | 同上，每对键值用独立 flag |
| P2 | `spec.source.kustomize.commonAnnotations` | `--kustomize-common-annotation` | 同上 |
| P2 | `spec.source.kustomize.namespace` | `--kustomize-namespace` | 同上 |
| P2 | `spec.source.kustomize.replicas[]` | `--kustomize-replicas` | 同上，每行用独立 flag |
| P2 | `spec.source.kustomize.labelWithoutSelector` | `--kustomize-label-without-selector` | 存在即设置 |
| P2 | `spec.source.kustomize.forceCommonLabels` | `--kustomize-force-common-labels` | 存在即设置 |
| P2 | `spec.source.kustomize.forceCommonAnnotations` | `--kustomize-force-common-annotations` | 存在即设置 |
| P2 | `spec.source.kustomize.labelIncludeTemplates` | `--kustomize-label-include-templates` | 存在即设置 |
| P2 | `spec.source.kustomize.commonAnnotationsEnvsubst` | `--kustomize-common-annotation-envsubst` | 存在即设置 |
| P2 | `spec.source.kustomize.apiVersions[]` | `--kustomize-api-versions` | 每行用独立 flag |
| P2 | `spec.source.kustomize.kubeVersion` | `--kustomize-kube-version` | 直接取值 |
| P2 | `spec.source.kustomize.ignoreMissingComponents` | `--ignore-missing-components` | 存在即设置 |

## 其他字段

| 优先级 | Application CRD 字段 | CLI Flag | 真实生产取值 |
|--------|----------------------|---------|---------|
| P0 | `spec.project` | `--project` | 100% 为 `default` |
| P2 | `spec.revisionHistoryLimit` | `--revision-history-limit` | 生产几乎不用 |

## 不支持字段（CLI 无对应 flag）

转换时需以注释标注：

| 字段 | 说明 |
|------|------|
| `spec.sources[]`（非 Helm 多源）| argocd CLI 不直接支持多源 create，**保留 `kubectl apply -f` 方式管理**；命中 Helm + `$values` 模式时改走 `argocd app create -f` |
| `spec.source.kustomize.patches` | Kustomize 补丁，建议保留 YAML 方式管理 |
| `spec.source.kustomize.components` | Kustomize 组件，同上 |

## argoapp 仓库命名/路径规范（提取自 README + 生产模板）

转换/生成时需遵守：

1. **`metadata.name`：** 不允许出现 `_`。若源信息含 `_`（如 git_branch `k8s_dly`），需替换为 `-`（→ `k8s-dly`）
2. **业务 app YAML 路径：** `argo-apps/{project}/{profile}/{git_branch}/{stack}-{app}.yaml`
3. **Root 聚合 YAML 路径：** `argo-apps/{project}/{profile}/{project}-{profile}-{git_branch}.yaml`
4. **业务应用名约定：** `{stack}-{app}` 或 `{profile}-{app}`（生产实例可见两种风格）
5. **Root 应用名约定：** `{project}-{profile}-{git_branch}`（其中 `_` 替换为 `-`）
6. **labels 四件套：** 业务应用必含 `project / profile / stack / app`

## 优先级判定 cheatsheet

转换时按以下顺序决策：

```
源 YAML 含 spec.sources?
├─ 是 → 多源场景
│      ├─ 每个 source ∈ {chart 源, ref 源} 且至少含一个 chart 源 → MULTI_SOURCE_HELM
│      │      产物：argocd app create -f helm-apps/<name>.yaml --upsert（保留多源 spec 不变）
│      └─ 否 → MULTI_SOURCE → 输出 kubectl apply 方案 + 标注 CLI 不支持
└─ 否 → 单源场景（继续）
       │
       ├─ destination.namespace == "argo-root"? → Root 入口
       │    必含：automated.prune+selfHeal，不含 labels
       │
       ├─ targetRevision 含 "k8s_ops" 或 path 含 ops 组件? → 运维组件
       │    通常不含 labels，常含 CreateNamespace=false
       │
       └─ 其他 → 业务应用
            必含 labels 四件套，不含 automated
```
