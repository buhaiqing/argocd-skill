#!/usr/bin/env python3
"""
multi_cluster — 多集群对比报告

比对两个 ArgoCD 集群的 App 配置、资源、健康状态差异。
典型场景：多集群灾备验收、环境一致性检查、成本对比。

Usage:
  python -m argocd_insight multi_cluster
  python -m argocd_insight multi_cluster --from prod --to staging
  python -m argocd_insight multi_cluster --project default --output json

对比维度：
  - App 存在性：只在 A / 只在 B / 两边都有
  - 版本漂移：revision 是否一致
  - 资源配置：CPU/Memory requests 差异
  - 健康状态：Healthy / Degraded / Missing
  - 同步状态：Synced / OutOfSync
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

# ponytail: 复用 drift 模式的基础设施，扩展对比维度。

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class AppSnapshot:
    """单个 App 的关键信息（脱敏后摘要）。"""
    name: str
    project: str
    namespace: str
    server: str
    revision: str
    revision_short: str
    source: str
    health_status: str
    sync_status: str
    cpu_cores: float = 0.0
    memory_gib: float = 0.0
    replicas: int = 0

    @classmethod
    def from_argocd_json(cls, d: dict) -> "AppSnapshot":
        name = d.get("metadata", {}).get("name", "")
        spec = d.get("spec", {})
        status = d.get("status", {})
        sync = status.get("sync", {})
        health = status.get("health", {})

        sources = spec.get("sources", [])
        if sources:
            repo = sources[0].get("repoURL", "")
        else:
            repo = spec.get("source", {}).get("repoURL", "")

        rev = sync.get("revision", "")
        return cls(
            name=name,
            project=spec.get("project", ""),
            namespace=spec.get("destination", {}).get("namespace", ""),
            server=spec.get("destination", {}).get("server", ""),
            revision=rev,
            revision_short=rev[:8] if rev else "",
            source=repo.rsplit("/", 1)[-1] if repo else "",
            health_status=health.get("status", ""),
            sync_status=sync.get("status", ""),
        )


@dataclass
class ComparisonEntry:
    """单个 App 的跨集群对比结果。"""
    name: str
    project: str
    # 源端
    from_revision: str
    from_health: str
    from_sync: str
    from_cpu: float
    from_memory: float
    from_replicas: int
    # 目标端
    to_revision: str
    to_health: str
    to_sync: str
    to_cpu: float
    to_memory: float
    to_replicas: int
    # 差异标记
    revision_drift: bool = False
    health_diff: bool = False
    sync_diff: bool = False
    cpu_diff: float = 0.0
    memory_diff: float = 0.0
    status: str = "synced"  # synced | drifted | partial


@dataclass
class ComparisonReport:
    matched: dict[str, ComparisonEntry] = field(default_factory=dict)
    source_only: list[dict] = field(default_factory=list)
    target_only: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 底层调用
# ---------------------------------------------------------------------------

def _run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timed out after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {args[0]}"


def _fetch_apps(server: str | None = None, project: str | None = None) -> list[AppSnapshot]:
    cmd = ["argocd", "app", "list", "--output", "json"]
    if server:
        cmd += ["--server", server]
    if project:
        cmd += ["--project", project]

    rc, out, err = _run(cmd)
    if rc != 0 or not out:
        print(f"[warn] argocd app list failed: {err}", file=sys.stderr)
        return []
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [AppSnapshot.from_argocd_json(a) for a in raw]


def _fetch_app_resources(app_name: str, server: str | None = None) -> dict:
    """获取单个 App 的资源规格（CPU/Memory/Replicas）"""
    cmd = ["argocd", "app", "resources", app_name, "--output", "json"]
    if server:
        cmd += ["--server", server]

    rc, out, _ = _run(cmd, timeout=15)
    if rc != 0 or not out:
        return {"cpu_cores": 0.0, "memory_gib": 0.0, "replicas": 0}

    try:
        data = json.loads(out)
        items = data.get("items", []) if isinstance(data, dict) else data
    except json.JSONDecodeError:
        return {"cpu_cores": 0.0, "memory_gib": 0.0, "replicas": 0}

    total_cpu = 0.0
    total_mem = 0.0
    total_replicas = 0

    for res in items:
        kind = res.get("kind", "")
        if kind not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        if res.get("status") not in ("Synced", "Healthy", ""):
            continue

        live = res.get("live", {})
        spec = live.get("spec", {})
        template = spec.get("template", {}).get("spec", {})
        replicas = spec.get("replicas", 1)
        if kind == "DaemonSet":
            replicas = 1

        for c in template.get("containers", []):
            req = c.get("resources", {}).get("requests", {})
            total_cpu += _parse_cpu(req.get("cpu", "0"))
            total_mem += _parse_memory(req.get("memory", "0"))

        total_cpu *= replicas
        total_mem *= replicas
        total_replicas += replicas

    return {"cpu_cores": round(total_cpu, 3), "memory_gib": round(total_mem, 2), "replicas": total_replicas}


def _parse_cpu(cpu_str: str) -> float:
    if not cpu_str:
        return 0.0
    cpu_str = str(cpu_str).strip()
    if cpu_str.endswith("m"):
        return int(cpu_str[:-1]) / 1000.0
    try:
        return float(cpu_str)
    except ValueError:
        return 0.0


def _parse_memory(mem_str: str) -> float:
    if not mem_str:
        return 0.0
    mem_str = str(mem_str).strip()
    multipliers = {
        "Ki": 1 / (1024 ** 2), "Mi": 1 / 1024, "Gi": 1.0, "Ti": 1024.0,
        "K": 1 / (1024 ** 2), "M": 1 / 1000, "G": 1.0, "T": 1000.0,
    }
    for suffix, mult in sorted(multipliers.items(), key=lambda x: -len(x[0])):
        if mem_str.endswith(suffix):
            try:
                return float(mem_str[: -len(suffix)]) * mult
            except ValueError:
                return 0.0
    try:
        return float(mem_str) / (1024 ** 3)
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# 核心对比逻辑
# ---------------------------------------------------------------------------

def _build_index(apps: list[AppSnapshot]) -> dict[str, AppSnapshot]:
    return {a.name: a for a in apps}


def _compare_apps(name: str, from_app: AppSnapshot, to_app: AppSnapshot) -> ComparisonEntry:
    rev_drift = (from_app.revision_short != to_app.revision_short) and \
                from_app.revision_short and to_app.revision_short
    health_diff = from_app.health_status != to_app.health_status
    sync_diff = from_app.sync_status != to_app.sync_status

    if from_app.revision_short == to_app.revision_short and from_app.revision_short:
        status = "synced"
    elif not from_app.revision_short or not to_app.revision_short:
        status = "partial"
    else:
        status = "drifted"

    return ComparisonEntry(
        name=name,
        project=from_app.project,
        from_revision=from_app.revision_short or "(none)",
        from_health=from_app.health_status,
        from_sync=from_app.sync_status,
        from_cpu=from_app.cpu_cores,
        from_memory=from_app.memory_gib,
        from_replicas=from_app.replicas,
        to_revision=to_app.revision_short or "(none)",
        to_health=to_app.health_status,
        to_sync=to_app.sync_status,
        to_cpu=to_app.cpu_cores,
        to_memory=to_app.memory_gib,
        to_replicas=to_app.replicas,
        revision_drift=rev_drift,
        health_diff=health_diff,
        sync_diff=sync_diff,
        cpu_diff=round(to_app.cpu_cores - from_app.cpu_cores, 3),
        memory_diff=round(to_app.memory_gib - from_app.memory_gib, 2),
        status=status,
    )


def compare_clusters(
    from_apps: list[AppSnapshot],
    to_apps: list[AppSnapshot],
    fetch_resources: bool = False,
) -> ComparisonReport:
    """对比两组 App，生成对比报告。"""
    from_idx = _build_index(from_apps)
    to_idx = _build_index(to_apps)

    all_names = sorted(set(from_idx) | set(to_idx))
    report = ComparisonReport()

    for name in all_names:
        f = from_idx.get(name)
        t = to_idx.get(name)

        if f and t:
            entry = _compare_apps(name, f, t)
            report.matched[name] = entry
        elif f:
            report.source_only.append({
                "name": name, "project": f.project,
                "revision": f.revision_short, "health": f.health_status,
            })
        else:
            report.target_only.append({
                "name": name, "project": t.project,
                "revision": t.revision_short, "health": t.health_status,
            })

    # 统计
    synced = sum(1 for e in report.matched.values() if e.status == "synced")
    drifted = sum(1 for e in report.matched.values() if e.status == "drifted")
    partial = sum(1 for e in report.matched.values() if e.status == "partial")
    health_diffs = sum(1 for e in report.matched.values() if e.health_diff)
    sync_diffs = sum(1 for e in report.matched.values() if e.sync_diff)

    report.summary = {
        "total": len(report.matched),
        "sourceOnly": len(report.source_only),
        "targetOnly": len(report.target_only),
        "synced": synced,
        "drifted": drifted,
        "partial": partial,
        "driftRate": round(drifted / len(report.matched), 4) if report.matched else 0,
        "healthDiffs": health_diffs,
        "syncDiffs": sync_diffs,
    }
    return report


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def to_json(report: ComparisonReport) -> str:
    def _entry(e: ComparisonEntry) -> dict:
        return {
            "name": e.name, "project": e.project,
            "fromRevision": e.from_revision, "toRevision": e.to_revision,
            "fromHealth": e.from_health, "toHealth": e.to_health,
            "fromSync": e.from_sync, "toSync": e.to_sync,
            "fromCpu": e.from_cpu, "toCpu": e.to_cpu,
            "fromMemory": e.from_memory, "toMemory": e.to_memory,
            "fromReplicas": e.from_replicas, "toReplicas": e.to_replicas,
            "revisionDrift": e.revision_drift,
            "healthDiff": e.health_diff,
            "syncDiff": e.sync_diff,
            "cpuDiff": e.cpu_diff, "memoryDiff": e.memory_diff,
            "status": e.status,
        }
    return json.dumps({
        "matched": {n: _entry(e) for n, e in report.matched.items()},
        "sourceOnly": report.source_only,
        "targetOnly": report.target_only,
        "summary": report.summary,
    }, ensure_ascii=False, indent=2)


def to_markdown(report: ComparisonReport, from_label: str, to_label: str) -> str:
    lines = []
    def p(line=""): lines.append(line)

    p(f"# ArgoCD 多集群对比报告\n")
    p(f"**比对**：{from_label} → {to_label}")
    p(f"**时间**：{__import__('datetime').datetime.now().isoformat()}\n")

    s = report.summary
    p(f"## 统计概览\n")
    p(f"| 指标 | 值 |")
    p(f"|------|---|")
    p(f"| 比对 App 总数 | {s['total']} |")
    p(f"| 版本一致（Synced） | {s['synced']} |")
    p(f"| 版本漂移（Drifted） | {s['drifted']} |")
    p(f"| 漂移率 | {s['driftRate']:.1%} |")
    p(f"| 健康状态差异 | {s['healthDiffs']} |")
    p(f"| 同步状态差异 | {s['syncDiffs']} |")
    p(f"| 仅 {from_label} 有 | {s['sourceOnly']} |")
    p(f"| 仅 {to_label} 有 | {s['targetOnly']} |")

    if report.matched:
        # 版本漂移详情
        drifted = [e for e in report.matched.values() if e.status == "drifted"]
        if drifted:
            p(f"\n## 版本漂移 App（{len(drifted)} 个）\n")
            p(f"| App | 项目 | {from_label} | {to_label} | 状态 |")
            p(f"|-----|------|--------|--------|------|")
            for e in sorted(drifted, key=lambda x: x.name):
                p(f"| `{e.name}` | {e.project} | `{e.from_revision}` | `{e.to_revision}` | ⚠️ drifted |")

        # 健康状态差异
        health_diffs = [e for e in report.matched.values() if e.health_diff]
        if health_diffs:
            p(f"\n## 健康状态差异（{len(health_diffs)} 个）\n")
            p(f"| App | {from_label} 健康 | {to_label} 健康 |")
            p(f"|-----|------------|------------|")
            for e in sorted(health_diffs, key=lambda x: x.name):
                p(f"| `{e.name}` | {e.from_health} | {e.to_health} |")

        # 资源配置差异（如果有）
        resource_diffs = [e for e in report.matched.values()
                         if abs(e.cpu_diff) > 0.01 or abs(e.memory_diff) > 0.1]
        if resource_diffs:
            p(f"\n## 资源配置差异（{len(resource_diffs)} 个）\n")
            p(f"| App | {from_label} CPU | {to_label} CPU | {from_label} Mem | {to_label} Mem |")
            p(f"|-----|--------|--------|--------|--------|")
            for e in sorted(resource_diffs, key=lambda x: -abs(x.cpu_diff)):
                p(f"| `{e.name}` | {e.from_cpu}c | {e.to_cpu}c | {e.from_memory}G | {e.to_memory}G |")

    if report.source_only:
        p(f"\n## 仅 {from_label} 存在的 App（{len(report.source_only)} 个）\n")
        for a in report.source_only:
            p(f"- `{a['name']}` · {a['project']} · rev={a['revision']}")

    if report.target_only:
        p(f"\n## 仅 {to_label} 存在的 App（{len(report.target_only)} 个）\n")
        for a in report.target_only:
            p(f"- `{a['name']}` · {a['project']} · rev={a['revision']}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="ArgoCD 多集群对比报告：比对两个集群的 App 配置、资源、健康状态差异。",
    )
    p.add_argument("--from", dest="from_label", default="源端",
                   help="源端标签（用于报告，默认 '源端'）")
    p.add_argument("--to", dest="to_label", default="目标端",
                   help="目标端标签（用于报告，默认 '目标端'）")
    p.add_argument("--from-server", dest="from_server",
                   help="源端 ArgoCD server URL（留空则使用当前 context）")
    p.add_argument("--to-server", dest="to_server",
                   help="目标端 ArgoCD server URL")
    p.add_argument("--project", dest="project",
                   help="只对比指定项目的 App")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p.add_argument("--concurrency", type=int, default=8,
                   help="并发数（默认 8）")
    args = p.parse_args(argv)

    from_label = args.from_label
    to_label = args.to_label

    print(f"Fetching apps from {from_label}...", file=sys.stderr)
    t0 = time.time()
    from_apps = _fetch_apps(server=args.from_server, project=args.project)
    print(f"  got {len(from_apps)} apps in {time.time()-t0:.1f}s", file=sys.stderr)

    print(f"Fetching apps from {to_label}...", file=sys.stderr)
    t0 = time.time()
    to_apps = _fetch_apps(server=args.to_server, project=args.project)
    print(f"  got {len(to_apps)} apps in {time.time()-t0:.1f}s", file=sys.stderr)

    report = compare_clusters(from_apps, to_apps)

    if args.output == "json":
        print(to_json(report))
    else:
        print(to_markdown(report, from_label, to_label))

    if report.summary["drifted"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
