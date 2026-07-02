"""Tests for skillopt module (SkillOpt SDK 集成)."""
import pytest
from argocd_insight.skillopt import IntentClassifier, ParameterRecommender
from argocd_insight.skillopt.adapter import SkillOptAdapter, RecognizedIntent, RecommendedParams


@pytest.fixture(autouse=True)
def reset_class_cache():
    """每个测试前重置类级别的 adapter 缓存，避免测试间状态污染。"""
    IntentClassifier.reset()
    ParameterRecommender.reset()


def test_intent_classifier():
    classifier = IntentClassifier()
    intent = classifier.recognize("帮我看看哪些 app 不同步")
    assert intent.intent in ("diagnose", "oos_analyzer")
    assert intent.confidence > 0.5


def test_intent_empty_input():
    classifier = IntentClassifier()
    intent = classifier.recognize("")
    assert intent.intent == "unknown"
    assert intent.confidence == 0.0


def test_intent_noise_input():
    classifier = IntentClassifier()
    intent = classifier.recognize("asdfghjkl12345!@#$%")
    assert intent.intent == "unknown"
    assert intent.confidence == 0.0


def test_intent_mixed_language():
    classifier = IntentClassifier()
    intent = classifier.recognize("帮我 check 一下 health score")
    assert intent.intent == "health"
    assert intent.confidence > 0.5


def test_intent_specific_before_generic():
    classifier = IntentClassifier()
    intent = classifier.recognize("帮我修复")
    assert intent.intent == "autofix"


def test_intent_composite_diagnose_then_fix():
    classifier = IntentClassifier()
    intent = classifier.recognize("修复")
    assert intent.intent == "autofix"


def test_intent_cost_analysis():
    classifier = IntentClassifier()
    intent = classifier.recognize("成本分析")
    assert intent.intent == "cost"


def test_intent_batch_concurrent():
    classifier = IntentClassifier()
    intent = classifier.recognize("并发批量处理")
    assert intent.intent == "batch"


def test_intent_scaffold_create():
    classifier = IntentClassifier()
    intent = classifier.recognize("生成")
    assert intent.intent == "scaffold"


def test_intent_diagnose():
    classifier = IntentClassifier()
    intent = classifier.recognize("诊断这个 app 的问题")
    assert intent.intent == "diagnose"


def test_intent_health():
    classifier = IntentClassifier()
    intent = classifier.recognize("评估一下健康情况")
    assert intent.intent == "health"


def test_intent_drift():
    classifier = IntentClassifier()
    intent = classifier.recognize("版本漂移")
    assert intent.intent == "drift"


def test_intent_compliance():
    classifier = IntentClassifier()
    intent = classifier.recognize("合规")
    assert intent.intent == "compliance"


def test_intent_cost():
    classifier = IntentClassifier()
    intent = classifier.recognize("费用统计")
    assert intent.intent == "cost"


def test_parameter_recommender():
    recommender = ParameterRecommender()
    params = recommender.recommend("diagnose", {"total_calls": 10, "error_rate": 0.1})
    assert "concurrency" in params.params


def test_parameter_recommender_high_load():
    recommender = ParameterRecommender()
    params = recommender.recommend("diagnose", {"total_calls": 200})
    assert params.params["concurrency"] == 10


def test_parameter_recommender_high_load_cap():
    recommender = ParameterRecommender()
    params = recommender.recommend("health", {"total_calls": 500})
    assert params.params["concurrency"] == 10


def test_parameter_recommender_unknown_module():
    recommender = ParameterRecommender()
    params = recommender.recommend("nonexistent_module", {"total_calls": 5})
    assert params.params == {}
    assert params.module == "nonexistent_module"


def test_parameter_recommender_error_rate_moderate():
    recommender = ParameterRecommender()
    params = recommender.recommend("diagnose", {"total_calls": 10, "error_rate": 0.15})
    assert params.params["concurrency"] == 6
    assert params.params["timeout"] == 60
    assert "错误率" in params.reasoning


def test_parameter_recommender_error_rate_high():
    recommender = ParameterRecommender()
    params = recommender.recommend("diagnose", {"total_calls": 10, "error_rate": 0.35})
    assert params.params["concurrency"] == 4
    assert params.params["timeout"] == 90
    assert "错误率" in params.reasoning


def test_parameter_recommender_error_rate_low():
    recommender = ParameterRecommender()
    params = recommender.recommend("diagnose", {"total_calls": 10, "error_rate": 0.05})
    assert params.params["concurrency"] == 8
    assert params.params["timeout"] == 60
    assert "错误率" not in params.reasoning


def test_parameter_recommender_high_load_and_error_rate():
    recommender = ParameterRecommender()
    params = recommender.recommend("diagnose", {"total_calls": 200, "error_rate": 0.35})
    assert params.params["concurrency"] == 6
    assert params.params["timeout"] == 90


def test_parameter_recommender_reasoning():
    recommender = ParameterRecommender()
    params = recommender.recommend("batch", {})
    assert "batch" in params.reasoning


def test_adapter_fallback():
    adapter = SkillOptAdapter()
    assert not adapter.is_available()
    intent = adapter.recognize("看看健康情况")
    assert intent.confidence > 0


def test_recognized_intent_dataclass():
    intent = RecognizedIntent(intent="drift", confidence=0.8, params={})
    assert intent.intent == "drift"


def test_recommended_params_dataclass():
    rp = RecommendedParams(module="diagnose", params={"timeout": 60}, reasoning="based on stats")
    assert rp.module == "diagnose"


def test_intent_tfidf_confidence_varies():
    """TF-IDF confidence varies with match quality (not always 0.8)."""
    classifier = IntentClassifier()
    exact = classifier.recognize("修复")
    partial = classifier.recognize("帮我修复问题")
    assert exact.confidence != partial.confidence


def test_intent_tfidf_no_false_match():
    """Input with no keyword character overlap returns unknown with 0 confidence."""
    classifier = IntentClassifier()
    intent = classifier.recognize("abcdefghijklm")
    assert intent.intent == "unknown"
    assert intent.confidence == 0.0


def test_intent_tfidf_english_ngram():
    """English multi-char keyword matched via char ngrams."""
    classifier = IntentClassifier()
    intent = classifier.recognize("check compliance")
    assert intent.intent == "compliance"
    assert intent.confidence > 0.3


def test_intent_tfidf_single_word_noise():
    """Single short noise word with no keyword bigram overlap."""
    classifier = IntentClassifier()
    intent = classifier.recognize("zxcvbnm")
    assert intent.intent == "unknown"
    assert intent.confidence == 0.0
