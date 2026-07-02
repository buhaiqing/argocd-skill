#!/usr/bin/env python3
"""argocd_deploy_stats CLI 入口（repo root 包装器）。

支持两种调用风格：
    python3 -m argocd_deploy_stats.stats       → stats.py
    python3 -m argocd_deploy_stats.oos_analyzer → oos_analyzer.py
    python3 argocd_deploy_stats.py stats       → stats.py
    python3 argocd_deploy_stats.py oos_analyzer → oos_analyzer.py
"""
import sys
from pathlib import Path

_repo_root = Path(__file__).parent
_scripts_root = _repo_root / "scripts"
if _scripts_root.exists():
    sys.path.insert(0, str(_scripts_root))

_name = Path(sys.argv[0]).name.removesuffix(".py")
_subcommands = {"stats", "oos_analyzer"}

if _name == "argocd_deploy_stats" and len(sys.argv) > 1 and sys.argv[1] in _subcommands:
    sys.argv = sys.argv[1:]
    _sub = sys.argv[0]
elif _name in _subcommands:
    _sub = _name
else:
    _sub = "stats"

import importlib
_mod = importlib.import_module(f"scripts.argocd_deploy_stats.{_sub}")
sys.exit(_mod.main())
