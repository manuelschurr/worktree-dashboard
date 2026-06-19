import importlib, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import orchestrator  # noqa: E402

def test_module_imports():
    assert hasattr(orchestrator, "register_proxy_routes")
