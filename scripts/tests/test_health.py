"""Tests for scripts/argocd_insight/health.py — dimension scoring logic.

No network calls — all argocd CLI invocations are mocked.
"""
from __future__ import annotations

from argocd_insight.health import (
    _calc_health_rate,
    _calc_sync_rate,
    _calc_error_rate,
)


def _app(name, health="Healthy", sync="Synced"):
    return {
        "metadata": {"name": name},
        "spec": {"project": "default"},
        "status": {
            "health": {"status": health},
            "sync": {"status": sync},
        },
    }


# _calc_health_rate

def test_health_rate_all_healthy():
    apps = [_app("a", health="Healthy"), _app("b", health="Healthy")]
    r = _calc_health_rate(apps)
    assert r.score == 100
    assert r.level == "info"
    assert r.apps_ok == 2
    assert r.apps_total == 2


def test_health_rate_partial():
    apps = [
        _app("a", health="Healthy"),
        _app("b", health="Degraded"),
        _app("c", health="Healthy"),
    ]
    r = _calc_health_rate(apps)
    assert r.score == round(2 / 3 * 100)
    assert r.level == "critical"


def test_health_rate_empty():
    r = _calc_health_rate([])
    assert r.score == 0  # no apps → no healthy apps → 0
    assert r.apps_total == 0
    assert "未发现" in r.findings[0]


def test_health_rate_lists_sick_apps():
    apps = [
        _app("good", health="Healthy"),
        _app("sick1", health="Degraded"),
        _app("sick2", health="Missing"),
    ]
    r = _calc_health_rate(apps)
    assert "sick1" in r.findings[-1]
    assert "sick2" in r.findings[-1]


def test_health_rate_suggestions_on_low_score():
    apps = [_app("a", health="Degraded")]
    r = _calc_health_rate(apps)
    assert len(r.suggestions) >= 1


# _calc_sync_rate

def test_sync_rate_all_synced():
    apps = [_app("a", sync="Synced"), _app("b", sync="Synced")]
    r = _calc_sync_rate(apps)
    assert r.score == 100
    assert r.level == "info"


def test_sync_rate_some_oos():
    apps = [
        _app("a", sync="Synced"),
        _app("b", sync="OutOfSync"),
        _app("c", sync="Synced"),
    ]
    r = _calc_sync_rate(apps)
    assert r.score == round(2 / 3 * 100)
    assert r.level == "critical"


def test_sync_rate_empty():
    r = _calc_sync_rate([])
    assert r.score == 0
    assert r.apps_total == 0


def test_sync_rate_reports_oos_count():
    apps = [
        _app("a", sync="OutOfSync"),
        _app("b", sync="OutOfSync"),
        _app("c", sync="Synced"),
    ]
    r = _calc_sync_rate(apps)
    assert any("2" in f and "OutOfSync" in f for f in r.findings)


# _calc_error_rate

def test_error_rate_zero_errors():
    apps = [_app("a", sync="Synced"), _app("b", sync="OutOfSync")]
    r = _calc_error_rate(apps)
    assert r.score == 100
    assert r.level == "info"


def test_error_rate_some_errors():
    apps = [
        _app("a", sync="Error"),
        _app("b", sync="Synced"),
    ]
    r = _calc_error_rate(apps)
    # 1/2 = 50% error rate → score = max(0, (1 - 0.5*5)*100) = 0
    assert r.score == 0
    assert r.level == "critical"


def test_error_rate_empty():
    r = _calc_error_rate([])
    # 0/0 = 0 error rate → score = max(0, (1-0)*100) = 100
    assert r.score == 100


def test_error_rate_nonzero_error_is_critical():
    apps = [_app("a", sync="Error")]
    r = _calc_error_rate(apps)
    assert r.level == "critical"


def test_error_rate_lists_error_app_names():
    apps = [_app("broken-app", sync="Error"), _app("ok-app", sync="Synced")]
    r = _calc_error_rate(apps)
    assert "broken-app" in r.findings[-1]
