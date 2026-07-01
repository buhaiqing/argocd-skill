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


def find_pod(client: ArgoCDClient, pod_name: str) -> PodLocation | None:
    """Search all ArgoCD Applications for the one that manages `pod_name`.

    Strategy:
      1. List all Applications.
      2. For each App, query its managed-resources (live state).
      3. Return the first match whose live-resource name equals pod_name.
    """
    print(f"[ulw] searching for pod={pod_name} across all Applications …", file=sys.stderr)

    apps = client.list_applications()
    print(f"[ulw] {len(apps)} Applications found", file=sys.stderr)

    for app in apps:
        app_name = app.get("metadata", {}).get("name", "") or app.get("name", "")
        if not app_name:
            continue

        try:
            resources = client.get_application_managed_resources(app_name)
        except Exception as exc:
            print(f"[ulw]   skip {app_name}: {exc}", file=sys.stderr)
            continue

        for res in resources:
            # Live-state resource
            live = res.get("liveState") or {}
            if live.get("metadata", {}).get("name") == pod_name:
                ns = live.get("metadata", {}).get("namespace", "")
                kind = live.get("kind", "")
                group = live.get("apiVersion", "").split("/")[0] if "/" in live.get("apiVersion", "") else ""
                version = live.get("apiVersion", "").split("/")[-1] if "/" in live.get("apiVersion", "") else ""

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
