#!/usr/bin/env python3
"""
repo_health — Git 源健康检查工具

Usage:
  python -m argocd_insight.repo_health               # 全量检查
  python -m argocd_insight.repo_health --output json
  python -m argocd_insight.repo_health --project default
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from collections import defaultdict


def run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"timeout after {timeout}s"
    except FileNotFoundError:
        return -2, "", "command not found"


def fetch_repos() -> list[dict]:
    _, out, _ = run(["argocd", "repo", "list", "--output", "json"])
    return json.loads(out) if out else []


def fetch_apps() -> list[dict]:
    _, out, _ = run(["argocd", "app", "list", "--output", "json"])
    return json.loads(out) if out else []


def check_repo_connectivity(repo_url: str) -> dict:
    """检查 repo 可达性和连接状态"""
    rc, _, err = run(["git", "ls-remote", repo_url], timeout=10)
    if rc == 0:
        return {"status": "reachable", "error": None}
    elif rc == -1:
        return {"status": "timeout", "error": "ls-remote timeout"}
    else:
        # ponytail: 忽略 git 认证失败（credential helper 未配置正常）
        # ArgoCD server 侧有凭证即可，agent 侧 ls-remote 可能无凭证
        return {"status": "unreachable_from_agent", "error": err.strip()[:80]}


def check_branch_exists(repo_url: str, revision: str) -> dict:
    """检查某 revision（分支/tag）在 repo 中是否存在"""
    # 先用 ls-remote 检查
    rc, out, _ = run(["git", "ls-remote", repo_url, revision], timeout=10)
    if rc == 0 and out.strip():
        return {"exists": True, "method": "ls-remote"}
    # 如果 ls-remote 失败（无凭证），用 ArgoCD 的 manifests 接口
    # ponytail: 暂时跳过 AppProject filter
    return {"exists": None, "method": "unknown_no_credential"}


def build_report(repos: list[dict], apps: list[dict], project_filter: str | None) -> dict:
    # 1. repo 连接状态
    repo_states = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [(ex.submit(check_repo_connectivity, r["repo"]), r["repo"]) for r in repos]
        for f, repo_url in futures:
            repo_states[repo_url] = f.result()

    # 2. 统计
    reachable = sum(1 for v in repo_states.values() if v["status"] == "reachable")
    unreachable = len(repo_states) - reachable

    # 3. 按 App 统计 revision 使用情况
    rev_usage = defaultdict(list)
    filtered_apps = [a for a in apps if not project_filter or a.get("spec", {}).get("project") == project_filter]
    for app in filtered_apps:
        name = app.get("metadata", {}).get("name", "")
        spec = app.get("spec", {})
        # 单源
        src = spec.get("source", {})
        repo_url = src.get("repoURL", "")
        revision = src.get("targetRevision", "HEAD")
        if repo_url:
            rev_usage[repo_url].append({"app": name, "revision": revision, "type": "single"})
        # 多源
        for i, s in enumerate(spec.get("sources", [])):
            repo_url = s.get("repoURL", "")
            revision = s.get("targetRevision", "HEAD")
            if repo_url:
                rev_usage[repo_url].append({"app": name, "revision": revision, "type": f"source-{i}"})

    # 4. 按 repo 统计 app 数量
    repo_apps = {url: len(items) for url, items in rev_usage.items()}

    by_repo = {}
    for r in repos:
        url = r["repo"]
        by_repo[url] = {
            "connectionState": r.get("connectionState", {}).get("status", "unknown"),
            "connectivity": repo_states.get(url, {}),
            "appCount": repo_apps.get(url, 0),
            "revisions": list({item["revision"] for item in rev_usage.get(url, [])})[:10],
        }

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalRepos": len(repos),
        "reachableRepos": reachable,
        "unreachableFromAgent": unreachable,
        "totalApps": len(filtered_apps),
        "byRepo": by_repo,
    }


def print_markdown(report: dict):
    print("# ArgoCD Git 源健康报告\n")
    print(f"生成时间：{report['generatedAt']}")
    print(f"仓库总数：{report['totalRepos']}，可达（agent 侧）：{report['reachableRepos']}，不可达：{report['unreachableFromAgent']}")
    print(f"关联 App 数：{report['totalApps']}\n")

    print("## 仓库健康状态\n")
    print("| 仓库 | App 数 | ArgoCD 连接 | Agent 可达 | 说明 |")
    print("|------|--------|------------|-----------|------|")
    for url, info in sorted(report["byRepo"].items(), key=lambda x: -x[1]["appCount"]):
        conn = info["connectionState"]
        conn_emoji = "✅" if conn == "Successful" else "⚠️" if conn else "❓"
        cx = info["connectivity"]
        cx_status = cx.get("status", "unknown") if cx else "unknown"
        cx_emoji = "✅" if cx_status == "reachable" else "⚠️" if "unreachable" in cx_status else "❓"
        note = cx.get("error", "")[:30] if cx.get("error") else ""
        repo_name = url.split("/")[-1].replace(".git", "")
        revs = ", ".join(info["revisions"][:3])
        print(f"| `{repo_name}` | {info['appCount']} | {conn_emoji} {conn} | {cx_emoji} | {note} |")

    print(f"\n> 注：Agent 侧不可达可能是 credential helper 未配置，ArgoCD server 侧凭证独立。")
    print(f"> 如需检查分支存在性，需在 ArgoCD server 有凭证的环境运行 `git ls-remote --heads <repo> <branch>`。")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ArgoCD Git 源健康检查")
    p.add_argument("--project")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    args = p.parse_args(argv)

    print("Fetching repos and apps...", file=sys.stderr)
    repos = fetch_repos()
    apps = fetch_apps()
    print(f"Got {len(repos)} repos, {len(apps)} apps", file=sys.stderr)

    report = build_report(repos, apps, args.project)

    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)
    return 0

