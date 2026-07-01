"""Auto-remediation based on diagnosis results.

Reads diagnosis JSON (from `diagnose --output json`), identifies fixable issues,
and executes repairs via argocd CLI.

Usage:
  python -m argocd_insight autofix diagnosis.json              # execute fixes
  python -m argocd_insight autofix diagnosis.json --dry-run    # preview only
  python -m argocd_insight autofix diagnosis.json --severity critical  # filter
"""
from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from typing import Any

# Risk thresholds — only auto-fix low/medium risk items
AUTO_FIX_RISKS = {"low", "medium"}
# Categories that are auto-fixable
FIXABLE_CATEGORIES = {"OutOfSync", "SyncError", "Degraded"}


@dataclass
class FixResult:
    """Result of an auto-fix attempt."""
    app: str
    operation: str  # sync / rollback / skip
    success: bool
    message: str
    command: str


def _run_cli(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run argocd CLI command."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Timed out"
    except FileNotFoundError:
        return -2, "", f"Not found: {args[0]}"


def _load_diagnosis(path: str) -> list[dict[str, Any]]:
    """Load diagnosis JSON file."""
    with open(path) as f:
        data = json.load(f)
    return data.get("diagnoses", data) if isinstance(data, dict) else data


def _is_fixable(diag: dict[str, Any], min_severity: str | None = None) -> bool:
    """Check if a diagnosis is auto-fixable."""
    severity = diag.get("severity", "")
    category = diag.get("category", "")

    # Filter by severity if specified
    if min_severity:
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        if order.get(severity, 4) > order.get(min_severity, 4):
            return False

    # Must be in fixable categories
    if category not in FIXABLE_CATEGORIES:
        return False

    # Check actions for risk level
    actions = diag.get("actions", [])
    return any(a.get("risk", "low") in AUTO_FIX_RISKS for a in actions)


def _determine_fix(diag: dict[str, Any]) -> tuple[str, list[str]]:
    """Determine what fix to apply based on diagnosis."""
    category = diag.get("category", "")
    app = diag.get("app", "")
    actions = diag.get("actions", [])

    # Find the highest priority action with acceptable risk
    for action in sorted(actions, key=lambda x: x.get("priority", 99)):
        command = action.get("command", "")
        risk = action.get("risk", "low")

        if risk not in AUTO_FIX_RISKS:
            continue

        if "argocd app sync" in command:
            return "sync", ["argocd", "app", "sync", app, "--prune", "--timeout", "120"]

        if "argocd app rollback" in command:
            parts = command.split()
            history_id = ""
            for i, p in enumerate(parts):
                if p == "rollback" and i + 2 < len(parts):
                    history_id = parts[i + 2] if parts[i + 2].isdigit() else ""
            cmd = ["argocd", "app", "rollback", app]
            if history_id:
                cmd.append(history_id)
            return "rollback", cmd

    # Default: try sync for OutOfSync
    if category == "OutOfSync":
        return "sync", ["argocd", "app", "sync", app, "--prune", "--timeout", "120"]

    return "skip", []


def execute_fixes(
    diagnosis_path: str,
    dry_run: bool = False,
    min_severity: str | None = None,
) -> list[FixResult]:
    """Execute auto-fixes based on diagnosis results."""
    diags = _load_diagnosis(diagnosis_path)
    results: list[FixResult] = []

    for diag in diags:
        app = diag.get("app", "")
        if not app:
            continue

        if not _is_fixable(diag, min_severity):
            results.append(FixResult(
                app=app, operation="skip", success=True,
                message=f"Skipped: not fixable (category={diag.get('category')}, severity={diag.get('severity')})",
                command="",
            ))
            continue

        operation, cmd = _determine_fix(diag)
        if operation == "skip":
            results.append(FixResult(
                app=app, operation="skip", success=True,
                message="No fixable action found",
                command="",
            ))
            continue

        if dry_run:
            results.append(FixResult(
                app=app, operation=operation, success=True,
                message=f"[DRY RUN] Would execute: {' '.join(cmd)}",
                command=" ".join(cmd),
            ))
            continue

        # Execute the fix
        rc, stdout, stderr = _run_cli(cmd)
        success = rc == 0
        message = stdout.strip() if success else f"Error: {stderr.strip()}"

        results.append(FixResult(
            app=app, operation=operation, success=success,
            message=message, command=" ".join(cmd),
        ))

    return results


def _format_results_markdown(results: list[FixResult]) -> str:
    """Format results as markdown."""
    lines = ["# Auto-Fix Results\n"]

    fixed = [r for r in results if r.operation != "skip" and r.success]
    skipped = [r for r in results if r.operation == "skip"]
    failed = [r for r in results if r.operation != "skip" and not r.success]

    lines.append(f"**Summary:** {len(fixed)} fixed, {len(skipped)} skipped, {len(failed)} failed\n")

    if fixed:
        lines.append("## ✅ Fixed\n")
        for r in fixed:
            lines.append(f"- **{r.app}** ({r.operation}): {r.message}")
            if r.command:
                lines.append(f"  ```bash\n  {r.command}\n  ```")
        lines.append("")

    if failed:
        lines.append("## ❌ Failed\n")
        for r in failed:
            lines.append(f"- **{r.app}** ({r.operation}): {r.message}")
        lines.append("")

    if skipped:
        lines.append("## ⏭️ Skipped\n")
        for r in skipped:
            lines.append(f"- **{r.app}**: {r.message}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="基于诊断结果批量修复",
    )
    parser.add_argument("diagnosis", help="诊断结果 JSON 文件路径")
    parser.add_argument("--dry-run", action="store_true", help="预览修复，不实际执行")
    parser.add_argument("--severity", choices=["critical", "high", "medium", "low"],
                        help="最低修复级别")
    parser.add_argument("--output", choices=["markdown", "json"], default="markdown")

    args = parser.parse_args(argv)

    results = execute_fixes(args.diagnosis, args.dry_run, args.severity)

    if args.output == "json":
        print(json.dumps([{
            "app": r.app, "operation": r.operation, "success": r.success,
            "message": r.message, "command": r.command,
        } for r in results], indent=2, ensure_ascii=False))
    else:
        print(_format_results_markdown(results))

    return 0 if all(r.success or r.operation == "skip" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
