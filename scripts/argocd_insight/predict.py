"""Prediction and risk scoring for ArgoCD applications.

Provides revision lag risk scoring and cost overrun early warning.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any


def _parse_timestamp(ts: str) -> datetime | None:
    """Parse ISO timestamp string, return None on failure."""
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def compute_lag_risk(app_data: dict[str, Any]) -> dict[str, Any]:
    """Compute revision lag risk score for an application.

    Risk factors:
    1. Time since last sync (days)
    2. Time since last commit (days)
    3. Auto-sync enabled vs disabled
    4. Number of pending changes

    Returns dict with risk_score (0-100), risk_level, and factors.
    """
    status = app_data.get("status", {})
    spec = app_data.get("spec", {})
    name = app_data.get("metadata", {}).get("name", "unknown")

    now = datetime.now(timezone.utc)
    factors: list[dict[str, Any]] = []
    score = 0

    # Factor 1: Last sync time
    sync_time_str = status.get("operationState", {}).get("finishedAt", "")
    sync_time = _parse_timestamp(sync_time_str) if sync_time_str else None
    if sync_time:
        days_since_sync = (now - sync_time).days
        if days_since_sync > 30:
            sync_score = min(30, days_since_sync)
            factors.append({
                "name": "last_sync",
                "days": days_since_sync,
                "score": sync_score,
                "detail": f"Last sync {days_since_sync}d ago",
            })
            score += sync_score
        else:
            factors.append({
                "name": "last_sync",
                "days": days_since_sync,
                "score": 0,
                "detail": f"Recent sync ({days_since_sync}d ago)",
            })
    else:
        factors.append({
            "name": "last_sync",
            "days": -1,
            "score": 15,
            "detail": "No sync history found",
        })
        score += 15

    # Factor 2: Last commit time
    revisions = status.get("revisions", [])
    source = spec.get("source", {})
    if revisions:
        for rev in revisions:
            if isinstance(rev, dict):
                committed_at = rev.get("committedAt", "")
                commit_time = _parse_timestamp(committed_at) if committed_at else None
                if commit_time:
                    days_since_commit = (now - commit_time).days
                    if days_since_commit > 14:
                        commit_score = min(25, days_since_commit // 2)
                        factors.append({
                            "name": "last_commit",
                            "days": days_since_commit,
                            "score": commit_score,
                            "detail": f"Commit {days_since_commit}d ago",
                        })
                        score += commit_score
                    break
    elif source.get("targetRevision"):
        # Cannot determine commit time from spec alone
        factors.append({
            "name": "last_commit",
            "days": -1,
            "score": 5,
            "detail": "Cannot determine commit age from spec",
        })
        score += 5

    # Factor 3: Auto-sync
    auto_sync = spec.get("syncPolicy", {}).get("automated")
    if auto_sync:
        factors.append({
            "name": "auto_sync",
            "score": 0,
            "detail": "Auto-sync enabled — low lag risk",
        })
    else:
        factors.append({
            "name": "auto_sync",
            "score": 20,
            "detail": "Manual sync only — higher lag risk",
        })
        score += 20

    # Factor 4: Pending changes
    health = status.get("health", {})
    sync_status = status.get("sync", {}).get("status", "")
    if sync_status == "OutOfSync":
        factors.append({
            "name": "out_of_sync",
            "score": 15,
            "detail": "Application is OutOfSync",
        })
        score += 15
    else:
        factors.append({
            "name": "out_of_sync",
            "score": 0,
            "detail": "Application is Synced",
        })

    # Factor 5: Revision count (multi-source apps)
    if len(revisions) > 1:
        multi_score = min(10, (len(revisions) - 1) * 5)
        factors.append({
            "name": "multi_source",
            "revision_count": len(revisions),
            "score": multi_score,
            "detail": f"{len(revisions)} source revisions",
        })
        score += multi_score

    # Cap at 100
    score = min(100, score)

    # Risk level
    if score >= 70:
        risk_level = "critical"
    elif score >= 50:
        risk_level = "high"
    elif score >= 30:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "name": name,
        "risk_score": score,
        "risk_level": risk_level,
        "factors": factors,
    }


def compute_cost_overrun_risk(
    app_data: dict[str, Any],
    budget_limit: float | None = None,
) -> dict[str, Any]:
    """Estimate cost overrun risk based on resource requests/limits.

    Analyzes container resource requests vs limits to detect potential
    over-provisioning or runaway resource consumption patterns.
    """
    name = app_data.get("metadata", {}).get("name", "unknown")
    spec = app_data.get("spec", {})
    source = spec.get("source", {})

    factors: list[dict[str, Any]] = []
    score = 0
    estimated_cpu_millicores = 0
    estimated_memory_mb = 0

    # Try to extract from Helm values
    helm = source.get("helm", {})
    if helm:
        values_str = helm.get("values", "")
        parameters = helm.get("parameters", [])

        # Parse Helm parameters for resource hints
        for param in parameters:
            pname = param.get("name", "").lower()
            pval = param.get("value", "")

            if "replicas" in pname:
                try:
                    replicas = int(pval)
                    if replicas > 5:
                        factors.append({
                            "name": "high_replicas",
                            "value": replicas,
                            "score": min(20, replicas * 2),
                            "detail": f"High replica count: {replicas}",
                        })
                        score += min(20, replicas * 2)
                except ValueError:
                    pass

            elif "cpu" in pname and "request" in pname:
                try:
                    cpu_str = pval.replace("m", "").replace("Mi", "")
                    cpu_m = int(cpu_str)
                    estimated_cpu_millicores += cpu_m
                except ValueError:
                    pass

            elif "memory" in pname and "request" in pname:
                try:
                    mem_str = pval.replace("Gi", "").replace("Mi", "").replace("G", "").replace("M", "")
                    mem_val = int(mem_str)
                    if "Gi" in pval or "G" in pval:
                        mem_val *= 1024
                    estimated_memory_mb += mem_val
                except ValueError:
                    pass

    # Check for resource limits vs requests ratio
    if estimated_cpu_millicores > 0:
        factors.append({
            "name": "estimated_cpu",
            "value": estimated_cpu_millicores,
            "score": 0,
            "detail": f"Estimated CPU: {estimated_cpu_millicores}m",
        })

    if estimated_memory_mb > 4096:
        mem_score = min(15, estimated_memory_mb // 1024)
        factors.append({
            "name": "high_memory",
            "value": estimated_memory_mb,
            "score": mem_score,
            "detail": f"High memory request: {estimated_memory_mb}MB",
        })
        score += mem_score

    # Budget check
    if budget_limit is not None:
        estimated_cost = (estimated_cpu_millicores / 1000) * 0.05 + (estimated_memory_mb / 1024) * 0.01
        if estimated_cost > budget_limit:
            overrun_pct = ((estimated_cost - budget_limit) / budget_limit) * 100
            budget_score = min(30, int(overrun_pct / 5))
            factors.append({
                "name": "budget_overrun",
                "estimated_cost": round(estimated_cost, 4),
                "budget_limit": budget_limit,
                "overrun_pct": round(overrun_pct, 1),
                "score": budget_score,
                "detail": f"Est. ${estimated_cost:.4f} > budget ${budget_limit:.4f} (+{overrun_pct:.0f}%)",
            })
            score += budget_score

    score = min(100, score)

    if score >= 70:
        risk_level = "critical"
    elif score >= 50:
        risk_level = "high"
    elif score >= 30:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "name": name,
        "risk_score": score,
        "risk_level": risk_level,
        "estimated_cpu_millicores": estimated_cpu_millicores,
        "estimated_memory_mb": estimated_memory_mb,
        "factors": factors,
    }


def predict_batch(
    apps: dict[str, dict[str, Any]],
    budget_limit: float | None = None,
) -> dict[str, Any]:
    """Run predictions on a batch of applications.

    Returns summary with lag risks and cost risks.
    """
    lag_risks = []
    cost_risks = []

    for name, data in apps.items():
        lag = compute_lag_risk(data)
        lag_risks.append(lag)

        cost = compute_cost_overrun_risk(data, budget_limit)
        cost_risks.append(cost)

    # Sort by risk score descending
    lag_risks.sort(key=lambda x: -x["risk_score"])
    cost_risks.sort(key=lambda x: -x["risk_score"])

    # Summary stats
    critical_lag = sum(1 for r in lag_risks if r["risk_level"] == "critical")
    high_lag = sum(1 for r in lag_risks if r["risk_level"] == "high")
    critical_cost = sum(1 for r in cost_risks if r["risk_level"] == "critical")
    high_cost = sum(1 for r in cost_risks if r["risk_level"] == "high")

    return {
        "app_count": len(apps),
        "lag_risks": lag_risks,
        "cost_risks": cost_risks,
        "summary": {
            "critical_lag": critical_lag,
            "high_lag": high_lag,
            "critical_cost": critical_cost,
            "high_cost": high_cost,
            "total_warnings": critical_lag + high_lag + critical_cost + high_cost,
        },
    }


def format_predict_markdown(results: dict[str, Any]) -> str:
    """Format prediction results as Markdown report."""
    lines = [
        "# 风险预测报告",
        "",
        f"**应用数**: {results['app_count']}",
        "",
    ]

    summary = results.get("summary", {})
    if summary.get("total_warnings", 0) > 0:
        lines.append("## ⚠️ 风险摘要")
        lines.append("")
        lines.append(f"- Revision 滞后风险: {summary.get('critical_lag', 0)} critical, {summary.get('high_lag', 0)} high")
        lines.append(f"- 成本超支风险: {summary.get('critical_cost', 0)} critical, {summary.get('high_cost', 0)} high")
        lines.append("")

    # Top lag risks
    lag_risks = [r for r in results.get("lag_risks", []) if r["risk_score"] > 0][:10]
    if lag_risks:
        lines.append("## Revision 滞后风险 (Top 10)")
        lines.append("")
        for r in lag_risks:
            emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(r["risk_level"], "")
            lines.append(f"### {emoji} {r['name']} — {r['risk_score']}/100 ({r['risk_level']})")
            lines.append("")
            for f in r.get("factors", []):
                if f.get("score", 0) > 0:
                    lines.append(f"- {f['detail']} (+{f['score']})")
            lines.append("")

    # Top cost risks
    cost_risks = [r for r in results.get("cost_risks", []) if r["risk_score"] > 0][:5]
    if cost_risks:
        lines.append("## 成本超支风险 (Top 5)")
        lines.append("")
        for r in cost_risks:
            emoji = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}.get(r["risk_level"], "")
            lines.append(f"### {emoji} {r['name']} — {r['risk_score']}/100 ({r['risk_level']})")
            lines.append("")
            for f in r.get("factors", []):
                if f.get("score", 0) > 0:
                    lines.append(f"- {f['detail']} (+{f['score']})")
            lines.append("")

    if not lag_risks and not cost_risks:
        lines.append("✅ 所有应用风险评估正常，无需预警。")
        lines.append("")

    return "\n".join(lines)


def format_predict_json(results: dict[str, Any]) -> str:
    """Format prediction results as JSON."""
    return json.dumps(results, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for prediction."""
    parser = argparse.ArgumentParser(
        prog="argocd_insight predict",
        description="Revision lag risk scoring and cost overrun early warning",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Paths to ArgoCD app JSON files",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=None,
        help="Budget limit per app (USD) for cost overrun detection",
    )
    parser.add_argument(
        "--type",
        choices=["all", "lag", "cost"],
        default="all",
        help="Prediction type (default: all)",
    )

    args = parser.parse_args(argv)

    # Load app data
    apps: dict[str, dict[str, Any]] = {}
    for filepath in args.files:
        try:
            with open(filepath) as f:
                data = json.load(f)
            name = data.get("metadata", {}).get("name", filepath)
            apps[name] = data
        except (json.JSONDecodeError, OSError) as e:
            print(f"Error loading {filepath}: {e}", file=sys.stderr)
            return 1

    if not apps:
        print("No valid application data found", file=sys.stderr)
        return 1

    results = predict_batch(apps, args.budget)

    # Filter by type if needed
    if args.type == "lag":
        results["cost_risks"] = []
    elif args.type == "cost":
        results["lag_risks"] = []

    if args.format == "json":
        print(format_predict_json(results))
    else:
        print(format_predict_markdown(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
