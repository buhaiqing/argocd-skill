#!/usr/bin/env python3
"""
argocd_deploy_stats — 部署频率统计工具

Usage:
  python -m argocd_deploy_stats.stats              # 全量统计
  python -m argocd_deploy_stats.stats --days 7    # 最近 7 天
  python -m argocd_deploy_stats.stats --project default
  python -m argocd_deploy_stats.stats --output json
"""
import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from collections import defaultdict


def run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a CLI command with timeout. Returns (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timed out after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"


def fetch_apps() -> list[dict]:
    rc, out, _ = run(["argocd", "app", "list", "--output", "json"])
    return json.loads(out) if rc == 0 and out else []


def fetch_history(app_name: str) -> tuple[str, list[dict]]:
    rc, out, _ = run(["argocd", "app", "get", app_name, "--output", "json"])
    if rc != 0 or not out:
        return app_name, []
    try:
        d = json.loads(out)
        return app_name, d.get("status", {}).get("history", [])
    except Exception:
        return app_name, []


def build_report(apps: list[dict], days: int | None, project_filter: str | None,
                 app_filter: str | None = None, concurrency: int = 20) -> dict:
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 1. 按 project / app 过滤
    filtered_apps = [
        a for a in apps
        if (not project_filter or a.get("spec", {}).get("project") == project_filter)
        and (not app_filter or a.get("metadata", {}).get("name") == app_filter)
    ]

    # 2. 并发拉 history
    import sys
    print(f"  fetching history for {len(filtered_apps)} apps (concurrency={concurrency})...", file=sys.stderr)
    print("  [ponytail: 并发 8，566 App 预计 ~3min；并发提至 20 若 server 允许]", file=sys.stderr)
    app_histories = {}
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(fetch_history, a.get("metadata", {}).get("name", "")): a for a in filtered_apps}
        done = 0
        for f in as_completed(futs):
            n, h = f.result()
            app_histories[n] = h
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(filtered_apps)} done", file=sys.stderr)

    # 3. 聚合统计
    def match(entry: dict) -> bool:
        if cutoff is None:
            return True
        ts = entry.get("deployedAt", "")
        if not ts:
            return False
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt >= cutoff
        except Exception:
            return False

    by_initiator: dict[str, int] = defaultdict(int)
    by_project: dict[str, int] = defaultdict(int)
    recent_deploys: list[dict] = []
    total_deploys = 0

    for app in filtered_apps:
        name = app.get("metadata", {}).get("name", "")
        project = app.get("spec", {}).get("project", "unknown")
        for entry in app_histories.get(name, []):
            if not match(entry):
                continue
            total_deploys += 1
            initiator = entry.get("initiatedBy", {})
            if initiator.get("automated"):
                who = "automated"
            else:
                who = str(initiator.get("username") or "unknown")
            by_initiator[who] += 1
            by_project[project] += 1
            recent_deploys.append({
                "app": name,
                "project": project,
                "deployedAt": entry.get("deployedAt", ""),
                "revision": entry.get("revision", "")[:8],
                "initiatedBy": who,
            })

    recent_deploys.sort(key=lambda x: x["deployedAt"], reverse=True)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "projectFilter": project_filter,
        "totalApps": len(filtered_apps),
        "totalDeploys": total_deploys,
        "byProject": dict(sorted(by_project.items(), key=lambda x: -x[1])),
        "byInitiator": dict(sorted(by_initiator.items(), key=lambda x: -x[1])),
        "recentDeploys": recent_deploys[:50],
    }


def print_markdown(report: dict):
    days = report["days"]
    suffix = f"（最近 {days} 天）" if days else "（全部时间）"
    pf = f"，项目={report['projectFilter']}" if report["projectFilter"] else ""
    print(f"# ArgoCD 部署频率报告 {suffix}{pf}\n")
    print(f"生成时间：{report['generatedAt']}")
    print(f"统计 App 数：{report['totalApps']}，部署次数：{report['totalDeploys']}\n")

    print("## 按项目部署次数\n")
    print("| 项目 | 部署次数 |")
    print("|------|---------|")
    for p, c in sorted(report["byProject"].items(), key=lambda x: -x[1]):
        print(f"| {p} | {c} |")

    print("\n## 按触发者部署次数\n")
    print("| 触发者 | 次数 |")
    print("|--------|-----|")
    for who, c in report["byInitiator"].items():
        print(f"| {who} | {c} |")

    print(f"\n## 最近 {min(20, len(report['recentDeploys']))} 次部署\n")
    print("| 时间 | App | 项目 | 触发者 | Revision |")
    print("|------|-----|------|--------|----------|")
    for d in report["recentDeploys"][:20]:
        dt = d["deployedAt"][:19].replace("T", " ")
        print(f"| {dt} | {d['app']} | {d['project']} | {d['initiatedBy']} | `{d['revision']}` |")


def main():
    p = argparse.ArgumentParser(description="ArgoCD 部署频率统计")
    p.add_argument("--days", type=int, default=None, help="只统计最近 N 天")
    p.add_argument("--project", type=str, default=None, help="只统计指定项目")
    p.add_argument("--app", type=str, default=None, help="只统计指定 App 名称")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p.add_argument("--concurrency", type=int, default=8, help="并发数（默认 8，过高会触发 ArgoCD server 限流）")
    p.add_argument("--limit", type=int, default=None, help="最多统计 N 个 App（默认全部）")
    args = p.parse_args()

    print("Fetching all apps...", file=__import__("sys").stderr)
    apps = fetch_apps()
    if args.limit:
        apps = apps[:args.limit]
    print(f"Got {len(apps)} apps, fetching histories (concurrency={args.concurrency})...", file=__import__("sys").stderr)
    t0 = time.time()
    report = build_report(apps, args.days, args.project, args.app, args.concurrency)
    print(f"Done in {time.time()-t0:.1f}s", file=__import__("sys").stderr)

    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)


if __name__ == "__main__":
    main()
