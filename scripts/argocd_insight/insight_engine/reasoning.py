"""推断链生成。"""
from __future__ import annotations


def build_reasoning_chain(steps: list[str]) -> list[str]:
    """构建推断链（CoT 显式化）。"""
    return [f"{i+1}. {step}" for i, step in enumerate(steps)]


def infer_confidence(data_points: int, variance: float = 0.0) -> float:
    """推断置信度。"""
    base = min(data_points / 20.0, 1.0)
    penalty = min(variance / 1000.0, 0.3)
    return round(min(base - penalty + 0.5, 0.95), 2)