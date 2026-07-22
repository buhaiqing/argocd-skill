# ArgoCD Rollouts 渐进式交付指南

> 本文件是 `argocd-skill` 的 Rollouts 能力深度参考。核心能力入口见
> `SKILL.md` 的「3.6 能力四：ArgoCD Rollouts 渐进式交付」。
> 运行态只读诊断工具：`python -m argocd_insight rollouts diagnose <name> -n <ns>`

## 1. Rollouts 是什么，与 ArgoCD 什么关系

ArgoCD Rollouts 是一个**独立于核心 ArgoCD** 的 Kubernetes 控制器，用
`Rollout` CRD（自定义资源）**替代原生的 `Deployment`**，提供：

- **金丝雀（Canary）**：按权重阶梯逐步放量（5% → 25% → 50% → 100%）。
- **蓝绿（BlueGreen）**：起一套 preview 副本，验证通过后切流量。
- **Analysis 驱动**：在发布步骤中嵌入指标分析，失败自动中止。

关系澄清：

- ArgoCD **Application** 负责把 Git 里的清单同步到集群（GitOps）。
- Rollout 是清单里的一种**工作负载资源**（替代 Deployment），由 `argo-rollouts`
  controller 管理其发布过程。
- 二者**不冲突**：Application 可以继续 GitOps 同步包含 `Rollout` 的清单。

前置条件（agent 必须提示用户）：

- 集群已安装 `argo-rollouts` controller（`kubectl get pods -n argo-rollouts`）。
- `kubectl argo rollouts` 插件已安装（见 §6）。
- Rollout 关联的 `Service`（canary/blueGreen 必须）需**预先存在**。

---

## 2. Deployment → Rollout 转换

当用户拿一个普通 `Deployment` 来问"怎么灰度/金丝雀/蓝绿"，按以下规则转换。

### 2.1 平移字段

| Deployment.spec | Rollout.spec | 说明 |
|---|---|---|
| `replicas` | `replicas` | 原样 |
| `selector` | `selector` | **必须**保留，且 `template.labels` 需匹配 |
| `template` | `template` | 原样 |
| `revisionHistoryLimit` | `revisionHistoryLimit` | 原样 |
| `progressDeadlineSeconds` | `progressDeadlineSeconds` | 原样 |
| `strategy.rollingUpdate` | （删除） | Rollout 用 `strategy.canary/blueGreen` 替代 |

### 2.2 必须新增的字段

1. **`spec.strategy`**：`canary` 或 `blueGreen`，否则 Rollout 退化为 basic。
2. **`spec.strategy.canary/blueGreen.service`**：关联 Service 名（canary 用 `trafficRouting` 时还需 `ingress`/`gateway` 配置）。
3. 应用名净化：`metadata.name` 中的 `_` → `-`（与 ArgoCD 死法 2 一致）。

### 2.3 转换示例

**原始 Deployment**：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-app
  namespace: default
spec:
  replicas: 4
  selector:
    matchLabels: {app: my-app}
  template:
    metadata:
      labels: {app: my-app}
    spec:
      containers:
        - name: my-app
          image: my-registry/my-app:1.0.0
```

**转换后 Rollout（canary 骨架，权重阶梯待填）**：

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: my-app          # 已做 s/_/-/g
  namespace: default
spec:
  replicas: 4
  selector:
    matchLabels: {app: my-app}
  template:
    metadata:
      labels: {app: my-app}
    spec:
      containers:
        - name: my-app
          image: my-registry/my-app:1.0.0
  strategy:
    canary:
      service: my-app          # 必须关联预存在的 Service
      steps:
        - setWeight: 5
        - pause: {duration: 5m}
        - setWeight: 25
        - pause: {duration: 5m}
        - setWeight: 50
        - pause: {duration: 5m}
        # 100% 由 rollout 自动达成，无需显式 setWeight: 100
```

> agent 输出后应提示：需在集群预先创建 `Service my-app`（selector 匹配
> `app: my-app`），并确认已安装 `argo-rollouts` controller。

---

## 3. 三种策略配置示例

### 3.1 Canary（最常用）

```yaml
strategy:
  canary:
    service: my-app          # 稳定流量 Service
    maxSurge: "25%"
    maxUnavailable: 0
    steps:
      - setWeight: 5
      - pause: {duration: 2m}          # 固定时长观察
      - setWeight: 25
      - pause: {duration: 5m}
      - setWeight: 50
      - pause: {duration: 10m}
      - setWeight: 100                  # 可选，显式收尾
    analysis:                            # 可选：全流程 Analysis
      templates:
        - templateName: success-rate
      startingStep: 2                   # 从 25% 那步开始分析
```

### 3.2 BlueGreen

```yaml
strategy:
  blueGreen:
    activeService: my-app-active        # 当前生产流量
    previewService: my-app-preview      # 新版本验证用
    previewReplicaCount: 1              # 预览副本数
    autoPromotionEnabled: false         # false=手动 promote 切流量
    # autoPromotionSeconds: 30          # 设了则自动切（去掉上面 false）
    scaleDownDelaySeconds: 30           # 旧版本缩容延迟
```

切流量命令：`kubectl argo rollouts promote my-app -n default`

### 3.3 Analysis（分析卡点）

Analysis 在发布步骤中验证指标，失败则中止发布。

```yaml
# AnalysisTemplate 示例（Prometheus 指标）
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
spec:
  metrics:
    - name: success-rate
      interval: 1m
      successCondition: result >= 0.95
      provider:
        prometheus:
          address: http://prometheus:9090
          query: |
            sum(rate(http_requests_total{status=~"2.."}[5m]))
              / sum(rate(http_requests_total[5m]))
```

在 canary steps 中嵌入 analysis：

```yaml
steps:
  - setWeight: 25
  - analysis:
      templates:
        - templateName: success-rate
      duration: 5m
```

---

## 4. 命令生成映射（kubectl argo rollouts）

| 用户意图 | 命令 |
|---|---|
| 查看状态 | `kubectl argo rollouts get rollout <name> -n <ns>` |
| 查看全称/简写 | `kubectl argo rollouts get rollout <name> -n <ns> --wide` |
| 手动推进到下一步 | `kubectl argo rollouts promote <name> -n <ns>` |
| 终止发布（保留旧版本） | `kubectl argo rollouts abort <name> -n <ns>` |
| 恢复被 abort 的发布 | `kubectl argo rollouts resume <name> -n <ns>` |
| 回滚到上一稳定版 | `kubectl argo rollouts undo <name> -n <ns>` |
| 暂停 | `kubectl argo rollouts pause <name> -n <ns>` |
| 更新镜像 | `kubectl argo rollouts set image <name> <container>=<image> -n <ns>` |
| 查看历史 | `kubectl argo rollouts history <name> -n <ns>` |
| 查看 AnalysisRun | `kubectl get analysisrun -n <ns> -l argo-rollouts=resource` |

---

## 5. 诊断（只读）

```bash
python -m argocd_insight rollouts diagnose <name> -n <ns> --output json
```

诊断工具**只读取**集群状态（`kubectl get rollout/analysisrun -o json`），
不执行任何写操作。输出两类结论：

### 5.1 Rollout 状态归因

| 状态 | 归类 | 严重级别 | 典型根因 |
|---|---|---|---|
| `aborted=true` | aborted | high | 用户或 Analysis 失败触发中止 |
| `paused=true`（Analysis） | paused | medium | 分析卡点未通过/未完成，需 `promote` |
| `phase=Degraded` | degraded | critical | 新版本不可用，建议 `undo` |
| `phase=Progressing` 卡在 step | stuck_progressing | medium | 卡在某 `setWeight`/`pause` 步骤 |
| `phase=Healthy` | healthy | info | 正常 |

### 5.2 AnalysisRun 失败归因

| phase | 归类 | 根因 |
|---|---|---|
| `Failed` + metric 未达标 | metric_failed | 阈值 `successCondition` 不满足 |
| `Error`/`Inconclusive` | run_incomplete | provider（Prometheus/Job）查询失败 |
| `Running` 无结果 | no_progression | 查询未返回 / 卡住 |

---

## 6. 插件安装（回退参考）

`kubectl argo rollouts` 插件缺失时：

```bash
# macOS
brew install argoproj/tap/kubectl-argo-rollouts

# Linux / 通用
curl -LO https://github.com/argoproj/argo-rollouts/releases/latest/download/kubectl-argo-rollouts-linux-amd64
chmod +x kubectl-argo-rollouts-linux-amd64
sudo mv kubectl-argo-rollouts-linux-amd64 /usr/local/bin/kubectl-argo-rollouts
```

---

## 7. 常见错误（agent 自查）

- 把 `Deployment` 直接 `kubectl apply` 成 `Rollout` 但**漏 strategy/service** → 退化为 basic（见 SKILL.md 死法 11）。
- `blueGreen.autoPromotionEnabled: false` 却等待自动切流量 → 需手动 `promote`。
- Analysis `successCondition` 写反（如 `result <= 0.95` 表示"错误率"）→ 语义确认。
- AnalysisRun 一直 `Running` → provider 地址不可达 / query 无数据。
- `setWeight: 100` 后还写 `pause` → 多余，100% 即终态。
