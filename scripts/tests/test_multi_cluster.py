"""Tests for scripts/argocd_insight/multi_cluster.py — cluster comparison logic.

No network calls — all argocd CLI invocations are mocked.
"""
from __future__ import annotations

from argocd_insight.multi_cluster import (
    AppSnapshot,
    compare_clusters,
    _build_index,
    _compare_apps,
    ComparisonReport,
)


def _snap(name, project="default", health="Healthy", sync="Synced",
          revision="abc12345", cpu=1.0, memory=2.0, replicas=1):
    return AppSnapshot(
        name=name, project=project, namespace="default",
        server="https://kubernetes", revision=revision,
        revision_short=revision[:8] if revision else "",
        source="repo.git", health_status=health, sync_status=sync,
        cpu_cores=cpu, memory_gib=memory, replicas=replicas,
    )


# _build_index

def test_build_index_keys_by_name():
    apps = [_snap("app-a"), _snap("app-b")]
    idx = _build_index(apps)
    assert set(idx.keys()) == {"app-a", "app-b"}


# _compare_apps

def test_compare_apps_synced():
    entry = _compare_apps("app", _snap("app", revision="abc12345"),
                          _snap("app", revision="abc12345"))
    assert entry.status == "synced"
    assert not entry.revision_drift
    assert not entry.health_diff
    assert not entry.sync_diff


def test_compare_apps_drifted():
    entry = _compare_apps("app", _snap("app", revision="abc12345"),
                          _snap("app", revision="xyz98765"))
    assert entry.status == "drifted"
    assert entry.revision_drift


def test_compare_apps_health_diff():
    entry = _compare_apps("app", _snap("app", health="Healthy"),
                          _snap("app", health="Degraded"))
    assert entry.health_diff


def test_compare_apps_sync_diff():
    entry = _compare_apps("app", _snap("app", sync="Synced"),
                          _snap("app", sync="OutOfSync"))
    assert entry.sync_diff


def test_compare_apps_resource_diff():
    entry = _compare_apps("app", _snap("app", cpu=1.0, memory=2.0),
                          _snap("app", cpu=2.0, memory=4.0))
    assert entry.cpu_diff == 1.0
    assert entry.memory_diff == 2.0


# compare_clusters

def test_compare_clusters_both_synced():
    from_apps = [_snap("a", revision="abc12345"), _snap("b", revision="def56789")]
    to_apps = [_snap("a", revision="abc12345"), _snap("b", revision="def56789")]
    report = compare_clusters(from_apps, to_apps)
    assert report.summary["total"] == 2
    assert report.summary["synced"] == 2
    assert report.summary["drifted"] == 0


def test_compare_clusters_all_drifted():
    from_apps = [_snap("a", revision="abc11111"), _snap("b", revision="def11111")]
    to_apps = [_snap("a", revision="abc99999"), _snap("b", revision="def99999")]
    report = compare_clusters(from_apps, to_apps)
    assert report.summary["drifted"] == 2
    assert report.summary["driftRate"] == 1.0


def test_compare_clusters_source_only():
    from_apps = [_snap("only-src")]
    to_apps = []
    report = compare_clusters(from_apps, to_apps)
    assert len(report.source_only) == 1
    assert report.source_only[0]["name"] == "only-src"


def test_compare_clusters_target_only():
    from_apps = []
    to_apps = [_snap("only-tgt")]
    report = compare_clusters(from_apps, to_apps)
    assert len(report.target_only) == 1
    assert report.target_only[0]["name"] == "only-tgt"


def test_compare_clusters_health_diffs():
    from_apps = [_snap("app", health="Healthy")]
    to_apps = [_snap("app", health="Degraded")]
    report = compare_clusters(from_apps, to_apps)
    assert report.summary["healthDiffs"] == 1


def test_compare_clusters_sync_diffs():
    from_apps = [_snap("app", sync="Synced")]
    to_apps = [_snap("app", sync="OutOfSync")]
    report = compare_clusters(from_apps, to_apps)
    assert report.summary["syncDiffs"] == 1


def test_compare_clusters_empty():
    report = compare_clusters([], [])
    assert report.summary["total"] == 0
    assert report.summary["driftRate"] == 0
