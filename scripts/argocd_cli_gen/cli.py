"""命令行入口与端到端编排。

流程：
    1. 解析 argparse 参数
    2. parser.load_directory()        → list[LoadedManifest]
    3. renderer.render_all() + write_results()
    4. fallback.collect() + write_fallback()
    5. report.build() + write_report()
    6. 打印总结到 stderr，并按 --fail-on 级别决定退出码

退出码（与 README 一致）：
    0  全部成功无警告
    1  存在警告（多源回退 / 不支持字段），但脚本可用
    2  YAML 解析致命错误
    3  CLI 参数错误（由 argparse 自动以 2 退出，这里只用于业务级参数校验）
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path
from typing import Sequence

from . import fallback, parser, renderer, report
from .renderer import RenderOptions


EXIT_OK = 0
EXIT_WARNING = 1
EXIT_PARSE_ERROR = 2
EXIT_CLI_ARG_ERROR = 3


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="argocd-cli-gen",
        description="将 ArgoCD Application YAML 目录批量反向生成为 `argocd app create` 脚本。",
    )
    ap.add_argument("--input", required=True, type=Path,
                    help="输入 manifest 目录（递归扫描）")
    ap.add_argument("--output", type=Path, default=Path("./out"),
                    help="输出目录（默认 ./out）")
    ap.add_argument("--include", default="**/*.yaml",
                    help="只处理匹配的 glob（默认 **/*.yaml）")

    # 布尔选项采用 --foo / --no-foo 对偶，默认 True。
    upsert = ap.add_mutually_exclusive_group()
    upsert.add_argument("--upsert", dest="upsert", action="store_true", default=True,
                        help="生成的命令追加 --upsert（默认开启）")
    upsert.add_argument("--no-upsert", dest="upsert", action="store_false",
                        help="不追加 --upsert")

    dry = ap.add_mutually_exclusive_group()
    dry.add_argument("--emit-dry-run", dest="emit_dry_run", action="store_true", default=True,
                     help="为每个脚本生成 *.dry-run.sh 副本（默认开启）")
    dry.add_argument("--no-emit-dry-run", dest="emit_dry_run", action="store_false",
                     help="不生成 dry-run 副本")

    ap.add_argument("--sleep", type=float, default=0.0,
                    help="每条 argocd 命令之间插入 sleep 秒数（默认 0）")

    ap.add_argument("--fail-on", choices=("warning", "error"), default="error",
                    help="遇到该级别问题时以非零退出码结束（默认 error）")
    return ap


def _validate_args(args: argparse.Namespace) -> str | None:
    """业务级参数校验，返回错误信息（None 表示通过）。"""
    if not args.input.exists():
        return f"--input 路径不存在：{args.input}"
    if not args.input.is_dir():
        return f"--input 必须是目录：{args.input}"
    if args.sleep < 0:
        return f"--sleep 必须 >= 0，当前为 {args.sleep}"
    return None


def _print_summary(
    rep: report.Report,
    written: list[Path],
    fallback_path: Path | None,
    helm_count: int,
) -> None:
    print(f"[ok] 处理 Application 总数：{rep.total}", file=sys.stderr)
    print(f"     - 转换为 CLI 命令：{rep.converted}", file=sys.stderr)
    if helm_count:
        print(f"       └ 含多源 Helm（argocd app create -f）：{helm_count}", file=sys.stderr)
    print(f"     - YAML 回退      ：{rep.fallback_to_yaml}", file=sys.stderr)
    if rep.warnings:
        print(f"     - 警告条数      ：{len(rep.warnings)}", file=sys.stderr)
    print(f"[ok] 输出脚本：{len(written)} 个", file=sys.stderr)
    if fallback_path:
        print(f"[warn] 多源/不支持字段回退 → {fallback_path}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_argparser()
    args = ap.parse_args(argv)

    err = _validate_args(args)
    if err:
        print(f"[error] {err}", file=sys.stderr)
        return EXIT_CLI_ARG_ERROR

    try:
        loaded = parser.load_directory(args.input, include=args.include)
    except ValueError as exc:
        print(f"[error] YAML parse failure: {exc}", file=sys.stderr)
        return EXIT_PARSE_ERROR

    if not loaded:
        print(f"[error] 在 {args.input} 下未发现任何 Argo CD Application YAML "
              f"（include={args.include}）", file=sys.stderr)
        return EXIT_PARSE_ERROR

    opts = RenderOptions(
        upsert=args.upsert,
        emit_dry_run=args.emit_dry_run,
        sleep_seconds=args.sleep,
    )

    run_timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    render_result = renderer.render_all(
        loaded, source_dir=args.input, opts=opts, timestamp=run_timestamp,
    )
    written = renderer.write_results(render_result, args.output)

    bundle = fallback.collect(loaded, timestamp=run_timestamp)
    fb_path = fallback.write_fallback(bundle, args.output)

    rep = report.build(
        loaded=loaded,
        mapped_by_tier=render_result.mapped_by_tier,
        fallback=bundle,
        input_dir=args.input,
        output_dir=args.output,
        timestamp=run_timestamp,
    )
    report.write_report(rep, args.output)

    _print_summary(rep, written, fb_path, helm_count=len(render_result.helm_apps))

    has_error = any(w.severity == "error" for w in rep.warnings)
    has_warning = any(w.severity == "warning" for w in rep.warnings)

    # --fail-on=error：仅 severity=error 触发非零退出（用 EXIT_PARSE_ERROR=2 表达"工具异常"）
    # --fail-on=warning：warning 及以上均触发非零退出（EXIT_WARNING=1 表达"脚本可用但存在回退"）
    if has_error:
        return EXIT_PARSE_ERROR
    if has_warning and args.fail_on == "warning":
        return EXIT_WARNING
    return EXIT_OK
