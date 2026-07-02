"""经验提取。"""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass
from .reasoning import build_reasoning_chain, infer_confidence


@dataclass
class Insight:
    """单条经验。"""
    category: str
    insight: str
    evidence: dict[str, Any]
    reasoning_chain: list[str]
    confidence: float
    action: dict[str, Any] | None = None


def extract_insights(report: dict[str, Any]) -> list[Insight]:
    """从分析报告提炼经验。"""
    insights = []

    stats = report.get("stats", {})
    if stats.get("p99_ms", 0) > stats.get("p50_ms", 0) * 5:
        insights.append(_perf_slow_tail(report))

    errors = report.get("errors", {})
    if sum(len(v) for v in errors.values()) > 0:
        insights.append(_error_pattern_insight(errors))

    bottlenecks = report.get("bottlenecks", {})
    if bottlenecks.get("serial_chains"):
        insights.append(_concurrency_insight(report))

    return insights


def _perf_slow_tail(report: dict) -> Insight:
    stats = report["stats"]
    reasoning = build_reasoning_chain([
        f"统计 {stats['total_calls']} 次调用",
        f"P50={stats['p50_ms']}ms, P99={stats['p99_ms']}ms",
        f"P99/P50 比值 = {stats['p99_ms'] / max(stats['p50_ms'], 1):.1f}x",
        "结论：存在长尾慢调用，建议检查网络或限流",
    ])
    return Insight(
        category="performance",
        insight="存在显著慢调用长尾",
        evidence={"p50_ms": stats["p50_ms"], "p99_ms": stats["p99_ms"], "total": stats["total_calls"]},
        reasoning_chain=reasoning,
        confidence=infer_confidence(stats["total_calls"]),
    )


def _error_pattern_insight(errors: dict) -> Insight:
    total_errors = sum(len(v) for v in errors.values())
    dominant = max(errors.items(), key=lambda x: len(x[1]))
    reasoning = build_reasoning_chain([
        f"共 {total_errors} 次错误",
        f"主要类型：{dominant[0]}（{len(dominant[1])} 次）",
        f"占比：{len(dominant[1]) / max(total_errors, 1) * 100:.0f}%",
        f"建议：优先排查 {dominant[0]} 根因",
    ])
    return Insight(
        category="error_pattern",
        insight=f"错误以 {dominant[0]} 为主",
        evidence={"total_errors": total_errors, "by_type": {k: len(v) for k, v in errors.items()}},
        reasoning_chain=reasoning,
        confidence=infer_confidence(total_errors),
        action={"target": "references/agent-protocols.md", "suggestion": f"补充 {dominant[0]} 处理流程"},
    )


def _concurrency_insight(report: dict) -> Insight:
    chains = report["bottlenecks"]["serial_chains"]
    reasoning = build_reasoning_chain([
        f"发现 {len(chains)} 组串行调用链",
        "串行执行可通过并发优化",
        "建议：使用 --concurrency 参数加速",
    ])
    return Insight(
        category="performance",
        insight="存在可并行的串行调用",
        evidence={"serial_chains": chains},
        reasoning_chain=reasoning,
        confidence=0.75,
        action={"target": "cli.py", "field": "default_concurrency", "current": 8, "suggested": 10},
    )