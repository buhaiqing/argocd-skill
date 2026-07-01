"""命令行入口，支持多子命令。"""

from __future__ import annotations

import argparse
import sys
import os

# 确保 argocd_insight 包内模块可导入
sys.path.insert(0, os.path.dirname(__file__))

from . import diagnose, drift, health, repo_health, compliance, cost, multi_cluster, report_push, report_composer
from . import snapshot_store, trend, config_compare, predict


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="argocd-insight",
        description="ArgoCD 洞察工具集：诊断、漂移检测、稳定性评估、Git 源健康、配置合规",
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

    # compliance
    p_comp = sub.add_parser("compliance", help="配置合规检查")
    p_comp.add_argument("--severity", choices=["low", "medium", "high", "critical"], default="low")
    p_comp.add_argument("--output", choices=["markdown", "json"], default="markdown")

    # repo-health
    p_repo = sub.add_parser("repo-health", help="Git 源健康检查")
    p_repo.add_argument("--project")
    p_repo.add_argument("--output", choices=["markdown", "json"], default="markdown")

    # cost
    p_cost = sub.add_parser("cost", help="资源成本估算")
    p_cost.add_argument("--project", help="按项目过滤")
    p_cost.add_argument("--output", choices=["markdown", "json"], default="markdown")

    # multi-cluster
    p_mc = sub.add_parser("multi-cluster", help="多集群对比报告")
    p_mc.add_argument("--from", dest="from_label", default="源端")
    p_mc.add_argument("--to", dest="to_label", default="目标端")
    p_mc.add_argument("--from-server", dest="from_server")
    p_mc.add_argument("--to-server", dest="to_server")
    p_mc.add_argument("--project")
    p_mc.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_mc.add_argument("--concurrency", type=int, default=8)

    # report-push
    p_rp = sub.add_parser("report-push", help="推送报告到飞书/钉钉/Slack")
    p_rp.add_argument("--file", "-f", help="报告文件路径")
    p_rp.add_argument("--channel", choices=["feishu", "dingtalk", "slack"], help="通知渠道")
    p_rp.add_argument("--webhook", required=True, help="Webhook URL")
    p_rp.add_argument("--title", default="ArgoCD 报告", help="消息标题")
    p_rp.add_argument("--style", choices=["markdown", "json"], default="markdown")

    # report-compose
    p_rc = sub.add_parser("report-compose", help="合成多模块综合报告")
    p_rc.add_argument("--include", default="diagnose,compliance,cost,health",
                       help="逗号分隔的模块列表（默认: 全部）")
    p_rc.add_argument("--project", help="项目过滤（传递给 diagnose/health）")
    p_rc.add_argument("--output", choices=["markdown", "json"], default="markdown",
                       help="输出格式（默认: markdown）")
    p_rc.add_argument("--push", action="store_true", help="合成后自动推送")
    p_rc.add_argument("--webhook", dest="webhook_url", default="", help="Webhook URL（推送时必填）")
    p_rc.add_argument("--channel", choices=["feishu", "dingtalk", "slack"], default="",
                       help="推送渠道（留空则自动检测）")
    p_rc.add_argument("--title", default="ArgoCD 综合报告", help="推送消息标题")

    # snapshot
    p_snap = sub.add_parser("snapshot", help="采集快照")
    p_snap.add_argument("--include", default="diagnose,compliance,cost,health",
                         help="逗号分隔的模块列表（默认: 全部）")
    p_snap.add_argument("--project", help="项目过滤（传递给 diagnose/health）")
    p_snap.add_argument("--store-dir", default="", help="快照存储目录")

    # trend
    p_trend = sub.add_parser("trend", help="趋势分析")
    p_trend.add_argument("--days", type=int, default=7, help="分析最近 N 天（默认 7）")
    p_trend.add_argument("--metric", default="", help="指定分析的指标路径")
    p_trend.add_argument("--store-dir", default="", help="快照存储目录")
    p_trend.add_argument("--output", choices=["markdown", "json"], default="markdown")

    # config-compare
    p_cc = sub.add_parser("config-compare", help="配置对比与环境差异检测")
    p_cc.add_argument("files", nargs="*", help="ArgoCD app JSON 文件路径")
    p_cc.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown")
    p_cc.add_argument("--group", "-g", action="append", help="分组对比: name=app1,app2（可重复）")

    # predict
    p_pred = sub.add_parser("predict", help="风险预测（Revision 滞后 + 成本超支）")
    p_pred.add_argument("files", nargs="*", help="ArgoCD app JSON 文件路径")
    p_pred.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown")
    p_pred.add_argument("--budget", type=float, default=None, help="每应用预算上限 (USD)")
    p_pred.add_argument("--type", choices=["all", "lag", "cost"], default="all", help="预测类型")

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
    elif args.command == "repo-health":
        return repo_health.main([
            "--project", args.project] if args.project else []
            + ["--output", args.output]
        )
    elif args.command == "compliance":
        return compliance.main([
            "--severity", args.severity,
            "--output", args.output,
        ])
    elif args.command == "cost":
        return cost.main([
            "--project", args.project] if args.project else []
            + ["--output", args.output]
        )
    elif args.command == "multi-cluster":
        return multi_cluster.main([
            "--from", args.from_label,
            "--to", args.to_label,
            "--from-server", args.from_server] if args.from_server else []
            + ["--to-server", args.to_server] if args.to_server else []
            + ["--project", args.project] if args.project else []
            + ["--output", args.output]
            + ["--concurrency", str(args.concurrency)]
        )
    elif args.command == "report-push":
        return report_push.main([
            "--file", args.file] if args.file else []
            + ["--channel", args.channel] if args.channel else []
            + ["--webhook", args.webhook]
            + ["--title", args.title]
            + ["--style", args.style]
        )
    elif args.command == "report-compose":
        cmd = [
            "--include", args.include,
            "--output", args.output,
            "--title", args.title,
        ]
        if args.project:
            cmd += ["--project", args.project]
        if args.push:
            cmd.append("--push")
        if args.webhook_url:
            cmd += ["--webhook", args.webhook_url]
        if args.channel:
            cmd += ["--channel", args.channel]
        return report_composer.main(cmd)
    elif args.command == "snapshot":
        from . import report_composer as _rc
        from .snapshot_store import SnapshotStore
        import io
        includes = [s.strip() for s in args.include.split(",") if s.strip()]
        results = {}
        for name in includes:
            if name not in _rc.MODULES:
                results[name] = None
                continue
            mod_entry = _rc.MODULES[name]
            argv = ["--output", "json"]
            if args.project and name in ("diagnose", "health"):
                argv += ["--project", args.project]
            data = _rc._capture_json(mod_entry["module"], argv)
            results[name] = data
        store = SnapshotStore(args.store_dir if args.store_dir else None)
        path = store.save(results)
        print(f"✓ 快照已保存: {path}", file=sys.stderr)
        return 0
    elif args.command == "trend":
        return trend.main([
            "--days", str(args.days),
            "--metric", args.metric,
            "--store-dir", args.store_dir,
            "--output", args.output,
        ])
    elif args.command == "config-compare":
        cmd = args.files + ["--format", args.format]
        if args.group:
            for g in args.group:
                cmd += ["--group", g]
        return config_compare.main(cmd)
    elif args.command == "predict":
        cmd = args.files + ["--format", args.format, "--type", args.type]
        if args.budget is not None:
            cmd += ["--budget", str(args.budget)]
        return predict.main(cmd)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
