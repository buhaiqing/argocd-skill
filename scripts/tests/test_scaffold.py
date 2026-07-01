"""Tests for scaffold.py — Application 配置模板生成器。"""
from __future__ import annotations

import json
import pytest

from argocd_insight.scaffold import (
    TIERS,
    ScaffoldInput,
    ScaffoldResult,
    scaffold_app,
    _generate_yaml,
    _generate_cli,
    _format_result_markdown,
    _format_result_json,
    _format_tiers_markdown,
    main,
)


# ── CLI helper functions ──────────────────────────────────────────

def _cli_has_flag(cmd: str, flag: str, value: str | None = None) -> bool:
    """Normalise `` \\\n  `` wrapping and check if *flag* (optionally +*value*) exists."""
    lines = [l.strip().rstrip("\\").strip() for l in cmd.split("\n")]
    for i, l in enumerate(lines):
        if l == flag:
            if value is None:
                return True
            if i + 1 < len(lines) and lines[i + 1] == value:
                return True
    return False


def _cli_startswith(cmd: str, prefix: str) -> bool:
    """Normalise wrapping and check if command starts with *prefix*."""
    normalized = " ".join(l.strip().rstrip("\\").strip() for l in cmd.split("\n"))
    return normalized.startswith(prefix)


# ── Fixtures ──────────────────────────────────────────────────────

def _make_input(**overrides: str | bool | dict | list | None) -> ScaffoldInput:
    """Helper to create a ScaffoldInput with sensible defaults."""
    defaults: dict = dict(
        name="test-app",
        tier="business",
        namespace="production",
        project="default",
        repo_url="https://github.com/org/repo.git",
        path="apps/my-app",
        revision="HEAD",
        source_type="kustomize",
        helm_chart="",
        helm_repo="",
        sync_policy="manual",
        auto_prune=False,
        self_heal=False,
        create_namespace=True,
        labels={},
        output_format="both",
        helm_values="",
        extra_args=[],
    )
    defaults.update(overrides)
    return ScaffoldInput(**defaults)


# ── _generate_yaml tests ─────────────────────────────────────────

class TestGenerateYaml:
    """_generate_yaml 单元测试。"""

    def test_basic_structure(self) -> None:
        inputs = _make_input()
        yaml = _generate_yaml(inputs)
        assert "apiVersion: argoproj.io/v1alpha1" in yaml
        assert "kind: Application" in yaml
        assert "  name: test-app" in yaml

    def test_helm_source(self) -> None:
        """Helm 源应输出 chart + valueFiles 而非 path。"""
        inputs = _make_input(
            source_type="helm",
            helm_chart="nginx-ingress",
            repo_url="https://charts.nginx.org",
            path="values/prod.yaml",
        )
        yaml = _generate_yaml(inputs)
        assert "chart: nginx-ingress" in yaml
        assert "repoURL: https://charts.nginx.org" in yaml
        assert "valueFiles:" in yaml
        assert "      - values/prod.yaml" in yaml
        assert "path:" not in yaml

    def test_automated_sync_policy(self) -> None:
        """automated 模式应输出 prune + selfHeal 块。"""
        inputs = _make_input(sync_policy="automated", auto_prune=True, self_heal=True)
        yaml = _generate_yaml(inputs)
        assert "syncPolicy:" in yaml
        assert "automated:" in yaml
        assert "prune: true" in yaml
        assert "selfHeal: true" in yaml

    def test_labels_included(self) -> None:
        """有 labels 时应在 metadata 中输出。"""
        inputs = _make_input(labels={"project": "my-proj", "stack": "backend"})
        yaml = _generate_yaml(inputs)
        assert "  labels:" in yaml
        assert "project: my-proj" in yaml
        assert "stack: backend" in yaml

    def test_create_namespace_in_sync_policy(self) -> None:
        """manual 模式下，CreateNamespace=true 应出现在 syncPolicy。"""
        inputs = _make_input(create_namespace=True)
        yaml = _generate_yaml(inputs)
        assert "syncPolicy:" in yaml
        assert "syncOptions:" in yaml
        assert "- CreateNamespace=true" in yaml

    def test_no_sync_policy_when_not_needed(self) -> None:
        """manual 且 create_namespace=False 时不应有 syncPolicy。"""
        inputs = _make_input(sync_policy="manual", create_namespace=False)
        yaml = _generate_yaml(inputs)
        assert "syncPolicy:" not in yaml


# ── _generate_cli tests ──────────────────────────────────────────

class TestGenerateCli:
    """_generate_cli 单元测试。"""

    def test_basic_kustomize(self) -> None:
        inputs = _make_input()
        cmd = _generate_cli(inputs)
        assert _cli_startswith(cmd, "argocd app create test-app")
        assert _cli_has_flag(cmd, "--repo", "https://github.com/org/repo.git")
        assert _cli_has_flag(cmd, "--path", "apps/my-app")
        assert _cli_has_flag(cmd, "--dest-namespace", "production")
        assert _cli_has_flag(cmd, "--upsert")

    def test_helm_source(self) -> None:
        """Helm 应输出 --helm-chart 而非 --path。"""
        inputs = _make_input(
            source_type="helm",
            helm_chart="nginx-ingress",
            helm_values="values/prod.yaml",
            repo_url="https://charts.nginx.org",
            path="",
        )
        cmd = _generate_cli(inputs)
        assert _cli_has_flag(cmd, "--helm-chart", "nginx-ingress")
        assert _cli_has_flag(cmd, "--helm-values", "values/prod.yaml")
        assert not _cli_has_flag(cmd, "--path")

    def test_automated_flags(self) -> None:
        """automated 模式应输出 --sync-policy --auto-prune --self-heal。"""
        inputs = _make_input(
            sync_policy="automated", auto_prune=True, self_heal=True,
        )
        cmd = _generate_cli(inputs)
        assert _cli_has_flag(cmd, "--sync-policy", "automated")
        assert _cli_has_flag(cmd, "--auto-prune")
        assert _cli_has_flag(cmd, "--self-heal")

    def test_create_namespace_flag(self) -> None:
        inputs = _make_input(create_namespace=True)
        cmd = _generate_cli(inputs)
        assert _cli_has_flag(cmd, "--sync-option", "CreateNamespace=true")

    def test_labels_as_cli_flags(self) -> None:
        inputs = _make_input(labels={"app": "my-app", "stack": "backend"})
        cmd = _generate_cli(inputs)
        assert _cli_has_flag(cmd, "--label", "app=my-app")
        assert _cli_has_flag(cmd, "--label", "stack=backend")


# ── scaffold_app tests ───────────────────────────────────────────

class TestScaffoldApp:
    """scaffold_app 核心逻辑测试。"""

    def test_basic_scaffold(self) -> None:
        inputs = _make_input()
        result = scaffold_app(inputs)
        assert result.name == "test-app"
        assert result.tier == "business"
        assert "apiVersion: argoproj.io/v1alpha1" in result.yaml
        assert _cli_startswith(result.cli_command, "argocd app create test-app")
        assert result.warnings == []

    def test_unknown_tier_warning(self) -> None:
        inputs = _make_input(tier="unknown")
        result = scaffold_app(inputs)
        assert any("未知层级" in w for w in result.warnings)

    def test_root_tier_manual_sync_warning(self) -> None:
        """root tier 未使用 automated 应提示。"""
        inputs = _make_input(tier="root", namespace="argo-root", sync_policy="manual")
        result = scaffold_app(inputs)
        assert any("Root" in w and "automated" in w for w in result.warnings)

    def test_business_tier_automated_warning(self) -> None:
        """business tier 使用 automated 应提示。"""
        inputs = _make_input(tier="business", sync_policy="automated")
        result = scaffold_app(inputs)
        assert any("业务应用" in w and "automated" in w for w in result.warnings)

    def test_unknown_source_type_warning(self) -> None:
        inputs = _make_input(source_type="custom")
        result = scaffold_app(inputs)
        assert any("未知源类型" in w for w in result.warnings)

    def test_argo_root_no_create_namespace_warning(self) -> None:
        """namespace=argo-root 且 create_namespace=False 应提示。"""
        inputs = _make_input(namespace="argo-root", create_namespace=False)
        result = scaffold_app(inputs)
        assert any("argo-root" in w and "无需 CreateNamespace" in w for w in result.warnings)

    def test_return_code_with_warnings(self) -> None:
        """有 warning 时 main() 应返回 1。"""
        rc = main([
            "my-app", "--tier", "business", "--namespace", "prod",
            "--repo", "https://r.git", "--path", "apps/app",
            "--sync-policy", "automated",
        ])
        assert rc == 1

    def test_return_code_clean(self) -> None:
        """无 warning 时 main() 应返回 0。"""
        rc = main([
            "my-app", "--tier", "business", "--namespace", "prod",
            "--repo", "https://r.git", "--path", "apps/app",
        ])
        assert rc == 0


# ── Formatting tests ─────────────────────────────────────────────

class TestFormatting:
    """格式化输出测试。"""

    def test_markdown_includes_yaml_and_cli(self) -> None:
        result = ScaffoldResult(
            name="my-app", tier="business",
            yaml="kind: Application", cli_command="argocd app create my-app",
            warnings=[],
        )
        md = _format_result_markdown(result)
        assert "my-app" in md
        assert "kind: Application" in md
        assert "argocd app create my-app" in md

    def test_markdown_with_warnings(self) -> None:
        result = ScaffoldResult(
            name="my-app", tier="business",
            yaml="kind: Application", cli_command="argocd app create my-app",
            warnings=["测试警告"],
        )
        md = _format_result_markdown(result)
        assert "⚠️" in md
        assert "测试警告" in md

    def test_json_output(self) -> None:
        result = ScaffoldResult(
            name="my-app", tier="root",
            yaml="kind: Application", cli_command="argocd app create my-app",
            warnings=["warn"],
        )
        data = json.loads(_format_result_json(result))
        assert data["app"] == "my-app"
        assert data["tier"] == "root"
        assert data["warnings"] == ["warn"]

    def test_tiers_table(self) -> None:
        table = _format_tiers_markdown()
        assert "4-Tier Model" in table or "4-Tier" in table
        for name in TIERS:
            assert name in table


# ── main() CLI entry tests ───────────────────────────────────────

class TestMain:
    """main() CLI 入口集成测试。"""

    def test_list_tiers(self) -> None:
        """--list-tiers 应返回 tier 列表且 exit 0。"""
        rc = main(["--list-tiers"])
        assert rc == 0

    def test_json_output(self) -> None:
        """--output json 应输出可解析的 JSON。"""
        # Capture stdout
        import io
        import sys
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        try:
            rc = main([
                "test-app", "--tier", "business", "--namespace", "prod",
                "--repo", "https://r.git", "--path", "apps/app",
                "--output", "json",
            ])
        finally:
            sys.stdout = old_stdout
        assert rc == 0
        data = json.loads(buffer.getvalue())
        assert data["app"] == "test-app"
        assert data["tier"] == "business"

    def test_name_required(self) -> None:
        """未提供应用名称且无 --list-tiers 时应报错。"""
        with pytest.raises(SystemExit):
            main(["--tier", "business"])

    def test_helm_scaffold(self) -> None:
        """Helm 源 scaffold 应正确生成。"""
        result = scaffold_app(_make_input(
            source_type="helm",
            helm_chart="nginx",
            repo_url="https://charts.nginx.org",
            helm_values="values/prod.yaml",
            path="",
        ))
        assert "chart: nginx" in result.yaml
        assert _cli_has_flag(result.cli_command, "--helm-chart", "nginx")

    def test_root_tier_defaults(self) -> None:
        """Root tier default (manual sync) 应产生 warning。"""
        inputs = _make_input(tier="root", namespace="argo-root")
        result = scaffold_app(inputs)
        assert any("Root" in w and "automated" in w for w in result.warnings)

    def test_ops_tier_create_namespace_false(self) -> None:
        """Ops tier 默认 CreateNamespace=false。"""
        result = scaffold_app(_make_input(tier="ops", namespace="ops", create_namespace=False))
        assert not _cli_has_flag(result.cli_command, "--sync-option", "CreateNamespace=true")
        assert "syncPolicy:" not in result.yaml

    def test_labels_with_cli_flag(self) -> None:
        """--label 参数应传递到 CLI 命令。"""
        rc = main([
            "my-app", "--tier", "business", "--namespace", "prod",
            "--repo", "https://r.git", "--path", "apps/app",
            "--label", "project=p1", "--label", "stack=s1",
            "--output", "json",
        ])
        assert rc == 0

    def test_helm_values_fallback(self) -> None:
        """--helm-values 未设时降级使用 --path。"""
        inputs = _make_input(
            source_type="helm", helm_chart="nginx",
            path="values/prod.yaml",
            helm_values="",
            repo_url="https://charts.nginx.org",
        )
        cmd = _generate_cli(inputs)
        assert _cli_has_flag(cmd, "--helm-values", "values/prod.yaml")