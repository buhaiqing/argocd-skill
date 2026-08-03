"""Unit tests for scripts/argocd_api/client.py helpers and construction logic.

No network calls — all external dependencies are mocked.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from argocd_api.client import (
    FIND_POD_MAX_WORKERS,
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
    """Shell env token is picked up; validate=False keeps the test offline."""
    with patch.dict(os.environ, {
        "ARGOCD_SERVER": "https://argocd.example.com",
        "ARGOCD_AUTH_TOKEN": "env-tok",
    }, clear=True):
        client = ArgoCDClient.from_env(validate=False)
        assert client.token == "env-tok"
        assert client.server == "https://argocd.example.com"


def test_from_env_fails_no_credentials():
    with patch.dict(os.environ, {
        "ARGOCD_SERVER": "https://argocd.example.com",
    }, clear=True):
        with patch.object(Path, "is_file", return_value=False):
            with pytest.raises(ValueError, match="No valid ArgoCD credentials"):
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
    """A failing app must not abort the search — keyed by name, not call order,
    because trees are now fetched concurrently."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[
        {"metadata": {"name": "broken-app"}},
        {"metadata": {"name": "good-app"}},
    ])
    trees = {
        "good-app": {"nodes": [{"kind": "Pod", "name": "target-pod"}]},
    }

    def fake_tree(app_name):
        if app_name not in trees:
            raise RuntimeError("API error")
        return trees[app_name]

    client.get_application_resource_tree = MagicMock(side_effect=fake_tree)
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
    with patch.object(client._session, "request", return_value=mock_resp):
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


# ------------------------------------------------------------------
# Performance: HTTP session reuse
# ------------------------------------------------------------------

def test_client_creates_session():
    """A single requests.Session is created per client so batch callers reuse
    one TCP/TLS connection instead of re-handshaking per request."""
    client = ArgoCDClient(server="https://x.com", token="x")
    assert isinstance(client._session, requests.Session)


def test_request_uses_session():
    """Every request must go through the pooled session, not bare `requests`."""
    client = ArgoCDClient(server="https://x.com", token="tok-1", ssl_verify=False)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ok": True}
    client._session.request = MagicMock(return_value=mock_resp)

    resp = client._get("/x")

    assert resp.json() == {"ok": True}
    client._session.request.assert_called_once()
    args, kwargs = client._session.request.call_args
    assert args[0] == "GET"
    assert args[1] == "https://x.com/api/v1/x"
    assert kwargs["headers"]["Authorization"] == "Bearer tok-1"
    assert kwargs["verify"] is False


# ------------------------------------------------------------------
# Performance: find_pod concurrency
# ------------------------------------------------------------------

def _apps(*names: str) -> list[dict]:
    return [{"metadata": {"name": n}} for n in names]


def test_find_pod_uses_threadpool():
    """Resource trees for multiple apps must be fetched concurrently, not
    one-by-one on the calling thread."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=_apps(*[f"app-{i}" for i in range(6)]))

    seen_threads: set[str] = set()
    lock = threading.Lock()
    barrier = threading.Barrier(2, timeout=5)

    def fake_tree(app_name):
        with lock:
            seen_threads.add(threading.current_thread().name)
        # Force at least two fetches to overlap in time; if the pool were
        # serial this would time out via BrokenBarrierError.
        try:
            barrier.wait()
        except threading.BrokenBarrierError:
            pass
        return {"nodes": []}

    client.get_application_resource_tree = MagicMock(side_effect=fake_tree)

    assert client.find_pod("nope") is None
    assert client.get_application_resource_tree.call_count == 6
    assert len(seen_threads) >= 2, f"expected concurrent fetches, saw threads: {seen_threads}"
    assert threading.current_thread().name not in seen_threads


def test_find_pod_max_workers_cap():
    """Concurrency stays bounded by FIND_POD_MAX_WORKERS even with many apps,
    and no app is silently dropped."""
    app_count = 20
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=_apps(*[f"app-{i}" for i in range(app_count)]))

    lock = threading.Lock()
    active = 0
    peak = 0

    def fake_tree(app_name):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)  # simulate IO so overlap is observable
        with lock:
            active -= 1
        return {"nodes": []}

    client.get_application_resource_tree = MagicMock(side_effect=fake_tree)

    assert client.find_pod("nope") is None
    assert client.get_application_resource_tree.call_count == app_count
    fetched = {c.args[0] for c in client.get_application_resource_tree.call_args_list}
    assert fetched == {f"app-{i}" for i in range(app_count)}
    assert peak <= FIND_POD_MAX_WORKERS, f"peak concurrency {peak} exceeded cap {FIND_POD_MAX_WORKERS}"


def test_find_pod_deterministic_on_duplicate_pod():
    """When two apps expose the same pod name, the winner follows
    list_applications order — not whichever future completes first."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=_apps("first-app", "second-app"))

    def fake_tree(app_name):
        # Make the *second* app finish first to prove ordering is not
        # driven by completion order.
        if app_name == "first-app":
            time.sleep(0.05)
        return {"nodes": [{"kind": "Pod", "name": "dup-pod", "namespace": app_name}]}

    client.get_application_resource_tree = MagicMock(side_effect=fake_tree)

    node = client.find_pod("dup-pod")
    assert node is not None
    assert node["app_name"] == "first-app"


def test_find_pod_empty_app_list():
    """No applications ⇒ short-circuit without spinning up the pool."""
    client = ArgoCDClient(server="https://x.com", token="x")
    client.list_applications = MagicMock(return_value=[])
    client.get_application_resource_tree = MagicMock()

    assert client.find_pod("any-pod") is None
    client.get_application_resource_tree.assert_not_called()


# ------------------------------------------------------------------
# Performance: from_env validate short-circuit
# ------------------------------------------------------------------

def test_from_env_validate_false_skips_network():
    """validate=False must not issue the /account probe."""
    probe = MagicMock(side_effect=AssertionError("_validate_token must not be called"))
    env = {
        "ARGOCD_SERVER": "https://argocd.example.com",
        "ARGOCD_AUTH_TOKEN": "env-tok",
    }
    with patch.dict(os.environ, env, clear=True), \
            patch.object(ArgoCDClient, "_validate_token", probe):
        client = ArgoCDClient.from_env(validate=False)

    assert client.token == "env-tok"
    probe.assert_not_called()


def test_from_env_validate_true_probes():
    """validate=True (the default) probes the token exactly once."""
    probe = MagicMock(return_value=True)
    env = {
        "ARGOCD_SERVER": "https://argocd.example.com",
        "ARGOCD_AUTH_TOKEN": "env-tok",
    }
    with patch.dict(os.environ, env, clear=True), \
            patch.object(ArgoCDClient, "_validate_token", probe):
        client = ArgoCDClient.from_env(validate=True)

    assert client.token == "env-tok"
    probe.assert_called_once()