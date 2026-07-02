"""conftest.py — pytest 全局 fixtures。

测试从 scripts/ 运行，需要把 repo root 加入 sys.path，
使 `from argocd_cli_gen import ...` 等 import 能找到对应的包。
"""
import sys
from pathlib import Path

# repo root（scripts/ 的父目录）
_repo_root = Path(__file__).parent.parent.parent
_scripts = _repo_root / "scripts"
if str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))
