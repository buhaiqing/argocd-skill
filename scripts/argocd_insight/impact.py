"""Change impact analysis for ArgoCD operations.

Analyzes what will be affected before executing sync/rollback operations.

Usage:
  python -m argocd_insight impact my-app sync         # analyze sync impact
  python -m argocd_insight impact my-app rollback 3   # analyze rollback impact
  python -m argocd_insight impact my-app sync --output json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from typing import Any


@dataclass
class ResourceImpact:
    """Impact on a single resource."""
    kind: str
    name: str
    namespace: str
    status: str  # unchanged / created / modified / deleted
    risk: str    # low / medium / high


@dataclass
class AppDependency:
    """Dependency on another app."""
    app: str
    relationship: str  # parent / child / peer
    risk: str


@dataclass
class ImpactAnalysis:
    """Full impact analysis result."""
    app: str
    operation: str
    current_status: dict[str, Any]
    resources_affected: list[ResourceImpact]
    dependencies: list[AppDependency]
    risks: list[str]
    recommendations: list[str]
    estimated_duration: str


def _run_cli(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run argocd CLI command."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timed out"
    except FileNotFoundError:
        return -2, "", f"Not found: {args[0]}"


def _fetch_app(name: str) -> dict[str, Any]:
    """Fetch application details."""
    rc, out, _ = _run_cli(["argocd", "app", "get", name, "--output", "json"])
    if rc != 0:
        raise RuntimeError(f"Failed to get app {name}")
    return json.loads(out)


def _fetch_resources(name: str) -> list[dict[str, Any]]:
    """Fetch managed resources."""
    rc, out, _ = _run_cli(["argocd", "app", "resources", name, "--output", "json"])
    if rc != 0:
        return []
    data = json.loads(out) if out else {}
    return data.get("nodes", []) if isinstance(data, dict) else []


def _find_dependents(app_name: str) -> list[AppDependency]:
    """Find apps that depend on or are depended by this app."""
    rc, out, _ = _run_cli(["argocd", "app", "list", "--output", "json"])
    if rc != 0:
        return []

    apps = json.loads(out) if out else []
    dependencies: list[AppDependency] = []

    for app in apps:
        name = app.get("name", "")
        if name == app_name:
            continue

        spec = app.get("spec", {})
        source = spec.get("source", {})

        # Check if this app's source points to app_name (App-of-Apps child)
        if source.get("path", "").endswith(app_name):
            dependencies.append(AppDependency(
                app=name, relationship="child", risk="medium"
            ))

    # Check if app_name is a child of any other app
    app_spec: dict[str, Any] = {}
    for a in apps:
        if a.get("name") == app_name:
            app_spec = a.get("spec", {})
            break

    app_source = app_spec.get("source", {})
    app_path = app_source.get("path", "")
    if app_path:
        for app in apps:
            name = app.get("name", "")
            if name == app_name:
                continue
            # Simple heuristic: if path segments overlap
            other_path = app.get("spec", {}).get("source", {}).get("path", "")
            if other_path and app_path.startswith(other_path):
                dependencies.append(AppDependency(
                    app=name, relationship="parent", risk="high"
                ))

    return dependencies


def analyze_impact(
    app_name: str,
    operation: str,
    history_id: int | None = None,
) -> ImpactAnalysis:
    """Analyze the impact of an operation on an app."""
    app_data = _fetch_app(app_name)
    status = app_data.get("status", {})

    current_status = {
        "health": status.get("health", {}).get("status", "Unknown"),
        "sync": status.get("sync", {}).get("status", "Unknown"),
        "revision": status.get("sync", {}).get("revision", ""),
        "operation": status.get("operationState", {}).get("phase", "None"),
    }

    # Analyze resources
    resources = _fetch_resources(app_name)
    resources_affected: list[ResourceImpact] = []

    for res in resources:
        res_status = res.get("status", "Unknown")
        risk = "low"
        if res_status in ("Degraded", "Error"):
            risk = "high"
        elif res_status == "Progressing":
            risk = "medium"

        resources_affected.append(ResourceImpact(
            kind=res.get("kind", ""),
            name=res.get("name", ""),
            namespace=res.get("namespace", ""),
            status="modified" if operation == "sync" else "unchanged",
            risk=risk,
        ))

    # Find dependencies
    dependencies = _find_dependents(app_name)

    # Assess risks
    risks: list[str] = []
    if current_status["health"] == "Degraded":
        risks.append("App is currently Degraded — sync may not resolve underlying issue")
    if current_status["operation"] in ("Running", "Pending"):
        risks.append("Another operation is in progress — new operation may conflict")
    if len(resources_affected) > 20:
        risks.append(f"Large number of resources ({len(resources_affected)}) — extended sync time")
    deps_at_risk = [d for d in dependencies if d.risk == "high"]
    if deps_at_risk:
        risks.append(f"Parent app(s) may be affected: {', '.join(d.app for d in deps_at_risk)}")

    # Generate recommendations
    recommendations: list[str] = []
    if operation == "sync":
        recommendations.append("Consider running with --dry-run first to preview changes")
        if current_status["health"] == "Degraded":
            recommendations.append("Investigate root cause before sync — degraded state may persist")
    elif operation == "rollback":
        recommendations.append("Verify the target revision is stable before rollback")
        if history_id:
            recommendations.append(f"Rolling back to history ID {history_id}")

    # Estimate duration
    n = len(resources_affected)
    if n < 5:
        duration = "< 30s"
    elif n < 20:
        duration = "1-2 min"
    else:
        duration = "> 5 min"

    return ImpactAnalysis(
        app=app_name,
        operation=operation,
        current_status=current_status,
        resources_affected=resources_affected,
        dependencies=dependencies,
        risks=risks,
        recommendations=recommendations,
        estimated_duration=duration,
    )


def _format_impact_markdown(analysis: ImpactAnalysis) -> str:
    """Format impact analysis as markdown."""
    lines = [f"# Impact Analysis: {analysis.app}\n"]

    lines.append(f"**Operation:** {analysis.operation}")
    lines.append(f"**Estimated Duration:** {analysis.estimated_duration}\n")

    # Current status
    lines.append("## Current Status\n")
    for key, val in analysis.current_status.items():
        lines.append(f"- **{key}:** {val}")
    lines.append("")

    # Resources affected
    if analysis.resources_affected:
        lines.append(f"## Resources Affected ({len(analysis.resources_affected)})\n")
        lines.append("| Kind | Name | Namespace | Status | Risk |")
        lines.append("|------|------|-----------|--------|------|")
        for r in analysis.resources_affected[:10]:
            lines.append(f"| {r.kind} | {r.name} | {r.namespace} | {r.status} | {r.risk} |")
        if len(analysis.resources_affected) > 10:
            lines.append("| ... | ... | ... | ... | ... |")
        lines.append("")

    # Dependencies
    if analysis.dependencies:
        lines.append("## Dependencies\n")
        for d in analysis.dependencies:
            lines.append(f"- **{d.app}** ({d.relationship}, risk: {d.risk})")
        lines.append("")

    # Risks
    if analysis.risks:
        lines.append("## ⚠️ Risks\n")
        for r in analysis.risks:
            lines.append(f"- {r}")
        lines.append("")

    # Recommendations
    if analysis.recommendations:
        lines.append("## Recommendations\n")
        for r in analysis.recommendations:
            lines.append(f"- {r}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="变更影响分析 — 操作前预览影响范围",
    )
    parser.add_argument("app", help="应用名称")
    parser.add_argument("operation", choices=["sync", "rollback"], help="操作类型")
    parser.add_argument("history_id", nargs="?", type=int, help="回滚历史 ID")
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args(argv)

    try:
        analysis = analyze_impact(args.app, args.operation, args.history_id)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.output == "json":
        print(json.dumps(asdict(analysis), indent=2, ensure_ascii=False))
    else:
        print(_format_impact_markdown(analysis))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
