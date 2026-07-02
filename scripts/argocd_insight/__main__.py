"""`python -m argocd_insight` 入口。"""

from __future__ import annotations

import sys
from pathlib import Path

# ponytail: 让 scripts/ 下所有子包在任何调用方式下都能被找到
_scripts_root = Path(__file__).parent.parent
if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))

from scripts.argocd_insight.cli import main

raise SystemExit(main())
