"""argocd-skill — ArgoCD CLI 技能包（repo root package）。

将 scripts/ 目录加入 sys.path，使 repo root 下所有子包均可被 `python -m <pkg>` 访问：
    python -m argocd_api         → scripts/argocd_api/
    python -m argocd_cli_gen     → scripts/argocd_cli_gen/
    python -m argocd_insight    → scripts/argocd_insight/
    python -m argocd_deploy_stats.stats       → scripts/argocd_deploy_stats/stats.py
    python -m argocd_deploy_stats.oos_analyzer → scripts/argocd_deploy_stats/oos_analyzer.py

使用注意：
- 本 __init__.py 只做 sys.path 注入，不做其他导入（避免拖慢 import）
- 独立可执行文件（如 argocd_api.py）有独立 shebang，直接运行不走包导入路径
- scripts/ 下各工具的 __main__.py 内部也已做路径自检，任何调用方式均兼容
"""
import sys
from pathlib import Path

_root = Path(__file__).parent
_scripts = _root / "scripts"
if _scripts.exists() and str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))
