# scripts/ — ArgoCD Python 工具集

`scripts/` 目录包含 5 个独立 Python 工具包，均可通过 `python -m <tool>` 调用。

## 运行环境

| 项 | 要求 |
|---|---|
| Python | **>= 3.10** |
| 第三方依赖 | `PyYAML >= 6.0`、`pytest >= 7.0`（仅测试） |
| 外部 CLI | `argocd`（argocd_cli_gen / argocd_api 运行时）、`git`（repo_health 运行时） |

```bash
pip install -r requirements.txt
```

## 工具一览

| 工具 | 调用方式 | 用途 |
|------|---------|------|
| **argocd_cli_gen** | `python -m argocd_cli_gen` | YAML 目录 → `argocd app create` 批量生成 shell 脚本 |
| **argocd_api** | `python -m argocd_api` | ArgoCD HTTP API CLI（绕过 argocd CLI bug） |
| **argocd_insight** | `python -m argocd_insight` | 诊断分析 / 漂移检测 / 健康评估 / 成本估算 / 合规检查 |
| **argocd_deploy_stats** | `python -m argocd_deploy_stats.stats` | 部署频率统计 + OOS 分析 |
| **ulw** | `python -m ulw` | ArgoCD 超级工作负载操作（通过 HTTP API 直接操作 Pod） |

## 认证

所有需要连接 ArgoCD 的工具共享统一认证方式（优先级从高到低）：

1. `ARGOCD_AUTH_TOKEN`（推荐，自动化场景）
2. `ARGOCD_USERNAME` + `ARGOCD_PASSWORD`
3. `~/.config/argocd/config`（`argocd login` 写入）

支持 `.env` 文件自动检测（从 skill 根目录或当前目录加载）。

---

## 1. argocd_cli_gen — 批量转换工具

将 ArgoCD Application YAML 目录批量反向生成为 `argocd app create` 命令的 shell 脚本。

### 快速开始

```bash
python -m argocd_cli_gen \
  --input  /path/to/argo-apps/dly/production \
  --output ./out \
  --upsert \
  --emit-dry-run

export ARGOCD_AUTH_TOKEN=eyJ...
export ARGOCD_SERVER=argocd.hd123.com

cd out
bash 00_preflight.sh                       # 完成一次性 login
bash 30_workloads_business.dry-run.sh      # 灰度校验
bash run_all.sh                            # 正式下发
```

### 输出结构

```
out/
├── 00_preflight.sh                # 登录与前置检查
├── 05_infra_roots.sh              # 管理 root 的 root（按需）
├── 10_app_roots.sh                # 聚合 Root 应用
├── 20_workloads_ops.sh            # 运维组件
├── 30_workloads_business.sh       # 业务应用
├── 40_workloads_helm.sh           # 多源 Helm + $values
├── helm-apps/                     # 每个多源 Helm 应用一份 manifest
├── 99_multisource_fallback.yaml   # CLI 不支持的多源 YAML（kubectl apply 兜底）
├── *.dry-run.sh                   # 每个脚本对应的 dry-run 副本
├── run_all.sh                     # 串联入口
├── report.json                    # 机器可读报告
└── report.md                      # 人读报告
```

### CLI 参数

| flag | 默认值 | 说明 |
|---|---|---|
| `--input PATH` | 必填 | 输入 manifest 目录 |
| `--output PATH` | `./out` | 输出目录 |
| `--upsert` | 启用 | 在生成的 `app create` 中追加 `--upsert` |
| `--emit-dry-run` | 启用 | 生成 `*.dry-run.sh` 副本 |
| `--include GLOB` | `**/*.yaml` | 仅处理匹配文件 |
| `--fail-on LEVEL` | `error` | `warning` \| `error`，遇相应级别终止 |
| `--sleep SECONDS` | 0 | 每条 CLI 命令之间插入 sleep |

### 退出码

- `0` 全部成功
- `1` 有警告（多源回退、未知字段）但脚本可用
- `2` 解析致命错误
- `3` CLI 参数错误

### 模块结构

```
argocd_cli_gen/
├── __init__.py
├── __main__.py            # python -m argocd_cli_gen 入口
├── cli.py                 # argparse 与编排
├── parser.py              # YAML 加载 + 层级判定
├── mapper.py              # 字段→flag 映射表（与 references/kustomize-mapping.md 同源）
├── renderer.py            # shell 脚本模板渲染
├── fallback.py            # 多源/不支持字段收集
└── report.py              # JSON/MD 报告生成
```

---

## 2. argocd_api — HTTP API CLI

通过 ArgoCD `/api/v1` 直接操作，绕过 argocd CLI 的路径处理 bug。

```bash
python -m argocd_api list                              # 列出所有 App
python -m argocd_api get <app>                         # 查看 App 详情
python -m argocd_api resource-tree <app>               # 查看资源树（Pod/Service/Ingress）
python -m argocd_api resource <app> <kind> <name> --ns NS  # 获取单个资源
python -m argocd_api find-pod <pod-name>               # 查找 Pod 所属 App
python -m argocd_api delete-resource <app> <kind> <name> --ns NS  # 删除资源
python -m argocd_api login                              # 测试认证
python -m argocd_api sync <app>                        # 触发同步
python -m argocd_api refresh <app>                     # 刷新 App 状态
python -m argocd_api manifests <app>                   # 获取渲染后的 manifests
python -m argocd_api create -f app.json                # 创建 App
python -m argocd_api delete <app>                      # 删除 App
python -m argocd_api rollback <app> --id N             # 回滚
python -m argocd_api whoami                             # 当前账号信息
python -m argocd_api projects                           # 列出 AppProjects
python -m argocd_api clusters                           # 列出集群
python -m argocd_api repos                              # 列出仓库
```

通用选项：`--json` 输出原始 JSON，`--env-file PATH` 指定 .env 文件。

### 模块结构

```
argocd_api/
├── __init__.py
├── __main__.py            # 入口
└── client.py              # ArgoCDClient HTTP 封装
```

---

## 3. argocd_insight — 诊断分析套件

多维度 ArgoCD 运维分析工具，支持 diagnose / drift / health / cost / compliance / repo_health / batch / autofix / impact / scaffold 等子命令。

```bash
python -m argocd_insight diagnose [--app NAME]          # 问题 App 诊断
python -m argocd_insight drift [--project NAME]         # 漂移检测
python -m argocd_insight health                         # 健康评估
python -m argocd_insight cost [--days N]                # 成本估算
python -m argocd_insight compliance [--severity LEVEL]  # 配置合规检查
python -m argocd_insight repo_health                    # Git 源健康检查
python -m argocd_insight batch --action sync|rollback|refresh  # 批量操作
python -m argocd_insight autofix                        # 批量自动修复
python -m argocd_insight impact --app NAME              # 变更影响分析
python -m argocd_insight scaffold --tier TIER           # 配置模板生成
```

### 模块结构

```
argocd_insight/
├── __init__.py
├── __main__.py            # 入口
├── cli.py                 # 子命令分发
├── diagnose.py            # 问题诊断
├── drift.py               # 漂移检测
├── health.py              # 健康评估
├── cost.py                # 成本估算
├── compliance.py          # 配置合规检查
├── repo_health.py         # Git 源健康检查
├── batch.py               # 批量操作（sync/rollback/refresh）
├── autofix.py             # 批量自动修复
├── impact.py              # 变更影响分析
├── scaffold.py            # 配置模板（4-tier 模型）
├── trace/                 # 轨迹记录（session/writer/@traced）
├── analyzer/              # 统计聚合 + 瓶颈识别 + 错误归因
├── insight_engine/        # 经验提取 + 推断链生成
├── evolver/               # 风险分级 + 写回执行器
├── skillopt/              # SDK 适配 + 意图识别 + 参数推荐
└── trigger/               # 离线触发（cron/threshold/session_end）
```

---

## 4. argocd_deploy_stats — 部署统计

### 部署频率统计

```bash
python -m argocd_deploy_stats.stats                # 全量统计
python -m argocd_deploy_stats.stats --days 7       # 最近 7 天
python -m argocd_deploy_stats.stats --project default
python -m argocd_deploy_stats.stats --output json
python -m argocd_deploy_stats.stats --concurrency 8  # 并发数（默认 8）
python -m argocd_deploy_stats.stats --limit 50       # 最多统计 N 个 App
```

### OOS（Out-of-Sync）分析

```bash
python -m argocd_deploy_stats.oos_analyzer           # 分析 OutOfSync 原因
python -m argocd_deploy_stats.oos_analyzer --project default
python -m argocd_deploy_stats.oos_analyzer --output json
```

### 模块结构

```
argocd_deploy_stats/
├── __init__.py
├── __main__.py            # 入口
├── stats.py               # 部署频率统计
└── oos_analyzer.py        # OutOfSync 分析
```

---

## 5. ulw — 超级工作负载操作

通过 ArgoCD HTTP API 直接操作 Pod（绕过 argocd CLI 的路径处理 bug），用于排查和管理"孤儿" Pod。

```bash
python -m ulw find-pod   <pod-name> [--env-file PATH]  # 查找 Pod 所属 App
python -m ulw delete-pod <pod-name> [--env-file PATH]  # 通过 App API 删除 Pod
```

### 模块结构

```
ulw/
├── __init__.py
├── __main__.py            # 入口
├── client.py              # ArgoCDClient HTTP 封装（复用 argocd_api.client）
├── commands.py            # find_pod / delete_pod 业务逻辑
└── ulw.py                 # CLI 入口（argparse）
```

---

## 质量检查

```bash
cd scripts/
pytest tests/ -v                          # 全量测试
pytest tests/test_stats.py -v             # 部署统计测试
pytest tests/test_repo_health.py -v       # Git 源健康测试
pytest tests/test_compliance.py -v        # 合规检查测试
```

测试 fixtures（`tests/fixtures/`）从内部 argoapp 仓库提取的 4 个层级各一个真实 YAML，外加多源边界案例。
