"""Unit tests for scripts/ulw/client.py and scripts/ulw/commands.py.

No network calls — all external dependencies are mocked.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ulw.client import ArgoCDClient
from ulw.commands import delete_pod, find_pod, PodLocation

# The canonical client lives in argocd_api.client; ulw re-exports it.
# from_env is inherited from the base class, so patch the base module that
# the resolved import path actually uses (argocd_api.client or
# scripts.argocd_api.client — same file, different sys.modules key).
import sys

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
    mock_request.return_value = MagicMock(status_code=200, json=lambda: {})
    client = ArgoCDClient(server="https://x.com", token="t")
    client._get("/applications")
    assert mock_request.call_args[0][1] == "https://x.com/api/v1/applications"


@patch("argocd_api.client.requests.request")
def test_post_uses_correct_url(mock_request):
    mock_request.return_value = MagicMock(status_code=200, json=lambda: {})
    client = ArgoCDClient(server="https://x.com", token="t")
    client._post("/applications/my-app/sync", json={})
    assert mock_request.call_args[0][1] == "https://x.com/api/v1/applications/my-app/sync"


@patch("argocd_api.client.requests.request")
def test_delete_uses_correct_url(mock_request):
    mock_request.return_value = MagicMock(status_code=200, json=lambda: {})
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
        json=lambda: {}
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
    client._delete = MagicMock(return_value=MagicMock(json=lambda: {}))
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
    client._delete = MagicMock(return_value=MagicMock(json=lambda: {}))
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
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "my-app"}},
    ])
    client.get_application_managed_resources = MagicMock(return_value=[
        {
            "kind": "Pod",
            "apiVersion": "v1",
            "liveState": {
                "metadata": {"name": "target-pod", "namespace": "ops"},
                "kind": "Pod",
                "apiVersion": "v1",
            },
        },
    ])

    loc = find_pod(client, "target-pod")
    assert loc is not None
    assert loc.app_name == "my-app"
    assert loc.namespace == "ops"
    assert loc.kind == "Pod"
    assert loc.name == "target-pod"


def test_find_pod_detects_api_version_group():
    """When apiVersion contains a group (apps/v1), extract group and version."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "my-app"}},
    ])
    client.get_application_managed_resources = MagicMock(return_value=[
        {
            "kind": "Deployment",
            "apiVersion": "apps/v1",
            "liveState": {
                "metadata": {"name": "my-deploy", "namespace": "prod"},
                "kind": "Deployment",
                "apiVersion": "apps/v1",
            },
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
    client.get_application_managed_resources = MagicMock(return_value=[
        {"kind": "Service", "liveState": {"metadata": {"name": "my-svc"}}},
    ])

    assert find_pod(client, "missing-pod") is None


def test_find_pod_skips_app_errors():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "broken-app"}},
        {"metadata": {"name": "good-app"}},
    ])
    client.get_application_managed_resources = MagicMock(side_effect=[
        RuntimeError("API error"),
        [
            {
                "kind": "Pod",
                "apiVersion": "v1",
                "liveState": {
                    "metadata": {"name": "target-pod", "namespace": "ops"},
                    "kind": "Pod",
                    "apiVersion": "v1",
                },
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
    client.get_application_managed_resources = MagicMock(return_value=[])
    assert find_pod(client, "anything") is None


# ======================================================================
# commands.delete_pod
# ======================================================================

def test_delete_pod_calls_client():
    client = ArgoCDClient(server="https://x.com", token="x")
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
    client = ArgoCDClient(server="https://x.com", token="x")
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