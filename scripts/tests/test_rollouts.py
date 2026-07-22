"""argocd_insight.rollouts 诊断逻辑与 CLI 入口测试。"""

from __future__ import annotations

import json
from unittest.mock import patch


from argocd_insight.rollouts import diagnose, analysis
from argocd_insight.rollouts.main import main


# ---------------------------------------------------------------------------
# Fixtures: 模拟 kubectl get rollout/analysisrun -o json 的返回
# ---------------------------------------------------------------------------

def _rollout(phase="Healthy", paused=False, aborted=False,
             pause_reasons=None, strategy="canary", message="",
             step_index=None, steps=None):
    status = {
        "phase": phase,
        "paused": paused,
        "aborted": aborted,
        "message": message,
    }
    if pause_reasons:
        status["pauseConditions"] = [{"reason": r} for r in pause_reasons]
    if strategy == "canary" and (step_index is not None or steps is not None):
        canary = {}
        if step_index is not None:
            canary["currentStepIndex"] = step_index
        if steps is not None:
            canary["steps"] = steps
        status["canary"] = canary
    return {
        "metadata": {"name": "my-app", "namespace": "default"},
        "spec": {strategy: {}} if strategy else {},
        "status": status,
    }


def _analysisrun(phase="Successful", name="my-app-analysis",
                 message="", results=None):
    status = {"phase": phase, "message": message}
    if results is not None:
        status["metricResults"] = results
    return {
        "metadata": {"name": name, "namespace": "default"},
        "status": status,
    }


# ---------------------------------------------------------------------------
# diagnose_status 归因
# ---------------------------------------------------------------------------

def test_healthy():
    d = diagnose.diagnose_status(_rollout(phase="Healthy"))
    assert d.severity == "info"
    assert d.category == "healthy"


def test_aborted():
    d = diagnose.diagnose_status(_rollout(aborted=True, message="user aborted"))
    assert d.category == "aborted"
    assert d.severity == "high"
    # 已 abort 后应提供 resume 恢复，而非再次 abort
    assert any("resume" in a.command for a in d.actions)


def test_paused_analysis():
    d = diagnose.diagnose_status(_rollout(paused=True, pause_reasons=["Analysis"]))
    assert d.category == "paused"
    assert any("analysisrun" in a.command for a in d.actions)


def test_degraded():
    d = diagnose.diagnose_status(_rollout(phase="Degraded", message="liveness failed"))
    assert d.severity == "critical"
    assert d.category == "degraded"
    assert any("undo" in a.command for a in d.actions)


def test_stuck_progressing():
    d = diagnose.diagnose_status(_rollout(
        phase="Progressing", strategy="canary",
        step_index=1, steps=[{"setWeight": 5}, {"pause": {"duration": "5m"}}],
    ))
    assert d.category == "stuck_progressing"
    assert any("卡在步骤" in s for s in d.symptoms)


def test_progressing_normal():
    d = diagnose.diagnose_status(_rollout(phase="Progressing"))
    assert d.category == "progressing"
    assert d.severity == "info"


def test_strategy_detection():
    assert diagnose.diagnose_status(_rollout(strategy="blueGreen")).strategy == "bluegreen"
    assert diagnose.diagnose_status(_rollout(strategy="canary")).strategy == "canary"
    assert diagnose.diagnose_status(_rollout(strategy=None)).strategy == "basic"


# ---------------------------------------------------------------------------
# analyze_run 归因
# ---------------------------------------------------------------------------

def test_analysis_successful():
    f = analysis.analyze_run(_analysisrun(phase="Successful"))
    assert f.category == "ok"


def test_analysis_metric_failed():
    f = analysis.analyze_run(_analysisrun(
        phase="Failed",
        results=[{"name": "success-rate", "phase": "Failed"}],
    ))
    assert f.category == "metric_failed"
    assert "success-rate" in f.root_cause


def test_analysis_metric_error():
    # 阈值未达标 (Failed) 与 查询异常 (Error) 必须区分归因
    f = analysis.analyze_run(_analysisrun(
        phase="Failed",
        results=[{"name": "success-rate", "phase": "Error"}],
    ))
    assert f.category == "metric_error"
    assert "success-rate" in f.root_cause


def test_analysis_error():
    f = analysis.analyze_run(_analysisrun(phase="Error", message="prometheus unreachable"))
    assert f.category == "run_incomplete"


def test_analysis_running_no_results():
    f = analysis.analyze_run(_analysisrun(phase="Running"))
    assert f.category == "no_progression"


# ---------------------------------------------------------------------------
# CLI 入口（monkeypatch subprocess）
# ---------------------------------------------------------------------------

def _fake_run(return_payload):
    """返回一个替身 subprocess.run，stdout=json(payload)。"""

    class _R:
        returncode = 0
        stdout = json.dumps(return_payload)
        stderr = ""
    return lambda *a, **k: _R()


def test_cli_diagnose_json(capsys):
    rollout = _rollout(phase="Degraded", message="liveness failed")
    runs = [_analysisrun(phase="Failed",
                         results=[{"name": "success-rate", "phase": "Failed"}])]
    with patch("argocd_insight.rollouts.main.fetch_rollout",
               return_value=rollout), \
         patch("argocd_insight.rollouts.main.fetch_analysis_runs",
               return_value=runs):
        rc = main(["diagnose", "my-app", "-n", "default", "--output", "json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["diagnosis"]["category"] == "degraded"
    assert payload["diagnosis"]["severity"] == "critical"
    assert payload["analysis"][0]["category"] == "metric_failed"
    assert "success-rate" in payload["analysis"][0]["root_cause"]


def test_cli_rollout_fetch_failure():
    def _boom(kubectl, name, namespace):
        raise RuntimeError("rollout.apps not found")
    with patch("argocd_insight.rollouts.main.fetch_rollout", side_effect=_boom):
        rc = main(["diagnose", "missing", "-n", "default"])
    assert rc == 1


def test_cli_analysis_skip_on_error():
    """AnalysisRun 拉取失败时主诊断仍应成功。"""
    rollout = _rollout(phase="Healthy")

    def _runs_boom(kubectl, namespace, label):
        raise RuntimeError("forbidden")

    with patch("argocd_insight.rollouts.main.fetch_rollout",
               return_value=rollout), \
         patch("argocd_insight.rollouts.main.fetch_analysis_runs",
               side_effect=_runs_boom):
        rc = main(["diagnose", "my-app", "-n", "default"])
    assert rc == 0
