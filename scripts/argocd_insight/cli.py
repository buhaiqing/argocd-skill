"""命令行入口，支持多子命令。"""

from __future__ import annotations

import argparse
import sys
import os

# 确保 argocd_insight 包内模块可导入
sys.path.insert(0, os.path.dirname(__file__))

from . import diagnose, drift, health


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="argocd-insight",
        description="ArgoCD 洞察工具集：诊断、漂移检测、稳定性评估",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # diagnose
    p_diag = sub.add_parser("diagnose", help="问题 App 智能诊断")
    p_diag.add_argument("--project")
    p_diag.add_argument("--severity", choices=["critical", "high", "medium", "low"])
    p_diag.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_diag.add_argument("--concurrency", type=int, default=8)

    # drift
    p_drift = sub.add_parser("drift", help="版本漂移检测")
    p_drift.add_argument("--from", dest="from_label", default="源端")
    p_drift.add_argument("--to", dest="to_label", default="目标端")
    p_drift.add_argument("--from-server", dest="from_server")
    p_drift.add_argument("--to-server", dest="to_server")
    p_drift.add_argument("--project")
    p_drift.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_drift.add_argument("--concurrency", type=int, default=8)

    # health
    p_health = sub.add_parser("health", help="运行稳定性评估")
    p_health.add_argument("--project")
    p_health.add_argument("--days", type=int, default=30)
    p_health.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_health.add_argument("--concurrency", type=int, default=8)

    args = parser.parse_args()

    if args.command == "diagnose":
        return diagnose.main([
            "--project", args.project] if args.project else []
            + ["--severity", args.severity] if args.severity else []
            + ["--output", args.output]
            + ["--concurrency", str(args.concurrency)]
        )
    elif args.command == "drift":
        return drift.main([
            "--from", args.from_label,
            "--to", args.to_label,
            "--from-server", args.from_server] if args.from_server else []
            + ["--to-server", args.to_server] if args.to_server else []
            + ["--project", args.project] if args.project else []
            + ["--output", args.output]
            + ["--concurrency", str(args.concurrency)]
        )
    elif args.command == "health":
        return health.main([
            "--project", args.project] if args.project else []
            + ["--days", str(args.days)]
            + ["--output", args.output]
            + ["--concurrency", str(args.concurrency)]
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
