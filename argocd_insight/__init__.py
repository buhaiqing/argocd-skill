# argocd_insight/__init__.py — repo root package (real file, not symlink)
import sys as _sys
from pathlib import Path as _Path

_scripts = _Path(__file__).parent.parent / "scripts"
if str(_scripts) not in _sys.path:
    _sys.path.insert(0, str(_scripts))
