"""Tests for scripts/argocd_insight/drift.py — detect_drift() logic.

No network calls — all argocd CLI invocations are mocked.
"""
from __future__ import annotations

from unittest.mock import patch

from argocd_insight.drift import (
    AppSnapshot,
    detect_drift,
    _build_index,
    _compare,
    DriftReport,
    DriftEntry,
)


# ------------------------------------------------------------------
# AppSnapshot factory
# ------------------------------------------------------------------

def _snap(name, project="default", namespace="default",
          health="Healthy", sync="Synced", revision="abc12345"):
    return AppSnapshot(
        name=name,
        project=project,
        namespace=namespace,
        server="https://kubernetes",
        revision=revision,
        revision_short=revision[:8] if revision else "",
        source="repo.git",
        health_status=health,
        sync_status=sync,
    )


# ------------------------------------------------------------------
# _build_index
# ------------------------------------------------------------------

def test_build_index_keys_by_name():
    apps = [_snap("app-a"), _snap("app-b")]
    idx = _build_index(apps)
    assert set(idx.keys()) == {"app-a", "app-b"}
    assert idx["app-a"].name == "app-a"


def test_build_index_last_wins_on_duplicate():
    apps = [_snap("dup"), _snap("dup")]
    idx = _build_index(apps)
    assert len(idx) == 1


# ------------------------------------------------------------------
# _compare
# ------------------------------------------------------------------

def test_compare_synced():
    entry = _compare("app", _snap("app", revision="abc12345"),
                     _snap("app", revision="abc12345"))
    assert entry.status == "synced"


def test_compare_drifted():
    entry = _compare("app", _snap("app", revision="abc12345"),
                     _snap("app", revision="xyz98765"))
    assert entry.status == "drifted"


def test_compare_partial_missing_rev():
    entry = _compare("app", _snap("app", revision=""),
                     _snap("app", revision="abc12345"))
    assert entry.status == "partial"


# ------------------------------------------------------------------
# detect_drift — core scenarios
# ------------------------------------------------------------------

def test_detect_drift_both_synced():
    """Same revision on both sides → all matched = synced."""
    from_apps = [_snap("app-a", revision="abc12345"), _snap("app-b", revision="def56789")]
    to_apps   = [_snap("app-a", revision="abc12345"), _snap("app-b", revision="def56789")]

    report = detect_drift(from_apps, to_apps)

    assert len(report.matched) == 2
    assert report.summary["synced"] == 2
    assert report.summary["drifted"] == 0
    assert report.summary["driftRate"] == 0.0


def test_detect_drift_all_drifted():
    """Different revisions everywhere → all drifted."""
    from_apps = [_snap("app-a", revision="abc11111"), _snap("app-b", revision="def11111")]
    to_apps   = [_snap("app-a", revision="abc99999"), _snap("app-b", revision="def99999")]

    report = detect_drift(from_apps, to_apps)

    assert len(report.matched) == 2
    assert report.summary["drifted"] == 2
    assert report.summary["driftRate"] == 1.0


def test_detect_drift_mixed():
    """Some synced, some drifted."""
    from_apps = [
        _snap("synced-app", revision="abc12345"),
        _snap("drifted-app", revision="def11111"),
    ]
    to_apps = [
        _snap("synced-app", revision="abc12345"),
        _snap("drifted-app", revision="def99999"),
    ]

    report = detect_drift(from_apps, to_apps)

    assert report.summary["synced"] == 1
    assert report.summary["drifted"] == 1


def test_detect_drift_source_only():
    """App only in source → source_only list populated."""
    from_apps = [_snap("only-src", revision="abc12345")]
    to_apps   = []

    report = detect_drift(from_apps, to_apps)

    assert len(report.source_only) == 1
    assert report.source_only[0]["name"] == "only-src"
    assert len(report.target_only) == 0


def test_detect_drift_target_only():
    """App only in target → target_only list populated."""
    from_apps = []
    to_apps   = [_snap("only-tgt", revision="abc12345")]

    report = detect_drift(from_apps, to_apps)

    assert len(report.target_only) == 1
    assert report.target_only[0]["name"] == "only-tgt"
    assert len(report.source_only) == 0


def test_detect_drift_empty_both_sides():
    """Empty lists → zero totals."""
    report = detect_drift([], [])
    assert report.summary["total"] == 0
    assert report.summary["driftRate"] == 0


def test_detect_drift_summary_totals():
    """Summary total equals matched count."""
    from_apps = [_snap("a"), _snap("b"), _snap("c")]
    to_apps   = [_snap("a"), _snap("b"), _snap("c")]
    report = detect_drift(from_apps, to_apps)
    assert report.summary["total"] == len(report.matched) == 3
