"""意图识别。"""
from __future__ import annotations
from .adapter import RecognizedIntent

INTENT_MAP = {
    "diagnose": ["不同步", "outsync", "问题", "诊断", "分析", "app 问题"],
    "health": ["健康", "health", "稳定性", "评估"],
    "drift": ["漂移", "drift", "版本", "revision"],
    "compliance": ["合规", "compliance", "配置风险"],
    "cost": ["成本", "cost", "费用", "资源"],
    "autofix": ["修复", "fix", "自动修复"],
    "batch": ["批量", "batch", "并发"],
    "scaffold": ["生成", "scaffold", "模板", "创建"],
}


class IntentClassifier:
    """意图分类器。"""

    def recognize(self, text: str) -> RecognizedIntent:
        """识别用户意图。"""
        from .adapter import SkillOptAdapter
        adapter = SkillOptAdapter()
        if adapter.is_available():
            return adapter.recognize(text)

        text_lower = text.lower()
        for intent, keywords in INTENT_MAP.items():
            if any(kw in text_lower for kw in keywords):
                return RecognizedIntent(intent=intent, confidence=0.8, params={})
        return RecognizedIntent(intent="unknown", confidence=0.0, params={})