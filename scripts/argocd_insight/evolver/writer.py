"""写回执行器。"""
from __future__ import annotations
from pathlib import Path
from typing import Any

from .validator import validate_write_back, classify_risk, RiskLevel
from ..insight_engine import Insight


def evolve(insights: list[Insight], dry_run: bool = True) -> dict[str, Any]:
    """执行自进化写回。"""
    results: dict[str, list[dict[str, Any]]] = {
        "low": [], "medium": [], "high": [], "skipped": [],
    }

    for insight in insights:
        risk = classify_risk(insight.confidence)
        if risk == RiskLevel.HIGH:
            results["skipped"].append({
                "insight": insight.insight,
                "reason": "confidence < 0.7",
            })
            continue

        if dry_run:
            results[risk.value].append({
                "insight": insight.insight,
                "action": insight.action,
                "would_write": True,
            })
        else:
            success = _do_write(insight)
            results[risk.value].append({
                "insight": insight.insight,
                "action": insight.action,
                "written": success,
            })

    return results


_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.resolve()


def _do_write(insight: Insight) -> bool:
    """执行写回。"""
    action = insight.action
    if not action:
        return False

    target = action.get("target", "")
    if not target:
        return False

    raw = Path(target)
    # ponytail: reject absolute paths and parent traversal
    if raw.is_absolute() or ".." in raw.parts:
        return False

    path = (_PROJECT_ROOT / target).resolve()
    # ponytail: ensure the resolved path stays inside the project
    if not str(path).startswith(str(_PROJECT_ROOT)):
        return False
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    if not validate_write_back(content, target):
        return False

    note = f"\n\n<!-- EVOLVED: {insight.insight} -->\n<!-- Confidence: {insight.confidence} -->\n"
    content += note
    path.write_text(content, encoding="utf-8")
    return True