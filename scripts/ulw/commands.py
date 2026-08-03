"""ArgoCD ultra-workload commands.

find-pod  — locate which ArgoCD Application manages a given Pod
delete-pod — delete a Pod via the managing Application's resource API
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from .client import ArgoCDClient


@dataclass
class PodLocation:
    """Identifies a Pod and its managing ArgoCD Application."""

    app_name: str
    namespace: str
    kind: str
    name: str
    group: str = ""
    version: str = ""


def _pod_api_version(pod: dict) -> tuple[str, str]:
    """Extract (group, version) from a Pod dict.

    ``/pods`` endpoint returns ``apiVersion`` (e.g. ``v1`` or ``apps/v1``);
    ``/resource-tree`` nodes return ``version`` (e.g. ``v1``). Handle both.
    """
    api_ver = pod.get("apiVersion") or pod.get("version") or "v1"
    if "/" in api_ver:
        group, version = api_ver.split("/", 1)
    else:
        group = ""
        version = api_ver
    return group, version


def find_pod(client: ArgoCDClient, pod_name: str) -> PodLocation | None:
    """Search all ArgoCD Applications for the one that manages `pod_name`.

    Strategy:
      1. List all Applications.
      2. For each App, call ``client.get_application_pods(app_name)`` —
         uses ``/pods`` endpoint (ArgoCD 1.9+) with ``/resource-tree``
         fallback (works on every version, since ``managed-resources``
         never returns Pods).
      3. Return the first Pod whose name equals ``pod_name``.
    """
    print(f"[ulw] searching for pod={pod_name} across all Applications …", file=sys.stderr)

    apps = client.list_applications()
    print(f"[ulw] {len(apps)} Applications found", file=sys.stderr)

    for app in apps:
        app_name = app.get("metadata", {}).get("name", "") or app.get("name", "")
        if not app_name:
            continue

        try:
            pods = client.get_application_pods(app_name)
        except Exception as exc:
            print(f"[ulw]   skip {app_name}: {exc}", file=sys.stderr)
            continue

        for pod in pods:
            # Pod dicts may be flat (resource-tree node) or wrapped in
            # metadata (some /pods implementations). Try both shapes.
            metadata = pod.get("metadata") if isinstance(pod.get("metadata"), dict) else {}
            name = metadata.get("name") or pod.get("name", "")
            if name != pod_name:
                continue

            ns = metadata.get("namespace") or pod.get("namespace", "")
            kind = pod.get("kind") or metadata.get("kind") or "Pod"
            group, version = _pod_api_version(pod if "apiVersion" in pod or "version" in pod else metadata)

            loc = PodLocation(
                app_name=app_name,
                namespace=ns,
                kind=kind,
                name=pod_name,
                group=group,
                version=version,
            )
            print(
                f"[ulw] FOUND: {pod_name} → App={app_name} "
                f"kind={kind} namespace={ns}",
                file=sys.stderr,
            )
            return loc

    print(f"[ulw] pod={pod_name} not found in any ArgoCD Application", file=sys.stderr)
    return None


def delete_pod(client: ArgoCDClient, loc: PodLocation) -> dict:
    """Delete the Pod via ArgoCD Application resource API.

    This does NOT delete the underlying Deployment/ReplicaSet — only the Pod.
    ArgoCD's sync policy will recreate the Pod on the next sync.
    """
    print(
        f"[ulw] deleting {loc.kind}/{loc.name} "
        f"(App={loc.app_name}, ns={loc.namespace}) …",
        file=sys.stderr,
    )
    result = client.delete_application_resource(
        app_name=loc.app_name,
        namespace=loc.namespace,
        kind=loc.kind,
        name=loc.name,
        group=loc.group,
        version=loc.version,
    )
    print(f"[ulw] delete result: {result}", file=sys.stderr)
    return result
