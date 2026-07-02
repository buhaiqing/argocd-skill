# ArgoCD Insight 命令参考

本文档是 `SKILL.md` 能力四~十五的完整命令索引。每个能力的「调用方式 + 输出示例 + 触发短语」三段式已从 `SKILL.md` 迁移至此。

---

## 能力四：诊断分析（OutOfSync 根因归因）

批量扫描所有 ArgoCD Application，筛选 OutOfSync 状态 App，通过 diff 分析自动归因：

| 归因维度 | CLI 命令 | 判断依据 |
|----------|---------|----------|
| Git 新增/未部署 | `argocd app diff` | diff 中出现 `+` / `>` 行（Git 有，集群无） |
| 手动漂移（集群多出） | `argocd app diff` | diff 中出现 `-` / `<` 行（集群有，Git 无） |
| 内容不一致 | `argocd app diff` | 同时有新增和删除行 |
| 孤儿资源 | `argocd app resources` | Orphaned 列值为 Yes |

### 调用方式

```bash
# 全量分析
python -m argocd_deploy_stats.oos_analyzer

# 只看最近 7 天 OutOfSync 的
python -m argocd_deploy_stats.oos_analyzer --days 7

# 指定项目
python -m argocd_deploy_stats.oos_analyzer --project default

# JSON 输出（供后续分析）
python -m argocd_deploy_stats.oos_analyzer --output json
```

### 输出示例

```
# ArgoCD OutOfSync 根因分析

总 App 数：102，OutOfSync：12

## 归因汇总
| 原因 | 数量 |
|------|------|
| 手动漂移（集群多出 Git 没有的资源） | 7 |
| Git 新增/未部署 | 3 |
| 内容不一致 | 2 |

### 手动漂移（7 个）
- `app-1`（手动漂移; 孤儿: Pod/stale-pod）
- `app-2`
```

### 触发短语

- "哪些 App 是 OutOfSync 的？什么原因？"
- "帮我批量分析 OutOfSync 根因"
- "看看有没有漂移的 App"
- "OutOfSync 归因，按原因分类"
- "有没有手动漂移的 App 和孤儿资源？"
- "哪些 App Git 有但集群没有？"
- "分析一下 production 项目的 OOS 情况"
- "给我一份 OutOfSync 诊断报告（JSON 格式）"
- "批量查所有 OutOfSync 的 App 是什么原因导致的"

### 输出字段说明

- `app` — 应用名称
- `cause` — 归因结果（None 表示已 Sync）
- `hasAdditions` — 是否有新增行
- `hasDeletions` — 是否有删除行
- `orphaned` — 孤儿资源列表
- `diffRc` — diff 命令退出码

> ⚠️ 注意：该工具每次运行时对每个 OOS App 执行 `argocd app resources` + `argocd app diff` 各一次（共 2 次 CLI 调用）。
> 566 App 环境按 ~10% OOS 率计，约 110 次调用，预估耗时 ~2 分钟。若 ArgoCD server 吞吐有限，可通过 `--concurrency 2` 降低并发。

**工具位置：** `scripts/argocd_deploy_stats/oos_analyzer.py`

---

## 能力五：批量操作（Batch Operations）

对指定 App 列表或筛选条件（project/label/status）批量并发执行 sync/rollback/refresh，支持 dry-run 预览和并发度控制。

### 调用方式

```bash
# 按项目过滤并同步
python -m argocd_insight batch sync --project my-project

# 按标签过滤并回滚 Degraded 应用
python -m argocd_insight batch rollback --label env=production

# 按状态过滤并刷新
python -m argocd_insight batch refresh --status Degraded

# 操作所有应用（dry-run 预览）
python -m argocd_insight batch sync --all --dry-run

# 指定应用列表
python -m argocd_insight batch sync --apps app1 app2 app3

# 控制并发度
python -m argocd_insight batch rollback --status Degraded --concurrency 10

# JSON 输出
python -m argocd_insight batch sync --project prod --output json
```

### 支持的操作

`sync` / `rollback` / `refresh`

### 筛选条件

`--project` / `--label` / `--status` / `--apps` / `--all`（至少指定一个）

### 可选参数

- `--dry-run` — 预览操作，不实际执行
- `--concurrency N` — 并发数（默认 5）
- `--timeout N` — 单个操作超时秒数（默认 120）
- `--output markdown|json` — 输出格式

### 输出示例

```
# Batch Operation Summary

**Operation:** sync
**Total:** 15
**Succeeded:** 14
**Failed:** 1

## ✅ Succeeded
- app-1 (2.3s): sync succeeded
- app-2 (1.8s): sync succeeded

## ❌ Failed
- app-3: sync failed: timeout
```

### 触发短语

- "批量同步所有 OutOfSync 的 App"
- "把所有 Degraded 的应用回滚到上一版本"
- "刷新 production 项目下所有 App"
- "把 label 为 env=production 的 App 全部同步"
- "批量操作，先 dry-run 预览一下"
- "并发执行 sync，控制并发数为 10"
- "给我一份批量操作报告（JSON 格式）"
- "按项目过滤，批量回滚"
- "把状态为 Missing 的应用全部刷新"
- "给指定列表的 App 批量执行 sync"

**工具位置：** `scripts/argocd_insight/batch.py`

---

## 能力六：版本漂移检测 (Drift)

比对两个 ArgoCD 集群（或同一集群两个环境）同名 App 的 revision 差异，识别版本漂移、仅源端/目标端独有的 App。

### 调用方式

```
python -m argocd_insight drift
python -m argocd_insight drift --from prod --to staging
python -m argocd_insight drift --project default --output json
```

### 参数

- `--from`/`--to` — 源端/目标端标签（报告显示用）
- `--from-server`/`--to-server` — 指定 ArgoCD server URL（留空用当前 context）
- `--project` — 按项目过滤
- `--output markdown|json`

### 输出维度

- `matched`：两端都存在的 App，按 revision 一致/漂移分组
- `sourceOnly`：仅源端有的 App
- `targetOnly`：仅目标端有的 App
- `summary`：漂移统计（总数/一致/漂移/漂移率）

### 示例输出

```
## 漂移检测报告：源端(prod) vs 目标端(staging)

| 匹配状态 | 数量 |
|---------|------|
| revision 一致 | 42 |
| 漂移 | 8 |
| 仅源端 | 3 |
| 仅目标端 | 2 |
| 漂移率 | 16.0% |

### 漂移 App 列表
- order-service (prod: v1.2 → staging: v1.1)
- payment-gateway (prod: v2.0 → staging: v1.9)
```

### 触发短语

- "比对一下 prod 和 staging 集群的版本漂移"
- "看看哪些 App 在不同环境 revision 不一致"
- "版本漂移检测，对比源端和目标端"
- "哪些 App 漂移了？漂移率多少？"
- "检查两个 ArgoCD 集群的版本一致性"
- "多集群灾备检查：revision 对比"
- "drift 检测：看下 staging 跟 prod 的差异"
- "帮我做版本漂移对比，输出 JSON"
- "只有源端集群有的 App 有哪些？"

**工具位置：** `scripts/argocd_insight/drift.py`

---

## 能力七：运行稳定性评估 (Health)

从 8 个维度对 ArgoCD 集群做全维度健康评估，输出总分、薄弱项和改进建议。

### 评分矩阵

| 维度 | 权重 | 数据来源 |
|------|------|---------|
| D1 App 健康率 | 20% | `argocd app list` 各 App health.status |
| D2 同步率 | 20% | `argocd app list` sync.status |
| D3 错误率 | 15% | `argocd app get` 最近事件 |
| D4 部署频率 | 10% | 最近 N 天 sync 操作计数 |
| D5 自动化覆盖 | 10% | `argocd app get` syncPolicy.automated |
| D6 聚合入口完整性 | 10% | 检查 Root App 的 automated 配置 |
| D7 多源冗余度 | 5% | spec.sources 数量分布 |
| D8 漂移复发率 | 10% | 连续同步后漂移复发的 App 比例 |

### 调用方式

```
python -m argocd_insight health
python -m argocd_insight health --project default
python -m argocd_insight health --output json
python -m argocd_insight health --detail
```

### 示例输出

```
## ArgoCD 稳定性评估报告

**总分：72/100 — Warning**

| 维度 | 得分 | 状态 |
|------|------|------|
| D1 App 健康率 | 85 | ✅ Good |
| D2 同步率 | 90 | ✅ Good |
| D3 错误率 | 60 | ⚠️ Warning |
| D4 部署频率 | 45 | ❌ Critical |
| D5 自动化覆盖 | 70 | ⚠️ Warning |
| D6 聚合入口完整性 | 80 | ✅ Good |
| D7 多源冗余度 | 90 | ✅ Good |
| D8 漂移复发率 | 65 | ⚠️ Warning |

### 薄弱项详细分析
...
```

### 触发短语

- "帮我看看 ArgoCD 集群整体健康度"
- "运行稳定性评估，8 维度打分"
- "ArgoCD 健康检查，哪些维度有问题？"
- "评估一下生产环境的 ArgoCD 稳定性"
- "看看自动化覆盖率和聚合入口完整性"
- "稳定性评估，输出薄弱项和改进建议"
- "ArgoCD 健康度打分，总分多少？"
- "部署频率统计，哪些 App 长期不部署？"
- "health 检查，给个总分和具体建议"

**工具位置：** `scripts/argocd_insight/health.py`

---

## 能力八：Git 源健康检查 (Repo Health)

检查 ArgoCD 所有注册仓库的连接状态（ArgoCD server 侧连接 + Agent 侧 git ls-remote 可达性），统计分支使用情况，输出健康报告。

### 检查维度

- ArgoCD server 侧连接状态（`connectionState`）
- Agent 侧 git ls-remote 可达性（区分凭证不可达与真正不可达）
- 仓库按 App 使用统计（关联 App 数、使用中的 revision 列表）

### 调用方式

```
python -m argocd_insight.repo_health
python -m argocd_insight.repo_health --output json
python -m argocd_insight.repo_health --project default
```

### 示例输出

```
## Repo 健康检查报告

| 仓库 | App 数 | Server 连接 | Agent 可达性 | 备注 |
|------|--------|-------------|-------------|------|
| github.com/team/apps.git | 23 | ✅ Connected | ✅ Reachable | |
| gitlab.internal/platform.git | 5 | ✅ Connected | ❌ Unreachable | 凭证可能过期 |
| bitbucket.org/legacy.git | 2 | ❌ Disconnected | ❌ Unreachable | 仓库已归档 |
| gitea.dev/tools.git | 8 | ✅ Connected | ⚠️ Partial | 部分分支不存在 |
```

### 触发短语

- "检查一下 Git 仓库连接状态"
- "Git 源健康检查，哪些仓库有问题？"
- "repo 健康检查：连接状态和分支可达性"
- "看看 ArgoCD 注册的仓库都健康吗"
- "仓库健康报告，哪些仓库不可达？"
- "repo-health 检查，输出 JSON"
- "检查所有 repo 的连通性"
- "Git 仓库认证是否正常？"

**工具位置：** `scripts/argocd_insight/repo_health.py`

---

## 能力九：配置合规检查 (Compliance)

检查 ArgoCD App 的配置风险点，输出风险数 + 严重级别 + 具体修复命令。

### 检查规则

| 规则 | 严重级别 | 说明 | 修复命令 |
|------|---------|------|---------|
| automated-no-retry | medium | 开了 automated 但没有 retry | `argocd app set <app> --sync-policy automated --sync-option Retry` |
| automated-no-selfheal | high | 开了 automated 但没有 self-heal | `argocd app set <app> --auto-prune --self-heal` |
| automated-no-prune | low | 开了 automated 但没有 auto-prune | `argocd app set <app> --auto-prune` |
| prune-last-not-automated | low | PruneLast=true 但非 automated | 配置矛盾，建议对齐 |
| system-namespace | high | 部署到系统 namespace | `argocd app set <app> --dest-namespace <business-ns>` |

### 调用方式

```
python -m argocd_insight.compliance
python -m argocd_insight.compliance --severity high
python -m argocd_insight.compliance --output json
```

### 参数

`--severity` — 最低严重级别（默认 low），`--output markdown|json`

### 示例输出

```
## Config Compliance Report

| 严重级别 | 违规数 | App 列表 |
|---------|--------|---------|
| 🔴 High | 4 | payment-gateway, order-svc, auth-svc, notification-svc |
| 🟡 Medium | 7 | user-svc, inventory-svc, ... |
| 🟢 Low | 12 | ... |

### 🔴 High: automated-no-selfheal (4 apps)
- payment-gateway → `argocd app set payment-gateway --auto-prune --self-heal`
- order-svc → `argocd app set order-svc --auto-prune --self-heal`
```

### 触发短语

- "检查 ArgoCD App 配置合规性"
- "合规检查：哪些 App 开了 automated 但没有 retry？"
- "看看哪些 App 没有配 self-heal"
- "配置风险检查，只看高风险项"
- "syncPolicy 风险分析"
- "哪些 App 部署到了系统 namespace？"
- "compliance 检查，输出 JSON"
- "帮我检查一下配置有没有风险"

**工具位置：** `scripts/argocd_insight/compliance.py`

---

## 能力十：批量自动修复 (Autofix)

基于诊断分析结果自动执行 sync/rollback 修复可修复的问题 App，支持 dry-run 预览和严重级别过滤。

### 自动修复逻辑

- OutOfSync → `argocd app sync --prune`
- Degraded → `argocd app rollback`（回滚到上版本）
- Missing → 跳过（需人工确认）
- Unknown → 跳过

### 调用方式

```
python -m argocd_insight autofix diagnosis.json
python -m argocd_insight autofix diagnosis.json --dry-run
python -m argocd_insight autofix diagnosis.json --severity high
```

### 参数

- `diagnosis` — 诊断结果 JSON 文件路径
- `--dry-run` — 预览修复，不实际执行
- `--severity` — 最低修复级别（critical/high/medium/low）

### 示例输出

```
## Autofix 结果汇总

| 状态 | 数量 |
|------|------|
| ✅ 修复成功 | 5 |
| ⏭️ 跳过 | 3 |
| ❌ 修复失败 | 1 |

### ✅ 修复成功
- payment-gateway: sync succeeded (2.3s)
- order-svc: sync succeeded (1.8s)
- auth-svc: rollback to v3 succeeded (2.1s)

### ❌ 修复失败
- notification-svc: sync failed — timeout
  建议手动检查：`argocd app get notification-svc`
```

### 触发短语

- "帮我自动修复诊断出来的问题 App"
- "基于诊断结果自动修复 OutOfSync 的 App"
- "自动修复：先 dry-run 看看会动哪些"
- "autofix：修复 low/medium 风险的问题"
- "批量修复诊断结果，只看 high 以上的"
- "诊断完以后自动修复一下"
- "自动修复 diagnosis.json，干跑预览"
- "修复所有 OutOfSync 和 Degraded 的 App"

**工具位置：** `scripts/argocd_insight/autofix.py`

---

## 能力十一：变更影响分析 (Impact)

执行 sync/rollback 前预览操作影响范围：资源列表、依赖关系、风险评估、预计耗时。属于只读操作，不修改任何状态。

### 调用方式

```
python -m argocd_insight impact my-app sync
python -m argocd_insight impact my-app rollback 3
python -m argocd_insight impact my-app sync --output json
```

### 参数

- `app` — 应用名称（位置参数）
- `operation` — 操作类型（sync/rollback，位置参数）
- `history_id` — 回滚历史 ID（rollback 操作可指定，位置参数）
- `--output markdown|json`

### 输出维度

- 当前应用状态（health/sync/revision）
- 受影响资源列表（kind/name/namespace/risk）
- 依赖关系（parent/child App，含跨 namespace 依赖）
- 风险评估（高风险项警告）
- 操作建议 + 预计耗时

### 示例输出

```
## 变更影响分析：payment-gateway — sync

### 当前状态
- Health: Healthy
- Sync: OutOfSync
- Revision: v2.0

### 受影响资源（共 12 个）
| Kind | Name | Namespace | Risk |
|------|------|-----------|------|
| Deployment | payment-gateway | production | low |
| Service | payment-gateway-svc | production | low |
| ConfigMap | payment-gateway-config | production | medium |
| Secret | db-credentials | production | high |

### 依赖关系
- ⬆ parent: infra-root → ecommerce-production-root
- ⬇ child apps: order-svc (depends on payment-gateway:ready)

### 风险评估
- 🔴 Secret `db-credentials` 即将更新 — 确认不含破坏性变更
- ⚠️ order-svc 有部署依赖 — sync 完成后再触发 order-svc sync

### 建议
预计耗时：30-60s。建议先 sync 后观察 2 分钟再操作 order-svc。
```

### 触发短语

- "先看看 sync my-app 会影响哪些资源"
- "操作前预览：rollback my-app 的风险"
- "变更影响分析，做之前先评估"
- "impact 分析：sync 这个 App 会动到什么？"
- "执行前检查：哪些依赖会被影响？"
- "预览一下 sync 操作的影响范围"
- "rollback 到版本 3 的影响分析"
- "风险评估：当前操作有什么风险？"
- "这个操作预计需要多久？"

**工具位置：** `scripts/argocd_insight/impact.py`

---

## 能力十二：资源成本估算 (Cost)

查询 ArgoCD App 的部署资源（CPU/Memory requests），估算运行成本。

### 调用方式

```bash
# 全量估算
python -m argocd_insight cost

# 按项目过滤
python -m argocd_insight cost --project prod

# JSON 输出
python -m argocd_insight cost --output json
```

### 示例输出

```
# ArgoCD 资源成本估算报告

生成时间：2026-07-01T12:00:00+00:00
成本模型：CPU $0.042/vCPU-hr，Memory $0.0047/GiB-hr

## 总览

| 指标 | 值 |
|------|-----|
| App 总数 | 50 |
| CPU 总量 | 32.5 cores |
| Memory 总量 | 64.2 GiB |
| 副本总数 | 128 |
| **每小时成本** | **$48.72** |
| **预估月成本** | **$35,118.24** |

## Top 10 高成本 App

| 排名 | App | Project | CPU (cores) | Memory (GiB) | 副本 | 月成本 |
|------|-----|---------|-------------|--------------|------|--------|
| 1 | payment-service | prod | 8.0 | 16.0 | 12 | $2,880.00 |
| 2 | order-service | prod | 4.0 | 8.0 | 8 | $1,440.00 |
```

### 触发短语

- "帮我看看 ArgoCD 里部署的资源成本"
- "估算一下 production 环境的运行成本"
- "哪些 App 消耗资源最多？"
- "给我一份资源成本报告"
- "CPU 和 Memory 用了多少？"
- "成本估算，按项目分组"
- "哪个服务最烧钱？"

**工具位置：** `scripts/argocd_insight/cost.py`

---

## 能力十三：多集群对比报告 (Multi-cluster)

比对两个 ArgoCD 集群的 App 配置、资源、健康状态差异。

### 调用方式

```bash
# 全量对比
python -m argocd_insight multi-cluster --from-server <server-a> --to-server <server-b>

# 按项目过滤
python -m argocd_insight multi-cluster --from-server <a> --to-server <b> --project prod

# JSON 输出
python -m argocd_insight multi-cluster --from-server <a> --to-server <b> --output json
```

### 对比维度

- App 存在性：只在 A / 只在 B / 两边都有
- 版本漂移：revision 是否一致
- 健康状态：Healthy / Degraded / Missing
- 同步状态：Synced / OutOfSync
- 资源配置：CPU/Memory requests 差异

### 触发短语

- "对比一下 prod 和 staging 两个集群的 App"
- "多集群对比，看看哪些 App 不一致"
- "检查两个环境的配置差异"
- "prod 和 staging 的资源差异"
- "哪些 App 只在一个集群有？"

**工具位置：** `scripts/argocd_insight/multi_cluster.py`

---

## 能力十四：报告推送（飞书 / 钉钉 / Slack）

将诊断、成本、对比等报告推送到即时通讯渠道。

### 调用方式

```bash
# 管道输入（推荐）：将其他命令的输出直接推送
python -m argocd_insight cost --output json | python -m argocd_insight report-push --webhook <url>

# 文件输入
python -m argocd_insight report-push --file report.md --webhook <url>

# 指定渠道（自动检测）
python -m argocd_insight report-push --file report.md --channel feishu --webhook <url>

# 自定义标题
python -m argocd_insight cost --output json | python -m argocd_insight report-push --webhook <url> --title "生产环境成本报告"
```

### 注意事项

- 不指定 `--channel` 时自动从 Webhook URL 检测渠道（feishu/dingtalk/slack）
- 不指定 `--file` 时从 stdin 读入
- 支持 Markdown / JSON 两种消息样式

### 触发短语

- "把这个报告推送到飞书"
- "把成本报告发到钉钉"
- "推送诊断报告到 Slack"
- "把对比报告结果通知给我"
- "把报告通过管道发给 Webhook"
- "推送报告，自动检测渠道"
- "报告发到群机器人"
- "帮我定时把成本报告推送到飞书"

**工具位置：** `scripts/argocd_insight/report_push.py`

---

## 能力十五：Application 配置模板生成 (Scaffold)

> **注意：** 本能力是**从零生成** YAML+CLI（正向），区别于子能力 3.1 的**从已有 YAML 反向生成** CLI。

从零快速生成 ArgoCD Application YAML 和等价 CLI 命令，基于 4-tier 模型自动填充最佳实践默认值。

### 调用方式

```bash
# 业务应用（手动 sync，自动 CreateNamespace=true）
python -m argocd_insight scaffold my-app \
  --tier business --namespace production --project default \
  --repo https://github.com/org/repo.git --path apps/my-app

# Root 聚合入口（auto sync + auto-prune + self-heal）
python -m argocd_insight scaffold my-root \
  --tier root --namespace argo-root \
  --repo https://github.com/org/repo.git --path apps/root

# 运维组件（CreateNamespace=false）
python -m argocd_insight scaffold prometheus \
  --tier ops --namespace ops \
  --repo https://github.com/org/repo.git --path monitoring/prometheus

# Helm 源（--source-type helm + --helm-chart + --helm-values）
python -m argocd_insight scaffold nginx \
  --tier business --namespace web --repo https://charts.nginx.org \
  --source-type helm --helm-chart nginx-ingress \
  --helm-values values/prod.yaml

# 列出可用层级
python -m argocd_insight scaffold --list-tiers

# JSON 输出
python -m argocd_insight scaffold my-app --tier business \
  --repo https://github.com/org/repo.git --path apps/my-app \
  --output json
```

### 4-tier 模型

| Tier | 说明 | 默认 Namespace | Sync Policy | CreateNamespace | Labels |
|------|------|---------------|-------------|-----------------|--------|
| root | 聚合入口 Root | argo-root | automated | true | - |
| business | 业务应用 | 需指定 | manual | true | project, profile, stack, app |
| ops | 运维组件 | ops | manual | false | - |
| infra_root | 基础设施 Root | argo-root | manual | false | - |

### 触发短语

- "帮我生成一个业务 ArgoCD 应用模板，名字叫 my-app"
- "用 scaffold 创建一个 ArgoCD 应用，从 main 到 prod"
- "创建一个 Root 聚合入口的 Application YAML"
- "生成一个运维组件模板，比如 Prometheus"
- "scaffold 一个 Helm 源的应用"
- "看下 4-tier 模型有哪些层级"
- "scaffold 一个 my-app，输出 JSON"
- "帮我生成个 ArgoCD 应用，用 scaffold --tier business"
- "我要快速创建个新 App，走 scaffold"
- "scaffold 支持哪些层级？--list-tiers 看看"
- "生成一个带 labels 业务应用模板"
- "创建一个 infra_root 基础设施模板，namespace 设 argo-root"

**工具位置：** `scripts/argocd_insight/scaffold.py`
