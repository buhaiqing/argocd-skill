"""skillopt 包：SDK 适配 + 意图识别 + 参数推荐。"""
from .adapter import SkillOptAdapter, RecognizedIntent, RecommendedParams
from .intent import IntentClassifier
from .recommend import ParameterRecommender