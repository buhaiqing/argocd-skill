<!-- Universal rules in ~/.config/opencode/AGENTS.md -->

<!-- CODEGRAPH_START -->
## CodeGraph

在已索引的仓库（存在 `.codegraph/` 目录）中，**优先使用 CodeGraph** 而非 grep/Read/find 来定位和理解代码。

**使用流程：**
1. **先同步**：`codegraph sync [path]` 确保索引与磁盘一致
2. **再查询**：`codegraph_explore`（MCP 工具）或 `codegraph explore`（CLI）返回相关符号的源码 + 调用链路，通常一次调用即可替代多轮 grep+Read
3. **处理未同步文件**：如果查询结果顶部出现 `"⚠️ Some files referenced below were edited since the last index sync…"` 的横幅，横幅中列出的文件应直接用 `Read` 读取最新内容，不要依赖索引

**优势：** 一次调用返回结构化的源码 + 调用链路 + 影响范围 (blast radius)，比多轮 grep+Read 节省 60-80% token，并且对动态分发 (dynamic dispatch, callback, JSX children) 的追踪比 grep 更准确。

若仓库没有 `.codegraph/` 目录，则跳过 CodeGraph，用常规工具。索引是用户决定——不要主动运行 `codegraph init`。
<!-- CODEGRAPH_END -->

# AGENTS.md — argocd-skill

Repo-specific guidance for OpenCode/AI agents working in the
`argocd-skill` repository. This file only records things an agent
would otherwise get wrong in **this** repo. It is not a general
ArgoCD tutorial.

## Current state

The repository is **v0.4.2+ (2026-07-02) — actively developed**.
The on-disk state is:

```
argocd-skill/
├── SKILL.md                  entry point, bilingual, frontmatter trigger
├── references/               15 docs
│   ├── cli-installation.md
│   ├── cli-commands.md
│   ├── kustomize-mapping.md
│   ├── kustomize-examples.md
│   ├── batch-conversion-design.md
│   ├── testing-guide.md
│   ├── performance-guide.md
│   ├── agent-protocols.md
│   ├── argocd-app-lifecycle.md
│   ├── argocd-appproject-guide.md
│   ├── argocd-sync-policy-deep-dive.md
│   ├── argocd-appset-guide.md
│   ├── argocd-troubleshooting.md
│   ├── argocd-insight-commands.md
│   └── argocd-prompts.md
├── scripts/                  Python tools + pytest tests (32 test files)
│   ├── argocd_cli_gen/       YAML→CLI batch converter
│   ├── argocd_api/           HTTP API CLI (bypasses argocd CLI bugs)
│   ├── argocd_insight/       insight suite (diagnose/drift/health/cost/...)
│   ├── argocd_deploy_stats/  deployment stats + OOS analyzer
│   ├── ulw/                  ArgoCD ultra-workload via HTTP API
│   ├── tests/                32 test files
│   ├── requirements.txt      PyYAML>=6.0, pytest>=7.0
│   └── README.md             tool usage manual
├── LICENSE                   MIT, 2026, buhaiqing
├── README.md                 repo overview
└── AGENTS.md                 this file
```

The root `.gitignore` is the generic Python template. Each subdir
with Python scratch state (`scripts/`, and any future `tests/`)
ships its own `.gitignore`. Do not move scratch-state ignores to
the root — keep the root lean and let subdirs own their state.

## What this repo is

A flat collection of AI-Agent runbooks for operating
[Argo CD](https://argo-cd.readthedocs.io/) — the GitOps controller
for Kubernetes. There is no build, no lint, no CI. The runtime is
the agent that loads `SKILL.md` via its `description` trigger. The
single shipped skill is **`argocd-skill`** (CLI installation +
natural language → CLI command generation + Application YAML →
`argocd app create` reverse engineering, with a Python tool for
batch conversion).

The layout mirrors the user's other skill collections
(`aws-skills`, `hcloud-skills`, `another-aliyun-skills`).

## Skill layout (current)

```
argocd-skill/
├── SKILL.md                   entry point — frontmatter + 概述 + 何时使用 + 能力清单 + 常见错误
├── references/                15 docs — how-to depth; do not duplicate into SKILL.md
│   ├── cli-installation.md    # argocd CLI binary install (Linux/macOS/Windows/Docker, version handling, offline)
│   ├── cli-commands.md        # 20+ CLI commands, argocd.py method→CLI mapping
│   ├── kustomize-mapping.md   # 字段→flag 映射表 (namePrefix, images, commonLabels, patches, components, …)
│   ├── kustomize-examples.md  # 真实 YAML 转换示例 (含多源边界 + 命名规范)
│   ├── batch-conversion-design.md  # argocd_cli_gen 方案设计 + 可行性论证
│   ├── testing-guide.md       # 测试标准、委托规则、Hypothesis 属性测试
│   ├── performance-guide.md   # 性能复盘流程、检查清单、基准指标
│   ├── agent-protocols.md     # 开机预检协议、CLI 回退协议
│   ├── argocd-app-lifecycle.md       # App 全生命周期 runbook
│   ├── argocd-appproject-guide.md    # AppProject 管理 runbook
│   ├── argocd-sync-policy-deep-dive.md  # syncPolicy 深度解析
│   ├── argocd-appset-guide.md        # ApplicationSet runbook
│   ├── argocd-troubleshooting.md     # 故障排查（按症状分流）
│   ├── argocd-insight-commands.md    # insight 子命令参考
│   └── argocd-prompts.md             # 提示词示例
├── scripts/                   Python tools + pytest tests (32 test files)
│   ├── argocd_cli_gen/        # python -m argocd_cli_gen (YAML→CLI batch converter)
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── cli.py             # argparse 与编排
│   │   ├── parser.py          # YAML 加载 + 4-tier 层级判定
│   │   ├── mapper.py          # 字段→flag 映射表 (与 kustomize-mapping.md 同源)
│   │   ├── renderer.py        # shell 脚本模板渲染
│   │   ├── fallback.py        # 多源 / 不支持字段收集
│   │   └── report.py          # JSON / MD 报告生成
│   ├── argocd_api/            # python -m argocd_api (HTTP API CLI, bypasses argocd CLI bugs)
│   ├── argocd_insight/        # python -m argocd_insight (diagnose/drift/health/cost/...)
│   │   ├── trace/             # 轨迹记录 (session/writer/@traced)
│   │   ├── analyzer/          # 统计聚合 + 瓶颈识别 + 错误归因
│   │   ├── insight_engine/    # 经验提取 + 推断链生成
│   │   ├── evolver/           # 风险分级 + 写回执行器
│   │   ├── skillopt/          # SDK 适配 + 意图识别 + 参数推荐
│   │   ├── trigger/           # 离线触发 (cron/threshold/session_end)
│   │   └── *.py               # diagnose/drift/health/cost/batch/autofix/...
│   ├── argocd_deploy_stats/   # python -m argocd_deploy_stats (部署统计 + OOS 分析)
│   ├── ulw/                   # python -m ulw (ArgoCD ultra-workload via HTTP API)
│   ├── tests/                 # 32 test files
│   ├── requirements.txt       # PyYAML>=6.0, pytest>=7.0
│   └── README.md              # 工具使用手册（输出结构、CLI 参数、退出码、模块结构）
```

**Top-level vs nested**: The skill lives at the repo root because the
repo currently contains only one skill. The next skill (e.g.
`argocd-skill-generator/`) MUST use the **nested** layout
(`<skill-name>/SKILL.md` + `references/` + `assets/`) to leave room
for parallel top-level skills. When the second skill lands, move
this one into `argocd-skill/SKILL.md` to keep the convention uniform.

## SKILL.md frontmatter (concrete)

The current `SKILL.md` ships with this frontmatter — preserve it
verbatim when editing. `name`, `description`, `allowed-tools` are
mandatory. `description` is a literal block (`|`) with bilingual
trigger phrases; both Chinese and English must stay in sync.

```yaml
---
name: argocd-skill
description: |
  ArgoCD CLI 全流程技能。Use when the user wants to:
  (1) 安装 / 升级 argocd CLI（含跨平台 Linux/macOS/Windows/Docker、指定版本、离线包）；
  (2) 用自然语言生成 argocd CLI 命令（app create / sync / rollback / get / list / login 等 20 个高频操作）；
  (3) 把 1 个 ArgoCD Application YAML（spec.source / spec.sources / kustomize / helm / syncPolicy / App-of-Apps Root）翻译成等价的 `argocd app create` 命令；
  (4) 把整个 manifest 目录（如 argoapp 仓库、argo-apps/dly/production 等）批量反向生成 shell 脚本（迁移 / 重建 / 备份 / 灾备 / 新集群初始化 / GitOps 配置脚本化场景），调用内置工具 `python -m argocd_cli_gen`；
  (5) 处理 ArgoCD CLI 不支持的边界（多源 spec.sources $values、kustomize.patches/components 等），引导用户回退到 `kubectl apply -f` 兜底方案；
  (6) 通过 HTTP API（`/api/v1`）执行 ArgoCD 操作，适用于 CLI 失败时的自动回退，调用 `python -m argocd_api`；
  (7) 诊断分析 / 漂移检测 / 健康评估 / 成本估算 / 合规检查 / 批量自动修复 / 变更影响分析 / 批量操作 / 配置模板生成 / Git 源健康检查 / 报告推送，调用 `python -m argocd_insight` 系列工具。
  Trigger keywords: argocd, ArgoCD, app of apps, App-of-Apps, Application YAML, manifest 转 CLI, argocd app create, kustomize, multi-source, 多源, 反向生成, 批量转换, 迁移 ArgoCD, GitOps, kubectl apply 兜底, HTTP API, argocd 回退, 诊断分析, 问题 App, OutOfSync, 根因归因, 漂移检测, 健康评估, 成本估算, 合规检查, 自动修复, 变更影响, 批量操作, 配置模板, Git 源健康, argocd-insight, argocd_insight.
allowed-tools: [Read, Write, Bash, Grep, Glob]
---
```

Common frontmatter bugs:

- `description: |` (literal) and `description: >-` (folded) are
  different. The on-disk version uses `|` so newlines are preserved.
- `name` MUST equal the directory name (here both are `argocd-skill`).
  Renaming either side breaks trigger-based skill resolution.
- The two `---` markers must be the only content on their line.

## Mandatory sections in SKILL.md

The on-disk `SKILL.md` is organized as:

1. **概述** (Overview) — one paragraph stating the three core
   capabilities.
2. **何时使用** (When to use) — bullet list of natural-language
   triggers.
3. **能力清单** (Capabilities) — 能力一 / 能力二 / 能力三
   (install / command-gen / YAML→CLI), each linking to its
   `references/` page.
4. **App-of-Apps 与层级分布** — the 4-tier production model with
   **real percentages from the argoapp 97-YAML sample**. Keep this
   table in sync with `scripts/argocd_cli_gen/parser.py`'s tier
   classifier (single source of truth split between Markdown and
   Python).
5. **提示词示例** (Prompt examples) — concrete phrases grouped by
   capability and sub-capability, migrated to `references/argocd-prompts.md`.
   New trigger phrases go there, not in `description`.
6. **常见错误** (Common errors) — the 11-row error table.
   **This is the most important table for the agent to consult
   before responding.** Every "translate this YAML" request must
   cross-check against this table.
7. **参考资料** (References) — external ArgoCD docs / GitHub Release
   page.

When adding a new capability, add a row to the error table covering
the failure mode you are introducing.

## Variable / credential convention

| Placeholder / var | Source | Agent action |
|---|---|---|
| `ARGOCD_AUTH_TOKEN` | env, exported by user | NEVER echo, mask as `***`; 优先使用 |
| `ARGOCD_USERNAME` | env, exported by user | 备用：ARGOCD_AUTH_TOKEN 未设时使用 |
| `ARGOCD_PASSWORD` | env, exported by user | 备用：ARGOCD_AUTH_TOKEN 未设时使用 |
| `ARGOCD_SERVER` | env, e.g. `https://argocd.hd123.com/dnet-int` | NEVER ask user to paste; 支持带 context path 的 base URL |
| `ARGOCD_SKILL_RUNTIME_DIR` | env 或 `.env`，可选 | 轨迹根目录；未设时默认 `<repo>/.runtime/argocd-skill`；见 `.env.example` |
| `{{user.app_name}}` | user input | Ask once; reuse |
| `{{user.namespace}}` | user input (业务 / 运维) | Ask once; reuse |
| `{{user.project}}` | AppProject name (NOT user project) | Ask once; reuse |
| `{{user.repo_url}}` | Git URL (HTTPS / SSH) | Ask once; reuse |
| `{{user.revision}}` | Git SHA, branch, or `HEAD` | Ask once; reuse |
| `{{user.argocd_version}}` | e.g. `v3.4.2` | Default to latest from GitHub API |
| `{{user.input_dir}}` | absolute path to manifest dir | Sub-capability 3.2 only; ASK for absolute path |
| `{{user.argocd_mode}}` | `inline` (3.1) or `batch` (3.2) | Default to `inline` for ≤4 YAMLs, `batch` for ≥5 |
| `{{output.run_all_path}}` | generator's `--output` join | Show to user at end |
| `{{output.report_md}}` | generator's `report.md` path | Surface fallback count + top warnings |

Credential priority order (highest first):

1. `ARGOCD_AUTH_TOKEN` — 优先使用，自动化场景推荐。
2. `ARGOCD_USERNAME` + `ARGOCD_PASSWORD` — ARGOCD_AUTH_TOKEN 未设时使用，preflight 脚本会用它们自动执行 `argocd login`。
3. `~/.config/argocd/config` (the `argocd login` write target).
4. Interactive `argocd login` (SSO / OIDC) — 仅当以上均无时触发。

The generator's `00_preflight.sh` does the login once via
`argocd login --auth-token $ARGOCD_AUTH_TOKEN --server $ARGOCD_SERVER`,
so subsequent scripts in the run can omit `--server / --auth-token`.
This is the **canonical** pattern for the skill to follow.

### 会话内状态复用（短期 in-memory）

上表中的 `{{user.*}}` 占位符在**同一 LLM 会话内**会被 agent 自动复用。
规则清单（按顺序执行）：

1. 上条命令中出现过的 `app_name / namespace / project / repo_url /
   revision`，下条命令省略时**自动沿用**——不再向用户重述。
2. 自动沿用时**必须在输出开头显式标注**：
   `复用：app_name=my-app, namespace=production, project=default`
   让用户一眼看清 agent 替它"记住"了哪些字段，便于纠错。
3. **跨会话不持久**：新会话必须让用户重述关键字段。
   不写入任何文件、不写入 LLM 长期记忆。
4. **冲突优先原则**：若上条命令的 `app_name` 与本次意图不匹配
   （例如上一条是 `my-app`，本次意图对象是 `other-app`），**不沿用**，
   优先让用户确认目标 app_name。
5. `ARGOCD_SERVER` 同样适用会话内复用规则——同一会话内不必每条
   命令都检查，能力二开机预检通过后默认沿用（详见下文"能力二开机
   环境检查"）。

> **与凭证屏蔽规则不冲突**：本节复用规则仅作用于 LLM 上下文中的
> `{{user.*}}` 占位符与 `ARGOCD_SERVER`。`ARGOCD_AUTH_TOKEN` 仍按
> 上表规则**绝不可回显、绝不可写进日志/非加密通道**。env 变量本身
> 由 shell 提供，不出现在 LLM 上下文——本节不改变该行为。

## Execution paths

- **Primary (capabilities 1, 2)**: `argocd` CLI v2.x directly. Use
  `--output json` so the agent can `jq` paths.（能力 2 在会话开头
  需先执行"开机环境检查"，详见下文。）
- **Sub-capability 3.1 (single YAML)**: Agent reads the YAML,
  applies the field→flag mapping from `references/kustomize-mapping.md`,
  outputs `argocd app create …` inline. No external tool needed.
- **Sub-capability 3.2 (batch)**: Invoke the bundled Python tool:
  ```bash
  python -m argocd_cli_gen \
    --input  /abs/path/to/argo-apps \
    --output ./out \
    --upsert --emit-dry-run
  ```
  Then read `out/report.md` to surface fallback entries and the
  `run_all.sh` invocation. **Use absolute `--input` paths** so the
  generator works from any working directory.
- **Fallback for unsupported cases** (multi-source `spec.sources`
  with `$values`, `kustomize.patches`, `kustomize.components`,
  custom plugins): emit `kubectl apply -f <original.yaml>` and
  explain in the response why the CLI cannot express the resource.
  Do NOT try to "force" the conversion — produce the `kubectl apply`
  fallback AND populate `99_multisource_fallback.yaml` in batch mode.
- **Cluster-side (rare)**: `kubectl -n argocd` for raw CRD inspection
  when the CLI / API returns an opaque error. Read-only.

Destructive operations (`argocd app delete`, `argocd app terminate-op`,
`argocd cluster rm`, `argocd repo rm`, `argocd proj delete`) MUST
require the user to repeat the exact resource identifier before
invocation. This skill does **not** exercise destructive paths in
its core flow — if the user wants destructive ops, delegate to
`kubectl` or run a custom script.

## Agent 协议（详见 [references/agent-protocols.md](references/agent-protocols.md)）

- **能力二开机环境检查**：会话开头预检 → 认证凭证检测 → CLI/API 回退
- **CLI 运行时回退协议**：CLI 失败 → 自动回退 `python -m argocd_api` → 3 条铁律

### 【IMPORTANT】多任务开发协作模式 — 编码 + 评审双 Agent

> 本节为**强制规则**，适用于仓库内任何被拆分为多任务的开发工作（如
> P3.5 离线触发、批量优化等）。用户已明确要求按此模式执行，不可省略。

**核心规则：每个 task 启动 2 个 subagent，配对协作直到无问题才能结束。**

| 角色 | 模型 | 职责 |
|------|------|------|
| 编码 Agent | `default` | TDD 实现：先写测试看失败 → 最小实现看通过 → 全量回归 |
| 评审 Agent | `reasoning`（**必须与编码 Agent 模型不同**） | 代码评审：风格 / 安全 / 边界 / 测试覆盖 / 与既有模块一致性 |

**协作流程（循环到评审无问题）：**

```
1. 编码 Agent 完成功能实现 + 自测全绿
2. 编码 Agent → SendMessage(评审 Agent)：附文件路径 + 测试结果
3. 评审 Agent 读取代码 + 测试，反馈问题清单（分类：阻塞 / 建议）
   - 若无问题 → SendMessage(编码 Agent)：approved，结束
   - 若有问题 → SendMessage(编码 Agent)：问题清单
4. 编码 Agent 修复所有阻塞项 + 接受的建议项
5. 编码 Agent → SendMessage(评审 Agent)：已修复，请复核
6. 回到 Step 3，直到评审 Agent 返回 approved
```

**关键约束：**

- **模型必须不同**：编码用 `default`，评审用 `reasoning`。同模型评审
  等于自我背书，违反本规则即作废。
- **评审 Agent 只读不写**：不直接修改代码，仅反馈问题清单。修复
  由编码 Agent 执行，保证责任单一。
- **循环上限**：最多 3 轮。第 3 轮仍有阻塞项时，编码 Agent 必须向
  主会话（team-lead）上报冲突点，由用户裁决，不得自行放行。
- **结束条件**：评审 Agent 明确回复 `approved` 且无阻塞项。仅"测试
  通过"不等于可结束——评审必须签字。
- **独立任务并行**：彼此无依赖的 task 可并行启动多对 agent；有依赖
  的 task 必须等依赖项的 agent 对结束并 merge 后再启动。
- **TDD 不可绕过**：编码 Agent 仍须遵守 Red-Green-Refactor，先看
  测试失败再实现。评审 Agent 应检查测试是否真实验证了行为（不是
  mock 自验）。

**适用范围：** 任何被 TaskCreate 拆分为多 task 的开发工作。单 task
一次性修复（< 30 行改动）可豁免，由主会话直接评审。

## App-of-Apps 4-tier production model

Encoded in both `SKILL.md` (Markdown table) and
`scripts/argocd_cli_gen/parser.py` (classifier). Real production
percentages from the argoapp 97-YAML sample — keep the two in sync:

| Tier | Share | Namespace | automated | labels | CreateNamespace |
|---|---:|---|---|---|---|
| 基础设施 Root (projects / repos / initns) | <1% | `argo-root` | n/a | no | n/a |
| 聚合入口 Root (`{project}-{profile}-{branch}.yaml`) | 5% | `argo-root` | **required** | no | true |
| 业务应用 (`{stack}-{app}.yaml`) | 76% | business ns | **NO** (manual sync) | **required** (project/profile/stack/app) | true |
| 运维组件 (`k8s_ops/...`) | 18% | `ops` / `loki` / `kube-system` / etc. | NO | usually no | **false** (namespace managed by initns) |

Tier classifier invariants — the agent must respect these when
translating a YAML into `argocd app create …`:

- `destination.namespace == "argo-root"` ⇒ Root tier ⇒ must emit
  `--sync-policy automated --auto-prune --self-heal`, omit labels.
- 业务 application ⇒ emit labels 四件套, omit `automated`, keep
  `CreateNamespace=true`.
- 运维 component ⇒ omit labels, set `CreateNamespace=false` (unless
  the source YAML explicitly sets it true).
- `metadata.name` containing `_` MUST be replaced with `-` (ArgoCD
  rejects underscores). But `--revision k8s_mas` (git branch) keeps
  underscores — that flag is git-revision, not app-name.

## Post-change self-reflection (argocd-specific)

After the universal self-reflection in `~/.config/opencode/AGENTS.md`,
also run these argocd-specific checks:

1. Re-read the modified file from disk (do not trust memory).
2. Verify the frontmatter parses (no tab indentation; `---` on its
   own line exactly twice; `name` matches directory name).
3. Cross-check the change against the **error table** in SKILL.md
   (the 11-row "常见错误" section). New YAML→CLI mapping rows must
   add corresponding error rows; new error rows must reference
   existing `references/` entries.
4. Verify every trigger phrase in `description` is also reflected
   in `references/argocd-prompts.md` (the prompt-examples section), and vice versa.
   If a new prompt example is added but not the trigger, the agent
   will not match it.
5. Verify all `references/` cross-links resolve (each
   `[text](references/cli-commands.md)` points to a file that exists on disk).
6. Verify `references/kustomize-mapping.md` stays in sync with
   `scripts/argocd_cli_gen/mapper.py` — both encode the same
   field→flag rules; they are the single source of truth split
   between human and machine. Run a diff of the field list:
   ```bash
   grep -oE '\b\w+(\.\w+)+\b' references/kustomize-mapping.md | sort -u > /tmp/md_fields.txt
   grep -oE '"\w+(\.\w+)+"' scripts/argocd_cli_gen/mapper.py | sort -u > /tmp/py_fields.txt
   diff /tmp/md_fields.txt /tmp/py_fields.txt
   ```
7. If any tool invocation in `SKILL.md` / `references/` changed or
   is newly documented, **verify it actually works** before claiming
   done.  Run the documented command from the repo root:
   ```bash
   cd /path/to/argocd-skill
   python3 -m argocd_api --help           # HTTP API CLI
   python3 -m argocd_cli_gen --help       # batch converter
   python3 -m argocd_insight --help      # insight suite
   python3 -m argocd_deploy_stats.stats --help   # deployment stats
   python3 -m argocd_deploy_stats.oos_analyzer --help  # OOS analyzer
   ```
   If it fails, fix the tool's `__main__.py` or `sys.path` setup —
   **never silently accept a broken invocation in the docs**.  This
   rule would have caught the `python -m argocd_api` docs-vs-implementation
   mismatch that prompted the v0.2.1 fix.
8. If a `scripts/argocd_cli_gen/*.py` file changed, run
   `pytest scripts/tests/ -v` from the `scripts/` directory and
   confirm zero failures. Performance baseline: 97-YAML full-sample
   processing < 1 s; 500-app < 5 s.
8. Verify the 4-tier percentages in SKILL.md match
   `scripts/argocd_cli_gen/parser.py`'s classifier constants (or
   the test fixtures in `scripts/tests/fixtures/`).
9. **TODO.md 同步更新**：每个新功能（含 bugfix / 文档变更 / 测试补充）完成并
   通过 post-change 自检后，**必须**将 TODO.md 中对应项标记为 `✅` 并更新状态
   说明。若本次变更新增了计划项但 TODO.md 尚未列出的，须同步添加新行。这是
   **强制规则**，不可省略。TODO.md 的迭代记录表（`## 📋 迭代记录`）也必须同步
   追加新行记录当前版本号与变更摘要。

Report `[OK] argocd-skill v0.4.2 — N rounds clean` when round N
finds no new issues.

## Cross-skill delegation (provisional)

| Task | Delegate to |
|---|---|
| argocd 会话开机预检（`command -v argocd` / `ARGOCD_*` env） | **argocd-skill 自身**（不委托） |
| Cluster / node / pod inspection | `kubectl` (external) |
| Image / registry operations | `docker` / `crane` / `oras` (external) |
| Git operations (clone, fetch, diff) | `git` CLI (external) |
| Helm chart linting / template | `helm` (external) |
| Kustomize build / validation | `kustomize` (external) |
| Notification target provisioning | Notify the user; do not invent tokens |
| Secret material | Always reference an existing ExternalSecret / SealedSecret; never generate inline |

When a second `argocd-*-ops` skill lands (e.g. `argocd-notification-ops`,
`argocd-applicationset-ops`), extend the table and add a
"delegation" subsection to each affected `SKILL.md`.

## What NOT to add

- ❌ `requirements.txt` at the repo root — Python deps belong in
  `scripts/requirements.txt`.  Note: repo root now has
  `__init__.py` (namespace package marker) and tool directories
  (`argocd_api/`, `argocd_cli_gen/`, `argocd_insight/`,
  `argocd_deploy_stats/`) and wrapper scripts (`argocd_deploy_stats.py`)
  for `python -m <tool>` compatibility;
  **each tool package's `__init__.py` and `__main__.py` MUST be real files**
  (not symlinks), otherwise `python3 -m <tool>` fails with
  "Cannot use package as __main__".
- ❌ CI / pre-commit config — no build, no lint, no CI by design.
  Tests are local-only via `pytest scripts/tests/`.
- ❌ A `tests/` mirror at the repo root — tests are colocated with
  the tool they exercise, in `scripts/tests/`.
- ❌ Long ArgoCD tutorials — link to
  <https://argo-cd.readthedocs.io/>. This repo is operational
  runbooks, not documentation.
- ❌ Speculative `argocd app …` flags — only reference flags the
  agent has actually seen exercised in the bundled fixtures
  (`scripts/tests/fixtures/`).
- ❌ Renaming `argocd-skill` to `argocd-ops` — the on-disk SKILL.md
  frontmatter, tests, and the Python tool all use `argocd-skill` as
  the canonical name. Renaming would break `name:` matching in
  trigger-based skill resolution and the `argocd_cli_gen` module.
- ❌ A `kustomize` Python wrapper — the field→flag mapping is a
  pure data structure in `mapper.py`. Keep it declarative; resist
  the urge to "improve" it with imperative logic.

## See also

- `README.md` — repo overview, capabilities, quick start.
- `LICENSE` — MIT, © 2026 buhaiqing.
- Sibling repos this layout mirrors: `aws-skills/AGENTS.md`,
  `hcloud-skills/AGENTS.md`, `another-aliyun-skills/AGENTS.md`.
- External: <https://argo-cd.readthedocs.io/en/stable/cli-reference/argocd/>,
  <https://argo-cd.readthedocs.io/en/stable/operator-manual/api/>.
- Tool manual: `scripts/README.md`.

## 语言要求

所有交互回复都必须使用中文内容回复。用户使用中文提问时，必须用中文回答；用户使用英文提问时，也优先用中文回答。仅在用户明确要求使用英文时，才用英文回复。
