# TODO — argocd-skill 行动项跟进

---

## ✅ 执行层（v0.2.0 — v0.2.3）

> 覆盖 ArgoCD UI 所有常用操作，不需用户登录界面

| 能力 | 命令/工具 | 状态 |
|------|---------|------|
| CLI 安装/升级 | `argocd install` | ✅ |
| App 全操作 | `app create/sync/rollback/set/delete-resource/refresh/unset/edit/terminate-op/logs/events/diff/history/wait` | ✅ |
| Project/ApplicationSet/Account/Repo/Cluster | `argocd proj/appset/account/repo/cluster ...` | ✅ |
| YAML→CLI + 批量脚本 | mapper.py + `argocd_cli_gen` | ✅ |

---

## ✅ P1 — 智能诊断（v0.3.0）

| 能力 | 命令/工具 | 状态 |
|------|---------|------|
| P1-1 OutOfSync 根因归因 | `python -m argocd_deploy_stats.oos_analyzer` | ✅ 73 App / 38s |
| P1-2 部署频率统计 | `python -m argocd_deploy_stats.stats` | ✅ 566 App / 150s |
| P1-3 版本漂移检测 | `python -m argocd_insight drift` | ✅ |
| P1-4 问题 App 诊断 | `python -m argocd_insight diagnose` | ✅ |
| P1-5 稳定性评估 | `python -m argocd_insight health` | ✅ |

---

## ✅ P2 — 运营优化

| 能力 | 命令/工具 | 状态 |
|------|---------|------|
| P2-4 Git 源健康检查 | `python -m argocd_insight repo-health` | ✅ 14 repos / 5s 实测 |
| P2-1 配置合规检查 | `python -m argocd_insight compliance` | ✅ 566 App 实测（547 风险 / 611 项）/ 1s |
| P2-2 资源成本估算 | `python -m argocd_insight cost` | ✅ 159/159 测试通过 |
| P2-3 多集群对比报告 | `python -m argocd_insight multi-cluster` | ✅ 172/172 测试通过 |
| P2-5 报告推送 | `python -m argocd_insight report-push` | ✅ 23/23 测试通过 |

---

## ✅ P3-优化层 P0（v0.4.0）

> 从"诊断"到"修复"的闭环，让 Skill 不仅能发现问题，还能自动/半自动解决问题

| 能力 | 命令/工具 | 状态 |
|------|---------|------|
| P3-1 批量修复 | `python -m argocd_insight autofix` | ✅ 11/11 测试通过 |
| P3-2 变更影响分析 | `python -m argocd_insight impact` | ✅ 5/5 测试通过 |

---

## 📋 迭代记录

| 日期 | 版本 | 变更 | 测试 |
|------|------|------|------|
| 2026-06-04 | v0.2.0 | 初始发布 | — |
| 2026-07-01 | v0.2.1 | delete-resource / logs / events / diff / set+patch | 67/67 ✅ |
| 2026-07-01 | v0.2.2 | refresh/unset/edit/terminate-op / proj全 / appset全 / account全 | 67/67 ✅ |
| 2026-07-01 | v0.2.3 | 准则五 Ponytail | — |
| 2026-07-01 | v0.3.0 | P1 诊断层：diagnose/drift/health/oos_analyzer/stats | 143/143 ✅ |
| 2026-07-01 | P2-4 | Git 源健康检查：repo-health，14 repos 实测 | 143/143 ✅ |
| 2026-07-01 | P2-1 | 配置合规检查：compliance，566 App / 1s | 143/143 ✅ |
| 2026-07-02 | v0.4.0 | P3-优化层 P0：autofix（批量修复）+ impact（变更影响分析） | 16/16 ✅ |

---

## 跟进规则

1. **每次对话结束时**：检查 TODO，更新状态 + 新增本次产生的任务
2. **完成 P0/P1/P2 任务时**：同步更新 `EVOLUTION.md`
3. **测试无回归**：`pytest scripts/tests/` 仍 100% 通过
4. **任务粒度**：1-2 小时内可完成，超过则拆分
