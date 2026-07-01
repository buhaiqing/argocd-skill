"""ArgoCD HTTP API Python client — alternative to `argocd login` + CLI.

Handles:
  - Session login (username + password → bearer token)
  - All CRUD operations on Application resources
  - Resource-level operations (get details, list, delete)
  - Auth priority: env ARGOCD_AUTH_TOKEN > ~/.config/argocd/config > .env username+password
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import requests


class ArgoCDClient:
    """Low-level ArgoCD HTTP API client."""

    def __init__(
        self,
        server: str,
        token: str | None = None,
        ssl_verify: bool = True,
    ) -> None:
        self.server = server.rstrip("/")
        self.token = token
        self.ssl_verify = ssl_verify

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------
    @classmethod
    def from_env(
        cls,
        env_path: str | Path | None = None,
    ) -> "ArgoCDClient":
        """Auto-configure from environment / .env / argocd config.

        Auth priority:
          1. ARGOCD_AUTH_TOKEN (shell env)
          2. ~/.config/argocd/config  (local config YAML)
          3. .env file → ARGOCD_USERNAME + ARGOCD_PASSWORD → API login
          4. .env file → ARGOCD_AUTH_TOKEN
        """
        if env_path:
            _load_dotenv(env_path)

        server = (os.environ.get("ARGOCD_SERVER") or "").rstrip("/")
        if not server:
            raise ValueError("ARGOCD_SERVER is not set")

        ssl_verify = os.environ.get("ARGOCD_SSL_VERIFY", "1") != "0"
        token = os.environ.get("ARGOCD_AUTH_TOKEN") or None

        client = cls(server=server, token=token, ssl_verify=ssl_verify)

        # Priority 2: try local config file
        if not token:
            token = _token_from_argocd_config(server)
            if token:
                print("[argocd-api] using token from ~/.config/argocd/config", file=sys.stderr)

        # Priority 3: username + password → API login
        if not token:
            username = os.environ.get("ARGOCD_USERNAME") or ""
            password = os.environ.get("ARGOCD_PASSWORD") or ""
            if username and password:
                token = client.login(username, password)
                print(f"[argocd-api] token obtained for {username}", file=sys.stderr)

        if not token:
            raise ValueError(
                "No ArgoCD credentials found. "
                "Set ARGOCD_AUTH_TOKEN, or ARGOCD_USERNAME+ARGOCD_PASSWORD, "
                "or configure ~/.config/argocd/config"
            )

        client.token = token
        return client

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def login(self, username: str, password: str) -> str:
        """Authenticate and return a bearer token."""
        resp = self._post("/session", json={"username": username, "password": password})
        data = resp.json()
        token: str | None = data.get("token") or data.get("tokenString")
        if not token:
            raise ValueError(f"Login response missing token: {data}")
        return token

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def list_applications(
        self,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all ArgoCD applications (optionally filtered by project)."""
        params: dict[str, str] = {}
        if project:
            params["project"] = project
        resp = self._get("/applications", params=params)
        return resp.json().get("items", [])

    def get_application(self, name: str) -> dict[str, Any]:
        """Return a single Application with full spec + status."""
        return self._get(f"/applications/{name}").json()

    def get_application_resource_tree(self, name: str) -> dict[str, Any]:
        """Return live resource tree (nodes + hosts) for an Application."""
        return self._get(f"/applications/{name}/resource-tree").json()

    def get_application_managed_resources(self, name: str) -> list[dict[str, Any]]:
        """Return live + target resource state for an Application."""
        return self._get(f"/applications/{name}/managed-resources").json().get("items", [])

    def get_application_manifests(self, name: str) -> list[dict[str, Any]]:
        """Return rendered manifests for an Application."""
        resp = self._get(f"/applications/{name}/manifests")
        return [json.loads(m) for m in resp.json().get("manifests", [])]

    def create_application(self, app_spec: dict[str, Any]) -> dict[str, Any]:
        """Create a new ArgoCD Application."""
        return self._post("/applications", json=app_spec).json()

    def delete_application(self, name: str, cascade: bool = True) -> dict[str, Any]:
        """Delete an ArgoCD Application and optionally cascade to resources."""
        return self._delete(f"/applications/{name}", params={"cascade": str(cascade).lower()}).json()

    def get_application_events(self, name: str) -> list[dict[str, Any]]:
        """Return events for an Application."""
        return self._get(f"/applications/{name}/events").json().get("items", [])

    # ------------------------------------------------------------------
    # Resource-level operations
    # ------------------------------------------------------------------
    def get_application_resource(
        self,
        app_name: str,
        kind: str,
        name: str,
        namespace: str,
        group: str = "",
        version: str = "",
    ) -> dict[str, Any]:
        """Get a specific managed resource's full definition."""
        params: dict[str, str] = {
            "namespace": namespace,
            "kind": kind,
            "resourceName": name,
        }
        if group:
            params["group"] = group
        if version:
            params["version"] = version
        return self._get(f"/applications/{app_name}/resource", params=params).json()

    def delete_application_resource(
        self,
        app_name: str,
        kind: str,
        name: str,
        namespace: str,
        group: str = "",
        version: str = "",
    ) -> dict[str, Any]:
        """Delete a specific managed resource."""
        params: dict[str, str] = {
            "namespace": namespace,
            "kind": kind,
            "resourceName": name,
        }
        if group:
            params["group"] = group
        if version:
            params["version"] = version
        return self._delete(f"/applications/{app_name}/resource", params=params).json()

    # ------------------------------------------------------------------
    # Sync / Refresh / Rollback
    # ------------------------------------------------------------------
    def sync_application(
        self,
        name: str,
        prune: bool = True,
        revision: str | None = None,
    ) -> dict[str, Any]:
        """Trigger a sync operation."""
        body: dict[str, Any] = {
            "prune": prune,
            "syncOptions": {"items": ["PruneLast=true"]},
        }
        if revision:
            body["revision"] = revision
        return self._post(f"/applications/{name}/sync", json=body).json()

    def refresh_application(self, name: str) -> dict[str, Any]:
        """Refresh Application (re-evaluate sync state)."""
        return self._get(f"/applications/{name}", params={"refresh": True}).json()

    def rollback_application(self, name: str, history_id: int) -> dict[str, Any]:
        """Rollback Application to a previous sync history ID."""
        return self._post(f"/applications/{name}/rollback", json={"id": history_id}).json()

    def terminate_operation(self, name: str) -> dict[str, Any]:
        """Terminate the currently running operation (sync/rollback)."""
        return self._delete(f"/applications/{name}/operation").json()

    # ------------------------------------------------------------------
    # Pod helpers
    # ------------------------------------------------------------------
    def find_pod(self, pod_name: str) -> dict[str, Any] | None:
        """Search every Application for a Pod by name. Returns the node dict."""
        apps = self.list_applications()
        for app in apps:
            app_name = app.get("metadata", {}).get("name", "") or app.get("name", "")
            if not app_name:
                continue
            try:
                tree = self.get_application_resource_tree(app_name)
            except Exception:
                continue
            for node in tree.get("nodes", []):
                if node.get("kind") == "Pod" and node.get("name") == pod_name:
                    node["app_name"] = app_name
                    return node
        return None

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def list_projects(self) -> list[dict[str, Any]]:
        """Return all ArgoCD AppProjects."""
        return self._get("/projects").json().get("items", [])

    def get_project(self, name: str) -> dict[str, Any]:
        """Return a single AppProject."""
        return self._get(f"/projects/{name}").json()

    def create_project(self, project_spec: dict[str, Any]) -> dict[str, Any]:
        """Create a new AppProject."""
        return self._post("/projects", json=project_spec).json()

    # ------------------------------------------------------------------
    # Account / Clusters / Repositories
    # ------------------------------------------------------------------
    def get_account_info(self) -> dict[str, Any]:
        """Return current user account info."""
        return self._get("/account").json()

    def list_clusters(self) -> list[dict[str, Any]]:
        """Return all managed clusters."""
        return self._get("/clusters").json().get("items", [])

    def list_repositories(self) -> list[dict[str, Any]]:
        """Return all configured repositories."""
        return self._get("/repositories").json().get("items", [])

    # ------------------------------------------------------------------
    # Low-level HTTP
    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{self.server}/api/v1{path}"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> requests.Response:
        resp = requests.request(
            method,
            self._url(path),
            headers=self._headers(),
            verify=self.ssl_verify,
            **kwargs,
        )
        if resp.status_code >= 400:
            raise RuntimeError(
                f"ArgoCD API {resp.status_code} at {path}: "
                f"{resp.json().get('message', resp.text)}",
            )
        return resp

    def _get(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("GET", path, **kwargs)

    def _post(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("POST", path, **kwargs)

    def _delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self._request("DELETE", path, **kwargs)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------

def _load_dotenv(path: str | Path) -> None:
    """Parse a .env file and set os.environ (do not override existing)."""
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def _token_from_argocd_config(server: str | None = None) -> str | None:
    """Try to extract a token from ~/.config/argocd/config.

    Matching strategy:
      1. Find the user whose name best matches the target server hostname.
      2. Fallback: return the first user whose token isn't empty.
    """
    import yaml

    config_path = Path.home() / ".config" / "argocd" / "config"
    if not config_path.is_file():
        return None

    try:
        cfg = yaml.safe_load(config_path.read_text())
    except Exception:
        return None

    if not isinstance(cfg, dict):
        return None

    users: list[dict] = cfg.get("users") or []
    if not users:
        return None

    # Extract host part from server URL for comparison
    target_host = server or ""
    # e.g. "https://argocd.hd123.com/dnet-int" -> "argocd.hd123.com"
    import urllib.parse
    try:
        target_host = urllib.parse.urlparse(target_host).hostname or target_host
    except Exception:
        pass

    # Priority match: user name containing the host
    for user in users:
        uid = user.get("name", "")
        token = user.get("auth-token") or ""
        if token and target_host and target_host in uid:
            return token

    # Fallback: return token for the server that matches the server list
    servers: list[dict] = cfg.get("servers") or []
    for srv in servers:
        srv_host = srv.get("server", "")
        for user in users:
            uid = user.get("name", "")
            token = user.get("auth-token") or ""
            if token and (srv_host in uid or uid in srv_host):
                return token

    # Last resort: return any non-empty token
    for user in users:
        token = user.get("auth-token") or ""
        if token:
            return token

    return None
