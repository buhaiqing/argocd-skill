# Agent 协议 (Agent Protocols)

> 本文件包含两部分内容：(1) **行为准则** — 所有 Agent 必须遵守的编码/执行纪律；(2) **会话开机自检协议** — 每个会话处理第一条 argocd 命令前的必检流程。**这两部分原来内嵌在 `SKILL.md` 中，为降低 `SKILL.md` 体积而抽出。Agent 读取 `SKILL.md` 后必须按 `→` 指针跳转到本文件展开执行。** 本文件内容优先级与内嵌时完全一致。

---

## 一、行为准则（执行前必读）— 🚫 强制遵守，不可违背

> 源自 Andrej Karpathy 对 LLM 编程陷阱的观察。**本 skill 所有 Agent 必须无例外遵守，不得以任何理由绕过。** 违反即为缺陷，需立即纠正。

### 准则一：想清楚再写（强制）
**必须**把假设、权衡、备选方案摆在桌面上，不允许悄悄选其一。
- 把假设明确说出来。不确定就问用户。
- 有多种理解，全部摆出来，别自己悄悄选一个。
- 有更简单的做法，直说。该反对的时候反对。
- 哪里不清楚，停下来，说清楚卡在哪，然后问。

### 准则二：简单优先（强制）
**必须**用最少的东西把问题解决，任何多余的东西都是缺陷。
- 不加用户没要求的功能。
- 不给一次性的活儿搭一套通用框架。
- 不加没要求的「灵活性」或「可配置」。
- 不为不可能发生的情况提前操心。
- 交付的东西明显比需要的多，砍到刚好够用，重来。
- 问自己：资深工程师会不会觉得这过度复杂？会的，简化。

### 准则三：外科手术式改动（强制）
**必须**只动你必须动的，只收拾你自己制造的乱。
- 不要去「改进」旁边没让你碰的内容、格式。
- 不要翻新没坏的东西。
- 跟着原本的风格走，哪怕你自己会用别的写法。
- 看到无关的、原本就有的多余内容，提一句就行，别删。
- 只收拾你这次改动产生的多余东西。
- 一条判据：每一处改动，都要能直接追溯到用户的需求。

### 准则四：目标驱动执行（强制）
**必须**先定清楚「做到什么算成功」，再动手，且交付前必须自己验证达标。
- 「把这个 manifest 转换」 → 「输出 `argocd app create` 命令，exit code 0，用户可执行」
- 「帮我查 App 状态」 → 「给出 health/sync 状态，有异常则标注原因」
- 复杂任务，先说简短计划，每步对应一个验证点。
- 成功标准给得够强，自己就能对答案；标准太虚，只能不停来问用户。

### 准则五：Ponytail — 最小代码优先（强制）

> 源自 Ponytail 最佳实践：**最懒的方案只要能工作，就是正确的方案。** 最好的代码是根本没写的代码。

**决策阶梯（遇到任何代码改动时，按顺序检查，stop at the first rung that holds）：**

1. **真的需要它吗？**（YAGNI）没有这个功能能不能跑通？能就删。
2. **项目里已有吗？** 复用现成的 util / helper / 类型，不重写。
3. **标准库能搞定吗？** 用 stdlib，不引入新依赖。
4. **平台原生能力够用吗？** Shell/Python 标准工具能做的事，不用额外脚本。
5. **已装的依赖能解决吗？** 不为几行代码引入新包。
6. **能一行搞定吗？** 一行能解决的，写一行。
7. **最后才动手：** 写最小可工作的代码。

**核心规则：**
- **不加没要求的功能。** 接口只有一个实现就不写接口；一次性的活不搭通用框架。
- **删除优于增加。** 能删就删，能不写就不写。
- **diff 最短的不一定是最好的。** 在错的地方改最小的 diff 是第二个 bug。
- **复杂度上身了再拆。** 在复杂度实际发生之前不预防性抽象。

**代码中的有意简化用 `ponytail:` 注释标记，并说明升级路径：**
```bash
# ponytail: 串行拉 history（并发加到 50 若 throughput 不够）
# ponytail: 全局异常捕获（分类型处理若需细分错误）
```

**输出格式：代码优先，解释最多三行。**
- 先给可执行的命令/代码
- 然后最多三行说明：跳过了什么，什么时候需要补全
- 不要长篇大论，不要设计文档，不要 feature tour
- 用户明确要求的解释、报告、流程说明例外（这些不是 debt）

**什么情况下不要偷懒：**
- 安全边界上的输入校验
- 防止数据丢失的错误处理
- 凭证/Token 屏蔽（永不回显）
- 用户明确要求的功能（不要二次 argue，直接做）

**理解问题永远排在懒之前。** 先完整读懂任务和代码，再爬梯子。跳过理解直接写 diff 的懒，是效率假扮的草率。

---

## 二、会话开机自检协议（跨能力通用，会话首条命令前执行）

每个会话处理第一条 argocd 相关命令前，Agent **必须**按以下顺序执行自检。自检结果应以 `[preflight]` 方式向用户显式标注（凭证屏蔽规则见下文）。

### 0.1 从 `.env` 加载凭证

Agent 收到第一条 argocd 命令时，**按以下优先级检查并加载 `.env` 文件**：

**优先级一：CWD `.env`（最高）**
```bash
# 当前工作目录（CWD）下的 .env，最先检查
if [ -f ".env" ]; then
  set -a; source .env; set +a
fi
```

**优先级二：skill 仓库根目录 `.env`（后备）**
```bash
# skill 仓库根目录（argocd-skill/.env）
ENV_FILE="$(dirname "$(realpath "$0")")/../../.env"
test -f "$ENV_FILE" && set -a; source "$ENV_FILE"; set +a
```

- **CWD `.env` 优先级最高**：用户当前会话目录下的 `.env` 最先被加载（反映用户当前工作上下文）
- **skill 仓库根目录 `.env` 作为后备**：当 CWD 无 `.env` 时回退到此
- **两者都存在时，CWD 覆盖**：同名变量以 CWD 为准（因为是用户当前工作区的配置）
- **`.env.example` 是模板文件**（**不自动加载**），所有变量默认注释；可观测相关变量见其中「可观测与自进化」小节（`ARGOCD_SKILL_RUNTIME_DIR` / `ARGOCD_SKILL_SESSION_HOOK`）
- 注入后即纳入后续认证凭证检测流程

### 0.1.5 `.env` → `~/.config/argocd/config` 同步 + 重新登录

> 前置条件：§0.1.4 的 `.env` 注入已完成，`ARGOCD_SERVER` / `ARGOCD_USERNAME` / `ARGOCD_PASSWORD` 已在 shell 中可用。

`.env` 中的 `ARGOCD_SERVER` / `ARGOCD_USERNAME` / `ARGOCD_PASSWORD` 可能与本地 config 不一致。Agent 在进入凭证检测前，**必须**执行一次 env→config 同步：

**触发条件**：以下任一成立时执行同步：
1. `~/.config/argocd/config` **不存在** → 从头创建
2. `.env` 中 `ARGOCD_SERVER` 的 server 在 config `servers[]` 中**无匹配条目**
3. `.env` 中 `ARGOCD_SERVER` 的 server 在 config 中匹配，但对应 user 的 `auth-token` **为空或过期**
4. `.env` 中的 `ARGOCD_USERNAME` / `ARGOCD_PASSWORD` **与 config 中匹配 user 的凭证不同**

```bash
# 解析 ARGOCD_SERVER（如 https://argocd.example.com/dnet-int）
# → host=argocd.example.com, path=/dnet-int, grpc-web=true, insecure=true
```

**同步步骤（Agent 按顺序执行）：**

**Step 1 — 确保 config 有 server 条目**
```bash
# 检查 servers[] 中是否有匹配 argocd.example.com 的条目
# 没有则写入：
argocd config set-server \
  --server argocd.example.com \
  --grpc-web-root-path /dnet-int \
  --insecure
```

**Step 2 — 判断是否需要重新登录**
```
需要重新登录的条件（任一）：
A. 步骤 1 新增了 server 条目（首次配置）
B. config 中该 server 对应的 user 的 auth-token 为空
C. .env 的 username/password 与 config 不同
D. 上一步 argocd CLI 命令执行时返回认证错误（401/403/过期）
```

**Step 3 — 用 `.env` 凭证重新 login**
```bash
# 不需要拆 ARGOCD_SERVER——argocd login 用 config 的参数
argocd login argocd.example.com \
  --username "$ARGOCD_USERNAME" \
  --password "$ARGOCD_PASSWORD" \
  --grpc-web \
  --grpc-web-root-path /dnet-int \
  --insecure
# → 成功后将新 token 写入 config（argocd CLI 自动处理）
```

**Step 4 — 验证新 token**
```bash
argocd account get-user-info
# 或
python3 -m argocd_api login
```

**为什么必须重新 login：** `argocd login` 会自动将新 token 写入 `~/.config/argocd/config` 的对应 user 条目下。后续所有 `argocd` 命令无需再传 `--auth-token` 或 `--server`，均沿用当前 context。如果 `.env` 中的 `ARGOCD_SERVER` / `ARGOCD_USERNAME` / `ARGOCD_PASSWORD` 较 config 有更新但不重新 login，会导致 config 中的 token 与 server 不匹配，后续命令返回 401/403。

### 0.2 认证凭证检测（4 层优先级）

按最高优先级的可用凭证处理：

| 优先级 | 凭证来源 | 说明 |
|--------|---------|------|
| **1** | `ARGOCD_AUTH_TOKEN`（shell env） | `argocd login --auth-token`，优先级最高 |
| **2** | `~/.config/argocd/config` | 本地已保存的 token（`argocd login` 遗留上下文），**含 `grpc-web-root-path` / `insecure` 等 server 配置**，优先复用 |
| **3** | 上一步 `.env` 中的 `ARGOCD_USERNAME` + `ARGOCD_PASSWORD` | 走 HTTP API `/api/v1/session` 获取 token（见 0.4） |
| **4** | `.env` 中的 `ARGOCD_AUTH_TOKEN` | `.env` 中的 token（不推荐，但作为后备兜底） |

> **凭证屏蔽规则（铁律）：** 任何来源的 `ARGOCD_AUTH_TOKEN`、`ARGOCD_PASSWORD` 在 Agent 输出中一律 mask 为 `***`，**绝不回显**。

#### 登录参数提取（优先级 2 的细化流程）

上述优先级 2（`~/.config/argocd/config`）**不仅是 token 来源，也是 gRPC 登录参数的权威来源**。Agent 在调用 `argocd login` 前，必须按以下顺序解析 config：

```yaml
# ~/.config/argocd/config 典型结构
current-context: argocd.example.com/dnet-int
servers:
- grpc-web: true
  grpc-web-root-path: /dnet-int
  insecure: true
  server: argocd.example.com
```

**解析流程：**

1. 从 `current-context` 确定目标 server 名称（如 `argocd.example.com/dnet-int`）
2. 在 `servers[]` 中找到匹配的 server 条目（匹配 `server` 字段或 `name` 字段）
3. 提取以下参数：
   - `grpc-web`（boolean）：决定 `--grpc-web` flag
   - `grpc-web-root-path`（string）：决定 `--grpc-web-root-path` 参数
   - `insecure`（boolean）：决定 `--insecure` flag

   如果无法从 config 提取（如 config 文件不存在或格式异常），再从 `ARGOCD_SERVER` URL 中解析：
   - URL 的 host 部分作为 server 地址
   - URL 的 path 部分作为 `grpc-web-root-path`（如 `/dnet-int`）

**正确登录示例（从 config 提取参数后）：**
```bash
argocd login argocd.example.com \
  --grpc-web \
  --grpc-web-root-path /dnet-int \
  --insecure
```

**反例（从 ARGOCD_SERVER 直取完整 URL）：**
```bash
# ❌ 错误：ARGOCD_SERVER=https://argocd.example.com/dnet-int
argocd login "$ARGOCD_SERVER"
# → 报错 "Argo CD server address unspecified"
```

> **不要用 `curl` 测 gRPC-web 服务连通性：** ArgoCD server 使用 gRPC-web 协议，`curl` 不支持（即使 `/api/v1/session` 也不会返回正常 JSON，只会得到 `HTTP 000` 或协议错误）。直接走 `argocd login --grpc-web`。

### 0.3 `argocd` CLI 可用性与 `ARGOCD_SERVER`

- `command -v argocd` → 未找到则提示安装（参考 `references/cli-installation.md`），并建议使用与 ArgoCD server 兼容的版本。
- `ARGOCD_SERVER` 是否已设 → 未设则提示用户设置（**不要让用户把 token 直接粘到对话里**，提示设置 env 即可）。

### 0.4 CLI login 回退：HTTP API 模式（Python 编程语言实现）

当 `argocd login` 失败时（常见原因：context path `/dnet-int` 导致 gRPC-web 代理解析失败、insecure 证书、proxy 配置），**不阻塞退出**，而是自动回退到内置的 Python HTTP API 客户端：

```bash
# 一键操作（自动处理 .env 加载 + 认证 + 执行）
python -m argocd_api login                         # 测试认证连通性
python -m argocd_api find-pod <pod-name>            # 查找 Pod
```

auth 优先级自动处理（shell env > `~/.config/argocd/config` > `.env` username+password），无需手动传凭证。

**工具位置：** `scripts/argocd_api/`
**调用入口：** `python -m argocd_api <command> [options]`
**依赖：** `requests`、`PyYAML`（已加入 `scripts/requirements.txt`）

### 0.5 预检通过后状态复用

自检通过的凭证在**同一会话内**默认沿用，复用规则同 `SKILL.md` 2.4（会话内状态复用）。预检话术示例：

```
[preflight] 检测到 argocd CLI 已安装（v3.2.3）
[preflight] 从 .env 加载凭证：ARGOCD_USERNAME=buhaiqing@hd123.com（*** 屏蔽）
[preflight] 从 .env 加载：ARGOCD_SERVER=https://argocd.hd123.com/dnet-int
[preflight] ~/.config/argocd/config 已有有效 token（*** 屏蔽），免登录
[ok] 会话就绪，可执行读写操作
```

如果 CLI login 失败 + HTTP API token 也失败：

```
[preflight] ⚠️ argocd login 失败（context path 解析错误），已回退 HTTP API
[preflight] ⚠️ HTTP API 认证也失败，请检查凭证
[err] 会话不可用，请先 export ARGOCD_AUTH_TOKEN 后重试
```

> **同一协议的两端：** 本协议的 0.1~0.5（LLM 端预检）与 `scripts/argocd_cli_gen/renderer.py` 顶部 `SCRIPT_HEADER` 注释、`PREFLIGHT_SCRIPT` 中的 `00_preflight.sh`（脚本端）是**同一协议的两端**：
>
> - 脚本端：`00_preflight.sh` 在每批 `argocd app create` 之前显式 `argocd login --auth-token $ARGOCD_AUTH_TOKEN --grpc-web` 并 `argocd account get-user-info` 校验。
> - LLM 端：会话开头一次性检查 + 显式标注。会话内后续命令默认 `argocd login` 已完成，不再重复 prompt（与 `00_preflight.sh` 的"建立全局 session"行为一致）。
>
> 措辞必须保持一致——同一份凭证/同一套协议，LLM 端和脚本端的报错应该让用户感觉是同一个工具在用。

### 0.6 运行时 CLI 命令回退协议（Agent 行为准则）

预检通过后的会话中，Agent 生成的**任何** `argocd` CLI 命令执行失败时（context path 解析失败、grpc-web 代理错误、证书/ insecure 问题、连接超时等），**不得仅报错退出**，必须自动回退到 HTTP API 方式重试：

| CLI 操作 | API 等价命令 |
|----------|-------------|
| `argocd app list` | `python -m argocd_api list` |
| `argocd app get <name>` | `python -m argocd_api get <name>` |
| `argocd app sync <name>` | `python -m argocd_api sync <name> [--revision <rev>]` |
| `argocd app refresh <name>` | `python -m argocd_api refresh <name>` |
| `argocd app manifests <name>` | `python -m argocd_api manifests <name>` |
| `argocd app create <name> ...` | `python -m argocd_api create <name> -f <spec.json>`（POST /api/v1/applications） |
| `argocd app rollback <name> <id>` | `python -m argocd_api rollback <name> --id <id>` |
| `argocd app resources <name>` | `python -m argocd_api resource-tree <name>` |
| `argocd app delete-resource <name>` | `python -m argocd_api delete-resource <name>` |
| `argocd app terminate-op <name>` | `python -m argocd_api terminate-op <name>` |
| 其他 `argocd app <sub>` | 先用 `python -m argocd_api --help` 查询是否支持 |

**回退规则（Agent 必须遵守）：**

1. **首先生成 CLI 命令**：Agent 按能力二流程，首先生成 `argocd` CLI 命令。
2. **用户反馈失败 → 自动回退**：用户反馈 CLI 执行失败时，Agent **必须自动输出等价的 API 命令**，无需用户重复描述意图。
3. **结果格式对齐**：API 输出格式应与 CLI 输出对齐（同字段、同排列），让用户感觉是同一个工具。
4. **API 也不支持 → `kubectl` 兜底**：若该操作无等价 API 端点（如 `argocd app logs`），输出 `kubectl` 兜底方案并说明原因。

**3 条铁律（与 `scripts/argocd_cli_gen/renderer.py` 中的脚本端对齐）：**

1. **自动匹配，不等待用户提示**：CLI 失败后 Agent 自行判断等价的 API 命令并直接输出，不需用户说"换 API 试试"。
2. **结果格式对齐**：API 输出格式尽量与 CLI 一致（同字段名、同排序），让用户感觉是同一工具在运作。
3. **API 也不支持 → `kubectl`**：若该操作无对应 API（如 `argocd app logs`），输出 `kubectl` 兜底并说明原因。

**Agent 输出话术示例：**

```
⚠️ CLI 执行失败（context path 解析错误），已回退 HTTP API
→ python -m argocd_api sync my-app
✅ 同步成功：my-app → Synced / Healthy
```

---

## 三、Insight 工具 subprocess 调用注意事项

`argocd_insight` 系列工具（health / compliance / diagnose / snapshot / trend / compare / predict）在被 Agent 通过 subprocess 调用时，有以下行为需要特别注意：

### stderr 进度输出

- 进度信息（如 `[health] 正在检查...`）输出到 **stderr**
- JSON 结果输出到 **stdout**
- 进度信息中可能包含 `[argocd-api] using token...` 字样

### subprocess 调用推荐方式

```python
import subprocess, json

# ✅ 推荐：shell=True + 2>/dev/null + 管道读取
result = subprocess.run(
    f"python3 -m argocd_insight health --json 2>/dev/null",
    shell=True, capture_output=True, text=True, timeout=120,
    cwd=scripts_dir,
)
data = json.loads(result.stdout)

# ✅ 备选：Python subprocess.PIPE（可能因缓冲导致 JSON 解析失败）
# result = subprocess.run(
#     ["python3", "-m", "argocd_insight", "health", "--json"],
#     capture_output=True, text=True, timeout=120, cwd=scripts_dir,
# )
# data = json.loads(result.stdout)
```

### 已知限制

| 工具 | 需要离线文件 | 说明 |
|------|-------------|------|
| health | 否 | 实时查询 ArgoCD API |
| compliance | 否 | 实时查询 |
| diagnose | 否 | 实时查询 |
| snapshot | 否 | 生成快照文件 |
| trend | 否 | 基于快照计算趋势 |
| compare | 否 | 对比两个快照 |
| predict | **是** | 需要离线 JSON 文件作为输入，不同设计于 live-query 工具 |

`predict` 工具需要离线 JSON 文件输入——这是设计差异，不是 bug。