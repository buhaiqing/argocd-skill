"""意图识别。"""
from __future__ import annotations
from .adapter import RecognizedIntent

# ⚠️ 设计约束：dict 遍历顺序 = 优先级顺序。
# 具体意图（autofix/batch/scaffold）必须放在泛化意图（diagnose）之前，
# 否则 "帮我修复问题" 会匹配 diagnose 而非 autofix。
INTENT_MAP = {
    "autofix": ["修复", "fix", "自动修复"],
    "batch": ["批量", "batch", "并发"],
    "scaffold": ["生成", "scaffold", "模板", "创建"],
    "diagnose": ["不同步", "outsync", "问题", "诊断", "app 问题"],
    "health": ["健康", "health", "稳定性", "评估"],
    "drift": ["漂移", "drift", "版本", "revision"],
    "compliance": ["合规", "compliance", "配置风险"],
    "cost": ["成本", "cost", "费用", "资源"],
}


class IntentClassifier:
    """意图分类器。"""

    _adapter: "SkillOptAdapter | None" = None

    def _get_adapter(self):
        if IntentClassifier._adapter is None:
            from .adapter import SkillOptAdapter
            IntentClassifier._adapter = SkillOptAdapter()
        return IntentClassifier._adapter

    def recognize(self, text: str) -> RecognizedIntent:
        """识别用户意图。"""
        adapter = self._get_adapter()
        if adapter.is_available():
            return adapter.recognize(text)

        text_lower = text.lower()
        for intent, keywords in INTENT_MAP.items():
            if any(kw in text_lower for kw in keywords):
                return RecognizedIntent(intent=intent, confidence=0.8, params={})
        return RecognizedIntent(intent="unknown", confidence=0.0, params={})