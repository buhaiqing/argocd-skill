# CLI 安装实现逻辑

## 背景

ArgoCD CLI 由 Golang 开发，编译为独立的单文件二进制，不依赖运行时和动态链接库。GitHub Release 页面统一提供各平台的可执行文件。

安装本质就是三步：下载 → chmod +x → mv 到 PATH。

## 平台检测

使用 `uname` 命令检测当前环境：

```bash
OS=$(uname -s | tr '[:upper:]' '[:lower:]')   # linux / darwin
ARCH=$(uname -m)                                 # x86_64 / aarch64
```

arch 映射规则：
- `x86_64` → `amd64`
- `aarch64` → `arm64`

## 版本确定

**不指定版本（安装最新版）：**

```bash
VERSION=$(curl -s "https://api.github.com/repos/argoproj/argo-cd/releases/latest" \
  | grep '"tag_name"' | sed -E 's/.*"([^"]+)".*/\1/')
```

**指定版本：**

```bash
# 用户输入 3.4.2 → 自动补全 v3.4.2
VERSION=${USER_INPUT#v}    # 去掉可能的 v 前缀
VERSION="v${VERSION}"      # 统一加上 v 前缀
```

## URL 拼接

```
https://github.com/argoproj/argo-cd/releases/download/${VERSION}/argocd-${OS}-${ARCH}
```

完整平台对应文件名：

| OS | ARCH | 文件名 |
|----|------|--------|
| Linux | amd64 | argocd-linux-amd64 |
| Linux | arm64 | argocd-linux-arm64 |
| Darwin (macOS) | amd64 | argocd-darwin-amd64 |
| Darwin (macOS) | arm64 | argocd-darwin-arm64 |
| Windows | amd64 | argocd-windows-amd64.exe |

## 安装步骤

**Linux / macOS：**

```bash
curl -sSL -o argocd "https://github.com/argoproj/argo-cd/releases/download/${VERSION}/argocd-${OS}-${ARCH}"
chmod +x argocd
sudo install -m 555 argocd /usr/local/bin/argocd
rm argocd
```

**Docker 容器（无 sudo 环境）：**

容器镜像通常已有 /usr/local/bin 写权限：

```bash
curl -sSL -o /usr/local/bin/argocd "https://github.com/argoproj/argo-cd/releases/download/${VERSION}/argocd-${OS}-${ARCH}"
chmod +x /usr/local/bin/argocd
```

**Windows (PowerShell)：**

```powershell
$version = (Invoke-RestMethod https://api.github.com/repos/argoproj/argo-cd/releases/latest).tag_name
Invoke-WebRequest -Uri "https://github.com/argoproj/argo-cd/releases/download/$version/argocd-windows-amd64.exe" -OutFile "argocd.exe"
```

## 安装后验证

```bash
argocd version --client
```

应输出类似：

```
argocd: v3.4.2+abc1234
  BuildDate: 2025-05-12T21:20:33Z
  GitCommit: abc1234...
  Platform: linux/amd64
```

## 边界条件处理

| 场景 | 处理方式 |
|------|---------|
| GitHub 无法访问 | 输出离线安装指引：手动下载指定平台的 argocd-{os}-{arch} 文件，通过 SCP 或 volume 挂载传入 |
| curl 不存在 | 优先检测 curl，不存在则用 wget：`wget -O argocd {URL}` |
| wget 也不存在 | 报错并提示安装 curl 或 wget |
| 目标目录无写权限 | 先尝试 `sudo install`；失败后提示 `~/.local/bin`（需在 PATH 中） |
| 已安装同版本 | 运行 `argocd version --client` 对比，版本一致则跳过 |
| 指定版本不存在 | `curl -f` 返回 404，打印错误并列出最近几个 release 版本 |
| 下载中断 | `curl` 默认不续传，建议加 `--retry 3 --retry-delay 5` 参数 |

## 离线安装指引

当无法访问 GitHub 时输出：

```
无法从 GitHub 下载 argocd CLI。

离线安装步骤：
1. 在可联网机器下载对应平台的 CLI 二进制：
   https://github.com/argoproj/argo-cd/releases/latest
   选择 argocd-{platform}-{arch} 文件

2. 将文件传送至目标机器：
   scp argocd-linux-amd64 user@target:/tmp/

3. 在目标机器执行：
   sudo install -m 555 /tmp/argocd-linux-amd64 /usr/local/bin/argocd
   argocd version --client
```
