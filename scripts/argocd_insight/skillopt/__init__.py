"""skillopt 包：SDK 适配 + 意图识别 + 参数推荐。"""
from .adapter import SkillOptAdapter as SkillOptAdapter, RecognizedIntent as RecognizedIntent, RecommendedParams as RecommendedParams
from .intent import IntentClassifier as IntentClassifier
from .recommend import ParameterRecommender as ParameterRecommender