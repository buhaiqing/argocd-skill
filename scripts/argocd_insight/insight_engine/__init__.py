"""insight_engine 包：经验提炼 + 推断链。"""
from .extractor import Insight as Insight, extract_insights as extract_insights
from .reasoning import build_reasoning_chain as build_reasoning_chain, infer_confidence as infer_confidence