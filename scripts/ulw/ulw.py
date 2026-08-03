"""`python -m ulw` CLI entry point.

Usage:
    python -m ulw find-pod   <pod-name> [--env-file PATH]
    python -m ulw delete-pod <pod-name> [--env-file PATH] [--yes]
                             [--app-name NAME --namespace NS]
                             [--wait-ready [--wait-timeout N] [--wait-interval N]]
    python -m ulw -h

Exit codes:
    0  success
    1  pod not found / aborted / --wait-ready timed out
    2  refused by the sync-policy safety guard (BlockedError)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .client import ArgoCDClient
from .commands import (
    DEFAULT_WAIT_INTERVAL,
    DEFAULT_WAIT_TIMEOUT,
    BlockedError,
    PodLocation,
    delete_pod,
    find_pod,
    wait_pod_ready,
)


def _env_file(s: str) -> Path:
    p = Path(s).expanduser()
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


def _positive_int(s: str) -> int:
    """Argparse type: reject non-positive wait timeouts/intervals."""
    value = int(s)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return value


def _build_find_parser(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("pod_name", help="Pod name to search for")
    sub.add_argument(
        "--env-file",
        type=_env_file,
        default=Path(__file__).parents[2] / ".env",
        help="Path to .env file (default: <ulw>/../../.env)",
    )


def _build_delete_parser(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("pod_name", help="Pod name to delete")
    sub.add_argument(
        "--env-file",
        type=_env_file,
        default=Path(__file__).parents[2] / ".env",
        help="Path to .env file (default: <ulw>/../../.env)",
    )
    sub.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation prompt (safety guard still applies)",
    )
    sub.add_argument(
        "--app-name",
        help="Owning Application name; with --namespace, skips the full scan",
    )
    sub.add_argument(
        "--namespace",
        help="Pod namespace; with --app-name, skips the full scan",
    )
    sub.add_argument(
        "--wait-ready",
        action="store_true",
        help="After deleting, poll until a replacement Pod is Running",
    )
    sub.add_argument(
        "--wait-timeout",
        type=_positive_int,
        default=DEFAULT_WAIT_TIMEOUT,
        help=f"--wait-ready timeout in seconds (default: {DEFAULT_WAIT_TIMEOUT})",
    )
    sub.add_argument(
        "--wait-interval",
        type=_positive_int,
        default=DEFAULT_WAIT_INTERVAL,
        help=f"--wait-ready poll interval in seconds (default: {DEFAULT_WAIT_INTERVAL})",
    )


def _do_find_pod(client: ArgoCDClient, pod_name: str) -> int:
    """Find which ArgoCD App manages a Pod."""
    loc = find_pod(client, pod_name)
    if loc:
        print(f"APP_NAME={loc.app_name}")
        print(f"NAMESPACE={loc.namespace}")
        print(f"KIND={loc.kind}")
        print(f"GROUP={loc.group}")
        print(f"VERSION={loc.version}")
        return 0
    return 1


def _do_delete_pod(client: ArgoCDClient, args: argparse.Namespace) -> int:
    """Delete a Pod via its managing ArgoCD App.

    Returns 0 on success, 1 on not-found/abort/wait-timeout, 2 when the
    sync-policy safety guard refuses the deletion.
    """
    pod_name = args.pod_name

    if args.app_name and args.namespace:
        # Short circuit: caller already knows the location, skip the full scan.
        loc = PodLocation(
            app_name=args.app_name,
            namespace=args.namespace,
            kind="Pod",
            name=pod_name,
            version="v1",
        )
        print(
            f"[ulw] using supplied location: App={loc.app_name} ns={loc.namespace}",
            file=sys.stderr,
        )
    else:
        loc = find_pod(client, pod_name)
        if not loc:
            print("[ulw] cannot delete: pod not found", file=sys.stderr)
            return 1

    # Safety: require explicit confirmation unless --yes was passed.
    if not args.yes:
        try:
            confirm = input(
                f"[ulw] delete Pod {pod_name} via App {loc.app_name}? "
                "Type 'yes': ",
            )
        except EOFError:
            # Non-TTY (CI/cron/piped stdin) with no --yes: abort cleanly.
            print(
                "[ulw] no TTY for confirmation; pass --yes to proceed",
                file=sys.stderr,
            )
            return 1
        if confirm.strip().lower() != "yes":
            print("[ulw] aborted", file=sys.stderr)
            return 1

    try:
        result = delete_pod(client, loc)
    except BlockedError as exc:
        print(f"[ulw] BLOCKED: {exc}", file=sys.stderr)
        return 2
    print(result)

    if args.wait_ready:
        ready = wait_pod_ready(
            client,
            loc.app_name,
            pod_name,
            timeout=args.wait_timeout,
            interval=args.wait_interval,
        )
        if not ready:
            print(
                "[ulw] replacement Pod did not become Running in time — "
                f"check `argocd app get {loc.app_name}`",
                file=sys.stderr,
            )
            return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ulw",
        description="ArgoCD ultra-workload via direct HTTP API (bypasses argocd CLI).",
    )
    parser.add_argument(
        "--env-file",
        type=_env_file,
        default=Path(__file__).parents[2] / ".env",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_find = sub.add_parser("find-pod", help="Find which ArgoCD App manages a Pod")
    _build_find_parser(p_find)

    p_del = sub.add_parser("delete-pod", help="Delete a Pod via its managing ArgoCD App")
    _build_delete_parser(p_del)

    args = parser.parse_args(argv)

    # Load env before creating the client
    if args.env_file and args.env_file.is_file():
        ArgoCDClient._load_dotenv(args.env_file)
        # Reset server/token from newly loaded env
        os.environ.setdefault(
            "ARGOCD_SERVER",
            os.environ.get("ARGOCD_SERVER", ""),
        )

    try:
        client = ArgoCDClient.from_env()
    except ValueError as exc:
        print(f"[ulw] configuration error: {exc}", file=sys.stderr)
        return 1

    if args.command == "find-pod":
        return _do_find_pod(client, args.pod_name)
    elif args.command == "delete-pod":
        return _do_delete_pod(client, args)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())