"""Tests for scripts/argocd_insight/cost.py — resource cost estimation.

No network calls — all argocd CLI invocations are mocked.
"""
from __future__ import annotations

from argocd_insight.cost import (
    parse_cpu,
    parse_memory,
    extract_resource_specs,
    build_report,
)


def _app(name, project="default", ns="prod"):
    return {
        "metadata": {"name": name},
        "spec": {"project": project, "destination": {"namespace": ns}},
        "status": {"health": {"status": "Healthy"}, "sync": {"status": "Synced"}},
    }


def _resource(kind, name, ns="prod", cpu="100m", memory="128Mi", replicas=1):
    return {
        "kind": kind,
        "name": name,
        "namespace": ns,
        "status": "Synced",
        "live": {
            "spec": {
                "replicas": replicas,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "name": "main",
                                "resources": {
                                    "requests": {"cpu": cpu, "memory": memory},
                                },
                            }
                        ]
                    }
                },
            }
        },
    }


# parse_cpu

def test_parse_cpu_cores():
    assert parse_cpu("1") == 1.0
    assert parse_cpu("0.5") == 0.5


def test_parse_cpu_millicores():
    assert parse_cpu("100m") == 0.1
    assert parse_cpu("500m") == 0.5
    assert parse_cpu("1000m") == 1.0


def test_parse_cpu_empty():
    assert parse_cpu("") == 0.0
    assert parse_cpu(None) == 0.0


def test_parse_cpu_invalid():
    assert parse_cpu("abc") == 0.0


# parse_memory

def test_parse_memory_gib():
    assert parse_memory("1Gi") == 1.0
    assert parse_memory("2Gi") == 2.0
    assert parse_memory("0.5Gi") == 0.5


def test_parse_memory_mib():
    assert parse_memory("128Mi") == 0.125
    assert parse_memory("1024Mi") == 1.0


def test_parse_memory_kib():
    assert parse_memory("1024Ki") == 1.0 / 1024


def test_parse_memory_bytes():
    assert parse_memory("1073741824") == 1.0  # 1 GiB in bytes


def test_parse_memory_empty():
    assert parse_memory("") == 0.0
    assert parse_memory(None) == 0.0


def test_parse_memory_invalid():
    assert parse_memory("abc") == 0.0


# extract_resource_specs

def test_extract_single_deployment():
    resources = [_resource("Deployment", "web", cpu="500m", memory="512Mi", replicas=3)]
    specs = extract_resource_specs(resources)
    assert specs["totalCpuCores"] == 1.5
    assert specs["totalMemoryGiB"] == 1.5
    assert specs["totalReplicas"] == 3
    assert len(specs["workloads"]) == 1


def test_extract_multiple_workloads():
    resources = [
        _resource("Deployment", "web", cpu="500m", memory="512Mi", replicas=2),
        _resource("StatefulSet", "db", cpu="2", memory="4Gi", replicas=1),
    ]
    specs = extract_resource_specs(resources)
    assert specs["totalCpuCores"] == 3.0
    assert specs["totalMemoryGiB"] == 5.0
    assert specs["totalReplicas"] == 3


def test_extract_skips_non_workload():
    resources = [
        _resource("Deployment", "web", cpu="100m", memory="128Mi"),
        {"kind": "Service", "name": "web-svc", "namespace": "prod", "status": "Synced", "live": {}},
        {"kind": "ConfigMap", "name": "web-cm", "namespace": "prod", "status": "Synced", "live": {}},
    ]
    specs = extract_resource_specs(resources)
    assert len(specs["workloads"]) == 1
    assert specs["workloads"][0]["name"] == "web"


def test_extract_skips_unhealthy():
    resources = [
        _resource("Deployment", "web", cpu="100m", memory="128Mi"),
        {
            "kind": "Deployment",
            "name": "broken",
            "namespace": "prod",
            "status": "Missing",
            "live": {"spec": {"replicas": 1, "template": {"spec": {"containers": []}}}},
        },
    ]
    specs = extract_resource_specs(resources)
    assert len(specs["workloads"]) == 1


def test_extract_empty():
    specs = extract_resource_specs([])
    assert specs["totalCpuCores"] == 0.0
    assert specs["totalMemoryGiB"] == 0.0
    assert specs["totalReplicas"] == 0
    assert specs["workloads"] == []


def test_extract_daemonset_uses_replica_1():
    resources = [_resource("DaemonSet", "log-agent", cpu="100m", memory="64Mi", replicas=5)]
    specs = extract_resource_specs(resources)
    assert specs["totalReplicas"] == 1
    assert specs["workloads"][0]["replicas"] == 1
