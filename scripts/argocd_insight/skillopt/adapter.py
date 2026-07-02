"""SDK 适配器框架。"""
from __future__ import annotations
from typing import Any
from dataclasses import dataclass


@dataclass
class RecognizedIntent:
    intent: str
    confidence: float
    params: dict[str, Any]


@dataclass
class RecommendedParams:
    module: str
    params: dict[str, Any]
    reasoning: str


class SkillOptAdapter:
    """SkillOpt SDK 适配器。"""

    def __init__(self, trace_dir: str = ".runtime/argocd-skill/sessions"):
        self.trace_dir = trace_dir
        self._available = self._check_availability()

    def _check_availability(self) -> bool:
        """检测 SkillOpt SDK 是否可用。"""
        try:
            from skillopt import IntentRecognizer, ParameterRecommender  # noqa: F401
            return True
        except ImportError:
            return False

    def is_available(self) -> bool:
        return self._available

    def recognize(self, text: str) -> RecognizedIntent:
        if not self._available:
            return self._fallback_recognize(text)
        from skillopt import IntentRecognizer
        recognizer = IntentRecognizer(skill_name="argocd-skill")
        result = recognizer.recognize(text)
        return RecognizedIntent(
            intent=result["intent"],
            confidence=result["confidence"],
            params=result.get("params", {}),
        )

    def recommend(self, module: str, history: dict) -> RecommendedParams:
        if not self._available:
            return self._fallback_recommend(module, history)
        from skillopt import ParameterRecommender
        recommender = ParameterRecommender(skill_name="argocd-skill", trace_dir=self.trace_dir)
        result = recommender.recommend(module, history)
        return RecommendedParams(
            module=module,
            params=result["params"],
            reasoning=result.get("reasoning", ""),
        )

    def _fallback_recognize(self, text: str) -> RecognizedIntent:
        from .intent import INTENT_MAP

        text_lower = text.lower()
        for intent, keywords in INTENT_MAP.items():
            if any(kw in text_lower for kw in keywords):
                return RecognizedIntent(intent=intent, confidence=0.8, params={})
        return RecognizedIntent(intent="unknown", confidence=0.0, params={})

    def _fallback_recommend(self, module: str, history: dict) -> RecommendedParams:
        from .recommend import PARAM_DEFAULTS

        return RecommendedParams(
            module=module,
            params=PARAM_DEFAULTS.get(module, {}).copy(),
            reasoning="基于历史轨迹统计的默认参数",
        )