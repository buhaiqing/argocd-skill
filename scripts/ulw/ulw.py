"""`python -m ulw` CLI entry point.

Usage:
    python -m ulw find-pod   <pod-name> [--env-file PATH]
    python -m ulw delete-pod <pod-name> [--env-file PATH]
    python -m ulw -h
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .client import ArgoCDClient
from .commands import delete_pod, find_pod


def _env_file(s: str) -> Path:
    p = Path(s).expanduser()
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


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
        loc = find_pod(client, args.pod_name)
        if loc:
            print(f"APP_NAME={loc.app_name}")
            print(f"NAMESPACE={loc.namespace}")
            print(f"KIND={loc.kind}")
            print(f"GROUP={loc.group}")
            print(f"VERSION={loc.version}")
            return 0
        return 1

    elif args.command == "delete-pod":
        loc = find_pod(client, args.pod_name)
        if not loc:
            print(f"[ulw] cannot delete: pod not found", file=sys.stderr)
            return 1

        # Safety: require explicit confirmation for delete-pod
        confirm = input(
            f"[ulw] delete Pod {args.pod_name} via App {loc.app_name}? "
            "Type 'yes': ",
        )
        if confirm.strip().lower() != "yes":
            print("[ulw] aborted", file=sys.stderr)
            return 1

        result = delete_pod(client, loc)
        print(result)
        return 0

    return 1
