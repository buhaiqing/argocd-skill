# EVOLUTION — argocd-skill 持续演进

> 让 Skill 成为一个会自己生长、持续进化的智能体
> 小步快跑，质量先行，不搞大规划大文档

---

## 一、愿景

**"用自然语言驱动 ArgoCD的一切操作"**

用户说一句话，Skill 理解意图、执行操作、返回结果。
用户提出新需求，Skill 能吸收、验证、固化，持续变强。

三层能力阶梯：

```
第一层（执行）—— 我替你操作 ArgoCD
  你说"把 xxx App sync 一下"
  你说"删掉 xxx App 里的某个资源"
  你说"查看 xxx 的日志"
  → 不登 UI，不记命令，Skill 替你跑完

第二层（诊断）—— 我替你分析问题
  你说"哪些 App 有问题，为什么"
  你说"过去一周部署了多少次"
  → 聚合数据，给出结论

第三层（优化）—— 我替你发现机会
  你说"帮我看看有没有配置风险"
  你说"哪个环境部署最频繁"
  → 主动洞察，主动建议
```

---

## 二、演进规则

### 收到新需求怎么走

```
用户需求进来
  │
  ├── 命中当前能力 ────────────→ 直接执行，交付
  │
  ├── 可扩展覆盖 ────────────→ 增量实现，交付，更新本文件
  │
  ├── 全新能力（ArgoCD 范围内）→ 小步实现，交付，更新本文件
  │
  ├── 越界（ArgoCD 范围外）───→ 告知边界，指引其他 Skill
  │
  └── 破坏性操作 ────────────→ 必须用户重复确认，方可执行
```

**一个核心原则：小功能优先，能快速交付的就快速交付，不要憋大版本。**

### 版本命名

| 标签 | 含义 |
|------|------|
| `patch` | bugfix / 文档修正 / 测试补充，不增加能力 |
| `minor` | 新增一个可独立交付的小能力 |
| `major` | 架构性变更或大批量能力升级（少见）|

---

## 三、质量门（Karpathy 行为准那么强制不可违背）

> 每次交付（即使是 patch）必须通过，验证后方可声称完成

- [ ] **Karpathy 准则合规**：想清楚再写 / 简单优先 / 外科手术 / 目标驱动，四条全部遵守
- [ ] **Ponytail 合规**：决策阶梯优先（YAGNI→复用→stdlib→原生→已有依赖→一行→最后动手），`ponytail:` 注释标记有意简化，输出代码优先+最多三行说明
- [ ] **能跑通**：用 ArgoCD CLI 实际执行验证，不只是代码存在
- [ ] **文档同步**：SKILL.md 的触发词和能力清单同步更新
- [ ] **本文件更新**：本次新增的能力写入「当前状态」，缺口池同步移除
- [ ] **无回归**：`pytest scripts/tests/` 仍 100% 通过（如有改动）
- [ ] **边界说明**：副作用（如 delete 后会被 reconcile）在响应中显式说明

---

## 四、当前状态

> 每次交付后更新此处

### 能力现状

| 层级 | 已实现 | 待实现 |
|------|--------|--------|
| 执行层 | **App**：create/delete/sync/rollback/set/patch/delete-resource/refresh/unset/edit/terminate-op/logs/events/diff/history/wait/add-source/remove-source；**Project**：create/delete/edit/get/list/add-source/remove-source/add-dest/remove-dest/set；**ApplicationSet**：get/list/create/delete/generate；**Account**：get-user-info/generate-token/delete-token/list/update-password/can-i；**Repo/Cluster**：add/list/get/rm；**YAML→CLI/批量工具/健康报告** | — |
| 诊断层 | **OutOfSync 根因归因**（Git新增/手动漂移/内容不一致/孤儿资源） | Sync 历史统计 / 漂移检测 / 版本一致性检查 |
| 优化层 | — | 合规检查 / 成本估算 / 多集群对比 / Git 源健康检查 / 报告推送 |

### 缺口池（下一步优先级）

| 缺口 | 来源 | 优先级 | 目标版本 |
|------|------|--------|----------|
| Sync 历史统计 | 用户需求 | P1 | v0.3.x |
| 漂移检测 | 用户需求 | P1 | v0.3.x |
| 版本一致性检查 | 用户需求 | P1 | v0.3.x |

### 范围定义

**在范围内**：ArgoCD Core（Application / Project / ApplicationSet / Account / Repo / Cluster）、argocd CLI、Application YAML → CLI 转换。

**在范围内（视用户环境而定）**：argocd HTTP API、argocd CLI 无法处理的边界场景兜底。

**明确排除**：
- Argo Rollouts — 独立二进制 `argocd-rollouts`，需单独 skill
- Argo Workflows — 超出 GitOps 范畴
- Argo CD Notifications — 告警路由另开 skill

### 版本升级 SOP

minor / patch 完成后执行：

1. `SKILL.md` frontmatter `version` → 新版本
2. 本文件 evolution log 新增一行（日期 / 版本 / 变更摘要）
3. `git tag vX.Y.Z && git push --tags`
4. 如有脚本改动：`pytest scripts/tests/` → 必须 100% 通过

regression 回滚：`git revert <bad-commit> && git tag -d vX.Y.Z && git push origin :refs/tags/vX.Y.Z`

---

## 五、演化日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-06-04 | v0.2.0 | 初始发布：CLI 安装 + 命令生成 + YAML→CLI + 批量工具 |
| 2026-07-01 上午 | v0.2.1 | P0 执行层初步补完：delete-resource / logs / events / diff / set+patch / 健康报告。67/67 测试通过 |
| 2026-07-01 下午 | v0.2.2 | 执行层全面覆盖：refresh/unset/edit/terminate-op/多源/proj全命令/appset全命令/account全命令/repo+cluster全命令。SKILL.md 能力表 25 条全映射。67/67 测试通过 |
| 2026-07-01 下午 | v0.2.3 | SKILL.md 新增准则五（Ponytail 最小代码优先）；EVOLUTION.md 质量门更新；TODO.md 重建结构 |
| 2026-07-01 下午 | v0.2.x | 诊断层工具原型：argocd_deploy_stats 部署频率统计，30 App 16s 实测通过，WIP |
| 2026-07-01 | v0.2.4 | 范围定义 + 版本 SOP + 缺口池补充目标版本；回滚路径补全 |
| 2026-07-01 | v0.3.0 | **P1-1 OutOfSync 根因归因交付**：oos_analyzer.py 代码加固（timeout/双格式diff/ponytail标记）+ 16例测试 + SKILL.md 集成（能力四+触发词+错误表） |
