# ArgoCD 故障排查 Runbook

> 按**症状**分类的排查路径。Agent 收到「App 有问题 / 同步失败 / 登录不了」时，先定位症状再下命令。
>
> **关联文档：** [argocd-app-lifecycle.md](argocd-app-lifecycle.md) · [agent-protocols.md](agent-protocols.md) · [cli-commands.md](cli-commands.md)

---

## 快速分流

```
用户报告问题
    │
    ├─ 无法连接 / login 失败 ──→ §1 认证与连通性
    ├─ App OutOfSync ──────────→ §2 同步与漂移
    ├─ App Degraded / Missing ─→ §3 健康与运行时
    ├─ sync 卡住 / 超时 ───────→ §4 Sync 操作异常
    ├─ 仓库 / Git 错误 ────────→ §5 源与仓库
    ├─ Permission denied ──────→ §6 RBAC 与 Project
    └─ 批量 / 多 App ──────────→ §7 批量诊断工具
```

---

## §1 认证与连通性

### 症状

- `rpc error: code = Unauthenticated`
- `argocd login` 失败（context path / insecure / grpc-web）
- `Failed to establish connection`

### 排查

```bash
echo "ARGOCD_SERVER=${ARGOCD_SERVER:+set}"   # 勿 echo token
command -v argocd && argocd version --client

# Token 登录
argocd login "$ARGOCD_SERVER" \
  --auth-token "$ARGOCD_AUTH_TOKEN" \
  --grpc-web --insecure   # 按环境调整

# 验证
argocd account get-user-info
```

### CLI 失败 → HTTP API 回退

```bash
python -m argocd_api get my-app
python -m argocd_api list-apps
```

详见 [agent-protocols.md](agent-protocols.md) 第 0.4 / 0.6 节。

---

## §2 同步与漂移（OutOfSync）

### 症状

- `sync.status: OutOfSync`
- 「Git 和集群不一致」

### 排查步骤

```bash
# 1. 看 diff
argocd app diff APPNAME

# 2. 看哪些资源 OutOfSync
argocd app get APPNAME -o json | jq '.status.resources[] | select(.status!="Synced")'

# 3. 孤儿资源
argocd app resources APPNAME

# 4. 批量根因归因
python -m argocd_deploy_stats.oos_analyzer --project default
python -m argocd_insight diagnose --output markdown
```

### 归因 → 动作

| 根因 | 动作 |
|------|------|
| Git 新增未部署 | `argocd app sync APP --prune` |
| 集群手动改动（漂移） | sync 回收 或 保留并加 ignoreDifferences |
| 内容不一致 | diff 定位字段 → 修 Git 或 sync |
| HPA 改 replicas | 加 ignoreDifferences |
| 多源 / patches | CLI 不支持 → `kubectl apply -f` |

### 修复

```bash
# 预览影响
python -m argocd_insight impact APPNAME sync

# 执行 sync
argocd app sync APPNAME --prune --sync-option PruneLast=true
argocd app wait APPNAME --health --timeout 300
```

---

## §3 健康与运行时（Degraded / Missing / Progressing）

### 症状

- `health.status: Degraded`
- Pod CrashLoopBackOff
- `Missing` 资源

### 排查

```bash
argocd app get APPNAME
argocd app resources APPNAME
argocd app logs APPNAME --tail 200
argocd app events APPNAME

# 深入 K8s
kubectl -n <ns> get pods -l app.kubernetes.io/instance=<app>
kubectl -n <ns> describe pod <pod>
kubectl -n <ns> get events --sort-by=.lastTimestamp
```

### 动作

| 情况 | 动作 |
|------|------|
| 新版本引入故障 | `argocd app history` → `rollback` |
| 配置错误 | 修 Git → sync |
| 依赖服务未就绪 | 检查上游 App / sync 顺序 |
| ImagePullBackOff | 检查镜像 tag / registry 凭证 |

```bash
python -m argocd_insight impact APPNAME rollback
argocd app rollback APPNAME
```

---

## §4 Sync 操作异常

### 症状

- sync 长时间 Running
- `operation phase: Running` 不结束
- 并发 sync 冲突

### 排查

```bash
argocd app get APPNAME -o json | jq '.status.operationState'
argocd app terminate-op APPNAME   # 危险 — 需用户确认
```

| 原因 | 处理 |
|------|------|
| 前一个 op 未结束 | `terminate-op` 后重试 sync |
| 资源 hook 卡住 | 查 PreSync/PostSync Job 日志 |
| 资源过大 timeout | 增大 `--timeout` 或 ApplyOutOfSyncOnly |
| server 限流 | 降低 batch concurrency / 加 sleep |

```bash
python -m argocd_insight batch sync --status OutOfSync --concurrency 2 --dry-run
```

---

## §5 源与仓库

### 症状

- `ComparisonError` / `Failed to load target state`
- `repository not accessible`
- `revision X not found`

### 排查

```bash
argocd repo list
argocd repo get https://github.com/org/repo.git
argocd app get APPNAME -o json | jq '.status.conditions'

python -m argocd_insight repo-health
```

| 原因 | 处理 |
|------|------|
| 凭证过期 | 更新 repo credential / ExternalSecret |
| 分支不存在 | 修正 `--revision` / targetRevision |
| 路径错误 | 修正 `--path` |
| 私有仓库未注册 | `argocd repo add` |

---

## §6 RBAC 与 AppProject

### 症状

- `permission denied`
- `repository not permitted`
- `destination is not permitted`

### 排查

```bash
argocd proj get PROJECT
argocd app get APPNAME -o json | jq '.spec.project, .spec.source, .spec.destination'
argocd account get-user-info
```

修复见 [argocd-appproject-guide.md](argocd-appproject-guide.md)：`proj add-source` / `proj add-destination`。

---

## §7 批量诊断工具

| 目标 | 命令 |
|------|------|
| 问题 App 全景 | `python -m argocd_insight diagnose` |
| OutOfSync 归因 | `python -m argocd_deploy_stats.oos_analyzer` |
| 稳定性评分 | `python -m argocd_insight health` |
| 配置风险 | `python -m argocd_insight compliance` |
| 多集群漂移 | `python -m argocd_insight drift` |
| 自动修复（需确认） | `diagnose --output json > d.json` → `autofix d.json --dry-run` |

**综合报告：**

```bash
python -m argocd_insight report-compose --include diagnose,compliance,health
```

---

## §8 常见错误码对照（SKILL.md 摘要）

| 错误 | 正确处理 |
|------|---------|
| 缺 `--dest-server` | 必填 `https://kubernetes.default.svc` 或实际集群 |
| Kustomize/Helm flag 混用 | `--kustomize-*` vs `--helm-*` 分开 |
| 多源强行转 CLI | `kubectl apply -f` |
| 应用名含 `_` | 改为 `-` |
| Root 漏 automated | 补 `--sync-policy automated --auto-prune --self-heal` |
| 业务 App 误开 automated | `app unset --sync-policy` |
| diff 超时 | `--concurrency 2` 或增大 timeout |

完整 11+ 行表见 SKILL.md「常见错误」。

---

## §9 Pod 级排查（ulw 工具）

当用户给 Pod 名而非 App 名：

```bash
python -m ulw find-pod my-pod-xxx
# 输出 APP_NAME / NAMESPACE / KIND

argocd app logs APP_NAME --kind Pod --name my-pod-xxx --namespace NS
```

删除 Pod（需交互确认 `yes`）：

```bash
python -m ulw delete-pod my-pod-xxx
```

---

## 升级排查（ArgoCD 版本变更后）

```bash
argocd version
kubectl -n argocd get deploy argocd-server -o jsonpath='{.spec.template.spec.containers[0].image}'

# Orphaned 列格式变化 → 改用 JSON
argocd app resources APPNAME --output json | jq '.[] | select(.orphaned==true)'
```

---

## 外部参考

- [FAQ](https://argo-cd.readthedocs.io/en/stable/faq/)
- [Diffing](https://argo-cd.readthedocs.io/en/stable/user-guide/diffing/)
- [Resource Hooks](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_hooks/)
