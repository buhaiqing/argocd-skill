"""ArgoCD HTTP API client — bypasses the argocd CLI path-handling bug.

Handles:
  - Session login (username + password → bearer token)
  - All CRUD operations on Application resources
  - Resource-level operations (list, delete)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

# requests is not in requirements.txt for argocd_cli_gen,
# but ulw is its own standalone tool — install it explicitly.
HAS_REQUESTS = True


@dataclass
class ArgoCDClient:
    """Low-level ArgoCD API client."""

    server: str          # e.g. "https://argocd.hd123.com/dnet-int"
    token: str | None   # bearer token (from login)
    ssl_verify: bool

    BASE: str = "/api/v1"   # API base path appended to server

    # ------------------------------------------------------------------
    # Factory — authenticate from env or explicit creds
    # ------------------------------------------------------------------
    @classmethod
    def from_env(cls, dotenv_path: str | Path | None = None) -> "ArgoCDClient":
        """Load ARGOCD_* vars from .env file or environment."""
        if dotenv_path:
            cls._load_dotenv(dotenv_path)

        server = os.environ.get("ARGOCD_SERVER", "").rstrip("/")
        if not server:
            raise ValueError("ARGOCD_SERVER is not set")

        token = os.environ.get("ARGOCD_AUTH_TOKEN", "") or None
        username = os.environ.get("ARGOCD_USERNAME", "")
        password = os.environ.get("ARGOCD_PASSWORD", "")

        ssl_verify = os.environ.get("ARGOCD_SSL_VERIFY", "1") != "0"

        client = cls(server=server, token=token, ssl_verify=ssl_verify)

        if not token and username:
            token = client.login(username, password)
            print(f"[ulw] token obtained for {username}", file=sys.stderr)
        elif not token:
            raise ValueError(
                "Neither ARGOCD_AUTH_TOKEN nor ARGOCD_USERNAME is set"
            )

        client.token = token
        return client

    @staticmethod
    def _load_dotenv(path: str | Path) -> None:
        """Parse a .env file and export vars into os.environ."""
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # strip surrounding quotes
            if len(value) >= 2 and value[0] in ('"', "'"):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def login(self, username: str, password: str) -> str:
        """Authenticate and return a bearer token."""
        resp = self._post("/session", json={"username": username, "password": password})
        data = resp.json()
        token = data.get("token") or data.get("tokenString")
        if not token:
            raise ValueError(f"Login response missing token: {data}")
        return token

    # ------------------------------------------------------------------
    # Applications
    # ------------------------------------------------------------------
    def list_applications(self) -> list[dict[str, Any]]:
        """Return all ArgoCD applications."""
        resp = self._get("/applications")
        items = resp.json().get("items", [])
        return items

    def get_application(self, name: str) -> dict[str, Any]:
        """Return a single Application."""
        resp = self._get(f"/applications/{name}")
        return resp.json()

    def get_application_resource_tree(
        self, name: str
    ) -> list[dict[str, Any]]:
        """Return the managed-resources tree for an Application."""
        resp = self._get(f"/applications/{name}/resource-tree")
        return resp.json().get("items", [])

    def get_application_managed_resources(
        self, name: str
    ) -> list[dict[str, Any]]:
        """Return live + target resource state for an Application."""
        resp = self._get(f"/applications/{name}/managed-resources")
        return resp.json().get("items", [])

    def delete_application_resource(
        self,
        app_name: str,
        namespace: str,
        kind: str,
        name: str,
        group: str = "",
        version: str = "",
    ) -> dict[str, Any]:
        """Delete a specific managed resource from an Application.

        ArgoCD API: DELETE /api/v1/applications/{app}/resources
        Query params: namespace, kind, name, group, version, resourceName
        """
        params: dict[str, str] = {
            "namespace": namespace,
            "kind": kind,
            "resourceName": name,
        }
        if group:
            params["group"] = group
        if version:
            params["version"] = version

        resp = self._delete(f"/applications/{app_name}/resources", params=params)
        return resp.json()

    def patch_application_resource(
        self,
        app_name: str,
        namespace: str,
        kind: str,
        name: str,
        patch: dict[str, Any],
        group: str = "",
        version: str = "",
    ) -> dict[str, Any]:
        """Patch a managed resource (e.g. delete a pod via App sync)."""
        params: dict[str, str] = {
            "namespace": namespace,
            "kind": kind,
            "resourceName": name,
        }
        if group:
            params["group"] = group
        if version:
            params["version"] = version

        resp = self._post(
            f"/applications/{app_name}/resource",
            params=params,
            json=patch,
        )
        return resp.json()

    # ------------------------------------------------------------------
    # Low-level HTTP primitives
    # ------------------------------------------------------------------
    def _url(self, path: str) -> str:
        """Join server + base + path, normalising slashes."""
        return f"{self.server}{self.BASE}{path}"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _get(self, path: str, **kwargs) -> requests.Response:
        return requests.get(
            self._url(path),
            headers=self._headers(),
            verify=self.ssl_verify,
            **kwargs,
        )

    def _post(self, path: str, **kwargs) -> requests.Response:
        return requests.post(
            self._url(path),
            headers=self._headers(),
            verify=self.ssl_verify,
            **kwargs,
        )

    def _delete(self, path: str, **kwargs) -> requests.Response:
        return requests.delete(
            self._url(path),
            headers=self._headers(),
            verify=self.ssl_verify,
            **kwargs,
        )

    def raise_for_status(self, resp: requests.Response) -> None:
        """Raise requests.HTTPError with ArgoCD error message."""
        if resp.status_code < 400:
            return
        try:
            err = resp.json()
            msg = err.get("message") or err.get("error") or str(err)
        except ValueError:
            msg = resp.text or f"HTTP {resp.status_code}"
        raise requests.HTTPError(
            f"ArgoCD API {resp.status_code} at {resp.url}: {msg}",
            response=resp,
        )
