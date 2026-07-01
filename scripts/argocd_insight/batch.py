"""Batch operations for ArgoCD applications.

Execute sync/rollback/refresh across multiple apps with filtering and concurrency.

Usage:
  python -m argocd_insight batch sync --project my-project
  python -m argocd_insight batch sync --label env=production
  python -m argocd_insight batch rollback --status Degraded
  python -m argocd_insight batch refresh --all --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from typing import Any

# Supported operations
OPERATIONS = {"sync", "rollback", "refresh"}

# Default concurrency
DEFAULT_CONCURRENCY = 5

# Timeout per operation (seconds)
DEFAULT_TIMEOUT = 120


@dataclass
class BatchResult:
    """Result of a batch operation on a single app."""
    app: str
    operation: str
    success: bool
    message: str
    command: str
    duration: float


@dataclass
class BatchSummary:
    """Summary of batch operation results."""
    operation: str
    total: int
    succeeded: int
    failed: int
    skipped: int
    duration: float
    results: list[BatchResult]


def _run_cli(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str, str]:
    """Run argocd CLI command."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timed out"
    except FileNotFoundError:
        return -2, "", f"Not found: {args[0]}"


def _list_apps(
    project: str | None = None,
    label: str | None = None,
    status: str | None = None,
) -> list[str]:
    """List apps matching filters."""
    cmd = ["argocd", "app", "list", "-o", "json"]
    if project:
        cmd += ["--project", project]
    if label:
        cmd += ["--selector", label]

    rc, out, err = _run_cli(cmd)
    if rc != 0:
        print(f"Error listing apps: {err}", file=sys.stderr)
        return []

    try:
        apps = json.loads(out) if out else []
    except json.JSONDecodeError:
        return []

    # Filter by status if specified
    if status:
        filtered = []
        for app in apps:
            app_status = app.get("status", {}).get("health", {}).get("status", "")
            if app_status.lower() == status.lower():
                filtered.append(app.get("name", ""))
        return [name for name in filtered if name]

    return [app.get("name", "") for app in apps if app.get("name")]


def _execute_operation(
    app: str,
    operation: str,
    dry_run: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
) -> BatchResult:
    """Execute a single operation on an app."""
    start = time.time()

    if operation == "sync":
        cmd = ["argocd", "app", "sync", app, "--prune", "--timeout", str(timeout)]
        if dry_run:
            cmd.append("--dry-run")
    elif operation == "rollback":
        cmd = ["argocd", "app", "rollback", app]
    elif operation == "refresh":
        cmd = ["argocd", "app", "get", app, "--refresh"]
    else:
        return BatchResult(
            app=app, operation=operation, success=False,
            message=f"Unknown operation: {operation}", command="", duration=0,
        )

    if dry_run:
        return BatchResult(
            app=app, operation=operation, success=True,
            message=f"[DRY RUN] Would execute: {' '.join(cmd)}",
            command=" ".join(cmd), duration=0,
        )

    rc, stdout, stderr = _run_cli(cmd, timeout)
    duration = time.time() - start
    success = rc == 0
    message = stdout.strip() if success else f"Error: {stderr.strip()}"

    return BatchResult(
        app=app, operation=operation, success=success,
        message=message, command=" ".join(cmd), duration=duration,
    )


def execute_batch(
    operation: str,
    apps: list[str] | None = None,
    project: str | None = None,
    label: str | None = None,
    status: str | None = None,
    dry_run: bool = False,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: int = DEFAULT_TIMEOUT,
) -> BatchSummary:
    """Execute batch operations across multiple apps."""
    start = time.time()

    # Resolve app list if not provided
    if apps is None:
        apps = _list_apps(project, label, status)
        if not apps:
            return BatchSummary(
                operation=operation, total=0, succeeded=0, failed=0,
                skipped=0, duration=0, results=[],
            )

    results: list[BatchResult] = []

    # Execute with concurrency
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = {
            executor.submit(_execute_operation, app, operation, dry_run, timeout): app
            for app in apps
        }

        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                app = futures[future]
                results.append(BatchResult(
                    app=app, operation=operation, success=False,
                    message=f"Exception: {e}", command="", duration=0,
                ))

    duration = time.time() - start
    succeeded = sum(1 for r in results if r.success)
    failed = sum(1 for r in results if not r.success)

    return BatchSummary(
        operation=operation, total=len(results),
        succeeded=succeeded, failed=failed, skipped=0,
        duration=duration, results=results,
    )


def _format_summary_markdown(summary: BatchSummary) -> str:
    """Format batch summary as markdown."""
    lines = [f"# Batch {summary.operation.capitalize()} Results\n"]

    lines.append(f"**Total:** {summary.total} apps")
    lines.append(f"**Succeeded:** {summary.succeeded}")
    lines.append(f"**Failed:** {summary.failed}")
    lines.append(f"**Duration:** {summary.duration:.1f}s\n")

    if summary.succeeded > 0:
        lines.append("## ✅ Succeeded\n")
        for r in summary.results:
            if r.success:
                lines.append(f"- **{r.app}** ({r.duration:.1f}s): {r.message[:100]}")
        lines.append("")

    if summary.failed > 0:
        lines.append("## ❌ Failed\n")
        for r in summary.results:
            if not r.success:
                lines.append(f"- **{r.app}**: {r.message[:200]}")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="批量操作 ArgoCD 应用",
    )
    parser.add_argument("operation", choices=list(OPERATIONS), help="操作类型")
    parser.add_argument("--project", help="按项目过滤")
    parser.add_argument("--label", help="按标签过滤 (key=value)")
    parser.add_argument("--status", help="按状态过滤 (如 Degraded, OutOfSync)")
    parser.add_argument("--apps", nargs="*", help="指定应用列表")
    parser.add_argument("--all", action="store_true", help="操作所有应用")
    parser.add_argument("--dry-run", action="store_true", help="预览操作，不实际执行")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                        help=f"并发数 (默认 {DEFAULT_CONCURRENCY})")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"单个操作超时秒数 (默认 {DEFAULT_TIMEOUT})")
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args(argv)

    # Determine app list
    apps = args.apps if args.apps else None
    if not apps and not args.all and not args.project and not args.label and not args.status:
        parser.error("请指定过滤条件: --project, --label, --status, --apps, 或 --all")

    summary = execute_batch(
        operation=args.operation,
        apps=apps,
        project=args.project,
        label=args.label,
        status=args.status,
        dry_run=args.dry_run,
        concurrency=args.concurrency,
        timeout=args.timeout,
    )

    if args.output == "json":
        print(json.dumps(asdict(summary), indent=2, ensure_ascii=False))
    else:
        print(_format_summary_markdown(summary))

    return 0 if summary.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
