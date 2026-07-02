"""scripts/ — ArgoCD skill 内置工具集（namespace package）。

本目录作为 namespace package，将 scripts/ 下的子包通过 repo root 重新导出，
使所有工具均可从 repo root 调用。

可用工具（均从 repo root 调用）：
    python -m argocd_api list                          # HTTP API 等价 CLI
    python -m argocd_api resource-tree <app>          # Pod 列表（phase/IP/node）
    python -m argocd_api resource <app> <kind> <name>  # 资源详情
    python -m argocd_api find-pod <pod-name>           # 查找 Pod 所属 App
    python -m argocd_api sync/refresh/login/...        # CRUD 操作

    python -m argocd_cli_gen --input DIR              # 批量 YAML → CLI 脚本
    python -m argocd_insight diagnose                  # 问题 App 诊断
    python -m argocd_insight drift                     # 版本漂移检测
    python -m argocd_insight health                    # 稳定性评估
    python -m argocd_insight compliance                 # 配置合规检查
    python -m argocd_insight batch sync                 # 批量同步
    # ... 更多子命令见 python -m argocd_insight --help

    python -m argocd_deploy_stats.stats                 # 部署频率统计
    python -m argocd_deploy_stats.oos_analyzer          # OutOfSync 根因归因

也可直接执行（repo root 目录下）：
    ./argocd_api.py ...     （等价 python -m argocd_api ...）
    ./argocd_cli_gen.py ... （等价 python -m argocd_cli_gen ...）
    ./argocd_insight.py ... （等价 python -m argocd_insight ...）
    ./argocd_deploy_stats.py stats ...
    ./argocd_deploy_stats.py oos_analyzer ...

所有工具自动从 .env 加载凭证（repo root 或 CWD），无需额外配置。
"""
