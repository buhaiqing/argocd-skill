# argocd_cli_gen/__init__.py — repo root package (real file, not symlink)
import sys as _sys
from pathlib import Path as _Path

_scripts = _Path(__file__).parent.parent / "scripts"
if str(_scripts) not in _sys.path:
    _sys.path.insert(0, str(_scripts))

from scripts.argocd_cli_gen import parser   # noqa: F401
from scripts.argocd_cli_gen import mapper   # noqa: F401
from scripts.argocd_cli_gen import renderer # noqa: F401
from scripts.argocd_cli_gen import fallback # noqa: F401
from scripts.argocd_cli_gen import cli     # noqa: F401
