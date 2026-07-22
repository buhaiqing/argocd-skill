"""Rollouts 诊断入口：状态诊断 + AnalysisRun 归因。

Usage:
  python -m argocd_insight rollouts diagnose <name> -n <ns>
  python -m argocd_insight rollouts diagnose <name> -n <ns> --output json
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from .analysis import analyze_run, fetch_analysis_runs
from .diagnose import diagnose_status, fetch_rollout
from .diagnose import RolloutDiagnosis
from .analysis import AnalysisFinding


def _render_markdown(diag: "RolloutDiagnosis", findings: list["AnalysisFinding"]) -> str:
    lines: list[str] = []
    lines.append(f"# Rollout 诊断: {diag.name} (ns={diag.namespace})")
    lines.append("")
    lines.append(f"- 策略: `{diag.strategy}`  状态: `{diag.status}`")
    lines.append(f"- 严重级别: **{diag.severity}**  归类: {diag.category}")
    lines.append(f"- 根因: {diag.root_cause}")
    if diag.message:
        lines.append(f"- 状态消息: {diag.message}")
    if diag.symptoms:
        lines.append("")
        lines.append("## 症状")
        for s in diag.symptoms:
            lines.append(f"- {s}")
    if diag.actions:
        lines.append("")
        lines.append("## 建议动作（只读优先）")
        for a in sorted(diag.actions, key=lambda x: x.priority):
            lines.append(f"{a.priority}. {a.description}")
            lines.append(f"   `{a.command}`")
    if findings:
        lines.append("")
        lines.append("## AnalysisRun 归因")
        for f in findings:
            lines.append(f"- `{f.name}` [{f.phase}] {f.severity}: {f.root_cause}")
            for d in f.details:
                lines.append(f"  - {d}")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="argocd-insight rollouts",
        description="ArgoCD Rollouts 只读诊断：状态诊断 + AnalysisRun 归因",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="诊断单个 Rollout")
    p_diag.add_argument("name", help="Rollout 名称")
    p_diag.add_argument("--namespace", "-n", default="default", help="命名空间")
    p_diag.add_argument("--kubectl", default="kubectl", help="kubectl 可执行文件路径")
    p_diag.add_argument("--analysis-label", default="argo-rollouts=resource",
                        help="关联 AnalysisRun 的 label 选择器")
    p_diag.add_argument("--output", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args(argv)

    if args.command == "diagnose":
        try:
            rollout = fetch_rollout(args.kubectl, args.name, args.namespace)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 1
        diag = diagnose_status(rollout)

        findings: list = []
        try:
            runs = fetch_analysis_runs(
                args.kubectl, args.namespace, args.analysis_label
            )
            findings = [analyze_run(r) for r in runs]
        except RuntimeError as exc:
            # AnalysisRun 拉取失败不阻断主诊断，仅提示
            print(f"[WARN] 跳过 AnalysisRun 归因: {exc}", file=sys.stderr)

        if args.output == "json":
            payload = {"diagnosis": diag.to_dict(),
                       "analysis": [f.to_dict() for f in findings]}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(_render_markdown(diag, findings))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
