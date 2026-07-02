"""analyzer 包：统计 + 瓶颈 + 错误归类。"""
from .stats import compute_stats
from .bottleneck import find_bottlenecks
from .error_classify import classify_errors
from pathlib import Path
import json


def analyze_session(session_dir: Path) -> dict:
    """分析单个会话轨迹。"""
    events = []
    for f in sorted(session_dir.glob("trace_*.jsonl")):
        with open(f) as fp:
            for line in fp:
                line = line.strip()
                if line:
                    events.append(json.loads(line))

    return {
        "session_id": session_dir.name,
        "stats": compute_stats(events),
        "bottlenecks": find_bottlenecks(events),
        "errors": classify_errors(events),
        "total_events": len(events),
    }