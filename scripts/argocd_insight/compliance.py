#!/usr/bin/env python3
"""
compliance — 配置合规检查工具

检查 ArgoCD App 的配置风险点（syncPolicy / namespace / self-heal / retry）

Usage:
  python -m argocd_insight.compliance               # 全量检查
  python -m argocd_insight.compliance --severity    # 只看高风险
  python -m argocd_insight.compliance --output json
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from collections import defaultdict

# ponytail: 一次性脚本，不建完整类。按风险维度组织代码。
RISK_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease",
                    "argocd", "openshift", "default"}


def run(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except FileNotFoundError:
        return -2, "", "command not found"


def fetch_all() -> list[dict]:
    _, out, _ = run(["argocd", "app", "list", "--output", "json"])
    return json.loads(out) if out else []


def check_app(app: dict) -> list[dict]:
    """检查单个 App 的配置风险，返回风险列表"""
    name = app.get("metadata", {}).get("name", "")
    spec = app.get("spec", {})
    dest = spec.get("destination", {})
    ns = dest.get("namespace", "")
    sp = spec.get("syncPolicy", {})
    auto = sp.get("automated")
    sync_opts = sp.get("syncOptions", [])
    retry = sp.get("retry")
    risks = []

    # R1: automated 无 retry
    if auto and not retry:
        risks.append({
            "rule": "automated-no-retry",
            "severity": "medium",
            "message": "开了 automated 但没有 retry 策略，sync 失败后不会自动重试",
            "suggestion": f"建议加 `argocd app set {name} --retry --retry-limit 3`",
        })

    # R2: automated 无 self-heal
    if auto:
        opts_lower = [o.lower() for o in sync_opts]
        has_selfheal = any("selfheal=true" in o for o in opts_lower)
        if not has_selfheal:
            risks.append({
                "rule": "automated-no-selfheal",
                "severity": "high",
                "message": "开了 automated 但没有 self-heal，集群漂移不会自动恢复",
                "suggestion": f"argocd app set {name} --sync-policy automated --auto-prune --self-heal",
            })

    # R3: automated 无 prune（建议加 PruneLast）
    if auto:
        opts_lower = [o.lower() for o in sync_opts]
        has_prune = any("prunelast=true" in o or "prune=true" in o for o in opts_lower)
        if not has_prune:
            risks.append({
                "rule": "automated-no-prune",
                "severity": "low",
                "message": "开了 automated 但没有 PruneLast=true，不会自动清理孤儿资源",
                "suggestion": f"argocd app set {name} --sync-option PruneLast=true",
            })

    # R4: PruneLast=true 但非 automated（行为可能不符合预期）
    opts_lower = [o.lower() for o in sync_opts]
    has_prune_last = any("prunelast=true" in o for o in opts_lower)
    if has_prune_last and not auto:
        risks.append({
            "rule": "prune-last-not-automated",
            "severity": "low",
            "message": "设置了 PruneLast=true 但未开启 automated，PruneLast 仅在手动 sync 时生效",
            "suggestion": f"确认是否需要 `argocd app sync {name}` 前预期行为",
        })

    # R5: 部署到系统 namespace
    if ns in RISK_NAMESPACES:
        risks.append({
            "rule": "system-namespace",
            "severity": "high",
            "message": f"部署到了系统 namespace: {ns}",
            "suggestion": f"确认是否必要，或调整 App 目标 namespace",
        })

    return risks


def build_report(apps: list[dict], min_severity: str = "low") -> dict:
    severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    min_level = severity_order.get(min_severity, 0)

    all_risks = []
    by_rule = defaultdict(list)
    by_severity = defaultdict(list)

    for app in apps:
        name = app.get("metadata", {}).get("name", "")
        for risk in check_app(app):
            if severity_order.get(risk["severity"], 0) >= min_level:
                risk["app"] = name
                all_risks.append(risk)
                by_rule[risk["rule"]].append(name)
                by_severity[risk["severity"]].append(name)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalApps": len(apps),
        "riskyApps": len({r["app"] for r in all_risks}),
        "totalRisks": len(all_risks),
        "bySeverity": {k: len(v) for k, v in by_severity.items()},
        "byRule": {
            k: {"count": len(v), "apps": v[:5], "total": len(v)}
            for k, v in by_rule.items()
        },
        "risks": all_risks,
    }


def print_markdown(report: dict):
    print(f"# ArgoCD 配置合规报告\n")
    print(f"生成时间：{report['generatedAt']}")
    print(f"总 App 数：{report['totalApps']}，有风险：{report['riskyApps']}，风险项：{report['totalRisks']}\n")

    sev = report.get("bySeverity", {})
    print(f"| 严重级别 | 风险 App 数 |")
    print(f"|----------|-----------|")
    for s in ["high", "medium", "low"]:
        if s in sev:
            print(f"| {s} | {sev[s]} |")

    for rule, info in sorted(report.get("byRule", {}).items(),
                              key=lambda x: -x[1]["total"]):
        label = {
            "automated-no-retry": "⚠️ automated 无 retry",
            "automated-no-selfheal": "🚨 automated 无 self-heal",
            "automated-no-prune": "ℹ️ automated 无 PruneLast",
            "prune-last-not-automated": "ℹ️ PruneLast 非 automated",
            "system-namespace": "🚨 部署到系统 namespace",
        }.get(rule, rule)
        apps_shown = ", ".join(f"`{a}`" for a in info["apps"][:5])
        more = f"（还有 {info['total']-info['count']} 个）" if info["total"] > info["count"] else ""
        print(f"\n### {label}（{info['total']} 个）\n")
        print(f"{apps_shown} {more}")
        # 取一条示例
        sample = next((r for r in report["risks"] if r["rule"] == rule), {})
        if sample:
            print(f"  → {sample['message']}")
            print(f"  → 建议：`{sample['suggestion']}`")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ArgoCD 配置合规检查")
    p.add_argument("--severity", choices=["low", "medium", "high", "critical"], default="low",
                   help="最小严重级别（默认 low）")
    p.add_argument("--output", choices=["markdown", "json"], default="markdown")
    args = p.parse_args(argv)

    print("Fetching apps...", file=sys.stderr)
    apps = fetch_all()
    print(f"Got {len(apps)} apps, analyzing...", file=sys.stderr)
    report = build_report(apps, args.severity)

    if args.output == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_markdown(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
