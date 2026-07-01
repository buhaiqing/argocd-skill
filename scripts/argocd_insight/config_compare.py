"""Config comparison and environment diff for ArgoCD applications.

Compares application configurations across environments (dev/staging/prod)
to detect drift, inconsistencies, and configuration differences.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def normalize_config(app_data: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize comparison-relevant fields from app data.

    Returns a clean dict with only fields that matter for comparison:
    - source (repo, revision, path)
    - destination (server, namespace)
    - syncPolicy
    - helm / kustomize overrides
    """
    spec = app_data.get("spec", {})

    result: dict[str, Any] = {}

    # Source comparison
    source = spec.get("source", {})
    if source:
        result["source"] = {
            "repoURL": source.get("repoURL", ""),
            "targetRevision": source.get("targetRevision", ""),
            "path": source.get("path", ""),
        }
        # Helm values
        if "helm" in source:
            helm = source["helm"]
            result["source"]["helm"] = {}
            if "valueFiles" in helm:
                result["source"]["helm"]["valueFiles"] = sorted(helm["valueFiles"])
            if "parameters" in helm:
                result["source"]["helm"]["parameters"] = sorted(
                    [{"name": p.get("name", ""), "value": p.get("value", "")}
                     for p in helm["parameters"]],
                    key=lambda x: x["name"],
                )
            if "values" in helm:
                result["source"]["helm"]["values"] = helm["values"]
        # Kustomize overrides
        if "kustomize" in source:
            ks = source["kustomize"]
            result["source"]["kustomize"] = {}
            for key in ("namePrefix", "commonLabels", "images"):
                if key in ks:
                    result["source"]["kustomize"][key] = ks[key]

    # Destination comparison
    dest = spec.get("destination", {})
    if dest:
        result["destination"] = {
            "server": dest.get("server", ""),
            "namespace": dest.get("namespace", ""),
        }

    # Sync policy
    sync_policy = spec.get("syncPolicy", {})
    if sync_policy:
        result["syncPolicy"] = {}
        auto = sync_policy.get("automated", {})
        if auto:
            result["syncPolicy"]["automated"] = {
                "prune": auto.get("prune", False),
                "selfHeal": auto.get("selfHeal", False),
            }
        if "syncOptions" in sync_policy:
            result["syncPolicy"]["syncOptions"] = sorted(sync_policy["syncOptions"])

    return result


def diff_configs(
    config_a: dict[str, Any],
    config_b: dict[str, Any],
    label_a: str = "A",
    label_b: str = "B",
) -> list[dict[str, str]]:
    """Compare two normalized configs and return list of differences.

    Each diff item: {"path": "source.repoURL", "a": "value1", "b": "value2"}
    """
    diffs: list[dict[str, str]] = []

    def _compare(a: Any, b: Any, prefix: str) -> None:
        if type(a) != type(b):
            diffs.append({"path": prefix, "a": str(a), "b": str(b)})
            return
        if isinstance(a, dict):
            all_keys = set(a.keys()) | set(b.keys())
            for key in sorted(all_keys):
                if key not in a:
                    diffs.append({"path": f"{prefix}.{key}", "a": "(missing)", "b": str(b[key])})
                elif key not in b:
                    diffs.append({"path": f"{prefix}.{key}", "a": str(a[key]), "b": "(missing)"})
                else:
                    _compare(a[key], b[key], f"{prefix}.{key}")
        elif isinstance(a, list):
            if a != b:
                diffs.append({"path": prefix, "a": str(a), "b": str(b)})
        else:
            if a != b:
                diffs.append({"path": prefix, "a": str(a), "b": str(b)})

    _compare(config_a, config_b, "root")
    return diffs


def compare_applications(
    apps: dict[str, dict[str, Any]],
    groups: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Compare configurations of multiple applications.

    Args:
        apps: dict of app_name -> app_data (raw ArgoCD app JSON)
        groups: optional dict of group_name -> [app_names] for grouped comparison

    Returns:
        Comparison results with diffs per group
    """
    if not apps:
        return {"error": "No applications provided"}

    # Normalize all configs
    normalized = {}
    for name, data in apps.items():
        normalized[name] = normalize_config(data)

    # Auto-group by similar source path pattern if no groups provided
    if groups is None:
        groups = _auto_group(apps)

    results: dict[str, Any] = {
        "app_count": len(apps),
        "group_count": len(groups),
        "groups": {},
    }

    for group_name, app_names in groups.items():
        if len(app_names) < 2:
            results["groups"][group_name] = {
                "apps": app_names,
                "diffs": [],
                "summary": "Single app — no comparison possible",
            }
            continue

        # Compare all pairs in the group
        all_diffs: dict[str, int] = {}
        for i in range(len(app_names)):
            for j in range(i + 1, len(app_names)):
                a_name, b_name = app_names[i], app_names[j]
                if a_name not in normalized or b_name not in normalized:
                    continue
                pair_diffs = diff_configs(
                    normalized[a_name], normalized[b_name],
                    label_a=a_name, label_b=b_name,
                )
                for d in pair_diffs:
                    path = d["path"]
                    if path not in all_diffs:
                        all_diffs[path] = 0
                    all_diffs[path] += 1

        # Sort by frequency (most common diffs first)
        sorted_diffs = sorted(all_diffs.items(), key=lambda x: -x[1])

        results["groups"][group_name] = {
            "apps": app_names,
            "diff_count": len(sorted_diffs),
            "top_diffs": [{"path": p, "occurrences": c} for p, c in sorted_diffs[:10]],
            "summary": _summarize_group(app_names, sorted_diffs),
        }

    # Overall summary
    total_diffs = sum(g.get("diff_count", 0) for g in results["groups"].values())
    results["total_diffs"] = total_diffs
    results["summary"] = (
        f"{len(apps)} apps in {len(groups)} groups, {total_diffs} unique config differences"
    )

    return results


def _auto_group(apps: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Auto-group apps by source repoURL + path prefix."""
    from collections import defaultdict

    groups: dict[str, list[str]] = defaultdict(list)
    for name, data in apps.items():
        spec = data.get("spec", {})
        source = spec.get("source", {})
        repo = source.get("repoURL", "unknown")
        path = source.get("path", "root")
        # Use repo + parent dir as group key
        parts = path.strip("/").split("/")
        group_key = f"{repo}::{parts[0] if parts else 'root'}"
        groups[group_key].append(name)

    return dict(groups)


def _summarize_group(app_names: list[str], diffs: list[tuple[str, int]]) -> str:
    """Generate a one-line summary for a group."""
    if not diffs:
        return f"All {len(app_names)} apps have identical config"
    top = diffs[0]
    return (
        f"{len(app_names)} apps, {len(diffs)} diffs — "
        f"most common: {top[0]} ({top[1]} occurrences)"
    )


def format_compare_markdown(results: dict[str, Any]) -> str:
    """Format comparison results as Markdown report."""
    if "error" in results:
        return f"⚠️ {results['error']}"

    lines = [
        "# 配置对比报告",
        "",
        f"**应用数**: {results['app_count']} | "
        f"**分组数**: {results['group_count']} | "
        f"**总差异数**: {results['total_diffs']}",
        "",
        results.get("summary", ""),
        "",
    ]

    for group_name, group_data in results.get("groups", {}).items():
        lines.append(f"## {group_name}")
        lines.append("")
        lines.append(f"应用: {', '.join(group_data.get('apps', []))}")
        lines.append("")

        if group_data.get("diffs"):
            lines.append(group_data["summary"])
        elif group_data.get("diff_count", 0) > 0:
            lines.append(f"差异 {group_data['diff_count']} 处:")
            for diff in group_data.get("top_diffs", []):
                lines.append(f"- `{diff['path']}` ({diff['occurrences']} 次)")
        else:
            lines.append(group_data.get("summary", "无差异"))

        lines.append("")

    return "\n".join(lines)


def format_compare_json(results: dict[str, Any]) -> str:
    """Format comparison results as JSON."""
    return json.dumps(results, indent=2, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for config comparison."""
    parser = argparse.ArgumentParser(
        prog="argocd_insight config-compare",
        description="Compare ArgoCD application configurations across environments",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Paths to ArgoCD app JSON files (output of argocd app get -o json)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--group", "-g",
        action="append",
        help="Group apps for comparison: group_name=app1,app2 (can repeat)",
    )

    args = parser.parse_args(argv)

    # Load app data from files
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

    # Parse groups if provided
    groups = None
    if args.group:
        groups = {}
        for g in args.group:
            if "=" not in g:
                print(f"Invalid group format: {g} (expected name=app1,app2)", file=sys.stderr)
                return 1
            name, app_list = g.split("=", 1)
            groups[name] = [a.strip() for a in app_list.split(",")]

    results = compare_applications(apps, groups)

    if args.format == "json":
        print(format_compare_json(results))
    else:
        print(format_compare_markdown(results))

    return 0


if __name__ == "__main__":
    sys.exit(main())
