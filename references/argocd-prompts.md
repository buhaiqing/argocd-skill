# ArgoCD Skill 提示词示例

本文档是 `SKILL.md`「提示词示例」章节的完整内容，已从主文件迁移至此。

## 安装相关

- "帮我装一下 argocd CLI"
- "安装 ArgoCD 3.4.2 到这台机器上"
- "在 Docker 容器里安装最新版本的 argocd"
- "我要给 CI runner 装一个 argocd 客户端"
- "离线环境怎么装 argocd CLI"

## 命令生成相关（自然语言 → CLI）

- "帮我创建一个 ArgoCD 应用 my-app，从 main 分支部署到 prod 命名空间"
- "同步一下 my-app"
- "把 my-app 回滚到上一个版本"
- "看看 my-app 有没有同步"
- "给我写一个自动同步 ArgoCD 应用的脚本"
- "帮我查一下所有 ArgoCD 应用列表"
- "argocd login 怎么用 token 登录"
- "怎么删除一个 ArgoCD 应用还顺便清理资源"

## 运维 Runbooks（深度操作指南）

**生命周期：** 见 [references/argocd-app-lifecycle.md](references/argocd-app-lifecycle.md)
- "App 从创建到删除完整流程怎么走"
- "创建并同步一个 App 的标准步骤"
- "回滚并验证 health 的命令组合"

**AppProject：** 见 [references/argocd-appproject-guide.md](references/argocd-appproject-guide.md)
- "怎么新建一个 AppProject 并限制仓库和 namespace"
- "repository not permitted 怎么修"

**syncPolicy：** 见 [references/argocd-sync-policy-deep-dive.md](references/argocd-sync-policy-deep-dive.md)
- "Root 入口要不要开 automated 和 self-heal"
- "业务 App 的 syncPolicy 生产规范是什么"
- "PruneLast 和 auto-prune 有什么区别"

**ApplicationSet：** 见 [references/argocd-appset-guide.md](references/argocd-appset-guide.md)
- "用 ApplicationSet 批量生成多环境 App"
- "appset generate 预览会创建哪些 Application"

**故障排查：** 见 [references/argocd-troubleshooting.md](references/argocd-troubleshooting.md)
- "App OutOfSync 怎么排查"
- "argocd login 失败怎么办"
- "sync 一直卡住怎么终止"

## 子能力 3.1：单 YAML 内联转换（粘贴 1 个 YAML）

**A. 通用触发短语**
- "把这个 ArgoCD YAML 转成 CLI 命令"
- "这段 ArgoCD manifest 怎么用命令行重建？"
- "我有个 Application 资源描述，给我等价的 argocd CLI"
- "粘贴的这段 YAML 转 CLI"
- "argocd app create 怎么写？我贴 YAML 给你"
- "把下面这个 Application 资源对应的 argocd 命令打出来"
- "这个 YAML 怎么用命令行创建应用？"
- "看一下我这个 spec.source 翻译成 argocd 命令是什么样"

**B. 按层级特化**
- "这是个 root 入口 / 聚合应用 YAML，转一下 CLI" → 必含 `--sync-policy automated --auto-prune --self-heal`
- "App-of-Apps 入口 Application 怎么转命令"
- "把这个 `projects.yaml` / `repos.yaml` 转 CLI"（基础设施 Root，namespace=`argo-root`）
- "业务应用 YAML 转命令，我贴给你"（必含 labels 四件套，无 automated）
- "k8s_ops 下面的 prometheus.yaml / loki.yaml 怎么转 CLI"（运维组件，多含 `CreateNamespace=false`）

**C. 按 kustomize 特性**
- "这个 YAML 的 `kustomize.images` 怎么映射到 CLI flag"
- "kustomize.commonLabels / nameSuffix / replicas 怎么转命令"
- "kustomize.patches / components 字段 CLI 支持吗？怎么转？" → **回退到 `kubectl apply -f`**

**D. 多源边界**
- "这个 loki / tempo / grafana YAML 怎么转 CLI"（`spec.sources` 多源）
- "这个应用是多源 Helm + `$values` 模式，CLI 写不出来怎么办" → **回退方案 + 解释原因**
- "我这个 Application 里有 `spec.sources`，argocd CLI 怎么写？"

## 子能力 3.2：目录批量转换（整目录 / 多文件 → shell 脚本）

**A. 直接给目录**
- "把 `argo-apps/dly/production` 整个目录的 manifest 转成 CLI 脚本"
- "我给你一个 ArgoCD app 目录，反向生成 shell 脚本"
- "把这个 git 仓库子目录的 ArgoCD YAML 全部生成 argocd app create 命令"
- "我有一堆 ArgoCD Application YAML，能批量转吗？"
- "我有 30+ 个 Application YAML，逐个写太累，能批量？"
- "整目录反向生成 argocd app create 脚本"
- "把 `/path/to/argoapp/` 下面所有 manifest 跑一遍生成命令"

**B. 场景化触发（迁移 / 灾备 / 备份）**
- "集群迁移：把现存所有 ArgoCD 应用 manifest 转成命令脚本"
- "灾备重建 ArgoCD 应用：从 YAML 目录生成命令"
- "新集群初始化：跑一遍历史所有 Application 创建命令"
- "ArgoCD 配置脚本化 / 导出 shell"
- "把 GitOps 仓库的 Application 反向生成 CLI 脚本"
- "运维交接：把 ArgoCD 应用配置 dump 成可执行命令"
- "把 prd / staging / 多套环境的 Application 一键生成创建脚本"

**C. 期望明确产物**
- "我想要 `run_all.sh` 串联入口 + 每个层级一个脚本"
- "生成脚本要带 dry-run 副本，能灰度跑一遍再上"
- "顺便给我一份转换报告 / report.md"

**任一上述触发 → Agent 应直接调用：**
```bash
python -m argocd_cli_gen --input <dir> --output ./out --upsert --emit-dry-run
```
然后向用户展示 `report.md` 摘要、回退条目数，以及 `run_all.sh` 的使用方法。

## 能力四：诊断分析（OutOfSync 根因归因）

**触发短语：**
- "哪些 App 是 OutOfSync 的？什么原因？"
- "帮我批量分析 OutOfSync 根因"
- "看看有没有漂移的 App"
- "OutOfSync 归因，按原因分类"
- "有没有手动漂移的 App 和孤儿资源？"
- "哪些 App Git 有但集群没有？"
- "分析一下 production 项目的 OOS 情况"
- "给我一份 OutOfSync 诊断报告（JSON 格式）"
- "批量查所有 OutOfSync 的 App 是什么原因导致的"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_deploy_stats.oos_analyzer [--project <name>] [--days N] [--output json]
```
然后向用户展示归因汇总表 + 每种原因的 App 列表。

## 能力五：资源成本估算

**触发短语：**
- "帮我看看 ArgoCD 里部署的资源成本"
- "估算一下 production 环境的运行成本"
- "哪些 App 消耗资源最多？"
- "给我一份资源成本报告"
- "CPU 和 Memory 用了多少？"
- "成本估算，按项目分组"
- "哪个服务最烧钱？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight cost [--project <name>] [--output json]
```
然后向用户展示成本概览 + Top 10 高成本 App 列表。

## 能力六：多集群对比报告

**触发短语：**
- "对比一下 prod 和 staging 两个集群的 App"
- "多集群对比，看看哪些 App 不一致"
- "检查两个环境的配置差异"
- "prod 和 staging 的资源差异"
- "哪些 App 只在一个集群有？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight multi-cluster --from-server <a> --to-server <b> [--project <name>] [--output json]
```
然后向用户展示对比概览 + 漂移/差异详情。

## 能力七：报告推送（飞书 / 钉钉 / Slack）

**触发短语：**
- "把这个报告推送到飞书"
- "把成本报告发到钉钉"
- "推送诊断报告到 Slack"
- "把对比报告结果通知给我"
- "把报告通过管道发给 Webhook"
- "推送报告，自动检测渠道"
- "报告发到群机器人"
- "帮我定时把成本报告推送到飞书"

**任一触发 → Agent 应直接执行（推荐管道模式）：**
```bash
python -m argocd_insight cost --output json | python -m argocd_insight report-push --webhook <url>
```
或使用文件输入：
```bash
python -m argocd_insight report-push --file report.md --webhook <url>
```

## 能力八：批量操作（Batch Operations）

**触发短语：**
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

**任一触发 → Agent 应直接调用：**
```bash
# 常用变体
python -m argocd_insight batch sync --status OutOfSync
python -m argocd_insight batch rollback --status Degraded
python -m argocd_insight batch refresh --all --dry-run
python -m argocd_insight batch sync --project prod --concurrency 10 --output json
```
然后向用户展示批量操作汇总结果（成功数 / 失败数 / 详情列表）。

## 能力九：Application 配置模板生成（Scaffold）

**触发短语：**
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

**任一触发 → Agent 应直接调用：**
```bash
# 确定 tier + 必填参数后调用
python -m argocd_insight scaffold <name> --tier <tier> --repo <url> [--path <path>] [--output json]
```
然后向用户展示生成的 YAML + CLI 命令。如果有警告（tier 参数不匹配等），一并提示。

## 能力十：版本漂移检测 (Drift)

**触发短语：**
- "比对一下 prod 和 staging 集群的版本漂移"
- "看看哪些 App 在不同环境 revision 不一致"
- "版本漂移检测，对比源端和目标端"
- "哪些 App 漂移了？漂移率多少？"
- "检查两个 ArgoCD 集群的版本一致性"
- "多集群灾备检查：revision 对比"
- "drift 检测：看下 staging 跟 prod 的差异"
- "帮我做版本漂移对比，输出 JSON"
- "只有源端集群有的 App 有哪些？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight drift [--from <label>] [--to <label>] [--project <name>] [--output json]
```
然后向用户展示漂移统计概览（整体漂移率）+ 漂移 App 列表 + 仅源端/目标端 App 列表。

## 能力十一：运行稳定性评估 (Health)

**触发短语：**
- "帮我看看 ArgoCD 集群整体健康度"
- "运行稳定性评估，8 维度打分"
- "ArgoCD 健康检查，哪些维度有问题？"
- "评估一下生产环境的 ArgoCD 稳定性"
- "看看自动化覆盖率和聚合入口完整性"
- "稳定性评估，输出薄弱项和改进建议"
- "ArgoCD 健康度打分，总分多少？"
- "部署频率统计，哪些 App 长期不部署？"
- "health 检查，给个总分和具体建议"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight health [--project <name>] [--output json]
```
然后向用户展示总分 + 各维度评分表 + 薄弱项详细分析 + 改进建议汇总。

## 能力十二：Git 源健康检查 (Repo Health)

**触发短语：**
- "检查一下 Git 仓库连接状态"
- "Git 源健康检查，哪些仓库有问题？"
- "repo 健康检查：连接状态和分支可达性"
- "看看 ArgoCD 注册的仓库都健康吗"
- "仓库健康报告，哪些仓库不可达？"
- "repo-health 检查，输出 JSON"
- "检查所有 repo 的连通性"
- "Git 仓库认证是否正常？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight.repo_health [--project <name>] [--output json]
```
然后向用户展示仓库健康总览表（仓库名、App 数、连接状态、Agent 可达性）。

## 能力十三：配置合规检查 (Compliance)

**触发短语：**
- "检查 ArgoCD App 配置合规性"
- "合规检查：哪些 App 开了 automated 但没有 retry？"
- "看看哪些 App 没有配 self-heal"
- "配置风险检查，只看高风险项"
- "syncPolicy 风险分析"
- "哪些 App 部署到了系统 namespace？"
- "compliance 检查，输出 JSON"
- "帮我检查一下配置有没有风险"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight.compliance [--severity high] [--output json]
```
然后向用户展示风险总览（按严重级别分组）+ 每类风险的 App 列表 + 具体修复命令。

## 能力十四：批量自动修复 (Autofix)

**触发短语：**
- "帮我自动修复诊断出来的问题 App"
- "基于诊断结果自动修复 OutOfSync 的 App"
- "自动修复：先 dry-run 看看会动哪些"
- "autofix：修复 low/medium 风险的问题"
- "批量修复诊断结果，只看 high 以上的"
- "诊断完以后自动修复一下"
- "自动修复 diagnosis.json，干跑预览"
- "修复所有 OutOfSync 和 Degraded 的 App"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight autofix <diagnosis.json> [--dry-run] [--severity high]
```
然后向用户展示修复汇总（成功数、跳过数、失败数）+ 每个 App 的修复详情。

## 能力十五：变更影响分析 (Impact)

**触发短语：**
- "先看看 sync my-app 会影响哪些资源"
- "操作前预览：rollback my-app 的风险"
- "变更影响分析，做之前先评估"
- "impact 分析：sync 这个 App 会动到什么？"
- "执行前检查：哪些依赖会被影响？"
- "预览一下 sync 操作的影响范围"
- "rollback 到版本 3 的影响分析"
- "风险评估：当前操作有什么风险？"
- "这个操作预计需要多久？"

**任一触发 → Agent 应直接调用：**
```bash
python -m argocd_insight impact <app> <sync|rollback> [history_id] [--output json]
```
然后向用户展示操作影响分析：当前状态 → 受影响资源 → 依赖关系 → 风险评估 → 操作建议。

## 可观测与自进化

**A. 轨迹记录（在线流程）**
> 用户操作时自动触发，无需显式提示词。装饰器 `@traced` 自动拦截所有 CLI/API 调用。

**B. 离线分析（手动触发）**
> 以下提示词触发离线流程，对历史轨迹进行分析/经验提炼/自进化。

**调用方式：**
```bash
# 分析指定会话
python -m argocd_insight trace --session <session_id>

# 分析最近 7 天所有会话
python -m argocd_insight trace --session <session_id> --extract-insights

# 分析 + 经验提炼 + 自进化写回（dry-run）
python -m argocd_insight trace --session <session_id> --extract-insights --evolve

# 实际执行写回（不加 --no-dry-run 时默认 dry-run）
python -m argocd_insight trace --session <session_id> --extract-insights --evolve --no-dry-run
```

**触发短语：**
- "分析一下这次会话的轨迹"
- "看看这次运行有什么性能瓶颈"
- "帮我看看执行效率怎么样"
- "输出轨迹报告，JSON 格式"
- "分析所有最近的会话轨迹"
- "跑一下离线分析流程"

**C. 经验提炼**
- "提炼这次会话的经验"
- "从轨迹里总结一些规律"
- "哪些参数设置有问题？"
- "这次诊断的参数有没有优化空间？"
- "帮我看看并发度设置合不合理"
- "生成经验报告"

**D. 自进化写回**
- "把分析结果写回 SKILL.md"
- "经验沉淀，更新一下参数建议"
- "把这次学到的东西记下来"
- "自进化，把新发现写回配置"
- "置信度够的话自动更新 tool 参数"
- "这次分析要写入文档吗？"

**E. SkillOpt 参数推荐**
- "SkillOpt 推荐一下这次用什么参数"
- "基于历史轨迹，suggest 一个并发数"
- "帮我推断最优的 timeout 设置"
- "这次诊断用什么参数组合最好？"

**任一触发 → Agent 应直接调用：**
```bash
# 基本分析
python -m argocd_insight trace --session <session_id>

# 分析 + 提炼经验（离线流程）
python -m argocd_insight trace --session <session_id> --extract-insights

# 完整流程：分析 + 提炼 + 自进化（dry-run）
python -m argocd_insight trace --session <session_id> --extract-insights --evolve
```
