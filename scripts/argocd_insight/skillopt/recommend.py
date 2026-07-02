"""参数推荐。"""
from __future__ import annotations
from .adapter import RecommendedParams

PARAM_DEFAULTS = {
    "diagnose": {"concurrency": 8, "timeout": 60, "severity": ""},
    "health": {"concurrency": 8, "timeout": 120, "days": 30},
    "drift": {"concurrency": 8, "timeout": 90},
    "batch": {"concurrency": 5, "timeout": 120},
    "autofix": {"concurrency": 3, "timeout": 180},
    "compliance": {"severity": "low"},
    "cost": {"concurrency": 8},
    "repo_health": {"concurrency": 4},
}


class ParameterRecommender:
    """参数推荐器。"""

    def recommend(self, module: str, history: dict) -> RecommendedParams:
        """推荐最优参数。"""
        from .adapter import SkillOptAdapter
        adapter = SkillOptAdapter()
        if adapter.is_available():
            return adapter.recommend(module, history)

        params = PARAM_DEFAULTS.get(module, {}).copy()
        if history.get("total_calls", 0) > 100:
            params["concurrency"] = min(params.get("concurrency", 8) + 2, 16)
        return RecommendedParams(
            module=module,
            params=params,
            reasoning=f"基于 {module} 模块历史轨迹统计 + 默认参数",
        )