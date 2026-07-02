"""统计聚合。"""
from __future__ import annotations
from typing import Any


def compute_stats(events: list[dict[str, Any]]) -> dict[str, Any]:
    """统计聚合。"""
    if not events:
        return {"total_calls": 0, "error_rate": 0.0, "p50_ms": 0, "p90_ms": 0, "p99_ms": 0}

    durations = sorted(e["duration_ms"] for e in events if "duration_ms" in e)
    errors = sum(1 for e in events if e.get("return_code", 0) != 0)

    def percentile(data: list[int], p: float) -> int:
        if not data:
            return 0
        idx = int(len(data) * p / 100)
        return data[min(idx, len(data) - 1)]

    module_counts: dict[str, int] = {}
    for e in events:
        m = e.get("module", "unknown")
        module_counts[m] = module_counts.get(m, 0) + 1

    return {
        "total_calls": len(events),
        "error_rate": errors / len(events),
        "p50_ms": percentile(durations, 50),
        "p90_ms": percentile(durations, 90),
        "p99_ms": percentile(durations, 99),
        "module_distribution": module_counts,
    }