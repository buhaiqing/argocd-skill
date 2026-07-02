"""insight_engine 包：经验提炼 + 推断链。"""
from .extractor import Insight, extract_insights
from .reasoning import build_reasoning_chain, infer_confidence