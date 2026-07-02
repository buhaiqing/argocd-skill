"""Tests for insight_engine module (经验提炼引擎)."""
import pytest
from argocd_insight.insight_engine import extract_insights, Insight
from argocd_insight.insight_engine.reasoning import build_reasoning_chain, infer_confidence


def test_build_reasoning_chain():
    steps = ["Step 1: 数据分组", "Step 2: 计算均值", "Step 3: 对比拐点"]
    chain = build_reasoning_chain(steps)
    assert len(chain) == 3
    assert chain[0].startswith("1.")


def test_infer_confidence():
    c = infer_confidence(data_points=10, variance=100)
    assert 0.0 <= c <= 1.0


def test_extract_concurrency_insight():
    report = {
        "stats": {"module_distribution": {"diagnose": 12}},
        "bottlenecks": {
            "hot_commands": [{"command": "argocd app list", "count": 8}],
            "frequent_commands": [{"command": "argocd app list", "count": 5}],
        },
        "errors": {},
    }
    insights = extract_insights(report)
    assert len(insights) > 0
    assert any(i.category == "performance" for i in insights)


def test_extract_insight_dataclass():
    insight = Insight(
        category="performance",
        insight="慢调用",
        evidence={"p50_ms": 100, "p99_ms": 500},
        reasoning_chain=["1. 分析数据", "2. 得出结果"],
        confidence=0.85,
    )
    assert insight.category == "performance"
    assert insight.confidence == 0.85