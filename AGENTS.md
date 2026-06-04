# AGENTS.md — argocd-skill

Repo-specific guidance for OpenCode/AI agents working in the
`argocd-skill` repository. This file only records things an agent
would otherwise get wrong in **this** repo. It is not a general
ArgoCD tutorial.

## Current state

The repository is **mid-development, not yet first-commit-clean**.
The on-disk state (all files dated 2026-05-26) is:

```
argocd-skill/
├── SKILL.md                  261 lines, name=argocd-skill, bilingual
├── references/               5 docs (~50 KB total)
│   ├── cli-installation.md
│   ├── cli-commands.md
│   ├── kustomize-mapping.md
│   ├── kustomize-examples.md
│   └── batch-conversion-design.md
├── scripts/                  Python tool `argocd_cli_gen` + pytest tests
│   ├── argocd_cli_gen/       8-file Python package
│   ├── tests/                5 test files
│   ├── requirements.txt      PyYAML>=6.0, pytest>=7.0
│   └── README.md             full tool usage manual
├── LICENSE                   MIT, 2026, buhaiqing
├── README.md                 repo overview
└── AGENTS.md                 this file
```

**Repo state:** Two commits on `main`. `31775e0` is the initial
LICENSE + generic-Python `.gitignore` commit. `2866fbe`
(`feat(argocd-skill): 添加 ArgoCD CLI 技能及批量转换工具`) brings
in the on-disk skill: `SKILL.md`, `references/` (5 docs), and
`scripts/` (`argocd_cli_gen` package, tests, requirements, and its
own `.gitignore`). This commit adds `AGENTS.md` and updates
`README.md` to match the actual on-disk state.

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
argocd-skill/                  # the skill lives at the repo root (only one skill exists)
├── SKILL.md                   # entry point — frontmatter + 概述 + 何时使用 + 能力清单 + 常见错误
├── references/                # how-to depth; do not duplicate into SKILL.md
│   ├── cli-installation.md    # argocd CLI binary install (Linux/macOS/Windows/Docker, version handling, offline)
│   ├── cli-commands.md        # 20+ CLI commands, argocd.py method→CLI mapping
│   ├── kustomize-mapping.md   # 字段→flag 映射表 (namePrefix, images, commonLabels, patches, components, …)
│   ├── kustomize-examples.md  # 真实 YAML 转换示例 (含多源边界 + 命名规范)
│   └── batch-conversion-design.md  # argocd_cli_gen 方案设计 + 可行性论证
└── scripts/                   # the argocd_cli_gen batch tool + tests
    ├── argocd_cli_gen/        # python -m argocd_cli_gen
    │   ├── __init__.py
    │   ├── __main__.py
    │   ├── cli.py             # argparse 与编排
    │   ├── parser.py          # YAML 加载 + 4-tier 层级判定
    │   ├── mapper.py          # 字段→flag 映射表 (与 kustomize-mapping.md 同源)
    │   ├── renderer.py        # shell 脚本模板渲染
    │   ├── fallback.py        # 多源 / 不支持字段收集
    │   └── report.py          # JSON / MD 报告生成
    ├── tests/                 # pytest 套件 (5 test_*.py + fixtures/)
    ├── requirements.txt
    └── README.md              # 工具使用手册（输出结构、CLI 参数、退出码、模块结构）
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
  (5) 处理 ArgoCD CLI 不支持的边界（多源 spec.sources $values、kustomize.patches/components 等），引导用户回退到 `kubectl apply -f` 兜底方案。
  Trigger keywords: argocd, ArgoCD, app of apps, App-of-Apps, Application YAML, manifest 转 CLI, argocd app create, kustomize, multi-source, 多源, 反向生成, 批量转换, 迁移 ArgoCD, GitOps, kubectl apply 兜底.
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
   capability and sub-capability. New trigger phrases go here, not
   in `description`.
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
| `ARGOCD_AUTH_TOKEN` | env, exported by user | NEVER echo, mask as `***`, fail if unset |
| `ARGOCD_SERVER` | env, e.g. `argocd.hd123.com` | NEVER ask user to paste; fail if unset |
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

1. Shell env vars (`ARGOCD_AUTH_TOKEN`, `ARGOCD_SERVER`).
2. `~/.config/argocd/config` (the `argocd login` write target).
3. Interactive `argocd login` (SSO / OIDC) — only when no token is set.

The generator's `00_preflight.sh` does the login once via
`argocd login --auth-token $ARGOCD_AUTH_TOKEN --server $ARGOCD_SERVER`,
so subsequent scripts in the run can omit `--server / --auth-token`.
This is the **canonical** pattern for the skill to follow.

## Execution paths

- **Primary (capabilities 1, 2)**: `argocd` CLI v2.x directly. Use
  `--output json` so the agent can `jq` paths.
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

## Self-reflection rule

After **any** change to `SKILL.md` or its `references/` / `scripts/`:

1. Re-read the modified file from disk (do not trust memory).
2. Verify the frontmatter parses (no tab indentation; `---` on its
   own line exactly twice; `name` matches directory name).
3. Cross-check the change against the **error table** in SKILL.md
   (the 11-row "常见错误" section). New YAML→CLI mapping rows must
   add corresponding error rows; new error rows must reference
   existing `references/` entries.
4. Verify every trigger phrase in `description` is also reflected
   in **提示词示例** (the prompt-examples section), and vice versa.
   If a new prompt example is added but not the trigger, the agent
   will not match it.
5. Verify all `references/` cross-links resolve (each
   `[text](file.md)` points to a file that exists on disk).
6. Verify `references/kustomize-mapping.md` stays in sync with
   `scripts/argocd_cli_gen/mapper.py` — both encode the same
   field→flag rules; they are the single source of truth split
   between human and machine. Run a diff of the field list:
   ```bash
   grep -oE '\b\w+(\.\w+)+\b' references/kustomize-mapping.md | sort -u > /tmp/md_fields.txt
   grep -oE '"\w+(\.\w+)+"' scripts/argocd_cli_gen/mapper.py | sort -u > /tmp/py_fields.txt
   diff /tmp/md_fields.txt /tmp/py_fields.txt
   ```
7. If a `scripts/argocd_cli_gen/*.py` file changed, run
   `pytest scripts/tests/ -v` from the `scripts/` directory and
   confirm zero failures. Performance baseline: 97-YAML full-sample
   processing < 1 s; 500-app < 5 s.
8. Verify the 4-tier percentages in SKILL.md match
   `scripts/argocd_cli_gen/parser.py`'s classifier constants (or
   the test fixtures in `scripts/tests/fixtures/`).

Report `[OK] argocd-skill v0.1.0 — N rounds clean` when round N
finds no new issues.

## Cross-skill delegation (provisional)

| Task | Delegate to |
|---|---|
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
  `scripts/requirements.txt`. Root has no Python code.
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
