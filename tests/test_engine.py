import importlib, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import orchestrator  # noqa: E402

def test_module_imports():
    assert hasattr(orchestrator, "register_proxy_routes")

import pytest

@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ("ORCH_TLD", "ORCH_SCHEME", "ORCH_URL_PORT", "ORCH_PROXY_PORT"):
        monkeypatch.delenv(k, raising=False)

def test_host_default_localhost():
    assert orchestrator.host_for("b3", "frontend", "scout") == "b3-frontend.scout.localhost"

def test_host_primary_collapses():
    assert orchestrator.host_for("b3", "frontend", "scout", primary=True) == "b3.scout.localhost"

def test_url_default_has_proxy_port():
    assert orchestrator.proxy_url("b3", "backend", "scout") == "http://b3-backend.scout.localhost:1337"

def test_url_public_no_port(monkeypatch):
    monkeypatch.setenv("ORCH_TLD", "rookpine.com")
    monkeypatch.setenv("ORCH_SCHEME", "https")
    monkeypatch.setenv("ORCH_URL_PORT", "")
    assert orchestrator.proxy_url("b3", "frontend", "scout", primary=True) == "https://b3.scout.rookpine.com"

def test_routes_with_primary(tmp_path, monkeypatch):
    # primary frontend → bare host; backend → -backend host; no redundant -frontend
    monkeypatch.setattr(orchestrator, "PROXY_ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr(orchestrator, "PROXY_DIR", tmp_path)
    orchestrator.register_proxy_routes(
        "scout", "b3", {"frontend": 10241, "backend": 50022},
        primary_server="frontend")
    routes = orchestrator.load_proxy_routes()
    assert routes["b3.scout.localhost"] == 10241
    assert routes["b3-backend.scout.localhost"] == 50022
    assert "b3-frontend.scout.localhost" not in routes

def test_routes_no_primary_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "PROXY_ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr(orchestrator, "PROXY_DIR", tmp_path)
    orchestrator.register_proxy_routes("scout", "b3", {"backend": 50022, "frontend": 10241})
    routes = orchestrator.load_proxy_routes()
    assert routes["b3-backend.scout.localhost"] == 50022
    assert routes["b3-frontend.scout.localhost"] == 10241
    assert routes["b3.scout.localhost"] == 50022  # shortcut → first server (backend)
