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

    _adapter: "SkillOptAdapter | None" = None

    def _get_adapter(self):
        if ParameterRecommender._adapter is None:
            from .adapter import SkillOptAdapter
            ParameterRecommender._adapter = SkillOptAdapter()
        return ParameterRecommender._adapter

    @classmethod
    def reset(cls) -> None:
        """重置类级别的 adapter 缓存。用于测试隔离或配置变更后刷新。"""
        cls._adapter = None

    def recommend(self, module: str, history: dict) -> RecommendedParams:
        """推荐最优参数。"""
        adapter = self._get_adapter()
        if adapter.is_available():
            return adapter.recommend(module, history)

        params = PARAM_DEFAULTS.get(module, {}).copy()
        reasoning_parts = [f"基于 {module} 模块历史轨迹统计 + 默认参数"]
        if history.get("total_calls", 0) > 100:
            params["concurrency"] = min(params.get("concurrency", 8) + 2, 16)
            reasoning_parts.append("高负载场景并发+2")
        error_rate = history.get("error_rate", 0.0)
        if error_rate > 0.3:
            params["concurrency"] = max(params.get("concurrency", 8) - 4, 2)
            params["timeout"] = int(params.get("timeout", 60) * 1.5)
            reasoning_parts.append(f"错误率{error_rate:.0%}过高，并发-4、超时+50%")
        elif error_rate > 0.1:
            params["concurrency"] = max(params.get("concurrency", 8) - 2, 2)
            reasoning_parts.append(f"错误率{error_rate:.0%}偏高，并发-2")
        return RecommendedParams(
            module=module,
            params=params,
            reasoning="；".join(reasoning_parts),
        )