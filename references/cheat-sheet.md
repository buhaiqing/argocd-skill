# ArgoCD Skill Cheat Sheet

> 一页速查，高频操作命令行。可打印 A4 大小。

## 前置准备

```bash
# 安装 CLI（Linux）
curl -sSL -o /usr/local/bin/argocd \
  https://github.com/argoproj/argo-cd/releases/download/v3.4.2/argocd-linux-amd64
chmod +x /usr/local/bin/argocd

# 配置认证（二选一）
export ARGOCD_AUTH_TOKEN="***"                    # 推荐：自动化 / CI
export ARGOCD_SERVER="https://argocd.hd123.com"
# 或
export ARGOCD_USERNAME="user" ARGOCD_PASSWORD="pass"

# 安装 Python 工具（可选，pip install -e . 后可用 argocd-insight 等命令）
pip install -e .
```

---

## argocd CLI 原生命令

```bash
argocd app create <name> --repo <url> --path <path> --dest-server <server> --dest-namespace <ns>  # 创建应用
argocd app sync <name>                                 # 同步
argocd app rollback <name> --id <history-id>          # 回滚
argocd app delete <name>                              # 删除（危险，需二次确认）
argocd app list                                        # 列出所有
argocd app get <name>                                  # 详情
argocd app history <name>                              # 同步历史
argocd app diff <name>                                # 差异对比
argocd app actions list <name>                         # 资源操作列表
argocd login --server <server> --username <user>      # 登录
argocd proj create <name>                             # 创建项目
argocd repo add <repo> --type <type>                  # 添加仓库
argocd cluster add <server>                            # 添加集群
```

---

## Python 工具（`pip install -e .` 后直接调用）

| 工具 | 安装后命令 | 常用场景 |
|---|---|---|
| **argocd-cli-gen** | `argocd-cli-gen --input DIR --output ./out --upsert` | YAML 目录批量生成 `argocd app create` 脚本 |
| **argocd-api** | `argocd-api list / get / sync / delete ...` | HTTP API 等价 CLI（绕过 argocd CLI bug） |
| **argocd-insight** | `argocd-insight diagnose / drift / health ...` | 诊断分析 / 漂移检测 / 健康评估等 |
| **argocd-deploy-stats** | `argocd-deploy-stats --days 7 --output json` | 部署频率统计 + OOS 分析 |
| **ulw** | `ulw find-pod <pod> / ulw delete-pod <pod>` | 孤儿 Pod 排查与删除 |

---

## argocd-insight 子命令速查

```bash
# 诊断 & 检测
argocd-insight diagnose --project <proj>              # 问题 App 智能诊断
argocd-insight drift --project <proj>                # 版本漂移检测
argocd-insight health --days 30                      # 运行稳定性评估
argocd-insight repo-health                          # Git 源健康检查

# 合规 & 成本
argocd-insight compliance --severity high            # 配置合规检查
argocd-insight cost --project <proj>                # 资源成本估算

# 批量操作
argocd-insight batch sync --project <proj> --dry-run  # 预览批量同步
argocd-insight batch sync --project <proj> --all       # 正式执行批量同步
argocd-insight batch refresh --label env=prod          # 按标签批量刷新

# 修复 & 影响
argocd-insight autofix <diagnosis.json> --dry-run    # 预览自动修复
argocd-insight impact <app> sync                     # 变更影响分析

# 模板 & 报告
argocd-insight scaffold --tier business              # 生成业务应用模板
argocd-insight report-compose --include diagnose,compliance  # 合成综合报告
argocd-insight report-push --file report.md --webhook <url>  # 推送报告

# Rollouts 渐进式交付
argocd-insight rollouts diagnose <name> -n <ns>     # Rollout 状态诊断

# 轨迹 & 自进化
argocd-insight trace --extract-insights             # 提炼经验
argocd-insight trace --evolve --no-dry-run         # 执行自进化写回
```

---

## 批量转换工具（argocd-cli-gen）输出结构

```bash
argocd-cli-gen --input /path/to/argo-apps --output ./out --upsert

./out/
├── 00_preflight.sh           # 一次性 login
├── 05_infra_roots.sh        # 基础设施 Root
├── 10_app_roots.sh          # 聚合入口 Root
├── 20_workloads_ops.sh      # 运维组件
├── 30_workloads_business.sh # 业务应用
├── *.dry-run.sh             # 每个脚本的 dry-run 副本
├── run_all.sh               # 串联入口
├── report.json / report.md  # 转换报告
└── 99_multisource_fallback.yaml  # CLI 不支持的多源 YAML（kubectl apply 兜底）
```

---

## 常见错误速查

| 错误信息 | 原因 | 解决 |
|---|---|---|
| `Unauthenticated desc = no session information` | 未执行 `argocd login` | 先 `argocd login` 或配置 `ARGOCD_AUTH_TOKEN` |
| `contains invalid character '_'` | 应用名含下划线 | ArgoCD 不允许 `_`，CLI 会自动替换为 `-` |
| `unknown flag: --helm-set` | Kustomize 配置误用 Helm flag | Kustomize 用 `--kustomize-*`，Helm 用 `--helm-*` |
| `missing required flag: --sync-policy automated` | 用 `--auto-prune` 但未加 `automated` | 必须同时加 `--sync-policy automated` |
| `spec.sources` length > 1 | 多源 App 无法用 CLI 表达 | 回退 `kubectl apply -f` |

---

## 4-Tier 层级速查

| 层级 | namespace | automated | CreateNamespace | 典型场景 |
|---|---|---|---|---|
| 基础设施 Root | `argo-root` | — | — | projects / repos |
| 聚合入口 Root | `argo-root` | **必选** | true | 聚合 App |
| 业务应用 | 业务 ns | **禁用** | true | 业务 Pod |
| 运维组件 | `ops`/`loki` 等 | 禁用 | **false** | prometheus / nginx |

---

来源：`references/cli-commands.md` · `references/kustomize-mapping.md` · `scripts/README.md`
