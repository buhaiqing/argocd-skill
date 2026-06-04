# argocd-cli-gen

将 ArgoCD Application YAML 目录批量反向生成为 `argocd app create` 命令的 shell 脚本。

## 运行环境

| 项 | 要求 |
|---|---|
| Python | **>= 3.8**（依赖 `from __future__ import annotations` 字符串化注解 + dataclass） |
| 第三方依赖 | `PyYAML >= 6.0`、`pytest >= 7.0`（仅测试） |
| Shell | `bash >= 3.2`（macOS 默认即可；生成的脚本 shebang `#!/usr/bin/env bash`） |
| 外部 CLI | 仅运行时需要 `argocd`（脚本内通过 `command -v` 校验） |

性能基线：dly 全仓 97 个真实生产 YAML 单线程串行处理 < 1 秒；500 应用规模下仍 < 5 秒，无需并行。

## 设计原则

- **机械化转换**：95% 标准 Kustomize 单源场景纯字段映射，无歧义
- **多源 Helm 收敛到 argocd CLI**：识别 `chart + ref:values` 模式后落到独立 `40_workloads_helm.sh`，每个应用通过 `argocd app create -f helm-apps/<name>.yaml --upsert` 提交（保留原始多源 spec，由 argocd 服务端解析）
- **边界回退**：仅真正不能 CLI 化的多源（多 git path、自定义 plugin）与 `kustomize.patches` 等字段归类到 `99_multisource_fallback.yaml`，由 `kubectl apply` 兜底
- **可灰度**：每个生成脚本配套 `*.dry-run.sh` 副本（追加 `--dry-run -o yaml`），供灰度验证
- **可追溯**：`report.json` + `report.md` 报告每个 YAML 的处理结果
- **认证收敛**：`00_preflight.sh` 通过 `argocd login --auth-token` 建立 session，后续脚本不再重复传 `--server / --auth-token`，与 argoapp 内部脚本一致

## 快速开始

```bash
pip install -r requirements.txt

python -m argocd_cli_gen \
  --input  /path/to/argo-apps/dly/production \
  --output ./out \
  --upsert \
  --emit-dry-run

export ARGOCD_AUTH_TOKEN=eyJ...
export ARGOCD_SERVER=argocd.hd123.com

cd out
bash 00_preflight.sh                       # 完成一次性 login
bash 30_workloads_business.dry-run.sh      # 灰度校验（输出 YAML 不下发）
bash run_all.sh                            # 正式下发
```

## 输出结构

```
out/
├── 00_preflight.sh                # 登录与前置检查
├── 05_infra_roots.sh              # 管理 root 的 root（按需）
├── 10_app_roots.sh                # 聚合 Root 应用
├── 20_workloads_ops.sh            # 运维组件
├── 30_workloads_business.sh       # 业务应用
├── 40_workloads_helm.sh           # 多源 Helm + $values：argocd app create -f helm-apps/*.yaml
├── helm-apps/                     # 每个多源 Helm 应用一份 manifest
│   └── <name>.yaml
├── 99_multisource_fallback.yaml   # CLI 完全不支持的多源 YAML（kubectl apply 兜底；仅在有此类用例时生成）
├── *.dry-run.sh                   # 每个脚本对应的 dry-run 副本
├── run_all.sh                     # 串联入口
├── report.json                    # 机器可读报告
└── report.md                      # 人读报告（含统计表 + 警告列表）
```

## CLI 参数

| flag | 默认值 | 说明 |
|---|---|---|
| `--input PATH` | 必填 | 输入 manifest 目录 |
| `--output PATH` | `./out` | 输出目录 |
| `--upsert` | 启用 | 在生成的 `app create` 中追加 `--upsert` |
| `--emit-dry-run` | 启用 | 生成 `*.dry-run.sh` 副本 |
| `--include GLOB` | `**/*.yaml` | 仅处理匹配文件 |
| `--fail-on LEVEL` | `error` | `warning` \| `error`，遇相应级别终止 |
| `--sleep SECONDS` | 0 | 每条 CLI 命令之间插入 sleep |

## 退出码

- `0` 全部成功
- `1` 有警告（多源回退、未知字段）但脚本可用
- `2` 解析致命错误
- `3` CLI 参数错误

## 模块结构

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

## 质量检查

```bash
pytest tests/ -v                                     # 单元 + 集成测试
shellcheck out/*.sh                                  # 生成脚本静态检查（可选）
python -m argocd_cli_gen --input fixtures/dly ...    # e2e 烟测
bash out/30_workloads_business.dry-run.sh            # 真实 argocd 服务器 dry-run 校验
```

测试 fixtures（`tests/fixtures/`）从内部 argoapp 仓库提取的 4 个层级各一个真实 YAML，外加多源边界案例。
