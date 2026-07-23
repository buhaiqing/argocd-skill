"""ArgoCD HTTP API client — thin re-export of argocd_api.client.

This module is a backward-compatible wrapper around the canonical
client in scripts/argocd_api/client.py.  It exists so that existing
ulw code (commands.py, ulw.py) continues to work unchanged.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# Import the canonical client, tolerant of which Python path is in effect.
try:
    from scripts.argocd_api.client import (
        ArgoCDClient as _BaseArgoCDClient,
        _load_dotenv as _load_dotenv_fn,
    )
except ImportError:
    from argocd_api.client import (
        ArgoCDClient as _BaseArgoCDClient,
        _load_dotenv as _load_dotenv_fn,
    )


class UlwClient(_BaseArgoCDClient):
    """Backward-compatible wrapper for the ulw calling convention.

    The canonical ``ArgoCDClient`` in ``argocd_api.client`` uses
    a different parameter order for ``delete_application_resource``
    (``kind`` before ``namespace``) and omits ``_load_dotenv`` as a
    static method.  This subclass bridges those differences so that
    ``commands.py`` and ``ulw.py`` work unchanged.
    """

    @staticmethod
    def _load_dotenv(path: str | Path) -> None:
        """Load environment variables from a ``.env`` file."""
        _load_dotenv_fn(path)

    @classmethod
    def from_env(
        cls,
        dotenv_path: str | Path | None = None,
        **kwargs: Any,
    ) -> "UlwClient":
        """ulw-compatible factory: accepts the historical ``dotenv_path`` kwarg.

        The canonical client renamed this to ``env_path``; this shim maps
        the old name so existing ulw callers (e.g. ``ulw.py``) keep working.
        """
        return super().from_env(env_path=dotenv_path, **kwargs)

    def get_application_resource_tree(self, name: str) -> list[dict[str, Any]]:
        """Return the managed-resources tree items for an Application.

        The base class returns the full ``dict`` (including ``nodes`` and
        ``hosts``).  This override preserves the original ulw convention
        of returning ``.items`` as a flat list.
        """
        return super().get_application_resource_tree(name).get("items", [])

    def delete_application_resource(
        self,
        app_name: str,
        namespace: str,
        kind: str,
        name: str,
        group: str = "",
        version: str = "",
    ) -> dict[str, Any]:
        """Delete a specific managed resource.

        The base class signature is ``(app_name, kind, name, namespace)``;
        this override uses ``(app_name, namespace, kind, name)`` to match
        the original ulw calling convention.
        """
        # Delegate to base class — reorder args to match its signature.
        return super().delete_application_resource(
            app_name=app_name,
            kind=kind,
            name=name,
            namespace=namespace,
            group=group,
            version=version,
        )


# Re-export under the original name so ``from .client import ArgoCDClient``
# in commands.py / ulw.py keeps working unchanged.
ArgoCDClient = UlwClient
