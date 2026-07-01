#!/usr/bin/env python3
"""
oos_analyzer — OutOfSync 根因归因工具

Usage:
  python -m argocd_deploy_stats.oos_analyzer               # 全量分析
  python -m argocd_deploy_stats.oos_analyzer --days 7     # 只看近 7 天 OOS 的
  python -m argocd_deploy_stats.oos_analyzer --project default
  python -m argocd_deploy_stats.oos_analyzer --output json
"""
import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from collections import defaultdict


def run(cmd: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run a CLI command with timeout. Returns (rc, stdout, stderr)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        return -1, "", f"Timed out after {timeout}s"
    except FileNotFoundError:
        return -2, "", f"Command not found: {cmd[0]}"


def fetch_apps() -> list[dict]:
    _, out, _ = run(["argocd", "app", "list", "--output", "json"])
    return json.loads(out) if out else []


def classify_app(app_name: str) -> dict:
    """对单个 App 做 OutOfSync 归因，返回原因分类"""
    # ponytail: 串行拉 resources + diff，2 call / app。
    #   566 App OOS 率 ~10% → ~110 calls，~2min。
    #   若吞吐不够，将 classify_app 拆为两步并发（先批量 resources，再批量 diff）。
    # 1. 拿 resources（含 orphaned 列）
    _, res_out, _ = run(["argocd", "app", "resources", app_name])
    orphaned = []
    for line in res_out.strip().splitlines():
        # ponytail: Orphaned 列检测基于列尾 "Yes"，格式依赖 ArgoCD 版本。
        #   若版本升级后失效，改为解析 res 的 JSON 输出取 orphaned 字段。
        if "\tOrphaned" in line or line.strip().endswith("Yes"):
            parts = line.split()
            if parts and parts[-1] == "Yes":
                name = parts[-2] if len(parts) >= 2 else parts[0]
                kind = parts[-3] if len(parts) >= 3 else "?"
                orphaned.append({"kind": kind, "name": name})

    # 2. diff 看具体差异
    diff_rc, diff_out, _ = run(["argocd", "app", "diff", app_name])

    has_additions = False
    has_deletions = False
    # ponytail: 逐行扫描 diff，不做结构化 diff 解析。
    #   统一 diff 格式用 `+`/`-` 前缀，普通 diff 用 `>`/`<` 前缀。
    #   同时匹配两种格式以避免 ArgoCD 版本差异。
    for line in diff_out.splitlines():
        if line.startswith("> ") or (line.startswith("+") and not line.startswith("+++")):
            has_additions = True
        elif line.startswith("< ") or (line.startswith("-") and not line.startswith("---")):
            has_deletions = True

    cause = None
    if has_additions and not has_deletions:
        cause = "Git 新增/未部署"
    elif has_deletions and not has_additions:
        cause = "手动漂移（集群多出 Git 没有的资源）"
    elif has_additions and has_deletions:
        cause = "内容漂移（Git 与集群不一致）"
    elif diff_rc == 1:
        cause = "未知差异"

    return {
        "app": app_name,
        "cause": cause,
        "hasAdditions": has_additions,
        "hasDeletions": has_deletions,
        "orphaned": [f"{o['kind']}/{o['name']}" for o in orphaned[:5]],
        "diffRc": diff_rc,
    }


def build_report(apps: list[dict], days: int | None, project_filter: str | None, concurrency: int = 4) -> dict:
    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # 过滤 OOS apps
    oos_apps = [
        a for a in apps
        if a.get("status", {}).get("sync", {}).get("status") == "OutOfSync"
        and (not project_filter or a.get("spec", {}).get("project") == project_filter)
    ]

    print(f"Found {len(oos_apps)} OOS apps, analyzing...", file=sys.stderr)

    results = {}
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {ex.submit(classify_app, a.get("metadata", {}).get("name", "")): a for a in oos_apps}
        done = 0
        for f in as_completed(futs):
            r = f.result()
            results[r["app"]] = r
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(oos_apps)} done", file=sys.stderr)

    # 聚合归因
    by_cause = defaultdict(list)
    for app_name, r in results.items():
        if r["cause"]:
            by_cause[r["cause"]].append(app_name)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "days": days,
        "totalApps": len(apps),
        "oosCount": len(oos_apps),
        "byCause": {k: len(v) for k, v in by_cause.items()},
        "byCauseApps": dict(by_cause),
        "details": dict(results),
    }


def print_markdown(report: dict):
    print(f"# ArgoCD OutOfSync 根因分析\n")
    print(f"生成时间：{report['generatedAt']}")
    print(f"总 App 数：{report['totalApps']}，OutOfSync：{report['oosCount']}\n")

    print("## 归因汇总\n")
    print("| 原因 | App 数量 |")
    print("|------|---------|")
    for cause, count in sorted(report["byCause"].items(), key=lambda x: -x[1]):
        print(f"| {cause} | {count} |")

    for cause, app_names in sorted(report.get("byCauseApps", {}).items(), key=lambda x: -len(x[1])):
        print(f"\n### {cause}（{len(app_names)} 个）\n")
        for name in app_names[:20]:
            r = report["details"].get(name, {})
            extras = []
            if r.get("hasAdditions") and r.get("hasDeletions"):
                extras.append("内容不一致")
            elif r.get("hasAdditions"):
                extras.append("Git 新增/未部署")
            elif r.get("hasDeletions"):
                extras.append("手动漂移")
            if r.get("orphaned"):
                extras.append(f"孤儿: {', '.join(r['orphaned'][:2])}")
            detail = f"（{'; '.join(extras)}）" if extras else ""
            print(f"- `{name}` {detail}")


def main():
    p = argparse.ArgumentParser(description="ArgoCD OutOfSync 根因归因")
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--project", type=str, default=None)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    args = p.parse_args()

    print("Fetching apps...", file=sys.stderr)
    apps = fetch_apps()
    report = build_report(apps, args.days, args.project, args.concurrency)

    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)


if __name__ == "__main__":
    main()
