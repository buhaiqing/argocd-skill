"""Unit tests for scripts/ulw/client.py and scripts/ulw/commands.py.

No network calls — all external dependencies are mocked.
"""

from __future__ import annotations

import os

# The canonical client lives in argocd_api.client; ulw re-exports it.
# from_env is inherited from the base class, so patch the base module that
# the resolved import path actually uses (argocd_api.client or
# scripts.argocd_api.client — same file, different sys.modules key).
import sys
from unittest.mock import MagicMock, patch

import pytest

from ulw.client import ArgoCDClient
from ulw.commands import BlockedError, PodLocation, delete_pod, find_pod, wait_pod_ready

_BASE_MODULE = sys.modules[ArgoCDClient.__mro__[1].__module__]


# ======================================================================
# _load_dotenv (static method on ArgoCDClient)
# ======================================================================

def test_load_dotenv_sets_vars(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ARGOCD_SERVER=https://argocd.example.com\nARGOCD_USERNAME=ops\n")
    with patch.dict(os.environ, {}, clear=True):
        ArgoCDClient._load_dotenv(env)
        assert os.environ["ARGOCD_SERVER"] == "https://argocd.example.com"
        assert os.environ["ARGOCD_USERNAME"] == "ops"


def test_load_dotenv_skips_comments_and_blanks(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nKEY=val\n")
    ArgoCDClient._load_dotenv(env)
    assert os.environ.get("KEY") == "val"
    del os.environ["KEY"]
    assert "comment" not in os.environ


def test_load_dotenv_does_not_override(tmp_path):
    os.environ["EXISTING"] = "original"
    env = tmp_path / ".env"
    env.write_text("EXISTING=should_not_override\n")
    ArgoCDClient._load_dotenv(env)
    assert os.environ["EXISTING"] == "original"
    del os.environ["EXISTING"]


def test_load_dotenv_strips_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text('HOST="localhost"\nPORT=\'8080\'\n')
    ArgoCDClient._load_dotenv(env)
    assert os.environ["HOST"] == "localhost"
    assert os.environ["PORT"] == "8080"
    del os.environ["HOST"]
    del os.environ["PORT"]


def test_load_dotenv_skips_malformed_lines(tmp_path):
    """Lines without '=' should be silently skipped."""
    env = tmp_path / ".env"
    env.write_text("MALFORMED\nKEY=val\n")
    ArgoCDClient._load_dotenv(env)
    assert os.environ.get("KEY") == "val"
    assert "MALFORMED" not in os.environ
    del os.environ["KEY"]


# ======================================================================
# ArgoCDClient construction / URL / headers
# ======================================================================

def test_client_url_construction():
    client = ArgoCDClient(server="https://argocd.example.com", token="x")
    assert client._url("/applications") == "https://argocd.example.com/api/v1/applications"
    assert client._url("/session") == "https://argocd.example.com/api/v1/session"


def test_client_url_with_path_prefix():
    """Server with sub-path (context path) should be preserved."""
    client = ArgoCDClient(server="https://argocd.hd123.com/dnet-int", token="x")
    assert client._url("/applications") == "https://argocd.hd123.com/dnet-int/api/v1/applications"


def test_client_url_strips_trailing_slash():
    client = ArgoCDClient(server="https://argocd.example.com/", token="x")
    assert client._url("/apps") == "https://argocd.example.com/api/v1/apps"


def test_client_headers_with_token():
    client = ArgoCDClient(server="https://x.com", token="my-token")
    h = client._headers()
    assert h["Authorization"] == "Bearer my-token"
    assert h["Content-Type"] == "application/json"


def test_client_headers_no_token():
    client = ArgoCDClient(server="https://x.com")
    h = client._headers()
    assert "Authorization" not in h
    assert h["Content-Type"] == "application/json"


def test_client_headers_token_none():
    """token=None should be treated same as no token."""
    client = ArgoCDClient(server="https://x.com", token=None)
    h = client._headers()
    assert "Authorization" not in h


# ======================================================================
# from_env (factory)
# ======================================================================

def test_from_env_missing_server():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="ARGOCD_SERVER is not set"):
            ArgoCDClient.from_env()


def test_from_env_uses_auth_token():
    with patch.dict(os.environ, {
        "ARGOCD_SERVER": "https://argocd.example.com",
        "ARGOCD_AUTH_TOKEN": "env-tok",
    }, clear=True):
        client = ArgoCDClient.from_env()
        assert client.token == "env-tok"
        assert client.server == "https://argocd.example.com"


def test_from_env_fails_no_credentials():
    with patch.dict(os.environ, {
        "ARGOCD_SERVER": "https://argocd.example.com",
    }, clear=True):
        with patch.object(_BASE_MODULE, "_token_from_argocd_config", return_value=None):
            with pytest.raises(ValueError, match="No ArgoCD credentials"):
                ArgoCDClient.from_env()


def test_from_env_empty_token_falls_through():
    """Empty-string ARGOCD_AUTH_TOKEN should not count as a credential."""
    with patch.dict(os.environ, {
        "ARGOCD_SERVER": "https://argocd.example.com",
        "ARGOCD_AUTH_TOKEN": "",
    }, clear=True):
        with patch.object(_BASE_MODULE, "_token_from_argocd_config", return_value=None):
            with pytest.raises(ValueError, match="No ArgoCD credentials"):
                ArgoCDClient.from_env()


def test_from_env_ssl_verify_default():
    with patch.dict(os.environ, {
        "ARGOCD_SERVER": "https://x.com",
        "ARGOCD_AUTH_TOKEN": "tok",
    }, clear=True):
        client = ArgoCDClient.from_env()
        assert client.ssl_verify is True


def test_from_env_ssl_verify_disabled():
    with patch.dict(os.environ, {
        "ARGOCD_SERVER": "https://x.com",
        "ARGOCD_AUTH_TOKEN": "tok",
        "ARGOCD_SSL_VERIFY": "0",
    }, clear=True):
        client = ArgoCDClient.from_env()
        assert client.ssl_verify is False


def test_from_env_with_dotenv(tmp_path):
    """from_env should load .env file when dotenv_path is given (ulw kwarg)."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ARGOCD_SERVER=https://dotenv.example.com\n"
        "ARGOCD_AUTH_TOKEN=dotenv-tok\n"
    )
    with patch.dict(os.environ, {}, clear=True):
        with patch.object(_BASE_MODULE, "_token_from_argocd_config", return_value=None):
            client = ArgoCDClient.from_env(dotenv_path=env_file)
            assert client.server == "https://dotenv.example.com"
            assert client.token == "dotenv-tok"


def test_from_env_login_flow():
    """When only USERNAME/PASSWORD are present, should call client.login()."""
    with patch.dict(os.environ, {
        "ARGOCD_SERVER": "https://x.com",
        "ARGOCD_USERNAME": "admin",
        "ARGOCD_PASSWORD": "secret",
    }, clear=True):
        with patch.object(_BASE_MODULE, "_token_from_argocd_config", return_value=None):
            with patch.object(ArgoCDClient, "login", return_value="login-tok"):
                client = ArgoCDClient.from_env()
                assert client.token == "login-tok"


# ======================================================================
# login
# ======================================================================

def test_login_success():
    client = ArgoCDClient(server="https://x.com")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"token": "bearer-tok"}
    with patch.object(client, "_post", return_value=mock_resp):
        token = client.login("admin", "pass")
    assert token == "bearer-tok"


def test_login_token_in_token_string():
    """Some ArgoCD API versions return tokenString instead of token."""
    client = ArgoCDClient(server="https://x.com")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"tokenString": "alt-tok"}
    with patch.object(client, "_post", return_value=mock_resp):
        token = client.login("admin", "pass")
    assert token == "alt-tok"


def test_login_missing_token():
    client = ArgoCDClient(server="https://x.com")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": "ok"}
    with patch.object(client, "_post", return_value=mock_resp):
        with pytest.raises(ValueError, match="Login response missing token"):
            client.login("admin", "pass")


# ======================================================================
# HTTP primitives: _get, _post, _delete
# ======================================================================

@patch("argocd_api.client.requests.request")
def test_get_uses_correct_url(mock_request):
    mock_request.return_value = MagicMock(status_code=200, json=dict)
    client = ArgoCDClient(server="https://x.com", token="t")
    client._get("/applications")
    assert mock_request.call_args[0][1] == "https://x.com/api/v1/applications"


@patch("argocd_api.client.requests.request")
def test_post_uses_correct_url(mock_request):
    mock_request.return_value = MagicMock(status_code=200, json=dict)
    client = ArgoCDClient(server="https://x.com", token="t")
    client._post("/applications/my-app/sync", json={})
    assert mock_request.call_args[0][1] == "https://x.com/api/v1/applications/my-app/sync"


@patch("argocd_api.client.requests.request")
def test_delete_uses_correct_url(mock_request):
    mock_request.return_value = MagicMock(status_code=200, json=dict)
    client = ArgoCDClient(server="https://x.com", token="t")
    client._delete("/applications/my-app", params={"foo": "bar"})
    assert mock_request.call_args[0][1] == "https://x.com/api/v1/applications/my-app"


# ======================================================================
# Error handling (delegates to argocd_api.client._request)
# ======================================================================

@patch("argocd_api.client.requests.request")
def test_request_4xx_raises_runtime_error(mock_request):
    mock_request.return_value = MagicMock(status_code=404, json=lambda: {"message": "not found"})
    client = ArgoCDClient(server="https://x.com", token="t")
    with pytest.raises(RuntimeError, match="404"):
        client._request("GET", "/applications/x", params={})


@patch("argocd_api.client.requests.request")
def test_request_4xx_uses_error_field(mock_request):
    """Some ArgoCD error responses use 'error' instead of 'message'."""
    mock_request.return_value = MagicMock(status_code=400, json=lambda: {"error": "invalid request"})
    client = ArgoCDClient(server="https://x.com", token="t")
    with pytest.raises(RuntimeError, match="invalid request"):
        client._request("GET", "/applications/x", params={})


@patch("argocd_api.client.requests.request")
def test_request_4xx_text_fallback(mock_request):
    """When JSON parsing fails, fall back to response text."""
    resp = MagicMock(status_code=500)
    resp.json.side_effect = ValueError("not json")
    resp.text = "Internal Server Error"
    mock_request.return_value = resp
    client = ArgoCDClient(server="https://x.com", token="t")
    with pytest.raises(RuntimeError, match="Internal Server Error"):
        client._request("GET", "/applications/x", params={})


# ======================================================================
# Application read methods
# ======================================================================

def test_list_applications():
    client = ArgoCDClient(server="https://x.com", token="t")
    client._get = MagicMock(return_value=MagicMock(
        json=lambda: {"items": [{"name": "a"}, {"name": "b"}]}
    ))
    items = client.list_applications()
    assert len(items) == 2
    assert items[0]["name"] == "a"


def test_list_applications_empty():
    client = ArgoCDClient(server="https://x.com", token="t")
    client._get = MagicMock(return_value=MagicMock(
        json=dict
    ))
    items = client.list_applications()
    assert items == []


def test_get_application():
    client = ArgoCDClient(server="https://x.com", token="t")
    client._get = MagicMock(return_value=MagicMock(
        json=lambda: {"metadata": {"name": "my-app"}}
    ))
    result = client.get_application("my-app")
    assert result["metadata"]["name"] == "my-app"


def test_get_application_resource_tree():
    client = ArgoCDClient(server="https://x.com", token="t")
    client._get = MagicMock(return_value=MagicMock(
        json=lambda: {"items": [{"kind": "Pod", "name": "p1"}]}
    ))
    items = client.get_application_resource_tree("my-app")
    assert len(items) == 1


def test_get_application_managed_resources():
    client = ArgoCDClient(server="https://x.com", token="t")
    client._get = MagicMock(return_value=MagicMock(
        json=lambda: {"items": [{"kind": "Pod", "namespace": "ops", "name": "p1"}]}
    ))
    items = client.get_application_managed_resources("my-app")
    assert len(items) == 1
    assert items[0]["kind"] == "Pod"


# ======================================================================
# Application write methods
# ======================================================================

def test_delete_application_resource():
    client = ArgoCDClient(server="https://x.com", token="t")
    client._delete = MagicMock(return_value=MagicMock(json=dict))
    result = client.delete_application_resource(
        app_name="my-app",
        namespace="ops",
        kind="Pod",
        name="target-pod",
    )
    client._delete.assert_called_once()
    assert result == {}


def test_delete_application_resource_with_group_version():
    client = ArgoCDClient(server="https://x.com", token="t")
    client._delete = MagicMock(return_value=MagicMock(json=dict))
    client.delete_application_resource(
        app_name="my-app",
        namespace="ops",
        kind="Deployment",
        name="my-deploy",
        group="apps",
        version="v1",
    )
    call_kwargs = client._delete.call_args[1]
    params = call_kwargs["params"]
    assert params["group"] == "apps"
    assert params["version"] == "v1"


# ======================================================================
# commands.find_pod
# ======================================================================

def test_find_pod_returns_location_when_found():
    """Pod via /pods endpoint (ArgoCD 1.9+) — flat shape."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "my-app"}},
    ])
    client.get_application_pods = MagicMock(return_value=[
        {
            "kind": "Pod",
            "apiVersion": "v1",
            "metadata": {"name": "target-pod", "namespace": "ops"},
        },
    ])

    loc = find_pod(client, "target-pod")
    assert loc is not None
    assert loc.app_name == "my-app"
    assert loc.namespace == "ops"
    assert loc.kind == "Pod"
    assert loc.name == "target-pod"
    assert loc.group == ""
    assert loc.version == "v1"


def test_find_pod_detects_api_version_group():
    """When apiVersion contains a group (apps/v1), extract group and version."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "my-app"}},
    ])
    client.get_application_pods = MagicMock(return_value=[
        {
            "kind": "Deployment",
            "apiVersion": "apps/v1",
            "metadata": {"name": "my-deploy", "namespace": "prod"},
        },
    ])

    loc = find_pod(client, "my-deploy")
    assert loc is not None
    assert loc.group == "apps"
    assert loc.version == "v1"


def test_find_pod_returns_none_when_missing():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "my-app"}},
    ])
    client.get_application_pods = MagicMock(return_value=[
        {"kind": "Service", "metadata": {"name": "my-svc"}},
    ])

    assert find_pod(client, "missing-pod") is None


def test_find_pod_skips_app_errors():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "broken-app"}},
        {"metadata": {"name": "good-app"}},
    ])
    client.get_application_pods = MagicMock(side_effect=[
        RuntimeError("API error"),
        [
            {
                "kind": "Pod",
                "apiVersion": "v1",
                "metadata": {"name": "target-pod", "namespace": "ops"},
            },
        ],
    ])

    loc = find_pod(client, "target-pod")
    assert loc is not None
    assert loc.app_name == "good-app"


def test_find_pod_handles_no_apps():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[])
    assert find_pod(client, "anything") is None


def test_find_pod_skips_app_without_name():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {},  # no metadata
        {"not_name": "irrelevant"},
    ])
    client.get_application_pods = MagicMock(return_value=[])
    assert find_pod(client, "anything") is None


def test_find_pod_via_pods_endpoint():
    """Regression: when /pods endpoint returns items, find_pod uses them directly.

    Simulates ArgoCD 1.9+ where ``GET /applications/{name}/pods`` returns a
    standard K8s-style list: ``{"items": [{"kind": "Pod", "metadata": ...}, ...]}``.
    """
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "hdops-mcp"}},
    ])
    # /pods endpoint succeeds — get_application_pods returns its items directly
    client._get = MagicMock(return_value=MagicMock(
        json=lambda: {"items": [
            {
                "kind": "Pod",
                "apiVersion": "v1",
                "metadata": {"name": "hdops-mcp-7b8cc44dd8-cx8x9", "namespace": "ops"},
            },
        ]},
    ))

    loc = find_pod(client, "hdops-mcp-7b8cc44dd8-cx8x9")
    assert loc is not None
    assert loc.app_name == "hdops-mcp"
    assert loc.namespace == "ops"
    assert loc.name == "hdops-mcp-7b8cc44dd8-cx8x9"
    # /pods endpoint was hit (path contains /pods), not /resource-tree
    called_path = client._get.call_args[0][0]
    assert "/pods" in called_path


def test_find_pod_via_resource_tree_fallback():
    """Regression: when /pods endpoint returns 404, find_pod falls back to /resource-tree.

    Real-world evidence (argocd.hd123.com): /applications/hdops-mcp/pods → HTTP 404
    "Not Found". The fix: get_application_pods internally retries
    /applications/{name}/resource-tree and filters nodes where kind == "Pod".
    """
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "hdops-mcp"}},
    ])

    # Simulate: /pods returns 404, /resource-tree returns Pod nodes
    def fake_get(path, **kwargs):
        if path.endswith("/pods"):
            # Mimic client._request behaviour on 4xx → RuntimeError
            raise RuntimeError(f"ArgoCD API 404 at {path}: Not Found")
        if path.endswith("/resource-tree"):
            real = MagicMock()
            real.json.return_value = {
                "nodes": [
                    {"kind": "Deployment", "name": "hdops-mcp", "namespace": "ops", "version": "v1"},
                    {"kind": "ReplicaSet", "name": "hdops-mcp-7b8cc44dd8", "namespace": "ops", "version": "v1"},
                    {"kind": "Pod", "name": "hdops-mcp-7b8cc44dd8-cx8x9", "namespace": "ops", "version": "v1"},
                    {"kind": "Pod", "name": "hdops-mcp-7b8cc44dd8-abcde", "namespace": "ops", "version": "v1"},
                ],
                "hosts": [],
            }
            return real
        raise AssertionError(f"unexpected path: {path}")

    client._get = MagicMock(side_effect=fake_get)

    loc = find_pod(client, "hdops-mcp-7b8cc44dd8-abcde")
    assert loc is not None
    assert loc.app_name == "hdops-mcp"
    assert loc.namespace == "ops"
    assert loc.name == "hdops-mcp-7b8cc44dd8-abcde"
    assert loc.kind == "Pod"
    assert loc.version == "v1"

    # Verify both endpoints were attempted: /pods (404) then /resource-tree
    called_paths = [c[0][0] for c in client._get.call_args_list]
    assert any(p.endswith("/pods") for p in called_paths)
    assert any(p.endswith("/resource-tree") for p in called_paths)


def test_find_pod_via_resource_tree_no_pods():
    """resource-tree fallback returns no Pod nodes → find_pod returns None."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "config-only-app"}},
    ])

    def fake_get(path, **kwargs):
        if path.endswith("/pods"):
            raise RuntimeError(f"ArgoCD API 404 at {path}: Not Found")
        if path.endswith("/resource-tree"):
            return MagicMock(json=lambda: {
                "nodes": [
                    {"kind": "ConfigMap", "name": "cm1", "namespace": "ops", "version": "v1"},
                    {"kind": "Deployment", "name": "deploy1", "namespace": "ops", "version": "v1"},
                ],
                "hosts": [],
            })
        raise AssertionError(f"unexpected path: {path}")

    client._get = MagicMock(side_effect=fake_get)
    assert find_pod(client, "anything") is None


# ======================================================================
# ArgoCDClient.get_application_pods (base client method)
# ======================================================================

def test_get_application_pods_uses_pods_endpoint():
    """When /pods endpoint returns 200, use its items directly."""
    client = ArgoCDClient(server="https://x.com", token="t")
    client._get = MagicMock(return_value=MagicMock(
        json=lambda: {"items": [{"kind": "Pod", "name": "p1"}]},
    ))
    pods = client.get_application_pods("my-app")
    assert len(pods) == 1
    assert pods[0]["name"] == "p1"
    assert "/pods" in client._get.call_args[0][0]


def test_get_application_pods_falls_back_to_resource_tree():
    """When /pods returns 404, extract Pod nodes from /resource-tree."""
    client = ArgoCDClient(server="https://x.com", token="t")

    def fake_get(path, **kwargs):
        if path.endswith("/pods"):
            raise RuntimeError(f"ArgoCD API 404 at {path}: Not Found")
        if path.endswith("/resource-tree"):
            return MagicMock(json=lambda: {
                "nodes": [
                    {"kind": "Deployment", "name": "deploy1"},
                    {"kind": "Pod", "name": "pod1"},
                    {"kind": "Pod", "name": "pod2"},
                ],
            })
        raise AssertionError(f"unexpected path: {path}")

    client._get = MagicMock(side_effect=fake_get)
    pods = client.get_application_pods("my-app")
    assert len(pods) == 2
    assert {p["name"] for p in pods} == {"pod1", "pod2"}
    called_paths = [c[0][0] for c in client._get.call_args_list]
    assert any(p.endswith("/pods") for p in called_paths)
    assert any(p.endswith("/resource-tree") for p in called_paths)


def test_get_application_pods_returns_empty_when_both_fail():
    """Both /pods (404) and /resource-tree (5xx) fail → return []."""
    client = ArgoCDClient(server="https://x.com", token="t")

    def fake_get(path, **kwargs):
        if path.endswith("/pods"):
            raise RuntimeError(f"ArgoCD API 404 at {path}: Not Found")
        if path.endswith("/resource-tree"):
            raise RuntimeError(f"ArgoCD API 500 at {path}: Internal Error")
        raise AssertionError(f"unexpected path: {path}")

    client._get = MagicMock(side_effect=fake_get)
    pods = client.get_application_pods("my-app")
    assert pods == []


# ======================================================================
# commands.delete_pod
# ======================================================================

def _automated_client() -> ArgoCDClient:
    """Client whose Application has an automated syncPolicy (delete allowed)."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application = MagicMock(return_value={
        "metadata": {"name": "my-app"},
        "spec": {"syncPolicy": {"automated": {"prune": True, "selfHeal": True}}},
    })
    return client


def test_delete_pod_calls_client():
    client = _automated_client()
    client.delete_application_resource = MagicMock(return_value={"status": "ok"})

    loc = PodLocation(
        app_name="my-app",
        namespace="ops",
        kind="Pod",
        name="target-pod",
    )
    result = delete_pod(client, loc)

    client.delete_application_resource.assert_called_once_with(
        app_name="my-app",
        namespace="ops",
        kind="Pod",
        name="target-pod",
        group="",
        version="",
    )
    assert result == {"status": "ok"}


def test_delete_pod_passes_group_version():
    client = _automated_client()
    client.delete_application_resource = MagicMock(return_value={})

    loc = PodLocation(
        app_name="my-app",
        namespace="prod",
        kind="Deployment",
        name="my-deploy",
        group="apps",
        version="v1",
    )
    delete_pod(client, loc)

    client.delete_application_resource.assert_called_once_with(
        app_name="my-app",
        namespace="prod",
        kind="Deployment",
        name="my-deploy",
        group="apps",
        version="v1",
    )


# ======================================================================
# commands.delete_pod — sync-policy safety guard (BlockedError)
# ======================================================================

_LOC = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")


@pytest.mark.parametrize("app_spec", [
    {"spec": {}},                                    # no syncPolicy at all
    {"spec": {"syncPolicy": {}}},                    # syncPolicy without automated
    {"spec": {"syncPolicy": {"automated": None}}},   # automated explicitly null
    {"spec": {"syncPolicy": {"automated": False}}},  # automated false
    {"spec": {"syncPolicy": "automated"}},           # syncPolicy is a str, not dict
    {"spec": {"syncPolicy": 123}},                   # syncPolicy is a number
    {},                                              # empty App payload
])
def test_delete_pod_blocks_when_not_automated(app_spec):
    """Manual-sync Apps never self-heal a deleted Pod → refuse to delete.

    Covers MAJOR-3: a non-dict ``syncPolicy`` must not raise AttributeError —
    it must be treated as "not automated" and raise BlockedError instead.
    """
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application = MagicMock(return_value=app_spec)
    client.delete_application_resource = MagicMock()

    with pytest.raises(BlockedError) as exc_info:
        delete_pod(client, _LOC)

    client.delete_application_resource.assert_not_called()
    message = str(exc_info.value)
    assert "my-app" in message
    assert "automated" in message
    assert "kubectl rollout restart" in message
    assert "argocd app sync" in message


@pytest.mark.parametrize("automated_value", [
    "false",   # YAML-quoted false — common and dangerous
    0,
    "",
    [],
])
def test_delete_pod_blocks_when_automated_is_falsy_non_dict(automated_value):
    """MAJOR-4: only a dict counts as automated; any other value is blocked.

    A quoted ``'false'`` in a real manifest would otherwise be let through by a
    blacklist and delete a Pod that ArgoCD will not recreate.
    """
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application = MagicMock(return_value={
        "spec": {"syncPolicy": {"automated": automated_value}},
    })
    client.delete_application_resource = MagicMock()

    with pytest.raises(BlockedError):
        delete_pod(client, _LOC)
    client.delete_application_resource.assert_not_called()


def test_delete_pod_allows_automated_empty_dict():
    """``automated: {}`` (all defaults) still counts as automated."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application = MagicMock(return_value={
        "spec": {"syncPolicy": {"automated": {}}},
    })
    client.delete_application_resource = MagicMock(return_value={"status": "ok"})

    assert delete_pod(client, _LOC) == {"status": "ok"}
    client.delete_application_resource.assert_called_once()


def test_delete_pod_blocks_when_get_application_fails():
    """Unable to read the App ⇒ cannot prove it is automated ⇒ block."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application = MagicMock(side_effect=RuntimeError("ArgoCD API 403"))
    client.delete_application_resource = MagicMock()

    with pytest.raises(BlockedError, match="sync policy"):
        delete_pod(client, _LOC)
    client.delete_application_resource.assert_not_called()


def test_delete_pod_skip_safety_check_bypasses_guard():
    """``skip_safety_check=True`` is the documented escape hatch."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application = MagicMock(return_value={"spec": {}})
    client.delete_application_resource = MagicMock(return_value={})

    delete_pod(client, _LOC, skip_safety_check=True)
    client.get_application.assert_not_called()
    client.delete_application_resource.assert_called_once()


# ======================================================================
# commands.wait_pod_ready
# ======================================================================

def _fake_clock(interval: int):
    """Drive time.monotonic/sleep from a controllable counter.

    Patching only ``time.sleep`` (as the old tests did) removes the only
    throttle and hides a busy-spin regression. Here both monotonic and sleep
    advance together so the poll loop is bounded and ``call_count`` is assertable.
    """
    state = {"t": 0.0}

    def fake_monotonic() -> float:
        return state["t"]

    def fake_sleep(duration: float) -> None:
        state["t"] += duration

    return fake_monotonic, fake_sleep


def test_wait_pod_ready_succeeds_when_new_running_pod_appears():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application_pods = MagicMock(side_effect=[
        # old pod still there, no replacement yet
        [{"name": "target-pod", "health": {"status": "Healthy"}}],
        # old pod gone, new pod running
        [{"name": "target-pod-new", "health": {"status": "Healthy"}}],
    ])
    fake_monotonic, fake_sleep = _fake_clock(1)
    with patch("ulw.commands.time.monotonic", fake_monotonic), patch(
        "ulw.commands.time.sleep", fake_sleep
    ):
        assert wait_pod_ready(client, "my-app", "target-pod", timeout=30, interval=1) is True
    assert client.get_application_pods.call_count == 2


def test_wait_pod_ready_ignores_non_running_new_pod():
    """A new Pod that is still Progressing does not satisfy the wait."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application_pods = MagicMock(return_value=[
        {"name": "target-pod-new", "health": {"status": "Progressing"}},
    ])
    fake_monotonic, fake_sleep = _fake_clock(1)
    with patch("ulw.commands.time.monotonic", fake_monotonic), patch(
        "ulw.commands.time.sleep", fake_sleep
    ):
        assert wait_pod_ready(client, "my-app", "target-pod", timeout=3, interval=1) is False
    # Bounded: never busy-spins. ~timeout/interval polls, +1 for the final check.
    assert client.get_application_pods.call_count <= 3 // 1 + 2


def test_wait_pod_ready_times_out_when_old_pod_persists():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application_pods = MagicMock(return_value=[
        {"name": "target-pod", "health": {"status": "Healthy"}},
        {"name": "target-pod-new", "health": {"status": "Healthy"}},
    ])
    fake_monotonic, fake_sleep = _fake_clock(1)
    with patch("ulw.commands.time.monotonic", fake_monotonic), patch(
        "ulw.commands.time.sleep", fake_sleep
    ):
        assert wait_pod_ready(client, "my-app", "target-pod", timeout=3, interval=1) is False
    assert client.get_application_pods.call_count <= 3 // 1 + 2


def test_wait_pod_ready_tolerates_transient_api_errors():
    """A failing poll should be retried, not abort the wait."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application_pods = MagicMock(side_effect=[
        RuntimeError("ArgoCD API 500"),
        [{"name": "target-pod-new", "health": {"status": "Healthy"}}],
    ])
    fake_monotonic, fake_sleep = _fake_clock(1)
    with patch("ulw.commands.time.monotonic", fake_monotonic), patch(
        "ulw.commands.time.sleep", fake_sleep
    ):
        assert wait_pod_ready(client, "my-app", "target-pod", timeout=30, interval=1) is True


def test_wait_pod_ready_accepts_nested_pod_status_shape():
    """``/pods`` endpoint shape: metadata.name + status.phase."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application_pods = MagicMock(return_value=[
        {"metadata": {"name": "target-pod-new"}, "status": {"phase": "Running"}},
    ])
    fake_monotonic, fake_sleep = _fake_clock(1)
    with patch("ulw.commands.time.monotonic", fake_monotonic), patch(
        "ulw.commands.time.sleep", fake_sleep
    ):
        assert wait_pod_ready(client, "my-app", "target-pod", timeout=30, interval=1) is True


def test_wait_pod_ready_detects_statefulset_in_place_recreation():
    """StatefulSet members keep their name (mysql-0); a changed
    resourceVersion proves recreation even though the name persists."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.get_application_pods = MagicMock(side_effect=[
        [{"name": "mysql-0", "metadata": {"resourceVersion": "100"}, "health": {"status": "Healthy"}}],
        [{"name": "mysql-0", "metadata": {"resourceVersion": "200"}, "health": {"status": "Healthy"}}],
    ])
    fake_monotonic, fake_sleep = _fake_clock(1)
    with patch("ulw.commands.time.monotonic", fake_monotonic), patch(
        "ulw.commands.time.sleep", fake_sleep
    ):
        assert wait_pod_ready(client, "my-app", "mysql-0", timeout=30, interval=1) is True


# ======================================================================
# ulw.py CLI — --yes / --app-name / --namespace / --wait-ready
# ======================================================================

@pytest.fixture
def cli_client(monkeypatch):
    """Patch ArgoCDClient.from_env in ulw.ulw to return a mock client."""
    from ulw import ulw as ulw_cli

    client = MagicMock()
    monkeypatch.setattr(ulw_cli.ArgoCDClient, "from_env", classmethod(lambda cls, **kw: client))
    return client


def test_cli_delete_pod_yes_skips_confirmation(cli_client, monkeypatch):
    from ulw import ulw as ulw_cli

    loc = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")
    monkeypatch.setattr(ulw_cli, "find_pod", MagicMock(return_value=loc))
    delete_mock = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(ulw_cli, "delete_pod", delete_mock)

    def _boom(*_a, **_kw):
        raise AssertionError("input() must not be called with --yes")

    monkeypatch.setattr("builtins.input", _boom)

    assert ulw_cli.main(["delete-pod", "target-pod", "--yes"]) == 0
    delete_mock.assert_called_once()


def test_cli_delete_pod_without_yes_still_prompts(cli_client, monkeypatch):
    from ulw import ulw as ulw_cli

    loc = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")
    monkeypatch.setattr(ulw_cli, "find_pod", MagicMock(return_value=loc))
    delete_mock = MagicMock(return_value={})
    monkeypatch.setattr(ulw_cli, "delete_pod", delete_mock)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: "no")

    assert ulw_cli.main(["delete-pod", "target-pod"]) == 1
    delete_mock.assert_not_called()


def test_cli_delete_pod_eoferror_without_yes_is_clean_abort(cli_client, monkeypatch):
    """MAJOR-5: piped/non-TTY stdin without --yes must abort with rc=1,
    not raise an uncaught EOFError traceback."""
    from ulw import ulw as ulw_cli

    loc = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")
    monkeypatch.setattr(ulw_cli, "find_pod", MagicMock(return_value=loc))
    delete_mock = MagicMock(return_value={})
    monkeypatch.setattr(ulw_cli, "delete_pod", delete_mock)
    monkeypatch.setattr("builtins.input", lambda *_a, **_kw: (_ for _ in ()).throw(EOFError()))

    assert ulw_cli.main(["delete-pod", "target-pod"]) == 1
    delete_mock.assert_not_called()


def test_cli_delete_pod_short_circuits_with_app_and_namespace(cli_client, monkeypatch):
    from ulw import ulw as ulw_cli

    find_mock = MagicMock()
    monkeypatch.setattr(ulw_cli, "find_pod", find_mock)
    delete_mock = MagicMock(return_value={"status": "ok"})
    monkeypatch.setattr(ulw_cli, "delete_pod", delete_mock)

    rc = ulw_cli.main([
        "delete-pod", "target-pod",
        "--app-name", "my-app",
        "--namespace", "ops",
        "--yes",
    ])
    assert rc == 0
    find_mock.assert_not_called()
    loc = delete_mock.call_args[0][1]
    assert loc.app_name == "my-app"
    assert loc.namespace == "ops"
    assert loc.name == "target-pod"
    assert loc.kind == "Pod"


def test_cli_delete_pod_partial_short_circuit_falls_back_to_find(cli_client, monkeypatch):
    """Only --app-name given ⇒ no short circuit, find_pod still runs."""
    from ulw import ulw as ulw_cli

    loc = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")
    find_mock = MagicMock(return_value=loc)
    monkeypatch.setattr(ulw_cli, "find_pod", find_mock)
    monkeypatch.setattr(ulw_cli, "delete_pod", MagicMock(return_value={}))

    assert ulw_cli.main(["delete-pod", "target-pod", "--app-name", "my-app", "--yes"]) == 0
    find_mock.assert_called_once()


def test_cli_delete_pod_blocked_error_returns_nonzero(cli_client, monkeypatch):
    from ulw import ulw as ulw_cli

    loc = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")
    monkeypatch.setattr(ulw_cli, "find_pod", MagicMock(return_value=loc))
    monkeypatch.setattr(
        ulw_cli, "delete_pod",
        MagicMock(side_effect=BlockedError("App my-app is not automated")),
    )

    assert ulw_cli.main(["delete-pod", "target-pod", "--yes"]) == 2


def test_cli_delete_pod_wait_ready_success(cli_client, monkeypatch):
    from ulw import ulw as ulw_cli

    loc = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")
    monkeypatch.setattr(ulw_cli, "find_pod", MagicMock(return_value=loc))
    monkeypatch.setattr(ulw_cli, "delete_pod", MagicMock(return_value={}))
    wait_mock = MagicMock(return_value=True)
    monkeypatch.setattr(ulw_cli, "wait_pod_ready", wait_mock)

    rc = ulw_cli.main([
        "delete-pod", "target-pod", "--yes", "--wait-ready",
        "--wait-timeout", "60", "--wait-interval", "2",
    ])
    assert rc == 0
    wait_mock.assert_called_once_with(
        cli_client, "my-app", "target-pod", timeout=60, interval=2,
    )


def test_cli_delete_pod_wait_ready_timeout_returns_nonzero(cli_client, monkeypatch):
    from ulw import ulw as ulw_cli

    loc = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")
    monkeypatch.setattr(ulw_cli, "find_pod", MagicMock(return_value=loc))
    monkeypatch.setattr(ulw_cli, "delete_pod", MagicMock(return_value={}))
    monkeypatch.setattr(ulw_cli, "wait_pod_ready", MagicMock(return_value=False))

    assert ulw_cli.main(["delete-pod", "target-pod", "--yes", "--wait-ready"]) == 1


def test_cli_delete_pod_no_wait_ready_skips_polling(cli_client, monkeypatch):
    from ulw import ulw as ulw_cli

    loc = PodLocation(app_name="my-app", namespace="ops", kind="Pod", name="target-pod")
    monkeypatch.setattr(ulw_cli, "find_pod", MagicMock(return_value=loc))
    monkeypatch.setattr(ulw_cli, "delete_pod", MagicMock(return_value={}))
    wait_mock = MagicMock()
    monkeypatch.setattr(ulw_cli, "wait_pod_ready", wait_mock)

    assert ulw_cli.main(["delete-pod", "target-pod", "--yes"]) == 0
    wait_mock.assert_not_called()
