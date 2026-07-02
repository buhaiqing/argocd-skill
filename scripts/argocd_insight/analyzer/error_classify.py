"""错误归因。"""
from __future__ import annotations
from typing import Any

ERROR_PATTERNS: list[tuple[str, list[str]]] = [
    ("auth_error", ["unauthorized", "401", "permission denied", "authentication"]),
    ("network_timeout", ["timeout", "timed out", "connection refused", "network"]),
    ("resource_not_found", ["not found", "404", "does not exist"]),
    ("invalid_args", ["invalid argument", "unrecognized", "unknown flag"]),
    ("server_error", ["500", "internal server error", "503"]),
]


def classify_errors(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """错误归因。"""
    result: dict[str, list[dict[str, Any]]] = {k: [] for k, _ in ERROR_PATTERNS}
    result["other"] = []

    for e in events:
        if e.get("return_code", 0) == 0 and not e.get("error"):
            continue
        error_text = (e.get("error") or "").lower()
        matched = False
        for label, patterns in ERROR_PATTERNS:
            if any(p in error_text for p in patterns):
                result[label].append(e)
                matched = True
                break
        if not matched:
            result["other"].append(e)

    return result