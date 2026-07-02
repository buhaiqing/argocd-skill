"""Unit tests for scripts/argocd_api/client.py helpers and construction logic.

No network calls — all external dependencies are mocked.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from argocd_api.client import (
    ArgoCDClient,
    _load_dotenv,
    _token_from_argocd_config,
)


# ------------------------------------------------------------------
# _load_dotenv
# ------------------------------------------------------------------

def test_load_dotenv_sets_vars(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ARGOCD_SERVER=https://argocd.example.com\nARGOCD_USERNAME=ops\n")
    with patch.dict(os.environ, {}, clear=True):
        _load_dotenv(env)
        assert os.environ["ARGOCD_SERVER"] == "https://argocd.example.com"
        assert os.environ["ARGOCD_USERNAME"] == "ops"


def test_load_dotenv_skips_comments_and_blanks(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# comment\n\nKEY=val\n")
    _load_dotenv(env)
    assert os.environ.get("KEY") == "val"
    del os.environ["KEY"]
    # Key not present for comment/blank lines
    assert "comment" not in os.environ


def test_load_dotenv_does_not_override(tmp_path):
    os.environ["EXISTING"] = "original"
    env = tmp_path / ".env"
    env.write_text("EXISTING=should_not_override\n")
    _load_dotenv(env)
    assert os.environ["EXISTING"] == "original"
    del os.environ["EXISTING"]


def test_load_dotenv_strips_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text('HOST="localhost"\nPORT=\'8080\'\n')
    _load_dotenv(env)
    assert os.environ["HOST"] == "localhost"
    assert os.environ["PORT"] == "8080"
    del os.environ["HOST"]
    del os.environ["PORT"]


# ------------------------------------------------------------------
# _token_from_argocd_config
# ------------------------------------------------------------------

def test_config_file_not_found_returns_none():
    with patch.object(Path, "is_file", return_value=False):
        assert _token_from_argocd_config() is None


def test_config_empty_users_returns_none():
    cfg = {"users": []}
    with patch.object(Path, "is_file", return_value=True):
        with patch.object(Path, "read_text", return_value="users: []"):
            with patch("yaml.safe_load", return_value=cfg):
                assert _token_from_argocd_config() is None


def test_config_matching_host_returns_token():
    cfg = {
        "users": [
            {"name": "argocd.hd123.com", "auth-token": "tok-123"},
        ]
    }
    with patch.object(Path, "is_file", return_value=True):
        with patch.object(Path, "read_text", return_value=""):
            with patch("yaml.safe_load", return_value=cfg):
                token = _token_from_argocd_config("https://argocd.hd123.com/dnet-int")
                assert token == "tok-123"


def test_config_fallback_any_token():
    cfg = {
        "users": [
            {"name": "some-other-server", "auth-token": "tok-fallback"},
        ]
    }
    with patch.object(Path, "is_file", return_value=True):
        with patch.object(Path, "read_text", return_value=""):
            with patch("yaml.safe_load", return_value=cfg):
                token = _token_from_argocd_config("https://unknown.example.com")
                assert token == "tok-fallback"


def test_config_prefers_username_host_match():
    """When multiple users exist, prefer the one with hostname in name."""
    cfg = {
        "users": [
            {"name": "other-server", "auth-token": "tok-other"},
            {"name": "argocd.hd123.com", "auth-token": "tok-match"},
            {"name": "third", "auth-token": "tok-third"},
        ]
    }
    with patch.object(Path, "is_file", return_value=True):
        with patch.object(Path, "read_text", return_value=""):
            with patch("yaml.safe_load", return_value=cfg):
                token = _token_from_argocd_config("https://argocd.hd123.com")
                assert token == "tok-match"


# ------------------------------------------------------------------
# ArgoCDClient construction
# ------------------------------------------------------------------

def test_client_url_construction():
    client = ArgoCDClient(server="https://argocd.example.com", token="x")
    assert client._url("/applications") == "https://argocd.example.com/api/v1/applications"
    assert client._url("/session") == "https://argocd.example.com/api/v1/session"


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
    assert "Authorization" not in h or h.get("Authorization") == "Bearer None"
    # Check the conditional in _headers — skip if None
    # Actually the code does: if self.token — so with None it should not add
    assert "Authorization" not in h


def test_from_env_missing_server():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="ARGOCD_SERVER"):
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
        with patch.object(Path, "is_file", return_value=False):
            with pytest.raises(ValueError, match="No ArgoCD credentials"):
                ArgoCDClient.from_env()


# ------------------------------------------------------------------
# find_pod
# ------------------------------------------------------------------

def test_find_pod_returns_node_when_found():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "my-app"}},
    ])
    client.get_application_resource_tree = MagicMock(return_value={
        "nodes": [
            {"kind": "Pod", "name": "my-pod-abc", "namespace": "ops"},
            {"kind": "Service", "name": "my-svc"},
        ]
    })
    node = client.find_pod("my-pod-abc")
    assert node is not None
    assert node["app_name"] == "my-app"
    assert node["kind"] == "Pod"
    assert node["name"] == "my-pod-abc"


def test_find_pod_returns_none_when_missing():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "my-app"}},
    ])
    client.get_application_resource_tree = MagicMock(return_value={
        "nodes": [{"kind": "Service", "name": "my-svc"}]
    })
    assert client.find_pod("missing-pod") is None


def test_find_pod_skips_app_errors():
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "broken-app"}},
        {"metadata": {"name": "good-app"}},
    ])
    client.get_application_resource_tree = MagicMock(side_effect=[
        RuntimeError("API error"),
        {"nodes": [{"kind": "Pod", "name": "target-pod"}]},
    ])
    node = client.find_pod("target-pod")
    assert node is not None
    assert node["app_name"] == "good-app"


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------

def test_4xx_raises_runtime_error():
    client = ArgoCDClient(server="https://x.com", token="x")
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.json.return_value = {"message": "not found"}
    with patch("requests.request", return_value=mock_resp):
        with pytest.raises(RuntimeError, match="404"):
            client._get("/applications/nope")


def test_login_missing_token_raises():
    client = ArgoCDClient(server="https://x.com")
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"message": "ok"}  # no token key
    with patch.object(client, "_post", return_value=mock_resp):
        with pytest.raises(ValueError, match="Login response missing token"):
            client.login("user", "pass")


# ------------------------------------------------------------------
# New methods
# ------------------------------------------------------------------

def test_create_application_calls_post():
    client = ArgoCDClient(server="https://x.com", token="x")
    client._post = MagicMock(return_value=MagicMock(json=lambda: {"name": "new-app"}))
    result = client.create_application({"metadata": {"name": "new-app"}})
    assert result["name"] == "new-app"
    client._post.assert_called_once()


def test_delete_application_calls_delete():
    client = ArgoCDClient(server="https://x.com", token="x")
    client._delete = MagicMock(return_value=MagicMock(json=lambda: {}))
    client.delete_application("my-app")
    client._delete.assert_called_once()


def test_rollback_application_calls_post():
    client = ArgoCDClient(server="https://x.com", token="x")
    client._post = MagicMock(return_value=MagicMock(json=lambda: {"status": "ok"}))
    result = client.rollback_application("my-app", 42)
    assert result["status"] == "ok"


def test_list_projects_returns_items():
    client = ArgoCDClient(server="https://x.com", token="x")
    client._get = MagicMock(return_value=MagicMock(json=lambda: {"items": [{"name": "default"}]}))
    items = client.list_projects()
    assert len(items) == 1
    assert items[0]["name"] == "default"


def test_get_account_info():
    client = ArgoCDClient(server="https://x.com", token="x")
    client._get = MagicMock(return_value=MagicMock(json=lambda: {"loggedIn": True}))
    info = client.get_account_info()
    assert info["loggedIn"] is True


def test_list_clusters_returns_items():
    client = ArgoCDClient(server="https://x.com", token="x")
    client._get = MagicMock(return_value=MagicMock(json=lambda: {"items": []}))
    assert client.list_clusters() == []


def test_list_repositories_returns_items():
    client = ArgoCDClient(server="https://x.com", token="x")
    client._get = MagicMock(return_value=MagicMock(json=lambda: {"items": []}))
    assert client.list_repositories() == []


def test_get_application_manifests_multi_document():
    client = ArgoCDClient(server="https://x.com", token="x")
    doc1 = '{"apiVersion":"v1","kind":"Service","metadata":{"name":"svc1"}}'
    doc2 = '{"apiVersion":"apps/v1","kind":"Deployment","metadata":{"name":"dep1"}}'
    client._get = MagicMock(return_value=MagicMock(json=lambda: {"manifests": [doc1, doc2]}))
    result = client.get_application_manifests("my-app")
    assert len(result) == 2
    assert result[0]["kind"] == "Service"
    assert result[1]["kind"] == "Deployment"


def test_get_application_manifests_empty():
    client = ArgoCDClient(server="https://x.com", token="x")
    client._get = MagicMock(return_value=MagicMock(json=lambda: {"manifests": []}))
    result = client.get_application_manifests("my-app")
    assert result == []


def test_get_application_manifests_invalid_json_in_list():
    client = ArgoCDClient(server="https://x.com", token="x")
    good = '{"apiVersion":"v1","kind":"ConfigMap","metadata":{"name":"cm1"}}'
    client._get = MagicMock(return_value=MagicMock(json=lambda: {"manifests": [good, "not-valid-json"]}))
    with pytest.raises(Exception):
        client.get_application_manifests("my-app")