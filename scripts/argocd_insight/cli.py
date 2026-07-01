"""命令行入口，支持多子命令。"""

from __future__ import annotations

import argparse
import sys

from . import diagnose, drift, health, repo_health, compliance, cost, multi_cluster, report_push, report_composer
from . import trend, config_compare, predict, autofix, impact, batch, scaffold
from .snapshot_store import SnapshotStore


def _handle_diagnose(args: argparse.Namespace) -> int:
    argv: list[str] = ["--output", args.output, "--concurrency", str(args.concurrency)]
    if args.project:
        argv += ["--project", args.project]
    if args.severity:
        argv += ["--severity", args.severity]
    return diagnose.main(argv)


def _handle_drift(args: argparse.Namespace) -> int:
    argv: list[str] = [
        "--from", args.from_label, "--to", args.to_label,
        "--output", args.output, "--concurrency", str(args.concurrency),
    ]
    if args.from_server:
        argv += ["--from-server", args.from_server]
    if args.to_server:
        argv += ["--to-server", args.to_server]
    if args.project:
        argv += ["--project", args.project]
    return drift.main(argv)


def _handle_health(args: argparse.Namespace) -> int:
    argv: list[str] = [
        "--days", str(args.days),
        "--output", args.output, "--concurrency", str(args.concurrency),
    ]
    if args.project:
        argv += ["--project", args.project]
    return health.main(argv)


def _handle_repo_health(args: argparse.Namespace) -> int:
    argv: list[str] = ["--output", args.output]
    if args.project:
        argv += ["--project", args.project]
    return repo_health.main(argv)


def _handle_compliance(args: argparse.Namespace) -> int:
    return compliance.main(["--severity", args.severity, "--output", args.output])


def _handle_cost(args: argparse.Namespace) -> int:
    argv: list[str] = ["--output", args.output]
    if args.project:
        argv += ["--project", args.project]
    return cost.main(argv)


def _handle_multi_cluster(args: argparse.Namespace) -> int:
    argv: list[str] = [
        "--from", args.from_label, "--to", args.to_label,
        "--output", args.output, "--concurrency", str(args.concurrency),
    ]
    if args.from_server:
        argv += ["--from-server", args.from_server]
    if args.to_server:
        argv += ["--to-server", args.to_server]
    if args.project:
        argv += ["--project", args.project]
    return multi_cluster.main(argv)


def _handle_report_push(args: argparse.Namespace) -> int:
    argv: list[str] = ["--webhook", args.webhook, "--title", args.title]
    if args.file:
        argv += ["--file", args.file]
    if args.channel:
        argv += ["--channel", args.channel]
    return report_push.main(argv)


def _handle_report_compose(args: argparse.Namespace) -> int:
    argv: list[str] = ["--include", args.include, "--output", args.output, "--title", args.title]
    if args.project:
        argv += ["--project", args.project]
    if args.push:
        argv.append("--push")
    if args.webhook_url:
        argv += ["--webhook", args.webhook_url]
    if args.channel:
        argv += ["--channel", args.channel]
    return report_composer.main(argv)


def _handle_snapshot(args: argparse.Namespace) -> int:
    includes = [s.strip() for s in args.include.split(",") if s.strip()]
    results: dict = {}
    for name in includes:
        if name not in report_composer.MODULES:
            results[name] = None
            continue
        mod_entry = report_composer.MODULES[name]
        argv = ["--output", "json"]
        if args.project and name in ("diagnose", "health"):
            argv += ["--project", args.project]
        results[name] = report_composer._capture_json(mod_entry["module"], argv)
    store = SnapshotStore(args.store_dir if args.store_dir else None)
    path = store.save(results)
    print(f"✓ 快照已保存: {path}", file=sys.stderr)
    return 0


def _handle_trend(args: argparse.Namespace) -> int:
    return trend.main([
        "--days", str(args.days),
        "--metric", args.metric,
        "--store-dir", args.store_dir,
        "--output", args.output,
    ])


def _handle_config_compare(args: argparse.Namespace) -> int:
    argv: list[str] = args.files + ["--format", args.format]
    if args.group:
        for g in args.group:
            argv += ["--group", g]
    return config_compare.main(argv)


def _handle_predict(args: argparse.Namespace) -> int:
    argv: list[str] = args.files + ["--format", args.format, "--type", args.type]
    if args.budget is not None:
        argv += ["--budget", str(args.budget)]
    return predict.main(argv)


def _handle_autofix(args: argparse.Namespace) -> int:
    argv: list[str] = [args.diagnosis, "--output", args.output]
    if args.dry_run:
        argv.append("--dry-run")
    if args.severity:
        argv += ["--severity", args.severity]
    return autofix.main(argv)


def _handle_impact(args: argparse.Namespace) -> int:
    argv: list[str] = [args.app, args.operation, "--output", args.output]
    if args.history_id is not None:
        argv.insert(2, str(args.history_id))
    return impact.main(argv)


def _handle_batch(args: argparse.Namespace) -> int:
    argv: list[str] = [args.operation, "--output", args.output]
    if args.project:
        argv += ["--project", args.project]
    if args.label:
        argv += ["--label", args.label]
    if args.status:
        argv += ["--status", args.status]
    if args.apps:
        argv += ["--apps"] + args.apps
    if args.all:
        argv.append("--all")
    if args.dry_run:
        argv.append("--dry-run")
    argv += ["--concurrency", str(args.concurrency)]
    argv += ["--timeout", str(args.timeout)]
    return batch.main(argv)


def _handle_scaffold(args: argparse.Namespace) -> int:
    """Forward remaining CLI args to scaffold's own argparse."""
    import sys
    try:
        idx = sys.argv.index("scaffold")
        return scaffold.main(sys.argv[idx + 1:])
    except ValueError:
        return scaffold.main([])


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="argocd-insight",
        description="ArgoCD 洞察工具集：诊断、漂移检测、稳定性评估、Git 源健康、配置合规",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="问题 App 智能诊断")
    p_diag.add_argument("--project")
    p_diag.add_argument("--severity", choices=["critical", "high", "medium", "low"])
    p_diag.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_diag.add_argument("--concurrency", type=int, default=8)
    p_diag.set_defaults(func=_handle_diagnose)

    p_drift = sub.add_parser("drift", help="版本漂移检测")
    p_drift.add_argument("--from", dest="from_label", default="源端")
    p_drift.add_argument("--to", dest="to_label", default="目标端")
    p_drift.add_argument("--from-server", dest="from_server")
    p_drift.add_argument("--to-server", dest="to_server")
    p_drift.add_argument("--project")
    p_drift.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_drift.add_argument("--concurrency", type=int, default=8)
    p_drift.set_defaults(func=_handle_drift)

    p_health = sub.add_parser("health", help="运行稳定性评估")
    p_health.add_argument("--project")
    p_health.add_argument("--days", type=int, default=30)
    p_health.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_health.add_argument("--concurrency", type=int, default=8)
    p_health.set_defaults(func=_handle_health)

    p_comp = sub.add_parser("compliance", help="配置合规检查")
    p_comp.add_argument("--severity", choices=["low", "medium", "high", "critical"], default="low")
    p_comp.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_comp.set_defaults(func=_handle_compliance)

    p_repo = sub.add_parser("repo-health", help="Git 源健康检查")
    p_repo.add_argument("--project")
    p_repo.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_repo.set_defaults(func=_handle_repo_health)

    p_cost = sub.add_parser("cost", help="资源成本估算")
    p_cost.add_argument("--project", help="按项目过滤")
    p_cost.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_cost.set_defaults(func=_handle_cost)

    p_mc = sub.add_parser("multi-cluster", help="多集群对比报告")
    p_mc.add_argument("--from", dest="from_label", default="源端")
    p_mc.add_argument("--to", dest="to_label", default="目标端")
    p_mc.add_argument("--from-server", dest="from_server")
    p_mc.add_argument("--to-server", dest="to_server")
    p_mc.add_argument("--project")
    p_mc.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_mc.add_argument("--concurrency", type=int, default=8)
    p_mc.set_defaults(func=_handle_multi_cluster)

    p_rp = sub.add_parser("report-push", help="推送报告到飞书/钉钉/Slack")
    p_rp.add_argument("--file", "-f", help="报告文件路径")
    p_rp.add_argument("--channel", choices=["feishu", "dingtalk", "slack"], help="通知渠道")
    p_rp.add_argument("--webhook", required=True, help="Webhook URL")
    p_rp.add_argument("--title", default="ArgoCD 报告", help="消息标题")
    p_rp.set_defaults(func=_handle_report_push)

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
    p_rc.set_defaults(func=_handle_report_compose)

    p_snap = sub.add_parser("snapshot", help="采集快照")
    p_snap.add_argument("--include", default="diagnose,compliance,cost,health",
                         help="逗号分隔的模块列表（默认: 全部）")
    p_snap.add_argument("--project", help="项目过滤（传递给 diagnose/health）")
    p_snap.add_argument("--store-dir", default="", help="快照存储目录")
    p_snap.set_defaults(func=_handle_snapshot)

    p_trend = sub.add_parser("trend", help="趋势分析")
    p_trend.add_argument("--days", type=int, default=7, help="分析最近 N 天（默认 7）")
    p_trend.add_argument("--metric", default="", help="指定分析的指标路径")
    p_trend.add_argument("--store-dir", default="", help="快照存储目录")
    p_trend.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_trend.set_defaults(func=_handle_trend)

    p_cc = sub.add_parser("config-compare", help="配置对比与环境差异检测")
    p_cc.add_argument("files", nargs="*", help="ArgoCD app JSON 文件路径")
    p_cc.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown")
    p_cc.add_argument("--group", "-g", action="append", help="分组对比: name=app1,app2（可重复）")
    p_cc.set_defaults(func=_handle_config_compare)

    p_pred = sub.add_parser("predict", help="风险预测（Revision 滞后 + 成本超支）")
    p_pred.add_argument("files", nargs="*", help="ArgoCD app JSON 文件路径")
    p_pred.add_argument("--format", "-f", choices=["markdown", "json"], default="markdown")
    p_pred.add_argument("--budget", type=float, default=None, help="每应用预算上限 (USD)")
    p_pred.add_argument("--type", choices=["all", "lag", "cost"], default="all", help="预测类型")
    p_pred.set_defaults(func=_handle_predict)

    p_autofix = sub.add_parser("autofix", help="基于诊断结果批量修复")
    p_autofix.add_argument("diagnosis", help="诊断结果 JSON 文件路径")
    p_autofix.add_argument("--dry-run", action="store_true", help="预览修复，不实际执行")
    p_autofix.add_argument("--severity", choices=["critical", "high", "medium", "low"],
                           help="最低修复级别")
    p_autofix.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_autofix.set_defaults(func=_handle_autofix)

    p_impact = sub.add_parser("impact", help="变更影响分析")
    p_impact.add_argument("app", help="应用名称")
    p_impact.add_argument("operation", choices=["sync", "rollback"], help="操作类型")
    p_impact.add_argument("history_id", nargs="?", type=int, help="回滚历史 ID")
    p_impact.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_impact.set_defaults(func=_handle_impact)

    p_batch = sub.add_parser("batch", help="批量操作 ArgoCD 应用")
    p_batch.add_argument("operation", choices=["sync", "rollback", "refresh"], help="操作类型")
    p_batch.add_argument("--project", help="按项目过滤")
    p_batch.add_argument("--label", help="按标签过滤 (key=value)")
    p_batch.add_argument("--status", help="按状态过滤 (如 Degraded, OutOfSync)")
    p_batch.add_argument("--apps", nargs="*", help="指定应用列表")
    p_batch.add_argument("--all", action="store_true", help="操作所有应用")
    p_batch.add_argument("--dry-run", action="store_true", help="预览操作，不实际执行")
    p_batch.add_argument("--concurrency", type=int, default=5, help="并发数 (默认 5)")
    p_batch.add_argument("--timeout", type=int, default=120, help="单个操作超时秒数 (默认 120)")
    p_batch.add_argument("--output", choices=["markdown", "json"], default="markdown")
    p_batch.set_defaults(func=_handle_batch)

    p_scaffold = sub.add_parser("scaffold", help="生成 ArgoCD Application 配置模板（4-tier）")
    p_scaffold.set_defaults(func=_handle_scaffold)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
