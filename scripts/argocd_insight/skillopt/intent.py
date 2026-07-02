from __future__ import annotations
from typing import TYPE_CHECKING
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .adapter import RecognizedIntent

if TYPE_CHECKING:
    from .adapter import SkillOptAdapter

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

_INTENT_ORDER = list(INTENT_MAP.keys())
_TFIDF_TOLERANCE = 0.1
_THRESHOLD = 0.3


class IntentClassifier:

    _adapter: "SkillOptAdapter | None" = None
    _vectorizer: TfidfVectorizer | None = None
    _kw_matrix = None
    _kw_to_intent: list | None = None

    def _get_adapter(self):
        if IntentClassifier._adapter is None:
            from .adapter import SkillOptAdapter
            IntentClassifier._adapter = SkillOptAdapter()
        return IntentClassifier._adapter

    @classmethod
    def reset(cls) -> None:
        cls._adapter = None

    def _get_fallback_model(self):
        if IntentClassifier._vectorizer is None:
            vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 3), sublinear_tf=True)
            kw_to_intent = []
            docs = []
            for intent, keywords in INTENT_MAP.items():
                for kw in keywords:
                    kw_to_intent.append(intent)
                    docs.append(kw)
            kw_matrix = vectorizer.fit_transform(docs)
            IntentClassifier._vectorizer = vectorizer
            IntentClassifier._kw_matrix = kw_matrix
            IntentClassifier._kw_to_intent = kw_to_intent
        return IntentClassifier._vectorizer, IntentClassifier._kw_matrix, IntentClassifier._kw_to_intent

    def recognize(self, text: str) -> RecognizedIntent:
        adapter = self._get_adapter()
        if adapter.is_available():
            return adapter.recognize(text)

        text = text.strip()
        if not text:
            return RecognizedIntent(intent="unknown", confidence=0.0, params={})

        vectorizer, kw_matrix, kw_to_intent = self._get_fallback_model()
        text_vec = vectorizer.transform([text])
        sims = cosine_similarity(text_vec, kw_matrix)[0]
        best_score = float(sims.max())
        if best_score < _THRESHOLD:
            return RecognizedIntent(intent="unknown", confidence=0.0, params={})

        candidates = {}
        for i in range(len(kw_to_intent)):
            score = float(sims[i])
            if score >= best_score - _TFIDF_TOLERANCE:
                intent = kw_to_intent[i]
                if intent not in candidates or score > candidates[intent]:
                    candidates[intent] = score
        for intent in _INTENT_ORDER:
            if intent in candidates:
                return RecognizedIntent(intent=intent, confidence=candidates[intent], params={})

        return RecognizedIntent(intent="unknown", confidence=0.0, params={})