"""ArgoCD ultra-workload commands.

find-pod  — locate which ArgoCD Application manages a given Pod
delete-pod — delete a Pod via the managing Application's resource API
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from typing import Any

from .client import ArgoCDClient

#: Poll defaults for :func:`wait_pod_ready` — also the CLI defaults.
DEFAULT_WAIT_TIMEOUT = 120
DEFAULT_WAIT_INTERVAL = 5

#: Pod health/phase values that count as "the replacement Pod is up".
_RUNNING_STATES = {"running", "healthy"}


class BlockedError(RuntimeError):
    """Raised when a destructive operation is refused by a safety guard.

    Deleting a Pod only makes sense when ArgoCD will recreate it, i.e. when
    the managing Application has ``spec.syncPolicy.automated``. On a
    manual-sync Application the Pod would simply stay gone.
    """


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
        except (RuntimeError, OSError) as exc:
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


def _infer_workload_name(pod_name: str) -> str:
    """Strip the ReplicaSet/StatefulSet hash suffixes from a Pod name.

    A managed Pod is named ``<workload>-<rs-hash>-<pod-hash>``
    (e.g. ``hdops-mcp-7b8cc44dd8-lmb2g``). The owning workload is the
    prefix. Pod names without those suffixes (e.g. ``target-pod``) are
    returned unchanged so the caller can substitute the real workload.
    """
    return re.sub(r"-[a-f0-9]{8,10}-[a-z0-9]{5}$", "", pod_name)


def _assert_automated(
    client: ArgoCDClient,
    app_name: str,
    namespace: str,
    pod_name: str,
) -> None:
    """Refuse to delete a Pod unless the owning App self-heals.

    Raises :class:`BlockedError` when ``spec.syncPolicy.automated`` is absent
    or falsy, or when the Application cannot be read at all (we must not
    guess — an unreadable App is treated as not-automated).
    """
    try:
        app = client.get_application(app_name)
    except Exception as exc:
        raise BlockedError(
            f"cannot verify sync policy of App '{app_name}': {exc}. "
            "Refusing to delete the Pod. Use "
            f"`kubectl rollout restart deployment/<workload> -n {namespace}`, "
            f"or run `argocd app sync {app_name}` after deleting manually."
        ) from exc

    spec = app.get("spec")
    sync_policy = spec.get("syncPolicy") if isinstance(spec, dict) else None
    automated = sync_policy.get("automated") if isinstance(sync_policy, dict) else None
    # ``automated: {}`` means "automated with all defaults" — only a dict is
    # treated as automated. Any non-dict value (None, False, the string
    # 'false', 0, '') is a manual-sync App where a deleted Pod would NOT be
    # recreated. Whitelist over blacklist to avoid quoting-edge cases.
    if not isinstance(automated, dict):
        workload = _infer_workload_name(pod_name)
        raise BlockedError(
            f"App '{app_name}' has no spec.syncPolicy.automated — a deleted "
            "Pod would NOT be recreated by ArgoCD. Refusing to delete. "
            f"Alternatives: `kubectl rollout restart deployment/{workload} "
            f"-n {namespace}` (replace <workload> if the owner differs), "
            f"or delete the Pod then run `argocd app sync {app_name}` to "
            "restore the desired state."
        )


def delete_pod(
    client: ArgoCDClient,
    loc: PodLocation,
    skip_safety_check: bool = False,
) -> dict:
    """Delete the Pod via ArgoCD Application resource API.

    This does NOT delete the underlying Deployment/ReplicaSet — only the Pod.
    ArgoCD's sync policy will recreate the Pod on the next sync, which is why
    the owning Application must be ``automated`` (see :func:`_assert_automated`).

    Raises:
        BlockedError: the owning Application is not automated (unless
            ``skip_safety_check`` is set).
    """
    if not skip_safety_check:
        _assert_automated(client, loc.app_name, loc.namespace, loc.name)

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


def _pod_name(pod: dict[str, Any]) -> str:
    """Read a Pod name from either the flat or the ``metadata``-nested shape."""
    metadata = pod.get("metadata") if isinstance(pod.get("metadata"), dict) else {}
    return metadata.get("name") or pod.get("name", "")


def _pod_resource_version(pod: dict[str, Any]) -> str:
    """Read a Pod's resourceVersion from either shape.

    Used to detect a StatefulSet member (e.g. ``mysql-0``) being recreated
    *in place* — its name never changes, so name-based detection misses it.
    """
    metadata = pod.get("metadata") if isinstance(pod.get("metadata"), dict) else {}
    return str(metadata.get("resourceVersion") or pod.get("resourceVersion") or "")


def _pod_is_running(pod: dict[str, Any]) -> bool:
    """True when the Pod reports a Running/Healthy state.

    ``/resource-tree`` nodes carry ``health.status`` (``Healthy``), while the
    ``/pods`` endpoint carries ``status.phase`` (``Running``). Accept both.
    """
    health = pod.get("health") if isinstance(pod.get("health"), dict) else {}
    status = pod.get("status") if isinstance(pod.get("status"), dict) else {}
    state = health.get("status") or status.get("phase") or ""
    return state.lower() in _RUNNING_STATES


def wait_pod_ready(
    client: ArgoCDClient,
    app_name: str,
    old_pod_name: str,
    timeout: int = DEFAULT_WAIT_TIMEOUT,
    interval: int = DEFAULT_WAIT_INTERVAL,
) -> bool:
    """Poll until the deleted Pod is replaced by a Running one.

    Success requires both conditions: ``old_pod_name`` is gone from the App's
    Pod list AND at least one other Pod reports Running/Healthy.

    Returns:
        True on success, False on timeout. Transient API errors are logged and
        retried rather than aborting the wait.
    """
    deadline = time.monotonic() + timeout
    print(
        f"[ulw] waiting up to {timeout}s for a replacement Pod in App={app_name} …",
        file=sys.stderr,
    )
    # Baseline resourceVersion of the old Pod, captured on the first poll.
    # For StatefulSet members (name stays the same across recreation) a changed
    # resourceVersion proves the Pod was recycled even though its name persists.
    old_rv_baseline: str | None = None

    while True:
        try:
            pods = client.get_application_pods(app_name)
        except (RuntimeError, OSError) as exc:
            # RuntimeError: ArgoCD API 4xx/5xx; OSError: transport hiccup.
            print(f"[ulw]   poll error (will retry): {exc}", file=sys.stderr)
            pods = None

        if pods is not None:
            names = [_pod_name(p) for p in pods]
            old_gone = old_pod_name not in names

            # Record the old Pod's resourceVersion once, so we can later detect
            # an in-place recreation (StatefulSet) by a changed version.
            if old_rv_baseline is None and old_pod_name in names:
                old_rv_baseline = next(
                    (_pod_resource_version(p) for p in pods if _pod_name(p) == old_pod_name),
                    None,
                )

            old_recreated = (
                old_pod_name in names
                and old_rv_baseline is not None
                and _pod_resource_version(next(p for p in pods if _pod_name(p) == old_pod_name))
                != old_rv_baseline
            )
            # Deployment/ReplicaSet: a *different* Running Pod proves replacement.
            # StatefulSet: the *same-named* Pod recreated in place (rv changed) and
            # is now Running — there is no second Pod to look for.
            replacement = next(
                (
                    _pod_name(p)
                    for p in pods
                    if (
                        (_pod_name(p) != old_pod_name or old_recreated)
                        and _pod_is_running(p)
                    )
                ),
                None,
            )
            if (old_gone or old_recreated) and replacement is not None:
                print(f"[ulw] replacement Pod is running: {replacement}", file=sys.stderr)
                return True

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(
                f"[ulw] timeout after {timeout}s — no Running replacement for "
                f"{old_pod_name} in App={app_name}",
                file=sys.stderr,
            )
            return False

        # Sleep the lesser of the interval and the remaining budget so we never
        # overshoot `timeout` by a full interval (and never busy-spin).
        time.sleep(min(interval, remaining))
