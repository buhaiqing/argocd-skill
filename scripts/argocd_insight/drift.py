#!/usr/bin/env python3
"""
drift — 版本漂移检测

比较两个 ArgoCD 集群（或同一集群两个 namespace）同名 App 的 revision 是否一致。
典型场景：多集群灾备、新旧环境迁移验收、SRE 例行巡检。

Usage:
  python -m argocd_insight drift
  python -m argocd_insight drift --from prod --to staging
  python -m argocd_insight drift --project default --output json
  python -m argocd_insight drift --from prod --to staging --sync-orphaned  # 找出仅存在于源端的 App

输出字段（JSON）：
  matched:      两端都存在的 App，按 revision 是否一致分组
  sourceOnly:   仅源端有、目标端无的 App
  targetOnly:   仅目标端有、源端无的 App
  summary:      漂移统计

脱敏：revision 原始值保留，仅缩短显示（取前 8 位）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class AppSnapshot:
    """单个 App 的关键版本信息（脱敏后摘要）。"""
    name: str
    project: str
    namespace: str
    server: str
    revision: str          # 原始值
    revision_short: str    # 显示用：前8位
    source: str            # repo URL 摘要（最后路径段）
    health_status: str
    sync_status: str

    @classmethod
    def from_argocd_json(cls, d: dict) -> "AppSnapshot":
        name = d.get("metadata", {}).get("name", "")
        spec = d.get("spec", {})
        status = d.get("status", {})
        sync = status.get("sync", {})
        health = status.get("health", {})

        # 单源 vs 多源
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
class DriftReport:
    matched: dict[str, "DriftEntry"] = field(default_factory=dict)
    source_only: list[dict] = field(default_factory=list)
    target_only: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


@dataclass
class DriftEntry:
    """一组（跨集群）同名 App 的比对结果。"""
    name: str
    project: str
    from_rev: str       # 源端 revision（short）
    to_rev: str         # 目标端 revision（short）
    from_health: str
    to_health: str
    from_sync: str
    to_sync: str
    status: str         # "synced" | "drifted" | "partial"


# ---------------------------------------------------------------------------
# 底层调用（subprocess 封装）
# ---------------------------------------------------------------------------

def _run(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timed out after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {args[0]}"


def _argocd_login(server: str, token: str | None = None,
                  username: str | None = None, password: str | None = None,
                  context: str | None = None) -> bool:
    """登录到指定 server，避免后续命令因未登录失败。"""
    cmd = ["argocd", "login", server,
           "--grpc-web", "--insecure"]
    if token:
        cmd += ["--auth-token", token]
    elif username and password:
        cmd += ["--username", username, "--password", password]
    else:
        # 无凭证，尝试跳过登录直接用 CLI
        return True
    rc, _, _ = _run(cmd)
    return rc == 0


def _fetch_apps(server: str | None = None, project: str | None = None,
                context: str | None = None, label: str | None = None) -> list[AppSnapshot]:
    """拉取 apps 并转为 AppSnapshot 列表。"""
    cmd = ["argocd", "app", "list", "--output", "json"]
    if server:
        cmd += ["--server", server]
    if project:
        cmd += ["--project", project]
    if label:
        cmd += ["--label", label]

    rc, out, err = _run(cmd)
    if rc != 0 or not out:
        print(f"[warn] argocd app list failed: {err}", file=sys.stderr)
        return []
    try:
        raw = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [AppSnapshot.from_argocd_json(a) for a in raw]


# ---------------------------------------------------------------------------
# 核心比对逻辑
# ---------------------------------------------------------------------------

def _build_index(apps: list[AppSnapshot]) -> dict[str, AppSnapshot]:
    """以 name 为 key 建立索引。"""
    return {a.name: a for a in apps}


def _compare(name: str, from_app: AppSnapshot, to_app: AppSnapshot) -> DriftEntry:
    """比较两个同名 App 的版本差异。"""
    f_rev = from_app.revision_short
    t_rev = to_app.revision_short

    if f_rev == t_rev and f_rev:
        status = "synced"
    elif not f_rev or not t_rev:
        status = "partial"
    else:
        status = "drifted"

    return DriftEntry(
        name=name,
        project=from_app.project,
        from_rev=f_rev or "(none)",
        to_rev=t_rev or "(none)",
        from_health=from_app.health_status,
        to_health=to_app.health_status,
        from_sync=from_app.sync_status,
        to_sync=to_app.sync_status,
        status=status,
    )


def detect_drift(
    from_apps: list[AppSnapshot],
    to_apps: list[AppSnapshot],
    project_filter: str | None = None,
) -> DriftReport:
    """对两组 App 做版本漂移比对。"""
    from_idx = _build_index(from_apps)
    to_idx = _build_index(to_apps)

    all_names = sorted(set(from_idx) | set(to_idx))

    report = DriftReport()

    for name in all_names:
        f = from_idx.get(name)
        t = to_idx.get(name)

        if f and t:
            entry = _compare(name, f, t)
            # ponytail: 暂不按 project 额外分组，保持输出扁平和可 jq
            # 如需 project 分组，在 report 层按 project 再 groupby 即可
            report.matched[name] = entry
        elif f:
            report.source_only.append({
                "name": name,
                "project": f.project,
                "revision": f.revision_short,
                "health": f.health_status,
                "sync": f.sync_status,
            })
        else:
            report.target_only.append({
                "name": name,
                "project": t.project,
                "revision": t.revision_short,
                "health": t.health_status,
                "sync": t.sync_status,
            })

    # 统计
    synced = sum(1 for e in report.matched.values() if e.status == "synced")
    drifted = sum(1 for e in report.matched.values() if e.status == "drifted")
    partial = sum(1 for e in report.matched.values() if e.status == "partial")
    report.summary = {
        "total": len(report.matched),
        "sourceOnly": len(report.source_only),
        "targetOnly": len(report.target_only),
        "synced": synced,
        "drifted": drifted,
        "partial": partial,
        "driftRate": round(drifted / len(report.matched), 4) if report.matched else 0,
    }
    return report


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def to_json(report: DriftReport) -> str:
    """序列化 DriftReport 为 JSON（含所有原始字段）。"""
    def _entry(e: DriftEntry) -> dict:
        return {
            "name": e.name,
            "project": e.project,
            "fromRevision": e.from_rev,
            "toRevision": e.to_rev,
            "fromHealth": e.from_health,
            "toHealth": e.to_health,
            "fromSync": e.from_sync,
            "toSync": e.to_sync,
            "status": e.status,
        }
    return json.dumps({
        "matched": {n: _entry(e) for n, e in report.matched.items()},
        "sourceOnly": report.source_only,
        "targetOnly": report.target_only,
        "summary": report.summary,
    }, ensure_ascii=False, indent=2)


def to_markdown(report: DriftReport, from_label: str, to_label: str) -> str:
    """生成可读 Markdown 报告。"""
    import io
    buf = io.StringIO()

    def p(line="", file=None):
        print(line, file=file)

    p("# ArgoCD 版本漂移检测报告\n")
    p(f"**比对**：{from_label} → {to_label}")
    p(f"**时间**：{__import__('datetime').datetime.now().isoformat()}\n")

    s = report.summary
    p("## 统计概览\n")
    p("| 指标 | 值 |")
    p("|------|---|")
    p(f"| 比对 App 总数 | {s['total']} |")
    p(f"| 版本一致（Synced） | {s['synced']} |")
    p(f"| 版本漂移（Drifted） | {s['drifted']} |")
    p(f"| 漂移率 | {s['driftRate']:.1%} |")
    p(f"| 仅源端有 | {s['sourceOnly']} |")
    p(f"| 仅目标端有 | {s['targetOnly']} |")

    if report.matched:
        p("\n## 漂移 App 详情（按 revision 分组）\n")
        p(f"| App | 项目 | {from_label} | {to_label} | 状态 | {from_label} 健康 | {to_label} 健康 |")
        p("|-----|------|--------|--------|------|------------|------------|")
        # 先漂移后一致，减少需要关注的信息量
        for entry in sorted(report.matched.values(),
                            key=lambda e: (e.status != "drifted", e.name)):
            flag = "⚠️" if entry.status == "drifted" else "✅"
            p(f"| {flag} `{entry.name}` | {entry.project} | "
              f"`{entry.from_rev}` | `{entry.to_rev}` | "
              f"`{entry.status}` | {entry.from_health} | {entry.to_health} |")

    if report.source_only:
        p(f"\n## 仅 {from_label} 存在的 App（{len(report.source_only)} 个）\n")
        for a in report.source_only:
            p(f"- `{a['name']}` · {a['project']} · rev={a['revision']}")

    if report.target_only:
        p(f"\n## 仅 {to_label} 存在的 App（{len(report.target_only)} 个）\n")
        for a in report.target_only:
            p(f"- `{a['name']}` · {a['project']} · rev={a['revision']}")

    return buf.getvalue()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="ArgoCD 版本漂移检测：比对两个集群同名 App 的 revision 是否一致。",
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
                   help="只比对指定项目的 App")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p.add_argument("--concurrency", type=int, default=8,
                   help="并发数（默认 8）")
    return p


def main(argv: list[str] | None = None) -> int:
    p = build_argparser()
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

    report = detect_drift(from_apps, to_apps, project_filter=args.project)

    if args.output == "json":
        print(to_json(report))
    else:
        print(to_markdown(report, from_label, to_label))

    # 漂移率 > 0 时返回警告退出码
    if report.summary["drifted"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
