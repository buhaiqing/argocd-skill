"""scripts/ — ArgoCD skill 内置工具集。

本目录是一个 PEP 420 namespace package，
scripts/argocd_api/、scripts/argocd_cli_gen/、scripts/argocd_insight/ 等子包
各自有完整的 __init__.py，可独立导入。

repo root 上的包（argocd_api/、argocd_cli_gen/、argocd_insight/）
通过 symlink 复用 scripts/ 下的模块文件。

可用工具（均从 repo root 调用）：
    python -m argocd_api list                          # HTTP API 等价 CLI
    python -m argocd_api resource-tree <app>          # Pod 列表（phase/IP/node）
    python -m argocd_cli_gen --input DIR              # 批量 YAML → CLI 脚本
    python -m argocd_insight diagnose                  # 问题 App 诊断
    python -m argocd_insight health                   # 稳定性评估
    python -m argocd_deploy_stats.stats                 # 部署频率统计
    python -m argocd_deploy_stats.oos_analyzer         # OutOfSync 根因归因

所有工具自动从 .env 加载凭证（repo root 或 CWD），无需额外配置。
"""
