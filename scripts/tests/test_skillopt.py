"""Tests for skillopt module (SkillOpt SDK 集成)."""
from argocd_insight.skillopt import IntentClassifier, ParameterRecommender
from argocd_insight.skillopt.adapter import SkillOptAdapter, RecognizedIntent, RecommendedParams


def test_intent_classifier():
    classifier = IntentClassifier()
    intent = classifier.recognize("帮我看看哪些 app 不同步")
    assert intent.intent in ("diagnose", "oos_analyzer")
    assert intent.confidence > 0.5


def test_parameter_recommender():
    recommender = ParameterRecommender()
    params = recommender.recommend("diagnose", {"total_calls": 10, "error_rate": 0.1})
    assert "concurrency" in params.params


def test_adapter_fallback():
    adapter = SkillOptAdapter()
    assert not adapter.is_available()  # 无 SDK 时返回 False
    intent = adapter.recognize("看看健康情况")
    assert intent.confidence > 0


def test_recognized_intent_dataclass():
    intent = RecognizedIntent(intent="drift", confidence=0.8, params={})
    assert intent.intent == "drift"


def test_recommended_params_dataclass():
    rp = RecommendedParams(module="diagnose", params={"timeout": 60}, reasoning="based on stats")
    assert rp.module == "diagnose"