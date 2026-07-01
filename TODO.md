# TODO — argocd-skill 行动项跟进

> 每次对话产生的任务在此登记，完成后划掉 + 更新 EVOLUTION.md
> 本文件不追求一次清空，追求每次有进度、每个任务有人跟进

---

## ✅ 执行层（v0.2.0 — v0.2.2）

> 目标：覆盖 ArgoCD UI 所有常用操作，不需用户登录界面

| 能力 | CLI 命令 | 状态 |
|------|---------|------|
| CLI 安装/升级 | `argocd install` | ✅ |
| 命令生成 | `argocd app create/sync/rollback/...` | ✅ |
| YAML→CLI 转换 | mapper.py + kustomize-mapping.md | ✅ |
| 批量脚本生成 | `python -m argocd_cli_gen` | ✅ |
| delete resource | `argocd app delete-resource` | ✅ 实测通过 |
| Pod/Container 日志 | `argocd app logs` | ✅ 实测通过 |
| 应用事件 | `argocd app events` | ✅ |
| App diff（干跑）| `argocd app diff` | ✅ exit code 语义验证 |
| 修改 App 参数 | `argocd app set` | ✅ |
| patch 资源 | `argocd app patch-resource` | ✅ |
| 强制刷新 | `argocd app refresh` | ✅ |
| 取消参数 | `argocd app unset` | ✅ |
| 交互式编辑 | `argocd app edit` | ✅ |
| 终止运行中操作 | `argocd app terminate-op` | ✅ |
| 多源增/删源 | `argocd app add-source/remove-source` | ✅ |
| 全量健康报告 | `argocd app list --json + python` | ✅ 566 App 实测 |
| Project CRUD + 源/目标管理 | `argocd proj ...` | ✅ |
| ApplicationSet 管理 | `argocd appset ...` | ✅ |
| Account / Token 管理 | `argocd account ...` | ✅ |
| Repo / Cluster 管理 | `argocd repo/cluster ...` | ✅ |

---

## 🟡 P1 — 智能诊断（规划中）

### P1-1 OutOfSync 根因归因
- **需求**：批量找出 OutOfSync 的 App，并按原因分类（Git 改了 / 手动漂移 / Repo 不可达）
- **方案**：`argocd app diff` + `argocd app resources --orphaned` + `argocd app history`
- **状态**：✅ **v0.3.0 已交付**，见 `scripts/argocd_deploy_stats/oos_analyzer.py`
- **工具**：`python -m argocd_deploy_stats.oos_analyzer`
- **测试**：16 个单元测试覆盖（sync/新增/漂移/不一致/孤儿/超时/聚合/输出格式）

### P1-2 Sync 历史 + 部署频率统计
- **需求**：按项目/时间统计 sync 次数，估算 MTTR / 部署频率
- **方案**：`argocd app get --output json` 并发拉 history，并发聚合
- **工具**：`scripts/argocd_deploy_stats/stats.py`
- **状态**：🟡 原型完成，待全量压测（566 App）

### P1-3 漂移检测 + 告警建议
- **需求**：检测 `kubectl apply` 手动修改但 Git 未改的资源
- **方案**：对比 ArgoCD managed resources vs Git desired state
- **状态**：🟡 规划中

### P1-4 版本一致性检查
- **需求**：对比多环境（int/uat/prod）App 的 Git revision 是否分化
- **状态**：🟡 规划中

---

## 🟢 P2 — 运营优化（规划中）

### P2-1 配置合规检查
### P2-2 资源成本估算
### P2-3 多集群对比报告
### P2-4 Git 源健康检查
### P2-5 报告自动生成 + 推送

---

## 📋 迭代记录

| 日期 | 版本 | 变更 | 测试 |
|------|------|------|------|
| 2026-06-04 | v0.2.0 | 初始发布 | — |
| 2026-07-01 上午 | v0.2.1 | delete-resource / logs / events / diff / set+patch / 健康报告 | 67/67 ✅ |
| 2026-07-01 下午 | v0.2.2 | refresh / unset / edit / terminate-op / 多源 / proj全 / appset全 / account全 / repo+cluster全 | 67/67 ✅ |
| 2026-07-01 下午 | v0.2.3 | 准则五 Ponytail / EVOLUTION 质量门 / TODO 重建 | — |
| 2026-07-01 下午 | P1-2 | argocd_deploy_stats 原型，30 App 实测通过 | — |
| 2026-07-01 | v0.3.0 | **P1-1 OutOfSync 根因归因交付**：oos_analyzer.py 加固+16测试+SKILL.md 集成 | 16/16 ✅ |

---

## 跟进规则

1. **每次对话结束时**：检查 TODO，更新状态 + 新增本次产生的任务
2. **完成 P0 任务时**：同步更新 `EVOLUTION.md` 能力注册表
3. **版本 tag**：每完成一个小节，向本文件追加一条记录
4. **任务粒度**：一个任务 1-2 小时内可完成，超过则拆分
