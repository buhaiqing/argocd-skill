"""写回前校验。"""
from __future__ import annotations
from enum import Enum
from typing import Any


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def classify_risk(confidence: float, destructive: bool = False) -> RiskLevel:
    """风险分级。"""
    if destructive or confidence < 0.7:
        return RiskLevel.HIGH
    if confidence >= 0.9:
        return RiskLevel.LOW
    return RiskLevel.MEDIUM


def validate_write_back(content: str, target: str) -> bool:
    """写回前格式校验。"""
    if target.endswith(".md"):
        return len(content) > 0 and "---" in content
    if target.endswith(".py"):
        try:
            compile(content, target, "exec")
            return True
        except SyntaxError:
            return False
    return True