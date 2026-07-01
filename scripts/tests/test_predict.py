"""Tests for predict.py"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from argocd_insight.predict import (
    compute_cost_overrun_risk,
    compute_lag_risk,
    format_predict_json,
    format_predict_markdown,
    main,
    predict_batch,
)


def _make_app(
    name: str = "test-app",
    sync_status: str = "Synced",
    last_sync_days: int = 5,
    last_commit_days: int = 3,
    auto_sync: bool = True,
    revisions_count: int = 1,
    replicas: int | None = None,
    memory_request: str | None = None,
) -> dict:
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)

    spec: dict = {
        "source": {
            "repoURL": "https://github.com/test/repo",
            "targetRevision": "main",
            "path": "apps/test",
        },
        "destination": {"server": "https://kubernetes.default.svc", "namespace": "default"},
    }

    if auto_sync:
        spec["syncPolicy"] = {"automated": {"prune": True, "selfHeal": True}}

    if replicas is not None or memory_request is not None:
        helm_params = []
        if replicas is not None:
            helm_params.append({"name": "replicas", "value": str(replicas)})
        if memory_request is not None:
            helm_params.append({"name": "resources.requests.memory", "value": memory_request})
        spec["source"]["helm"] = {"parameters": helm_params}

    status: dict = {
        "sync": {"status": sync_status},
        "health": {"status": "Healthy"},
    }

    if last_sync_days >= 0:
        sync_time = now - timedelta(days=last_sync_days)
        status["operationState"] = {"finishedAt": sync_time.isoformat()}

    if revisions_count > 0 and last_commit_days >= 0:
        commit_time = now - timedelta(days=last_commit_days)
        status["revisions"] = [
            {"revision": "abc123", "committedAt": commit_time.isoformat()}
        ] * revisions_count

    return {"metadata": {"name": name}, "spec": spec, "status": status}


class TestComputeLagRisk:
    def test_low_risk(self):
        app = _make_app(last_sync_days=2, last_commit_days=1, auto_sync=True, sync_status="Synced")
        result = compute_lag_risk(app)
        assert result["risk_score"] < 30
        assert result["risk_level"] in ("low", "medium")

    def test_high_risk_no_sync(self):
        app = _make_app(last_sync_days=45, last_commit_days=40, auto_sync=False, sync_status="OutOfSync")
        result = compute_lag_risk(app)
        assert result["risk_score"] >= 50
        assert result["risk_level"] in ("high", "critical")

    def test_critical_risk(self):
        app = _make_app(last_sync_days=90, last_commit_days=60, auto_sync=False, sync_status="OutOfSync")
        result = compute_lag_risk(app)
        assert result["risk_score"] >= 70
        assert result["risk_level"] == "critical"

    def test_multi_source_penalty(self):
        app = _make_app(revisions_count=3, auto_sync=True)
        result = compute_lag_risk(app)
        multi_factor = next((f for f in result["factors"] if f["name"] == "multi_source"), None)
        assert multi_factor is not None
        assert multi_factor["score"] > 0

    def test_auto_sync_no_penalty(self):
        app = _make_app(auto_sync=True, last_sync_days=0)
        result = compute_lag_risk(app)
        sync_factor = next((f for f in result["factors"] if f["name"] == "auto_sync"), None)
        assert sync_factor["score"] == 0

    def test_manual_sync_penalty(self):
        app = _make_app(auto_sync=False)
        result = compute_lag_risk(app)
        sync_factor = next((f for f in result["factors"] if f["name"] == "auto_sync"), None)
        assert sync_factor["score"] == 20

    def test_no_sync_history(self):
        app = {"metadata": {"name": "no-sync"}, "spec": {}, "status": {}}
        result = compute_lag_risk(app)
        assert result["risk_score"] > 0

    def test_name_preserved(self):
        app = _make_app(name="my-app")
        result = compute_lag_risk(app)
        assert result["name"] == "my-app"


class TestComputeCostOverrunRisk:
    def test_low_risk(self):
        app = _make_app(replicas=2)
        result = compute_cost_overrun_risk(app)
        assert result["risk_score"] < 30

    def test_high_replicas_risk(self):
        app = _make_app(replicas=10)
        result = compute_cost_overrun_risk(app)
        assert result["risk_score"] > 0

    def test_budget_overrun(self):
        app = _make_app(replicas=20, memory_request="8Gi")
        result = compute_cost_overrun_risk(app, budget_limit=0.01)
        assert result["risk_score"] > 0
        budget_factor = next((f for f in result["factors"] if f["name"] == "budget_overrun"), None)
        assert budget_factor is not None

    def test_no_helm(self):
        app = {"metadata": {"name": "no-helm"}, "spec": {"source": {}}, "status": {}}
        result = compute_cost_overrun_risk(app)
        assert result["risk_score"] == 0

    def test_high_memory(self):
        app = _make_app(memory_request="8192Mi")
        result = compute_cost_overrun_risk(app)
        assert result["risk_score"] > 0


class TestPredictBatch:
    def test_batch(self):
        apps = {
            "app-a": _make_app(name="app-a", auto_sync=True, last_sync_days=1),
            "app-b": _make_app(name="app-b", auto_sync=False, last_sync_days=60),
        }
        result = predict_batch(apps)
        assert result["app_count"] == 2
        assert len(result["lag_risks"]) == 2
        assert result["summary"]["total_warnings"] >= 0

    def test_empty_batch(self):
        result = predict_batch({})
        assert result["app_count"] == 0


class TestFormat:
    def test_markdown_normal(self):
        results = {
            "app_count": 2,
            "lag_risks": [
                {"name": "app-a", "risk_score": 10, "risk_level": "low", "factors": []},
                {"name": "app-b", "risk_score": 60, "risk_level": "high", "factors": [
                    {"name": "last_sync", "score": 25, "detail": "Last sync 50d ago"},
                ]},
            ],
            "cost_risks": [],
            "summary": {"critical_lag": 0, "high_lag": 1, "critical_cost": 0, "high_cost": 0, "total_warnings": 1},
        }
        md = format_predict_markdown(results)
        assert "# 风险预测报告" in md
        assert "app-b" in md

    def test_markdown_no_warnings(self):
        results = {
            "app_count": 1,
            "lag_risks": [{"name": "a", "risk_score": 0, "risk_level": "low", "factors": []}],
            "cost_risks": [],
            "summary": {"total_warnings": 0},
        }
        md = format_predict_markdown(results)
        assert "✅" in md

    def test_json_output(self):
        results = {"app_count": 1, "lag_risks": [], "cost_risks": [], "summary": {}}
        j = format_predict_json(results)
        parsed = json.loads(j)
        assert parsed["app_count"] == 1


class TestMain:
    def test_valid_file(self, tmp_path):
        app_file = tmp_path / "app.json"
        app_file.write_text(json.dumps(_make_app()))
        ret = main([str(app_file), "--format", "json"])
        assert ret == 0

    def test_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json")
        ret = main([str(bad_file)])
        assert ret == 1

    def test_no_files(self):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 2

    def test_type_filter(self, tmp_path):
        app_file = tmp_path / "app.json"
        app_file.write_text(json.dumps(_make_app()))
        ret = main([str(app_file), "--type", "lag"])
        assert ret == 0
