"""ArgoCD Application 配置模板生成器 (scaffold)。

根据 4-tier 模型快速生成 ArgoCD Application YAML 和等价 CLI 命令。

Usage:
  python -m argocd_insight scaffold my-app --tier business  \\
    --namespace production --project default \\
    --repo https://github.com/org/repo.git --path apps/my-app

  python -m argocd_insight scaffold my-root --tier root  \\
    --namespace argo-root --project default \\
    --repo https://github.com/org/repo.git --path apps/root --sync-policy automated

  python -m argocd_insight scaffold my-app --output json

  python -m argocd_insight scaffold --list-tiers
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 4-tier model definitions
# ---------------------------------------------------------------------------

TIERS = {
    "root": {
        "label": "聚合入口 Root",
        "default_namespace": "argo-root",
        "desc": "App-of-Apps 聚合入口，必须开启 automated",
        "sync_policy": "automated",
        "auto_prune": True,
        "self_heal": True,
        "create_namespace": True,
        "labels": {},
    },
    "business": {
        "label": "业务应用",
        "default_namespace": "",
        "desc": "业务应用，手动同步，需 labels 四件套",
        "sync_policy": "manual",
        "auto_prune": False,
        "self_heal": False,
        "create_namespace": True,
        "labels": {
            "project": None,
            "profile": None,
            "stack": None,
            "app": None,
        },
    },
    "ops": {
        "label": "运维组件",
        "default_namespace": "ops",
        "desc": "运维组件如 Prometheus/Loki，通常不开 CreateNamespace",
        "sync_policy": "manual",
        "auto_prune": False,
        "self_heal": False,
        "create_namespace": False,
        "labels": {},
    },
    "infra_root": {
        "label": "基础设施 Root",
        "default_namespace": "argo-root",
        "desc": "基础设施初始化：projects/repos/initns",
        "sync_policy": "manual",
        "auto_prune": False,
        "self_heal": False,
        "create_namespace": False,
        "labels": {},
    },
}

SOURCE_TYPES = {"kustomize", "helm"}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ScaffoldInput:
    """Input parameters for scaffold generation."""
    name: str
    tier: str
    namespace: str
    project: str
    repo_url: str
    path: str
    revision: str
    source_type: str
    helm_chart: str
    helm_repo: str
    sync_policy: str
    auto_prune: bool
    self_heal: bool
    create_namespace: bool
    labels: dict[str, str]
    output_format: str  # "yaml" | "cli" | "both"
    helm_values: str = ""
    extra_args: list[str] = field(default_factory=list)


@dataclass
class ScaffoldResult:
    """Generated scaffold output."""
    name: str
    tier: str
    yaml: str
    cli_command: str
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------

def _indent(text: str, level: int = 2) -> str:
    """Indent text by `level` spaces."""
    indent = " " * level
    return "\n".join(f"{indent}{line}" if line.strip() else line for line in text.splitlines())


def _generate_yaml(inputs: ScaffoldInput) -> str:
    """Generate ArgoCD Application YAML from input parameters."""
    lines: list[str] = [
        "apiVersion: argoproj.io/v1alpha1",
        "kind: Application",
        "metadata:",
        f"  name: {inputs.name}",
    ]

    if inputs.labels:
        lines.append("  labels:")
        for key, val in sorted(inputs.labels.items()):
            if val:
                lines.append(f"    {key}: {val}")
        lines.append("")

    lines.append("spec:")
    lines.append("  project: " + inputs.project)

    # Source block
    if inputs.source_type == "helm":
        lines.append("  source:")
        lines.append(f"    repoURL: {inputs.repo_url}")
        lines.append(f"    chart: {inputs.helm_chart}")
        lines.append(f"    targetRevision: {inputs.revision}")
        lines.append("    helm:")
        lines.append("      valueFiles:")
        lines.append(f"        - {inputs.path}")
    else:
        lines.append("  source:")
        lines.append(f"    repoURL: {inputs.repo_url}")
        lines.append(f"    path: {inputs.path}")
        lines.append(f"    targetRevision: {inputs.revision}")

    # Destination block
    lines.append("  destination:")
    lines.append("    server: https://kubernetes.default.svc")
    lines.append(f"    namespace: {inputs.namespace}")

    # Sync policy block
    if inputs.sync_policy == "automated":
        lines.append("  syncPolicy:")
        lines.append("    automated:")
        lines.append(f"      prune: {str(inputs.auto_prune).lower()}")
        lines.append(f"      selfHeal: {str(inputs.self_heal).lower()}")
        if inputs.create_namespace:
            lines.append("    syncOptions:")
            lines.append("      - CreateNamespace=true")
    elif inputs.create_namespace:
        lines.append("  syncPolicy:")
        lines.append("    syncOptions:")
        lines.append("      - CreateNamespace=true")

    # Extra args as annotations
    if inputs.extra_args:
        if "metadata.annotations" not in str(inputs.extra_args):
            lines.append("  annotations:")
            for arg in inputs.extra_args:
                if "=" in arg:
                    k, v = arg.split("=", 1)
                    lines.append(f"    {k}: {v}")

    return "\n".join(lines) + "\n"


def _generate_cli(inputs: ScaffoldInput) -> str:
    """Generate `argocd app create` CLI command from input parameters."""
    cmd = ["argocd", "app", "create", inputs.name]

    # Project
    cmd += ["--project", inputs.project]

    # Source
    if inputs.source_type == "helm":
        cmd += ["--repo", inputs.repo_url]
        cmd += ["--helm-chart", inputs.helm_chart]
        cmd += ["--revision", inputs.revision]
        cmd += ["--helm-values", inputs.helm_values or inputs.path]
    else:
        cmd += ["--repo", inputs.repo_url]
        cmd += ["--path", inputs.path]
        cmd += ["--revision", inputs.revision]

    # Destination
    cmd += ["--dest-server", "https://kubernetes.default.svc"]
    cmd += ["--dest-namespace", inputs.namespace]

    # Sync policy
    if inputs.sync_policy == "automated":
        cmd += ["--sync-policy", "automated"]
        if inputs.auto_prune:
            cmd.append("--auto-prune")
        if inputs.self_heal:
            cmd.append("--self-heal")

    # CreateNamespace
    if inputs.create_namespace:
        cmd += ["--sync-option", "CreateNamespace=true"]

    # Labels
    for key, val in sorted(inputs.labels.items()):
        if val:
            cmd += ["--label", f"{key}={val}"]

    # Upsert for safety
    cmd.append("--upsert")

    return " \\\n  ".join(cmd)


# ---------------------------------------------------------------------------
# Core scaffolding function
# ---------------------------------------------------------------------------

def scaffold_app(inputs: ScaffoldInput) -> ScaffoldResult:
    """Generate ArgoCD Application template (YAML + CLI command).

    Validates inputs against the 4-tier model and returns the scaffold result.
    """
    warnings: list[str] = []

    # Validate tier
    if inputs.tier not in TIERS:
        valid = ", ".join(sorted(TIERS))
        warnings.append(f"未知层级 '{inputs.tier}'，可用: {valid}，使用默认 business 行为")

    # Validate source type
    if inputs.source_type not in SOURCE_TYPES:
        warnings.append(f"未知源类型 '{inputs.source_type}'，使用默认 kustomize")

    # Tier-specific validation
    if inputs.tier == "root" and inputs.sync_policy != "automated":
        warnings.append("Root 层级应用应使用 automated sync policy")
    elif inputs.tier == "business" and inputs.sync_policy == "automated":
        warnings.append("业务应用通常不使用 automated sync policy（生产规范要求手动同步）")
    if inputs.tier == "root" and not inputs.auto_prune:
        warnings.append("Root 层级应用建议启用 auto-prune")

    # Namespace validation
    if inputs.namespace == "argo-root" and inputs.create_namespace is False:
        warnings.append("argo-root 命名空间已存在，无需 CreateNamespace=true，已自动调整")

    # Generate YAML and CLI
    yaml_output = _generate_yaml(inputs)
    cli_output = _generate_cli(inputs)

    return ScaffoldResult(
        name=inputs.name,
        tier=inputs.tier,
        yaml=yaml_output,
        cli_command=cli_output,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_result_markdown(result: ScaffoldResult) -> str:
    """Format scaffold result as markdown."""
    lines = [f"# ArgoCD App Scaffold: {result.name}", ""]

    lines.append(f"**层级:** {result.tier} ({TIERS.get(result.tier, {}).get('label', '未知')})")
    lines.append("")

    if result.warnings:
        lines.append("## ⚠️ 警告\n")
        for w in result.warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Application YAML\n")
    lines.append("```yaml")
    lines.append(result.yaml.strip())
    lines.append("```")
    lines.append("")

    lines.append("## CLI Command\n")
    lines.append("```bash")
    lines.append(result.cli_command)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def _format_tiers_markdown() -> str:
    """Format tier definitions as markdown."""
    lines = ["# ArgoCD 4-Tier Model\n", ""]
    lines.append("| Tier | 说明 | 默认 Namespace | Sync Policy | CreateNamespace | Labels |")
    lines.append("|------|------|---------------|-------------|-----------------|--------|")

    for name, cfg in TIERS.items():
        label = cfg["label"]
        ns = cfg["default_namespace"] or "需指定"
        sp = cfg["sync_policy"]
        cn = "true" if cfg["create_namespace"] else "false"
        labels = ", ".join(cfg["labels"].keys()) if cfg["labels"] else "-"
        lines.append(f"| {name} | {label} | {ns} | {sp} | {cn} | {labels} |")

    lines.append("")
    return "\n".join(lines)


def _format_result_json(result: ScaffoldResult) -> str:
    """Format scaffold result as JSON."""
    data = {
        "app": result.name,
        "tier": result.tier,
        "yaml": result.yaml.strip(),
        "cli_command": result.cli_command,
        "warnings": result.warnings,
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ArgoCD Application 配置模板生成器",
    )
    parser.add_argument("name", nargs="?", help="应用名称")
    parser.add_argument("--tier", choices=list(TIERS), default="business",
                        help="App 层级（默认: business）")
    parser.add_argument("--namespace", default="", help="目标命名空间")
    parser.add_argument("--project", default="default", help="ArgoCD Project（默认: default）")
    parser.add_argument("--repo", dest="repo_url", default="",
                        help="Git 仓库 URL")
    parser.add_argument("--path", default="", help="Kustomize 路径")
    parser.add_argument("--revision", default="HEAD", help="Git 分支/SHA（默认: HEAD）")
    parser.add_argument("--source-type", choices=list(SOURCE_TYPES), default="kustomize",
                        help="源类型（默认: kustomize）")
    parser.add_argument("--helm-chart", default="", help="Helm Chart 名称")
    parser.add_argument("--helm-repo", default="", help="Helm Repo URL")
    parser.add_argument("--helm-values", default="", help="Helm values 文件路径")
    parser.add_argument("--sync-policy", choices=["manual", "automated"], default="manual",
                        help="同步策略（默认: manual）")
    parser.add_argument("--auto-prune", action="store_true", default=None,
                        help="启用 automated prune")
    parser.add_argument("--no-auto-prune", action="store_false", dest="auto_prune", default=None,
                        help="禁用 automated prune")
    parser.add_argument("--self-heal", action="store_true", default=None,
                        help="启用 automated self-heal")
    parser.add_argument("--no-self-heal", action="store_false", dest="self_heal", default=None,
                        help="禁用 automated self-heal")
    parser.add_argument("--create-namespace", action="store_true", default=None,
                        help="启用 CreateNamespace")
    parser.add_argument("--no-create-namespace", action="store_false", dest="create_namespace",
                        default=None, help="禁用 CreateNamespace")
    parser.add_argument("--label", action="append", default=[],
                        help="标签: key=value（可重复）")
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown",
                        help="输出格式（默认: markdown）")
    parser.add_argument("--list-tiers", action="store_true",
                        help="列出所有可用层级定义")

    args = parser.parse_args(argv)

    # Handle --list-tiers
    if args.list_tiers:
        print(_format_tiers_markdown())
        return 0

    # Name is required for generation
    if not args.name:
        parser.error("需要应用名称，或使用 --list-tiers 查看层级定义")

    # Resolve tier defaults
    tier_def = TIERS.get(args.tier, TIERS["business"])

    # Resolve namespace
    namespace = args.namespace or tier_def["default_namespace"] or "default"

    # Resolve sync policy from tier or args
    if args.sync_policy:
        sync_policy = args.sync_policy
    else:
        sync_policy = tier_def["sync_policy"]

    # Resolve boolean flags with tier fallback
    auto_prune = args.auto_prune if args.auto_prune is not None else tier_def["auto_prune"]
    self_heal = args.self_heal if args.self_heal is not None else tier_def["self_heal"]
    create_namespace = (
        args.create_namespace
        if args.create_namespace is not None
        else tier_def["create_namespace"]
    )

    # Parse labels
    labels: dict[str, str] = {}
    for label in args.label:
        if "=" in label:
            key, val = label.split("=", 1)
            labels[key.strip()] = val.strip()
        else:
            labels[label.strip()] = ""

    inputs = ScaffoldInput(
        name=args.name,
        tier=args.tier,
        namespace=namespace,
        project=args.project,
        repo_url=args.repo_url,
        path=args.path,
        revision=args.revision or "HEAD",
        source_type=args.source_type,
        helm_chart=args.helm_chart,
        helm_repo=args.helm_repo,
        helm_values=args.helm_values,
        sync_policy=sync_policy,
        auto_prune=auto_prune,
        self_heal=self_heal,
        create_namespace=create_namespace,
        labels=labels,
        output_format=args.output,
    )

    result = scaffold_app(inputs)

    if args.output == "json":
        print(_format_result_json(result))
    else:
        print(_format_result_markdown(result))

    return 1 if result.warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())