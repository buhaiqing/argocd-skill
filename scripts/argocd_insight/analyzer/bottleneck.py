"""瓶颈识别。"""
from __future__ import annotations
from typing import Any
from collections import Counter


def find_bottlenecks(events: list[dict[str, Any]]) -> dict[str, Any]:
    """瓶颈识别。"""
    durations = sorted(e["duration_ms"] for e in events if "duration_ms" in e)
    if not durations:
        return {"hot_commands": [], "slow_calls": [], "concurrency_inefficient": False}

    p95 = durations[int(len(durations) * 0.95)] if durations else 0

    commands = [e.get("command", "") for e in events]
    hot = Counter(commands).most_common(10)

    slow = [e for e in events if e.get("duration_ms", 0) > p95]

    serial_chains = _find_serial_chains(events)

    return {
        "hot_commands": [{"command": cmd, "count": cnt} for cmd, cnt in hot],
        "slow_calls": slow[:10],
        "p95_ms": p95,
        "serial_chains": serial_chains,
    }


def _find_serial_chains(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检测串行瓶颈。"""
    commands = [e.get("command", "") for e in events]
    counts = Counter(commands)
    return [{"command": cmd, "count": cnt} for cmd, cnt in counts.items() if cnt > 3]