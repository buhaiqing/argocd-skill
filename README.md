# argocd-skill

> **Latest (v0.2.0, 2026-06-04):** Capability 2 (自然语言 → CLI) 升级为向导化模式：5 子协议 (2.1 必填清单 / 2.2 复合意图 / 2.3 危险命令二次确认 / 2.4 会话内复用 / 2.5 命令吐出前自检 11 项)。`SKILL.md` / `references/cli-commands.md` / `AGENTS.md` 三处文档改动共 +290 行；Python 工具未动。详见 `AGENTS.md`「Current state」。
>
> The on-disk skill (`SKILL.md`, `references/`, `scripts/`) is
> already committed in `2866fbe`. This repo adds `AGENTS.md`
> (AI-Agent guidance) and tracks a bilingual README on top.

ArgoCD CLI 全流程技能 — 一站式覆盖 argocd CLI 安装、自然语言生成 CLI
命令、Application YAML 反向生成可执行 shell 脚本。

> A one-stop AI Agent skill for the ArgoCD CLI: install
> (cross-platform), generate `argocd app create` commands from
> natural language, and reverse-engineer manifest directories
> into versionable shell scripts for migration, backup, and
> disaster-recovery scenarios.

## 三项核心能力 (Three core capabilities)

| # | 能力 | 入口 | 说明 |
|---|---|---|---|
| 1 | **CLI 安装** | [references/cli-installation.md](references/cli-installation.md) | 跨平台 (Linux / macOS / Windows / Docker)，支持指定版本 + 离线包 |
| 2 | **自然语言生成 CLI** | [references/cli-commands.md](references/cli-commands.md) | 20+ 高频操作：app create / sync / rollback / get / list / login 等。**v0.2.0 起为向导化模式**：5 子协议（必填清单 / 复合意图编排 / 危险命令二次确认 / 会话内状态复用 / 命令吐出前 11 项自检）|
| 3 | **YAML 反向生成** | [references/kustomize-mapping.md](references/kustomize-mapping.md) + [scripts/README.md](scripts/README.md) | 子能力 3.1 单 YAML 内联转换；子能力 3.2 目录批量转换（调用 `python -m argocd_cli_gen`） |

## 触发关键词 (Trigger keywords)

`argocd`, `ArgoCD`, `app of apps`, `App-of-Apps`, `Application YAML`,
`manifest 转 CLI`, `argocd app create`, `kustomize`, `multi-source`,
`多源`, `反向生成`, `批量转换`, `迁移 ArgoCD`, `GitOps`,
`kubectl apply 兜底`.

## 仓库结构 (Repository layout)

```
argocd-skill/
├── SKILL.md                   入口（frontmatter trigger + 何时使用 + 能力清单 + 常见错误）
├── references/                深度文档（不与 SKILL.md 重复）
│   ├── cli-installation.md
│   ├── cli-commands.md
│   ├── kustomize-mapping.md
│   ├── kustomize-examples.md
│   └── batch-conversion-design.md
└── scripts/                   argocd_cli_gen 批量转换工具 + pytest 套件
    ├── argocd_cli_gen/        python -m argocd_cli_gen
    ├── tests/                 单元 + 集成测试
    ├── requirements.txt       PyYAML>=6.0, pytest>=7.0
    └── README.md              工具使用手册（输出结构 / CLI 参数 / 退出码 / 模块结构）
```

> The skill lives at the repo root because the repo currently
> contains only one skill. When a second skill lands, this
> directory becomes `argocd-skill/SKILL.md` (nested layout, leaving
> room for parallel top-level skills).

## 快速开始 (Quick start)

### 1. 一次性环境准备 (One-time setup)

```bash
# 安装 argocd CLI（详见 references/cli-installation.md）
curl -sSL -o /usr/local/bin/argocd \
  https://github.com/argoproj/argo-cd/releases/download/v3.4.2/argocd-linux-amd64
chmod +x /usr/local/bin/argocd
argocd version --client
```

### 2. 配置认证 (Configure credentials)

```bash
export ARGOCD_AUTH_TOKEN="***"   # 来自 argocd account generate-token 或 SSO
export ARGOCD_SERVER="argocd.hd123.com"
```

**严禁**：让用户在聊天中粘贴 token；agent 在 env 未设置时必须 fail closed。

### 3. 触发技能 (Trigger the skill)

| 你说 | 技能做的事 |
|---|---|
| "帮我装一下 argocd CLI" / "安装 ArgoCD 3.4.2" | 能力 1：下载并安装指定版本 |
| "创建一个 ArgoCD 应用 my-app 从 main 分支到 prod" | 能力 2：生成 `argocd app create …` 命令 |
| "把这个 Application YAML 转成 CLI" / 粘贴 YAML 文本 | 能力 3.1：内联字段映射 + 常见错误检查 |
| "把 /path/to/argo-apps 整目录生成脚本" / "批量迁移 ArgoCD" | 能力 3.2：调用 `python -m argocd_cli_gen` |
| "这个 loki 是多源 Helm，CLI 写不出来怎么办" | 能力 3 + 兜底：回退到 `kubectl apply -f` |

完整提示词示例见 [`SKILL.md`](SKILL.md) 提示词示例小节。

## App-of-Apps 层级模型 (4-tier production model)

基于真实生产环境 97 个 YAML 样本统计（argoapp 仓库）：

| 层级 | 占比 | 命名 | namespace | 关键约束 |
|---|---:|---|---|---|
| 基础设施 Root | <1% | `projects.yaml`、`repos.yaml`、`initns/namespace.yaml` | `argo-root` | 自启动初始化 |
| 聚合入口 Root | 5% | `{project}-{profile}-{git_branch}.yaml` | `argo-root` | 必含 `automated.prune+selfHeal` |
| 业务应用 | 76% | `{stack}-{app}.yaml` | 业务命名空间 | labels 四件套；**不开 automated** |
| 运维组件 | 18% | `prometheus.yaml` / `loki.yaml` / `redis.yaml` | `ops` / `loki` 等 | 多含 `CreateNamespace=false` |

判定规则见 [`SKILL.md`](SKILL.md) 的"App-of-Apps 与层级分布"小节；批量工具的分类实现在 [`scripts/argocd_cli_gen/parser.py`](scripts/argocd_cli_gen/parser.py)。

## 批量转换示例 (Batch conversion example)

```bash
cd scripts/
pip install -r requirements.txt

# 把一个真实 manifest 目录反向生成为可执行脚本
python -m argocd_cli_gen \
  --input  /abs/path/to/argo-apps/dly/production \
  --output ./out \
  --upsert --emit-dry-run

# 执行
cd out/
bash 00_preflight.sh                  # 一次性 argocd login
bash 30_workloads_business.dry-run.sh # 灰度验证（输出 YAML 不下发）
bash run_all.sh                       # 正式下发
```

输出结构、退出码语义、CLI 参数详见 [`scripts/README.md`](scripts/README.md)。

## 常见错误速查 (Common error cheatsheet)

完整版见 [`SKILL.md`](SKILL.md) 的"常见错误"小节（11 行）。最高频的 5 条：

| 错误 | 正确处理 |
|---|---|
| 缺 `--dest-server` | 必填，不允许省略 |
| Kustomize 参数误用 `--helm-set` | Kustomize 用 `--kustomize-*`，Helm 用 `--helm-*` |
| Root 应用漏 `automated` | `destination.namespace=argo-root` 必须 `--sync-policy automated --auto-prune --self-heal` |
| 业务应用错开 `automated` | 生产规范手动 sync，**勿臆加** |
| 多源 `spec.sources` 强行转 CLI | argocd CLI 不支持，**回退到 `kubectl apply -f`** |

## 依赖 (Dependencies)

- `argocd` CLI v2.x — [安装指引](https://argo-cd.readthedocs.io/en/stable/cli_installation/)
- Python >= 3.8（仅 `scripts/argocd_cli_gen` 需要）
- `PyYAML >= 6.0`、`pytest >= 7.0`（仅测试）

## 许可 (License)

MIT — see [LICENSE](./LICENSE).

---

镜像仓库 (Mirrored layout): [`aws-skills`](https://github.com/buhaiqing/aws-skills) ·
[`hcloud-skills`](https://github.com/buhaiqing/hcloud-skills) ·
[`another-aliyun-skills`](https://github.com/buhaiqing/another-aliyun-skills)
