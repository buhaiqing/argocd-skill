"""Tests for evolver module (自进化写回器)."""
import pytest
from pathlib import Path
from argocd_insight.evolver import evolve, RiskLevel
from argocd_insight.evolver.validator import classify_risk, validate_write_back
from argocd_insight.insight_engine import Insight


def test_risk_level_classification():
    assert classify_risk(0.95, destructive=False) == RiskLevel.LOW
    assert classify_risk(0.7, destructive=False) == RiskLevel.MEDIUM
    assert classify_risk(0.6, destructive=False) == RiskLevel.HIGH


def test_validate_yaml_structure():
    content = """---
name: argocd-skill
description: |
  ArgoCD CLI 全流程技能。
---
"""
    assert validate_write_back(content, "SKILL.md")


def test_evolve_dry_run():
    insight = Insight(
        category="performance",
        insight="慢调用优化建议",
        evidence={"p50_ms": 100, "p99_ms": 500},
        reasoning_chain=["1. 分析", "2. 结论"],
        confidence=0.85,
        action={"target": "SKILL.md", "suggestion": "增加并发参数"},
    )
    results = evolve([insight], dry_run=True)
    assert "medium" in results
    assert len(results["medium"]) == 1
    assert results["medium"][0]["would_write"] is True


def test_evolve_skips_low_confidence():
    insight = Insight(
        category="performance",
        insight="低置信度建议",
        evidence={},
        reasoning_chain=[],
        confidence=0.5,
    )
    results = evolve([insight], dry_run=True)
    assert len(results["skipped"]) == 1