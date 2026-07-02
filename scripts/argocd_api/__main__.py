"""`python -m argocd_api` — ArgoCD HTTP API CLI.

Usage:
    python -m argocd_api list                        List applications
    python -m argocd_api get     <app>               Get application details
    python -m argocd_api resource-tree <app>         Get resource tree (pods, health)
    python -m argocd_api resource <app> <kind> <name> [--ns NS] Get resource spec
    python -m argocd_api find-pod <pod-name>         Find which App manages a Pod
    python -m argocd_api delete-resource <app> <kind> <name> [--ns NS]
    python -m argocd_api login                       Test auth, show token status
    python -m argocd_api sync <app>                  Trigger sync
    python -m argocd_api refresh <app>               Refresh app status
    python -m argocd_api manifests <app>             Get rendered manifests

Options:
    -h, --help               Show this message
    --env-file PATH          Path to .env file (default: auto-detect)
    --project NAME           Filter by project (for list)
    --ns NAMESPACE           Namespace (for resource operations)
    --group GROUP            API group (for resource operations)
    --version VERSION        API version (for resource operations)
    --json                   Output raw JSON
"""

from __future__ import annotations

import argparse
import json as stdjson
import os
import sys
from pathlib import Path

# ponytail: 让 scripts/ 下所有子包（argocd_insight、argocd_cli_gen 等）
# 在任何调用方式下都能被找到（python -m scripts.argocd_api / python -m argocd_api / ./argocd_api.py）
_scripts_root = Path(__file__).parent.parent
if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))

from scripts.argocd_api.client import ArgoCDClient
from scripts.argocd_insight.trace.decorator import traced


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _env_file(s: str) -> Path:
    p = Path(s).expanduser()
    if not p.is_file():
        raise FileNotFoundError(p)
    return p


def _detect_env_file() -> Path | None:
    """Auto-detect .env: check skill root, then ulw root, then cwd."""
    candidates = [
        Path(__file__).parents[2] / ".env",     # argocd-skill/.env
        Path.cwd() / ".env",                     # cwd/.env
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def _pprint(data: dict | list, json_mode: bool) -> None:
    if json_mode:
        print(stdjson.dumps(data, indent=2, ensure_ascii=False))
    elif isinstance(data, dict):
        _print_dict(data)
    elif isinstance(data, list):
        for item in data:
            _print_dict(item)
            print()


def _print_dict(d: dict, indent: str = "") -> None:
    for k, v in d.items():
        if isinstance(v, dict):
            print(f"{indent}{k}:")
            _print_dict(v, indent + "  ")
        elif isinstance(v, list):
            print(f"{indent}{k}:")
            for item in v:
                item_str = stdjson.dumps(item, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
                print(f"{indent}  - {item_str}")
        else:
            print(f"{indent}{k}: {v}")


# ------------------------------------------------------------------
# Subcommands
# ------------------------------------------------------------------

@traced(module="api", operation="list", interface="api")
def cmd_list(client: ArgoCDClient, args: argparse.Namespace) -> int:
    apps = client.list_applications(project=args.project)
    if not apps:
        print("[argocd-api] no applications found")
        return 0
    if args.json:
        print(stdjson.dumps(apps, indent=2, ensure_ascii=False))
        return 0
    print(f"{'NAME':<50} {'NAMESPACE':<20} {'PROJECT':<15} {'SYNC':<12} {'HEALTH':<10}")
    print("-" * 110)
    for app in apps:
        meta = app.get("metadata", {})
        spec = app.get("spec", {})
        status = app.get("status", {})
        name = meta.get("name", "")
        ns = spec.get("destination", {}).get("namespace", "")
        proj = spec.get("project", "")
        sync = status.get("sync", {}).get("status", "")
        health = status.get("health", {}).get("status", "")
        print(f"{name:<50} {ns:<20} {proj:<15} {sync:<12} {health:<10}")
    print(f"\nTotal: {len(apps)} applications")
    return 0


@traced(module="api", operation="get", interface="api")
def cmd_get(client: ArgoCDClient, args: argparse.Namespace) -> int:
    app = client.get_application(args.app)
    _pprint(app, args.json)
    return 0


@traced(module="api", operation="resource_tree", interface="api")
def cmd_resource_tree(client: ArgoCDClient, args: argparse.Namespace) -> int:
    tree = client.get_application_resource_tree(args.app)
    if args.json:
        print(stdjson.dumps(tree, indent=2, ensure_ascii=False))
        return 0

    nodes = tree.get("nodes", [])
    print(f"Application: {args.app}")
    print(f"Total nodes: {len(nodes)}")
    print()

    pods = [n for n in nodes if n.get("kind") == "Pod"]
    if pods:
        print(f"Pods ({len(pods)}):")
        for p in pods:
            info = {i["name"]: i["value"] for i in p.get("info", [])}
            status = info.get("Status Reason", "?")
            node = info.get("Node", "?")
            containers = info.get("Containers", "?")
            health = p.get("health", {}).get("status", "?")
            images = ", ".join(p.get("images", []))
            print(f"  {p['name']}")
            print(f"    Status: {status} | Health: {health} | Node: {node}")
            print(f"    Containers: {containers} | Image: {images}")

    svcs = [n for n in nodes if n.get("kind") == "Service"]
    if svcs:
        print(f"\nServices ({len(svcs)}):")
        for s in svcs:
            print(f"  {s['name']}")

    ingresses = [n for n in nodes if n.get("kind") == "Ingress"]
    if ingresses:
        print(f"\nIngresses ({len(ingresses)}):")
        for ing in ingresses:
            print(f"  {ing['name']}")
    return 0


@traced(module="api", operation="resource", interface="api")
def cmd_resource(client: ArgoCDClient, args: argparse.Namespace) -> int:
    ns = args.ns or input("Namespace: ").strip()
    if not ns:
        print("[argocd-api] error: namespace is required", file=sys.stderr)
        return 1
    resource = client.get_application_resource(
        app_name=args.app,
        kind=args.kind,
        name=args.name,
        namespace=ns,
        group=args.group,
        version=args.version,
    )
    _pprint(resource, args.json)
    return 0


@traced(module="api", operation="find_pod", interface="api")
def cmd_find_pod(client: ArgoCDClient, args: argparse.Namespace) -> int:
    node = client.find_pod(args.pod_name)
    if not node:
        print(f"[argocd-api] pod '{args.pod_name}' not found in any Application",
              file=sys.stderr)
        return 1

    app_name = node.pop("app_name", "")
    info = {i["name"]: i["value"] for i in node.get("info", [])}
    images = node.get("images", [])

    print(f"Pod:     {node['name']}")
    print(f"App:     {app_name}")
    print(f"Kind:    {node.get('kind')}")
    print(f"Ns:      {node.get('namespace')}")
    print(f"Status:  {info.get('Status Reason', '?')}")
    print(f"Node:    {info.get('Node', '?')}")
    print(f"Health:  {node.get('health', {}).get('status', '?')}")
    print(f"Image:   {images[0] if images else '?'}")
    print(f"Created: {node.get('createdAt', '?')}")
    print(f"UID:     {node.get('uid', '?')}")
    return 0


@traced(module="api", operation="delete_resource", interface="api")
def cmd_delete_resource(client: ArgoCDClient, args: argparse.Namespace) -> int:
    ns = args.ns or input("Namespace: ").strip()
    if not ns:
        print("[argocd-api] error: namespace is required", file=sys.stderr)
        return 1

    confirm = input(
        f"[argocd-api] delete {args.kind}/{args.name} "
        f"via App {args.app} (ns={ns})? Type 'yes': ",
    )
    if confirm.strip().lower() != "yes":
        print("[argocd-api] aborted", file=sys.stderr)
        return 1

    result = client.delete_application_resource(
        app_name=args.app,
        kind=args.kind,
        name=args.name,
        namespace=ns,
        group=args.group,
        version=args.version,
    )
    print(stdjson.dumps(result, indent=2, ensure_ascii=False))
    return 0


@traced(module="api", operation="login", interface="api")
def cmd_login(client: ArgoCDClient, args: argparse.Namespace) -> int:
    # Client already authenticated via from_env
    # Test by listing apps
    try:
        apps = client.list_applications()
        print(f"[argocd-api] ✅ Auth success ({len(apps)} apps accessible)")
        print(f"Server: {client.server}")
        print(f"Token:  {'***' + client.token[-8:] if client.token else 'N/A'}")
        return 0
    except Exception as e:
        print(f"[argocd-api] ❌ Auth failed: {e}", file=sys.stderr)
        return 1


@traced(module="api", operation="sync", interface="api")
def cmd_sync(client: ArgoCDClient, args: argparse.Namespace) -> int:
    result = client.sync_application(args.app, revision=args.revision)
    _pprint(result, args.json)
    return 0


@traced(module="api", operation="refresh", interface="api")
def cmd_refresh(client: ArgoCDClient, args: argparse.Namespace) -> int:
    app = client.refresh_application(args.app)
    sync_status = app.get("status", {}).get("sync", {}).get("status", "?")
    health = app.get("status", {}).get("health", {}).get("status", "?")
    print(f"[argocd-api] {args.app}: sync={sync_status}, health={health}")
    return 0


@traced(module="api", operation="manifests", interface="api")
def cmd_manifests(client: ArgoCDClient, args: argparse.Namespace) -> int:
    manifests = client.get_application_manifests(args.app)
    if args.json:
        print(stdjson.dumps(manifests, indent=2, ensure_ascii=False))
    else:
        for m in manifests:
            print("---")
            print(stdjson.dumps(m, indent=2, ensure_ascii=False))
    print(f"\nTotal: {len(manifests)} manifests")
    return 0


@traced(module="api", operation="create", interface="api")
def cmd_create(client: ArgoCDClient, args: argparse.Namespace) -> int:
    import json as _json
    if args.file:
        spec = _json.loads(Path(args.file).read_text())
    else:
        spec = _json.loads(sys.stdin.read())
    result = client.create_application(spec)
    _pprint(result, args.json)
    return 0


@traced(module="api", operation="delete", interface="api")
def cmd_delete(client: ArgoCDClient, args: argparse.Namespace) -> int:
    confirm = input(f"[argocd-api] delete application '{args.app}'? Type 'yes': ")
    if confirm.strip().lower() != "yes":
        print("[argocd-api] aborted", file=sys.stderr)
        return 1
    result = client.delete_application(args.app, cascade=args.cascade)
    print(stdjson.dumps(result, indent=2, ensure_ascii=False))
    return 0


@traced(module="api", operation="rollback", interface="api")
def cmd_rollback(client: ArgoCDClient, args: argparse.Namespace) -> int:
    result = client.rollback_application(args.app, args.id)
    _pprint(result, args.json)
    return 0


@traced(module="api", operation="terminate_op", interface="api")
def cmd_terminate_op(client: ArgoCDClient, args: argparse.Namespace) -> int:
    result = client.terminate_operation(args.app)
    _pprint(result, args.json)
    return 0


@traced(module="api", operation="whoami", interface="api")
def cmd_whoami(client: ArgoCDClient, args: argparse.Namespace) -> int:
    info = client.get_account_info()
    _pprint(info, args.json)
    return 0


@traced(module="api", operation="projects", interface="api")
def cmd_projects(client: ArgoCDClient, args: argparse.Namespace) -> int:
    projs = client.list_projects()
    if not projs:
        print("[argocd-api] no projects found")
        return 0
    if args.json:
        print(stdjson.dumps(projs, indent=2, ensure_ascii=False))
        return 0
    for p in projs:
        meta = p.get("metadata", {})
        spec = p.get("spec", {})
        name = meta.get("name", "")
        desc = spec.get("description", "")
        src_repos = spec.get("sourceRepos", [])
        print(f"{name:<40} {desc:<30} src_repos={src_repos}")
    print(f"\nTotal: {len(projs)} projects")
    return 0


@traced(module="api", operation="project", interface="api")
def cmd_project(client: ArgoCDClient, args: argparse.Namespace) -> int:
    proj = client.get_project(args.name)
    _pprint(proj, args.json)
    return 0


@traced(module="api", operation="clusters", interface="api")
def cmd_clusters(client: ArgoCDClient, args: argparse.Namespace) -> int:
    clusters = client.list_clusters()
    if not clusters:
        print("[argocd-api] no clusters found")
        return 0
    if args.json:
        print(stdjson.dumps(clusters, indent=2, ensure_ascii=False))
        return 0
    for c in clusters:
        name = c.get("name", "")
        server = c.get("server", "")
        namespaces = c.get("namespaces", [])
        ns_str = ",".join(namespaces) if namespaces else "*"
        print(f"{name:<30} {server:<60} ns={ns_str}")
    print(f"\nTotal: {len(clusters)} clusters")
    return 0


@traced(module="api", operation="repos", interface="api")
def cmd_repos(client: ArgoCDClient, args: argparse.Namespace) -> int:
    repos = client.list_repositories()
    if not repos:
        print("[argocd-api] no repos found")
        return 0
    if args.json:
        print(stdjson.dumps(repos, indent=2, ensure_ascii=False))
        return 0
    for r in repos:
        repo = r.get("repo", "")
        type_ = r.get("type", "git")
        project = r.get("project", "")
        print(f"{repo:<80} type={type_:<5} project={project}")
    print(f"\nTotal: {len(repos)} repos")
    return 0


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="argocd_api",
        description="ArgoCD HTTP API CLI (bypasses argocd CLI).",
    )
    parser.add_argument(
        "--env-file",
        type=_env_file,
        default=_detect_env_file(),
        help="Path to .env file (auto-detected by default)",
    )
    parser.add_argument("--json", action="store_true", help="Output raw JSON")

    sub = parser.add_subparsers(dest="command", required=True)

    # list
    p = sub.add_parser("list", help="List applications")
    p.add_argument("--project", help="Filter by project")
    p.set_defaults(func=cmd_list)

    # get
    p = sub.add_parser("get", help="Get application details")
    p.add_argument("app")
    p.set_defaults(func=cmd_get)

    # resource-tree
    p = sub.add_parser("resource-tree", help="Get application resource tree")
    p.add_argument("app")
    p.set_defaults(func=cmd_resource_tree)

    # resource
    p = sub.add_parser("resource", help="Get a specific managed resource (Pod, etc.)")
    p.add_argument("app")
    p.add_argument("kind", help="Resource kind (Pod, Service, etc.)")
    p.add_argument("name", help="Resource name")
    p.add_argument("--ns", help="Namespace")
    p.add_argument("--group", default="", help="API group")
    p.add_argument("--version", default="", help="API version")
    p.set_defaults(func=cmd_resource)

    # find-pod
    p = sub.add_parser("find-pod", help="Find which App manages a Pod")
    p.add_argument("pod_name")
    p.set_defaults(func=cmd_find_pod)

    # delete-resource
    p = sub.add_parser("delete-resource", help="Delete a managed resource")
    p.add_argument("app")
    p.add_argument("kind")
    p.add_argument("name")
    p.add_argument("--ns", help="Namespace")
    p.add_argument("--group", default="")
    p.add_argument("--version", default="")
    p.set_defaults(func=cmd_delete_resource)

    # login
    p = sub.add_parser("login", help="Test authentication")
    p.set_defaults(func=cmd_login)

    # sync
    p = sub.add_parser("sync", help="Trigger sync for an Application")
    p.add_argument("app")
    p.add_argument("--revision", help="Revision (branch/tag/SHA) to sync to")
    p.set_defaults(func=cmd_sync)

    # refresh
    p = sub.add_parser("refresh", help="Refresh an Application")
    p.add_argument("app")
    p.set_defaults(func=cmd_refresh)

    # manifests
    p = sub.add_parser("manifests", help="Get rendered manifests")
    p.add_argument("app")
    p.set_defaults(func=cmd_manifests)

    # create
    p = sub.add_parser("create", help="Create application from JSON (file or stdin)")
    p.add_argument("-f", "--file", help="JSON spec file (omit for stdin)")
    p.set_defaults(func=cmd_create)

    # delete
    p = sub.add_parser("delete", help="Delete an Application")
    p.add_argument("app")
    p.add_argument("--cascade", action="store_true", default=True,
                   help="Cascade delete resources (default: true)")
    p.set_defaults(func=cmd_delete)

    # rollback
    p = sub.add_parser("rollback", help="Rollback Application to a history ID")
    p.add_argument("app")
    p.add_argument("--id", type=int, required=True, help="History revision ID")
    p.set_defaults(func=cmd_rollback)

    # terminate-op
    p = sub.add_parser("terminate-op", help="Terminate running operation")
    p.add_argument("app")
    p.set_defaults(func=cmd_terminate_op)

    # whoami
    p = sub.add_parser("whoami", help="Show current account info")
    p.set_defaults(func=cmd_whoami)

    # projects
    p = sub.add_parser("projects", help="List AppProjects")
    p.set_defaults(func=cmd_projects)

    # project
    p = sub.add_parser("project", help="Get AppProject details")
    p.add_argument("name")
    p.set_defaults(func=cmd_project)

    # clusters
    p = sub.add_parser("clusters", help="List managed clusters")
    p.set_defaults(func=cmd_clusters)

    # repos
    p = sub.add_parser("repos", help="List configured repositories")
    p.set_defaults(func=cmd_repos)

    args = parser.parse_args(argv)

    # Load .env before client
    if args.env_file and args.env_file.is_file():
        from scripts.argocd_api.client import _load_dotenv as _ld
        _ld(args.env_file)

    try:
        client = ArgoCDClient.from_env()
    except ValueError as exc:
        print(f"[argocd-api] configuration error: {exc}", file=sys.stderr)
        return 1

    return args.func(client, args)


if __name__ == "__main__":
    raise SystemExit(main())