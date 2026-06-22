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

FREE = ("              total        used        free      shared  buff/cache   available\n"
        "Mem:           7936        3280        3566           4        1399        4655\n"
        "Swap:             0           0           0\n")

def test_parse_free_mb():
    m = orchestrator.parse_free_mb(FREE)
    assert m == {"total_mb":7936,"used_mb":3280,"available_mb":4655,
                 "swap_total_mb":0,"swap_used_mb":0}

def test_build_status_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "find_repo_root", lambda: tmp_path)
    (tmp_path / ".orchestrator").mkdir()
    (tmp_path / ".orchestrator" / "sessions.json").write_text(
        '{"3":{"branch":"b3","status":"running","worktree":"/x",'
        '"servers":[{"name":"frontend","port":10241,"pid":1}],"ports":{"frontend":10241}}}')
    (tmp_path / ".orchestrator.toml").write_text(
        "[servers.frontend]\nstart_command=\"x\"\nprimary=true\n")
    monkeypatch.setattr(orchestrator, "is_process_alive", lambda pid: False)
    # Force memory to None so the shape assertion is host-independent (this box
    # has a working `free`, so read_system_memory() would otherwise return real data).
    monkeypatch.setattr(orchestrator, "read_system_memory", lambda: None)
    data = orchestrator.build_status(tmp_path)
    s = data["sessions"]["3"]["servers"][0]
    assert s["url"] == f"http://3.{tmp_path.name}.localhost:1337"
    assert s["up"] is False and data["memory"] is None

from datetime import datetime, timezone, timedelta

def test_should_record_access():
    now = datetime(2026,6,18,12,0,30,tzinfo=timezone.utc)
    assert orchestrator.should_record_access(None, now) is True
    recent = (now - timedelta(seconds=10)).isoformat()
    assert orchestrator.should_record_access(recent, now) is False
    old = (now - timedelta(seconds=40)).isoformat()
    assert orchestrator.should_record_access(old, now) is True

def test_substitute_url_primary_vs_nonprimary():
    pm = {"frontend": 10241, "backend": 50022}
    out = orchestrator.substitute_vars("{frontend.url} {backend.url}", pm,
                                       project="scout", session="3",
                                       primary_server="frontend")
    assert out == "http://3.scout.localhost:1337 http://3-backend.scout.localhost:1337"

def test_substitute_url_honors_env(monkeypatch):
    monkeypatch.setenv("ORCH_TLD", "rookpine.com")
    monkeypatch.setenv("ORCH_SCHEME", "https")
    monkeypatch.setenv("ORCH_URL_PORT", "")
    out = orchestrator.substitute_vars("{frontend.url}", {"frontend": 1},
                                       project="scout", session="3",
                                       primary_server="frontend")
    assert out == "https://3.scout.rookpine.com"

def test_unregister_honors_env_tld(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "PROXY_ROUTES_FILE", tmp_path / "routes.json")
    monkeypatch.setattr(orchestrator, "PROXY_DIR", tmp_path)
    monkeypatch.setenv("ORCH_TLD", "rookpine.com")
    orchestrator.register_proxy_routes("scout", "3", {"frontend": 1, "backend": 2},
                                       primary_server="frontend")
    assert "3.scout.rookpine.com" in orchestrator.load_proxy_routes()
    orchestrator.unregister_proxy_routes("scout", "3")
    assert orchestrator.load_proxy_routes() == {}

# ─── kill: reap the whole process group, not just the wrapper PID ──────────
import subprocess
import signal as _signal
import time as _time

@pytest.mark.skipif(orchestrator.IS_WINDOWS, reason="POSIX process-group semantics")
def test_kill_process_reaps_detached_child_group():
    # `sh -c 'sleep 30 & echo $!; wait'` forks a child `sleep` (PID echoed) and
    # waits — the wrapper+server shape that start_new_session=True produces.
    # Killing only the recorded wrapper PID orphans the child; kill_process must
    # reap the whole group so the detached child dies too. The child reparents to
    # init (not our child), so is_process_alive is reliable once it's gone.
    p = subprocess.Popen(["sh", "-c", "sleep 30 & echo $!; wait"],
                         stdout=subprocess.PIPE, text=True, start_new_session=True)
    try:
        child_pid = int(p.stdout.readline().strip())
        assert orchestrator.is_process_alive(child_pid)
        orchestrator.kill_process(p.pid)
        deadline = _time.time() + 6
        while orchestrator.is_process_alive(child_pid) and _time.time() < deadline:
            _time.sleep(0.1)
        assert not orchestrator.is_process_alive(child_pid), \
            "detached child survived — kill_process did not reap the group"
    finally:
        try:
            os.killpg(os.getpgid(p.pid), _signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        try:
            p.wait(timeout=5)
        except Exception:
            pass

@pytest.mark.skipif(orchestrator.IS_WINDOWS, reason="POSIX-only safety guard")
def test_kill_process_non_group_leader_kills_only_pid():
    # A PID that is NOT its own group leader shares a group (e.g. with the
    # orchestrator). kill_process must signal only that PID — never killpg the
    # shared group, which would kill siblings/the parent (this very test process
    # shares the group, so a killpg bug would terminate the test runner).
    p = subprocess.Popen(["sleep", "30"])  # no start_new_session -> shares our group
    try:
        assert os.getpgid(p.pid) != p.pid  # not a group leader
        orchestrator.kill_process(p.pid)
        deadline = _time.time() + 6
        while p.poll() is None and _time.time() < deadline:
            _time.sleep(0.1)
        assert p.returncode is not None and p.returncode < 0  # killed by a signal
    finally:
        try:
            p.kill(); p.wait(timeout=5)
        except Exception:
            pass

# ─── post-kill verification: parse listeners + detect stragglers ───────────
SS_OUT = (
    'LISTEN 0      128          0.0.0.0:50022      0.0.0.0:*    users:(("dart:server.dar",pid=9302,fd=10))\n'
    'LISTEN 0      4096               *:443              *:*    users:(("caddy",pid=205006,fd=7))\n'
    'LISTEN 0      128          127.0.0.1:1337     0.0.0.0:*    users:(("python3",pid=9304,fd=6))\n'
    'LISTEN 0      4096            [::]:22            [::]:*    users:(("sshd",pid=1256,fd=4),("systemd",pid=1,fd=239))\n'
)

def test_parse_ss_listeners():
    m = orchestrator.parse_ss_listeners(SS_OUT)
    assert m[50022] == {9302}
    assert m[443] == {205006}
    assert m[1337] == {9304}
    assert m[22] == {1256, 1}  # multiple holders collected

def test_verify_servers_stopped_flags_straggler(monkeypatch):
    monkeypatch.setattr(orchestrator, "listening_ports_with_pids",
                        lambda: {50022: {9302}})
    servers = [{"name": "backend", "port": 50022}, {"name": "frontend", "port": 33737}]
    stragglers = orchestrator.verify_servers_stopped(servers)
    assert stragglers == [("backend", 50022, {9302})]

def test_verify_servers_stopped_all_clear(monkeypatch):
    monkeypatch.setattr(orchestrator, "listening_ports_with_pids", lambda: {})
    servers = [{"name": "backend", "port": 50022}]
    assert orchestrator.verify_servers_stopped(servers) == []

# ─── rss: count the whole subtree, not just the shell wrapper PID ──────────
PS_TREE = (
    "  214116       1    1940\n"   # backend wrapper (sh)
    "  214117  214116  246744\n"   # its real dart server (the memory lives here)
    "  214118       1    1900\n"   # unrelated frontend wrapper
    "  214119  214118  101000\n"   # its flutter child
    "      1       0    5000\n"
)

def test_sum_descendant_rss_mb_counts_real_child():
    # the recorded wrapper PID (214116) reports ~2MB on its own; the real RSS is
    # the dart child — summing the subtree gives the true footprint.
    assert orchestrator.sum_descendant_rss_mb(214116, PS_TREE) == round((1940 + 246744) / 1024)

def test_sum_descendant_rss_mb_leaf_and_unknown():
    assert orchestrator.sum_descendant_rss_mb(214117, PS_TREE) == round(246744 / 1024)
    assert orchestrator.sum_descendant_rss_mb(999999, PS_TREE) is None
