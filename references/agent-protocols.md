# Agent 协议 (Agent Protocols)

## 能力二开机环境检查

在 LLM 会话内处理**第一条** argocd CLI 命令前，agent 必须**先**
做以下检查（不阻塞用户提问，但必须先告诉用户结果）：

0. **从 `.env` 加载凭证**：检查 skill 仓库根目录（`argocd-skill/`）下
   是否有 `.env` 文件，有则用 `set -a; source .env; set +a` 注入当前 env。
   注入后 `.env` 中的 `ARGOCD_USERNAME`、`ARGOCD_PASSWORD`、`ARGOCD_SERVER`
   等变量即可纳入后续检测流程。同名字段以 shell env 优先（`set -a` 不覆盖已设变量）。

1. `command -v argocd` → 未找到则提示安装（参考
   `references/cli-installation.md`），并建议使用与 ArgoCD server
   兼容的版本。

2. 认证凭证检测（按优先级）：
   - **1st** `ARGOCD_AUTH_TOKEN`（shell env）已设 → 直接使用；
   - **2nd** `~/.config/argocd/config` 有匹配 server 的 token → 复用免登录
     （需读取 YAML 提取该 server 的 user auth-token + grpc-web-root-path）；
   - **3rd** 上一步 `.env` 中的 `ARGOCD_USERNAME` + `ARGOCD_PASSWORD` 均已设
     → 使用用户名密码登录；
   - **4th** `.env` 中的 `ARGOCD_AUTH_TOKEN` → 兜底使用；
   - 均未设 → 提示"sync / rollback / delete 等写操作将无法执行"，
     并提示可配置 `.env.example` 中的任一方式。

3. `ARGOCD_SERVER` 是否已设 → 未设则提示并要求用户提供
   （**不要让用户把 token 直接粘到对话里**，提示设置 env 即可）。

4. **CLI login 失败 → HTTP API 回退**：当 `argocd login` 因 context
   path（如 `/dnet-int`）、grpc-web 代理解析失败、insecure 证书等问题报错时，
   不阻塞退出。改为用内置 Python 模块执行操作：
   ```bash
   python -m argocd_api login             # 自动处理凭证（config > .env）
   python -m argocd_api find-pod <name>   # 查找 Pod
   ```
   该模块位于 `scripts/argocd_api/`，自动处理 3 层凭证优先级。

5. 若认证凭证 + server 均齐备，提示"环境就绪，可执行写操作"。

这套"LLM 端预检"与 `scripts/argocd_cli_gen/renderer.py` 顶部
`SCRIPT_HEADER` 注释、`PREFLIGHT_SCRIPT` 中的 `00_preflight.sh`
是**同一协议的两端**：

- 脚本端：`00_preflight.sh` 在每批 `argocd app create` 之前显式
  `argocd login --auth-token $ARGOCD_AUTH_TOKEN --grpc-web` 并
  `argocd account get-user-info` 校验。
- LLM 端：会话开头一次性检查 + 显式标注。会话内后续命令默认
  `argocd login` 已完成，不再重复 prompt（与 `00_preflight.sh`
  的"建立全局 session"行为一致）。

措辞必须保持一致——同一份凭证/同一套协议，LLM 端和脚本端的报错
应该让用户感觉是同一个工具在用。

LLM 端预检话术示例（agent 视角，不是给用户看的代码）：

```
[preflight] 检测到 argocd CLI 已安装（v3.4.2）
[preflight] 从 .env 加载凭证：ARGOCD_USERNAME=buhaiqing@hd123.com（*** 屏蔽）
[preflight] 从 .env 加载：ARGOCD_SERVER=argocd.hd123.com（含 context path）
[preflight] ~/.config/argocd/config 已有有效 token（*** 屏蔽），免登录
[preflight] 或：ARGOCD_AUTH_TOKEN 已设（*** 屏蔽）
[ok] 会话就绪，可执行写操作
```

## CLI 运行时回退协议

预检通过后，Agent 生成的**任何** `argocd` CLI 命令执行失败时，必须自动回退到 `python -m argocd_api` 等价命令重试，**不得仅报错退出**。

**回退流程：**

```
用户描述意图
  ↓
Agent 生成 CLI 命令（argocd app sync my-app --prune）
  ↓
用户执行并反馈失败（context path / grpc-web / 证书 / 超时）
  ↓
Agent 自动输出等价 API 命令
  python -m argocd_api sync my-app
  ↓
API 结果格式化输出（与 CLI 对齐）
```

**回退映射表（Agent 必须熟记）：**

| 用户意图 | CLI 命令 | API 回退命令 |
|----------|---------|-------------|
| 应用列表 | `argocd app list` | `python -m argocd_api list` |
| 应用详情 | `argocd app get <name>` | `python -m argocd_api get <name>` |
| 同步 | `argocd app sync <name>` | `python -m argocd_api sync <name>` |
| 刷新 | `argocd app refresh <name>` | `python -m argocd_api refresh <name>` |
| Manifest | `argocd app manifests <name>` | `python -m argocd_api manifests <name>` |
| 创建应用 | `argocd app create <name>` | `python -m argocd_api create <name> -f <spec.json>` |
| 回滚 | `argocd app rollback <name> <id>` | `python -m argocd_api rollback <name> --id <id>` |
| 资源树 | `argocd app resources <name>` | `python -m argocd_api resource-tree <name>` |
| 删除资源 | `argocd app delete-resource <name>` | `python -m argocd_api delete-resource <name>` |
| 终止操作 | `argocd app terminate-op <name>` | `python -m argocd_api terminate-op <name>` |

**3 条铁律：**

1. **自动匹配，不等待用户提示**：CLI 失败后 Agent 自行判断等价的 API 命令并直接输出，不需用户说"换 API 试试"。
2. **结果格式对齐**：API 输出格式尽量与 CLI 一致（同字段名、同排序），让用户感觉是同一工具在运作。
3. **API 也不支持 → `kubectl`**：若该操作无对应 API（如 `argocd app logs`），输出 `kubectl` 兜底并说明原因。

**话术模板：**

```
⚠️ CLI 执行失败（context path 解析错误），已回退 HTTP API
→ python -m argocd_api sync my-app
✅ 同步成功：my-app → Synced / Healthy
```
