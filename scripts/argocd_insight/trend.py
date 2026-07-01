"""趋势分析 — 对比历史快照，计算指标变化趋势。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any

from .snapshot_store import SnapshotStore


def _extract_number(data: Any, *path: str) -> float | None:
    """从嵌套 dict 中提取数值。"""
    current = data
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            return None
    if isinstance(current, (int, float)):
        return float(current)
    return None


def _count_by_severity(module_data: Any, severity: str) -> int:
    """统计模块数据中指定严重级别的数量。"""
    if module_data is None:
        return 0

    items: list[dict] = []
    if isinstance(module_data, dict):
        for key in ("apps", "risks", "results", "items"):
            if key in module_data and isinstance(module_data[key], list):
                items = module_data[key]
                break
    elif isinstance(module_data, list):
        items = module_data

    return sum(1 for item in items if item.get("severity") == severity)


def compute_delta(
    snapshots: list[dict[str, Any]],
    metric_key: str,
) -> dict[str, Any]:
    """计算两个快照之间的指标变化。

    Args:
        snapshots: 按时间排序的快照列表（至少 2 个）
        metric_key: 指标路径，如 "health_score" 或 "cost/total"

    Returns:
        包含 first/last/delta/pct_change 的字典
    """
    if len(snapshots) < 2:
        return {"error": "需要至少 2 个快照"}

    first_data = snapshots[0].get("modules", {})
    last_data = snapshots[-1].get("modules", {})

    parts = metric_key.split(".")
    first_val = _extract_number(first_data, *parts)
    last_val = _extract_number(last_data, *parts)

    if first_val is None or last_val is None:
        return {"error": f"无法提取指标 {metric_key}"}

    delta = last_val - first_val
    pct = (delta / first_val * 100) if first_val != 0 else 0.0

    return {
        "metric": metric_key,
        "first_ts": snapshots[0].get("timestamp"),
        "last_ts": snapshots[-1].get("timestamp"),
        "first_value": first_val,
        "last_value": last_val,
        "delta": round(delta, 2),
        "pct_change": round(pct, 2),
    }


def _discover_metrics(snapshots: list[dict[str, Any]]) -> list[str]:
    """从快照数据自动发现所有数值型 metric paths。"""
    paths: set[str] = set()

    def _walk(data: Any, prefix: str) -> None:
        if isinstance(data, dict):
            for key, val in data.items():
                full = f"{prefix}.{key}" if prefix else key
                if isinstance(val, (int, float)):
                    paths.add(full)
                elif isinstance(val, dict):
                    _walk(val, full)
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            _walk(data[0], prefix)

    for snap in snapshots:
        modules = snap.get("modules", {})
        if isinstance(modules, dict):
            for mod_name, mod_data in modules.items():
                if isinstance(mod_data, (int, float)):
                    paths.add(mod_name)
                elif isinstance(mod_data, dict):
                    _walk(mod_data, mod_name)

    return sorted(paths)


def analyze_trend(
    store: SnapshotStore,
    days: int = 7,
    metric: str = "",
) -> dict[str, Any]:
    """分析趋势主函数。"""
    all_ts = store.list_snapshots()
    if not all_ts:
        return {"error": "无历史快照数据"}

    cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent_ts = [ts for ts in all_ts if ts >= cutoff[:len(ts)]]

    if len(recent_ts) < 2:
        recent_ts = all_ts[-min(len(all_ts), 30):]

    snapshots = []
    for ts in recent_ts:
        snap = store.load(ts)
        if snap:
            snapshots.append(snap)

    if len(snapshots) < 2:
        return {"error": f"有效快照不足（仅有 {len(snapshots)} 个）"}

    result = {
        "snapshot_count": len(snapshots),
        "first_ts": snapshots[0].get("timestamp"),
        "last_ts": snapshots[-1].get("timestamp"),
        "deltas": {},
    }

    metrics_to_check = (
        [metric] if metric else _discover_metrics(snapshots)
    )

    for m in metrics_to_check:
        delta = compute_delta(snapshots, m)
        if "error" not in delta:
            result["deltas"][m] = delta

    return result


def format_trend_markdown(trend: dict[str, Any]) -> str:
    """将趋势结果格式化为 Markdown。"""
    if "error" in trend:
        return f"⚠️ {trend['error']}"

    lines = [
        "# 趋势分析报告",
        "",
        f"> 快照数量: {trend['snapshot_count']}",
        f"> 时间范围: {trend['first_ts']} → {trend['last_ts']}",
        "",
        "## 指标变化",
        "",
        "| 指标 | 起始值 | 当前值 | 变化量 | 变化率 |",
        "|------|--------|--------|--------|--------|",
    ]

    for name, delta in trend.get("deltas", {}).items():
        direction = "📈" if delta["delta"] > 0 else ("📉" if delta["delta"] < 0 else "➡️")
        lines.append(
            f"| {name} | {delta['first_value']} | {delta['last_value']} "
            f"| {direction} {delta['delta']:+.2f} | {delta['pct_change']:+.1f}% |"
        )

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="argocd-insight trend",
        description="分析历史快照趋势",
    )
    p.add_argument("--days", type=int, default=7, help="分析最近 N 天（默认 7）")
    p.add_argument("--metric", default="", help="指定分析的指标路径（默认全部）")
    p.add_argument("--store-dir", default="", help="快照存储目录")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")

    args = p.parse_args(argv)

    store = SnapshotStore(args.store_dir if args.store_dir else None)
    trend = analyze_trend(store, days=args.days, metric=args.metric)

    if args.output == "json":
        print(json.dumps(trend, ensure_ascii=False, indent=2))
    else:
        print(format_trend_markdown(trend))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
