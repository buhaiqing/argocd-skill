"""Tests for config_compare.py"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argocd_insight.config_compare import (
    compare_applications,
    diff_configs,
    format_compare_json,
    format_compare_markdown,
    main,
    normalize_config,
)


def _make_app(
    repo: str = "https://github.com/test/repo",
    revision: str = "main",
    path: str = "apps/test",
    namespace: str = "default",
    server: str = "https://kubernetes.default.svc",
    helm: dict | None = None,
    sync_policy: dict | None = None,
    name: str = "test-app",
) -> dict:
    spec: dict = {
        "source": {"repoURL": repo, "targetRevision": revision, "path": path},
        "destination": {"server": server, "namespace": namespace},
    }
    if helm:
        spec["source"]["helm"] = helm
    if sync_policy:
        spec["syncPolicy"] = sync_policy
    return {"metadata": {"name": name}, "spec": spec}


class TestNormalizeConfig:
    def test_basic(self):
        app = _make_app()
        result = normalize_config(app)
        assert result["source"]["repoURL"] == "https://github.com/test/repo"
        assert result["source"]["targetRevision"] == "main"
        assert result["destination"]["namespace"] == "default"

    def test_helm_values(self):
        app = _make_app(helm={
            "valueFiles": ["values-prod.yaml", "values.yaml"],
            "parameters": [
                {"name": "replicas", "value": "3"},
                {"name": "image.tag", "value": "v1.0"},
            ],
        })
        result = normalize_config(app)
        helm = result["source"]["helm"]
        assert helm["valueFiles"] == ["values-prod.yaml", "values.yaml"]
        assert helm["parameters"][0]["name"] == "image.tag"
        assert helm["parameters"][1]["name"] == "replicas"

    def test_sync_policy(self):
        app = _make_app(sync_policy={
            "automated": {"prune": True, "selfHeal": False},
            "syncOptions": ["CreateNamespace=true", "PrunePropagationPolicy=foreground"],
        })
        result = normalize_config(app)
        assert result["syncPolicy"]["automated"]["prune"] is True
        assert result["syncPolicy"]["automated"]["selfHeal"] is False
        assert result["syncPolicy"]["syncOptions"] == [
            "CreateNamespace=true", "PrunePropagationPolicy=foreground"
        ]

    def test_empty_spec(self):
        result = normalize_config({"metadata": {"name": "empty"}})
        assert "source" not in result
        assert "destination" not in result


class TestDiffConfigs:
    def test_identical(self):
        a = {"source": {"repoURL": "x"}, "destination": {"ns": "a"}}
        assert diff_configs(a, a) == []

    def test_different_values(self):
        a = {"source": {"repoURL": "repo-a"}}
        b = {"source": {"repoURL": "repo-b"}}
        diffs = diff_configs(a, b)
        assert len(diffs) == 1
        assert diffs[0]["path"] == "root.source.repoURL"
        assert diffs[0]["a"] == "repo-a"
        assert diffs[0]["b"] == "repo-b"

    def test_missing_key(self):
        a = {"source": {"repoURL": "x", "path": "a"}}
        b = {"source": {"repoURL": "x"}}
        diffs = diff_configs(a, b)
        assert len(diffs) == 1
        assert "missing" in diffs[0]["b"]

    def test_type_mismatch(self):
        a = {"syncPolicy": {"automated": True}}
        b = {"syncPolicy": {"automated": {"prune": True}}}
        diffs = diff_configs(a, b)
        assert len(diffs) >= 1


class TestCompareApplications:
    def test_identical_apps(self):
        apps = {
            "app-a": _make_app(name="app-a", path="apps/test"),
            "app-b": _make_app(name="app-b", path="apps/test"),
        }
        result = compare_applications(apps)
        assert result["total_diffs"] == 0

    def test_different_apps(self):
        apps = {
            "app-a": _make_app(name="app-a", namespace="ns-a"),
            "app-b": _make_app(name="app-b", namespace="ns-b"),
        }
        result = compare_applications(apps)
        assert result["total_diffs"] > 0

    def test_empty_apps(self):
        result = compare_applications({})
        assert "error" in result

    def test_custom_groups(self):
        apps = {
            "app-a": _make_app(name="app-a"),
            "app-b": _make_app(name="app-b", namespace="other"),
        }
        groups = {"group1": ["app-a", "app-b"]}
        result = compare_applications(apps, groups)
        assert result["group_count"] == 1

    def test_single_app_group(self):
        apps = {"app-a": _make_app(name="app-a")}
        groups = {"lonely": ["app-a"]}
        result = compare_applications(apps, groups)
        assert result["groups"]["lonely"]["summary"] == "Single app — no comparison possible"


class TestFormat:
    def test_markdown_error(self):
        md = format_compare_markdown({"error": "no data"})
        assert "⚠️" in md

    def test_markdown_normal(self):
        results = {
            "app_count": 2,
            "group_count": 1,
            "total_diffs": 1,
            "summary": "2 apps in 1 groups, 1 diffs",
            "groups": {
                "test-group": {
                    "apps": ["a", "b"],
                    "diff_count": 1,
                    "top_diffs": [{"path": "root.dest.ns", "occurrences": 1}],
                    "summary": "2 apps, 1 diff",
                }
            },
        }
        md = format_compare_markdown(results)
        assert "# 配置对比报告" in md
        assert "test-group" in md

    def test_json_output(self):
        results = {"app_count": 1, "total_diffs": 0}
        j = format_compare_json(results)
        parsed = json.loads(j)
        assert parsed["app_count"] == 1


class TestMain:
    def test_no_files(self, tmp_path):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2

    def test_valid_file(self, tmp_path):
        app_file = tmp_path / "app.json"
        app_file.write_text(json.dumps(_make_app(name="my-app")))
        ret = main([str(app_file), "--format", "json"])
        assert ret == 0

    def test_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json {{{")
        ret = main([str(bad_file)])
        assert ret == 1

    def test_invalid_group_format(self, tmp_path):
        app_file = tmp_path / "app.json"
        app_file.write_text(json.dumps(_make_app()))
        ret = main([str(app_file), "--group", "bad-format"])
        assert ret == 1
