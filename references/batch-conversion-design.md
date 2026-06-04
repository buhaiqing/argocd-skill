# 批量目录转换工具设计文档

> 子能力 3.2 "目录批量转换" 的实现设计。
> 实现位于 `scripts/argocd_cli_gen/`，使用说明见 `scripts/README.md`。

## 1. 需求背景

### 1.1 问题陈述

用户场景："给我一个包含 ArgoCD Application manifest 的目录（类似 `argo-apps/dly/production/`），反向生成出 `argocd app create` CLI 指令序列，保存到 shell 脚本文件中。"

典型场景：
- ArgoCD 集群迁移（A 集群导出 → B 集群导入）
- 灾备/重建（git manifest 还在，集群状态丢失）
- 历史项目从 `kubectl apply YAML` 切换到"基于 CLI 的 IaC 流程"
- 给 CI/CD 灰度验证脚本提供基线

### 1.2 现有能力缺口

在本方案前，argocd-skill 仅支持：
- 能力一：CLI 安装
- 能力二：自然语言生成 CLI 命令（每次一条）
- 能力三 · 子能力 3.1：单 YAML 内联转换（每次一个文件）

5+ 个 YAML 时人工逐个粘贴效率太低；97 个真实业务 YAML 完全不可行。

## 2. 可行性结论

**结论：完全可行**，95% 标准 Kustomize 单源场景可机械化转换、5% 边界场景明确回退到 `kubectl apply -f`。

### 2.1 可行性分维度评估

| 维度 | 评估 | 依据 |
|---|---|---|
| 数据可行性 | ✅ 强 | argoapp 目录结构标准，层级清晰 |
| 字段映射可行性 | ✅ 强 | 已有 P0/P1/P2 全字段映射表（kustomize-mapping.md） |
| 输出脚本可行性 | ✅ 强 | shell 是纯文本拼接 |
| 边界处置可行性 | ⚠️ 中 | 多源/patches 占 ~5%，必须明确回退 |
| 语义等价性验证 | ⚠️ 中 | 部分字段省略/格式差异需 dry-run 校验兜底 |
| 工程实施成本 | ✅ 低-中 | ~1000 行 Python（业务 + 测试） |

### 2.2 不可机械转换的边界

| 边界 | 真实占比 | 处置策略 |
|---|---|---|
| `spec.sources` 多源 Helm + `$values` | 3.1% | argocd CLI 不支持，整文件回退到 YAML |
| `spec.source.kustomize.patches` | 0%（dly 样本无） | 同上 |
| `spec.source.kustomize.components` | 0%（dly 样本无） | 同上 |
| `automated: {}` 空对象简写 | 1+% | CLI 用 `--sync-policy automated` 不带 prune/selfHeal，语义等价 |
| `metadata.namespace` 省略 | 3% | CLI 默认值兜底，报告中标注 |
| YAML 注释 / 键顺序 | 100% | 必然丢失，脚本头部以 `# source: <path>` 锚定追溯 |

## 3. 关键决策记录

需求确认阶段通过结构化提问确定的 4 个关键决策：

| 决策维度 | 选择 | 理由 |
|---|---|---|
| 实现路线 | **C. 混合方案** | Python 工具处理 95% 标准；Agent 处理边界判断与异常诊断 |
| 幂等策略 | **A. `--upsert`** | argocd 原生支持，最简洁；与 argoapp 内部脚本 `gen_argo_app_manifest.py` 语义一致 |
| 校验环节 | **A. dry-run 副本** | 每个脚本配套 `*.dry-run.sh`，可灰度验证不污染集群 |
| 首版范围 | **A. 仅 Kustomize 单源** | 覆盖 97% 场景；多源走 `kubectl apply` 回退 |

另外四个工程实施决策：

| 维度 | 选择 |
|---|---|
| 工具位置 | `skills/argocd-skill/scripts/`（与 argoapp 项目 `script/` 命名一致） |
| 配置策略 | 全部通过 CLI flag 覆写（无 profile.yaml） |
| 报告格式 | JSON（机器可读） + Markdown（人读） |
| 实施路径 | 直接 8 步递进，每步带单元/集成测试 |

## 4. 整体架构

### 4.1 三层分工

```
┌────────────────────────────────────────────────────────────────┐
│  Agent 编排层 (SKILL.md + 对话)                                │
│   - 识别输入：单 YAML 内联 vs 目录批量                         │
│   - 调用工具：python -m argocd_cli_gen ...                     │
│   - 解读报告：把 report.md 摘要给用户                          │
│   - 异常诊断：执行失败时 argocd app get 调试                   │
└────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  Python 工具层 (argocd_cli_gen/*.py)                           │
│   - YAML 解析、层级判定、字段映射                              │
│   - shell 脚本渲染、dry-run 副本                               │
│   - 多源回退收集、报告生成                                     │
│   - 纯函数式，无副作用，易测试                                 │
└────────────────────────────────────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────────────┐
│  输出层 (out/)                                                 │
│   - 4 个分层 shell 脚本 + 4 个 dry-run 副本                    │
│   - 1 个 preflight 脚本 + 1 个 run_all 串联入口                │
│   - 1 个多源回退 YAML（按需）                                  │
│   - report.json + report.md                                    │
└────────────────────────────────────────────────────────────────┘
```

### 4.2 模块图

```
argocd_cli_gen/
├── __init__.py        版本号
├── __main__.py        python -m 入口
├── cli.py             argparse + 端到端编排（main 函数）
├── parser.py          YAML 加载（含多文档兼容）+ 层级判定
├── mapper.py          字段 → CLI flag 映射 + 命名规范处理
├── renderer.py        shell 模板渲染 + dry-run 副本生成
├── fallback.py        多源/不支持字段收集 + 回退 YAML 输出
└── report.py          报告构建 + JSON/MD 序列化
```

依赖关系（单向）：

```
cli.py
  ├── parser.py  (yaml + 层级判定)
  ├── renderer.py
  │     └── mapper.py
  ├── fallback.py
  │     └── parser.LoadedManifest
  └── report.py
        ├── fallback.FallbackBundle
        ├── mapper.MappedApp
        └── parser.LoadedManifest
```

无循环依赖。

## 5. 数据流

### 5.1 端到端流程

```
用户目录 (argo-apps/dly/production/)
      │
      ▼
parser.load_directory(input)
      │  扫描 **/*.yaml，递归
      │  多文档 YAML 自动取首个 Application
      │  非 Application（如 ConfigMap）跳过
      ▼
list[LoadedManifest]   ← 每个含 manifest + Tier + reason
      │
      ├──────────────────┬─────────────────┐
      ▼                  ▼                 ▼
renderer.render_all   fallback.collect   report.build
  按 Tier 分桶          挑出 MULTI_SOURCE   汇总统计
  逐个 map_single_source  与 patches        + 警告列表
  生成 shell 块         整文件回退         + 后续操作指引
      │                   │                    │
      ▼                   ▼                    ▼
RenderResult          FallbackBundle         Report
      │                   │                    │
      ▼                   ▼                    ▼
write_results()       write_fallback()       write_report()
  → 多个 .sh +          → 99_multisource_     → report.json
    .dry-run.sh           fallback.yaml         + report.md
```

### 5.2 输出文件结构

按依赖顺序编号（数字前缀决定执行顺序）：

| 文件 | 来源 Tier | 说明 |
|---|---|---|
| `00_preflight.sh` | - | 校验 argocd CLI + 通过 `argocd login --auth-token` 建立全局 session |
| `05_infra_roots.sh` | `INFRA_ROOT` | projects/repos/initns 自启动 root |
| `10_app_roots.sh` | `ROOT_APP` | 聚合 root（App-of-Apps 入口） |
| `20_workloads_ops.sh` | `OPS_APP` | 运维组件 |
| `30_workloads_business.sh` | `BUSINESS_APP` | 业务应用 |
| `*.dry-run.sh` | - | 每个上述脚本对应的 `--dry-run -o yaml` 副本 |
| `99_multisource_fallback.yaml` | `MULTI_SOURCE` | kubectl 兜底 |
| `run_all.sh` | - | 串联所有可用脚本 |
| `report.json` / `report.md` | - | 转换报告 |

依赖语义：**infra → app_root → workload**，工具运行时严格保证此顺序。

## 6. 关键算法

### 6.1 层级判定决策树（parser.detect_tier）

```python
if not is_argocd_application(manifest):
    return UNKNOWN, "not_argocd_application"

if spec.sources:                       # 含多源字段
    return MULTI_SOURCE, "has_spec_sources"

if dest.namespace == "argo-root":
    if metadata.finalizers:            # 含 finalizer 标记
        return ROOT_APP, "argo-root + finalizers"
    else:                              # 无 finalizer，更精简
        return INFRA_ROOT, "argo-root + no finalizers"

if revision contains ops keyword:      # k8s_ops / k8s-ops
    return OPS_APP, "revision is ops"

if dest.namespace in OPS_NAMESPACE_KEYWORDS:  # ops/loki/kube-system/...
    return OPS_APP, "dest_namespace is ops"

return BUSINESS_APP, "default"
```

判定规则源自对 argoapp 仓库 100 个真实 YAML 的频次统计（见 `kustomize-mapping.md`）。

### 6.2 字段 → CLI flag 映射（mapper）

按 5 个分组实现，每组一个独立函数，纯函数式：

| 函数 | 输出字段范围 |
|---|---|
| `map_metadata` | name（位置参数）/ namespace / finalizers / labels / annotations |
| `map_source` | repoURL / targetRevision / path / kustomize.* |
| `map_destination` | server / namespace / name |
| `map_sync_policy` | automated.* / syncOptions / retry.* |
| `map_misc` | project / revisionHistoryLimit |

入口：`map_single_source(manifest) → MappedApp`，组合上述五组并返回带 warnings 的结果。

### 6.3 命名规范处理

`mapper.safe_app_name(raw)`：将 `metadata.name` 中的 `_` 替换为 `-`，因为 argocd 不允许应用名含下划线。

不替换的字段：
- `--revision`（git 分支名如 `k8s_mas` / `dly_prd` 必须保留原样）
- `--path`（路径中的下划线属于目录名一部分）

### 6.4 dry-run 副本生成

`renderer._to_dry_run_block(block)`：把每个 `argocd app create ...` 块的命令头替换为 `argocd app create --dry-run -o yaml ...`，其他 flags 保持不变。

dry-run 副本与主脚本同步生成，文件名 `xxx.dry-run.sh`。

## 7. 边界处置策略

### 7.1 多源（`spec.sources`）

- 工具行为：
  1. `parser.detect_tier` 标记为 `MULTI_SOURCE`，**不进入 renderer**
  2. `fallback.collect` 把原 YAML 文档整篇收集，按 `---` 拼到 `99_multisource_fallback.yaml`
  3. `report` 中以 `severity=warning` 记录
- 用户操作：执行完主脚本后追加 `kubectl -n argocd apply -f 99_multisource_fallback.yaml`

### 7.2 不支持的 Kustomize 字段（patches / components）

- 工具行为：与多源同样**整文件回退**到 `99_multisource_fallback.yaml`，**不进入主脚本**（避免与 fallback YAML 重复创建）
- 触发条件：`spec.source.kustomize.patches` 或 `kustomize.components` 存在
- **实现关键**：`fallback.reasons_for(lm)` 是 renderer 和 fallback 共用的省判定源。`renderer.render_all` 在分桶时调用此函数，命中则整体跳过；`fallback.collect` 也调用同一函数收集到 YAML 回退包——**保证两边判定 100% 同源**

### 7.3 多文档 YAML（如 `initns/namespace.yaml`）

- 真实场景：`initns/` 目录下文件常含 `Namespace + ResourceQuota + LimitRange` 多文档
- 工具行为：`parser.load_manifest` 用 `yaml.safe_load_all` 兼容；遍历每个文档，**取首个 `kind=Application` 的文档**；其他文档跳过
- 兜底：若全部为非 Application，整文件跳过且不报错

### 7.4 字段省略语义差异

- `metadata.namespace` 省略：CLI 默认补 `argocd`
- `automated: {}` 空对象：CLI 输出 `--sync-policy automated`（不带 prune/selfHeal）
- `destination.name: ''` 空字符串：CLI 完全省略 `--dest-name`

这些差异通过两层保障可控：
1. 工具内 mapper.py 的代码注释 + 测试用例 `test_destination_skips_empty_name` 等
2. dry-run 副本可执行后用 `argocd app get -o yaml` 与原 YAML diff 校验

### 7.5 未知字段告警

- **实现方式**：`mapper._detect_unknown_fields(manifest)` 按白名单扫描 6 个已映射"层"：
  - `metadata` / `spec` / `spec.source` / `spec.source.kustomize` / `spec.destination` / `spec.syncPolicy`
  - 每层的已识别字段集合（如 `KNOWN_SOURCE_FIELDS`）与 `references/kustomize-mapping.md` 数据同源
- **工具行为**：遇 mapping 表外的字段返回 `UnsupportedField`，severity=`info`，写入 `report.warnings`
- **默认策略**：**跳过该字段** + 写入 `report.json` / `report.md` 警告明细
- **严格模式**：`--fail-on warning` 时仍以非零退出码终止
- **覆盖率验证**：在 argoapp 真实仓库 100 个 YAML 上跑零未知字段告警，证明白名单覆盖完整

## 8. I/O 契约

### 8.1 CLI 参数

```bash
python -m argocd_cli_gen \
  --input  PATH       # 必填，输入目录
  --output PATH       # 默认 ./out
  --upsert / --no-upsert         # 默认开启
  --emit-dry-run / --no-emit-dry-run  # 默认开启
  --include "**/*.yaml"          # glob 过滤
  --sleep 0.0                    # 命令间隔
  --fail-on error|warning        # 默认 error
```

### 8.2 退出码（受 `--fail-on` 控制）

| 码 | 含义 | 触发条件 |
|---|---|---|
| 0 | 全部成功 / 仅有 warning 但 `--fail-on=error`（默认） | 无 error；warning（如 multi_source 回退）不强制非零 |
| 1 | 有 warning 且 `--fail-on=warning` | 存在 multi_source / patches 回退、CI 想以严格模式守门时使用 |
| 2 | 工具异常或解析致命错误 | YAMLError、has_error 级别的警告（保留给未来扩展） |
| 3 | CLI 参数错误 | input 目录不存在、sleep 为负等 |

**设计权衡：**
- 默认 `--fail-on=error` 让"有 fallback 但脚本可用"的常见场景**不打断 shell pipeline**，便于嵌入自动化流水线
- CI 守门需要严格语义时显式传 `--fail-on=warning`，遇 fallback 即非零退出
- 与 `report.json` / `report.md` 的语义解耦：报告永远会列出所有 warning，退出码只决定 shell 是否中断

### 8.3 报告 JSON 结构

```json
{
  "timestamp": "2026-05-26T07:41:32Z",
  "input_dir": "/path/to/manifests",
  "output_dir": "/path/to/out",
  "total": 100,
  "by_tier": {
    "infra_root": 3,
    "root_app": 5,
    "business_app": 74,
    "ops_app": 15,
    "multi_source": 3
  },
  "converted": 97,
  "fallback_to_yaml": 3,
  "failed": 0,
  "warnings": [
    {
      "file": "...",
      "name": "loki",
      "severity": "warning",
      "reason": "multi_source",
      "field_path": "multi_source",
      "suggestion": "使用 kubectl apply -f 99_multisource_fallback.yaml"
    }
  ]
}
```

## 9. 测试策略

### 9.1 测试覆盖（47 用例）

| 测试文件 | 用例数 | 覆盖范围 |
|---|---|---|
| `test_mapper.py` | 14 | 每个 P0/P1 字段映射 + 命名规范 + 业务/Root e2e |
| `test_parser.py` | 8 | 6 个层级判定分支 + 多文档加载 + 非 Application 跳过 |
| `test_renderer.py` | 9 | 三层脚本生成 + dry-run 副本 + run_all 仅含可用层 + **P0 回归（patches/multi_source 不进主脚本）** |
| `test_fallback_and_report.py` | 6 | 多源收集 / patches 收集 / JSON+MD 输出 |
| `test_cli.py` | 10 | argparse 解析 + 端到端 + 各退出码 |

### 9.2 测试夹具策略

- **代码内嵌 YAML 字符串**：mapper/parser/renderer 测试直接在 .py 中写多行 YAML，无外部依赖
- **临时目录 fixture**：renderer/fallback/cli 测试用 pytest `tmp_path` fixture 验证文件落盘
- **真实数据回归**：手动用 argoapp 仓库做 e2e 比对（详见 §10）

### 9.3 真实数据 e2e 验证

每次 release 前执行：

```bash
rm -rf /tmp/argocd-out-full
python -m argocd_cli_gen --input /path/to/argoapp --output /tmp/argocd-out-full
python -c "import json; d=json.load(open('/tmp/argocd-out-full/report.json')); print(d['by_tier'])"
```

预期产出（dly 主分支基线）：

```python
{
    "infra_root": 3,
    "root_app": 5,
    "business_app": 74,
    "ops_app": 15,
    "multi_source": 3,
}  # total=100, converted=97, fallback=3
```

## 10. 实际验证结果

### 10.1 argoapp 全仓 e2e（基线）

| 指标 | 数值 |
|---|---|
| 输入 Application 总数 | 100 |
| 成功转换 CLI | 97 |
| YAML 回退 | 3（loki / tempo / rabbitmq-cluster-operator） |
| 解析失败 | 0 |
| 退出码 | 1（fallback 存在） |

### 10.2 分层正确性核对

| Tier | 工具输出 | 人工预期 | 一致性 |
|---|---|---|---|
| infra_root | 3 | 3 (projects/repos/initns) | ✅ |
| root_app | 5 | 5 (5 个 dly-production-k8s_*) | ✅ |
| business_app | 74 | 74 (k8s_dly + k8s_mas + k8s_oas + k8s_pluto) | ✅ |
| ops_app | 15 | 15 (k8s_ops 减去 3 个多源) | ✅ |
| multi_source | 3 | 3 (loki/tempo/rabbitmq-operator) | ✅ |

### 10.3 字段映射抽样核对

对 `dl1h-prometheus.yaml`、`production-mas-user-service.yaml`、`dly-production-k8s_ops.yaml`、`projects.yaml` 四类典型 YAML 的输出做人工逐字段比对，**100% 与 `kustomize-examples.md` 中的预期输出一致**。

## 11. 未来扩展点

### 11.1 暂未实现，列入 backlog

| 扩展项 | 触发条件 | 实现方向 |
|---|---|---|
| 多源 Helm + values CLI 支持 | argocd CLI 增加 `--source` 多次重复参数语义 | renderer 增加 multi_source 渲染分支 |
| 增量同步（diff 现有 argocd state） | 用户用 `--diff-only` flag | cli.py 增加 `argocd app get` 反查 → 输出 diff |
| 多项目并发执行 | 用户给一个 monorepo 含多 project | renderer 支持 by-project 分组 |
| Helm 单源（非多源） | 用户 manifest 中只用 `spec.source.helm` | mapper.py 增加 `--helm-set/--helm-values` 分支 |
| 反向校验（与原 YAML diff） | 用户执行后想验证一致性 | 新增 `argocd-cli-gen verify` 子命令 |

### 11.2 已知不会实现

| 项目 | 理由 |
|---|---|
| 反向修改 source YAML | 工具定位为只读转换，不修改输入 |
| 在工具内部直接调用 argocd CLI | 工具仅负责"生成脚本"，认证由生成的 `00_preflight.sh` 在执行阶段完成（`argocd login --auth-token`） |
| 自动执行生成的脚本 | 解耦"生成"与"执行"，让用户灰度可控 |

## 12. 与其他参考文档的关系

| 文档 | 角色 |
|---|---|
| `references/kustomize-mapping.md` | **数据源**：字段→flag 映射表，mapper.py 与其同源 |
| `references/kustomize-examples.md` | **测试基线**：7 个示例的预期 CLI 输出，工具回归测试参考 |
| `scripts/README.md` | **使用手册**：面向最终用户的 CLI 调用指南 |
| 本文档 | **设计参考**：面向工具维护者的实现细节 |

四份文档形成完整闭环：用户文档 → 数据规范 → 示例验证 → 实现设计。
