#!/usr/bin/env python3
"""
Worktree Dashboard — manage worktree-orchestrator sessions across projects.

Usage:
    python tui.py

Requires: pip install rich
Config:   config.toml (adjacent to this script)
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Fix stdout encoding on Windows cp1252 consoles
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure") and sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from orchestrator import parse_toml, is_process_alive, get_alive_pids, IS_WINDOWS, DEFAULT_PROXY_PORT, DEFAULT_TLD, ensure_proxy_running


# ---------------------------------------------------------------------------
# Config & discovery
# ---------------------------------------------------------------------------

CONFIG_PATH = Path(__file__).parent / "config.toml"


def find_orchestrator_script() -> Path:
    """Find orchestrator.py: env var override, then adjacent to this script."""
    env = os.environ.get("ORCHESTRATOR_SCRIPT")
    if env:
        p = Path(env)
        if p.is_file():
            return p

    adjacent = Path(__file__).parent / "orchestrator.py"
    if adjacent.is_file():
        return adjacent

    print("Error: orchestrator.py not found.", file=sys.stderr)
    print("  Expected adjacent to tui.py or set ORCHESTRATOR_SCRIPT env var.", file=sys.stderr)
    sys.exit(1)


def load_dashboard_config() -> list[dict]:
    """Load ~/.config/worktree-dashboard.toml, return list of project dicts."""
    if not CONFIG_PATH.exists():
        print(f"Config not found: {CONFIG_PATH}", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f"Create it with:", file=sys.stderr)
        print(f"", file=sys.stderr)
        print(f'  [[projects]]', file=sys.stderr)
        print(f'  path = "/path/to/your-project"', file=sys.stderr)
        sys.exit(1)

    raw = parse_toml(CONFIG_PATH.read_text(encoding="utf-8"))
    projects = raw.get("projects", [])
    if not projects:
        print(f"No [[projects]] entries in {CONFIG_PATH}", file=sys.stderr)
        sys.exit(1)

    return [{"path": Path(p["path"]), "name": Path(p["path"]).name} for p in projects if "path" in p]


# ---------------------------------------------------------------------------
# Session data
# ---------------------------------------------------------------------------


def load_sessions(project_path: Path) -> dict:
    """Load sessions.json for a project. Returns {} on any error."""
    sessions_file = project_path / ".orchestrator" / "sessions.json"
    if not sessions_file.exists():
        return {}
    try:
        return json.loads(sessions_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}



def build_dashboard_data(projects: list[dict]) -> list[dict]:
    """Build the full data model for rendering.

    Returns a list of project dicts, each with:
    - name: str
    - path: Path
    - sessions: list of session dicts with server health annotated
    """
    # Pass 1: load all sessions and collect all PIDs for a single batch check
    project_sessions = []
    all_pids = set()
    for proj in projects:
        if not proj["path"].is_dir():
            project_sessions.append((proj, None))
            continue
        raw = load_sessions(proj["path"])
        project_sessions.append((proj, raw))
        for s in raw.values():
            for srv in s.get("servers", []):
                pid = srv.get("pid")
                if pid is not None:
                    all_pids.add(int(pid))

    alive_pids = get_alive_pids(all_pids)

    # Pass 2: build the dashboard data using the batch result
    dashboard = []
    for proj, raw_sessions in project_sessions:
        if raw_sessions is None:
            dashboard.append({"name": proj["name"], "path": proj["path"], "sessions": [], "warning": "directory not found"})
            continue

        sessions = []
        for key, s in raw_sessions.items():
            wt = s.get("worktree", "")
            wt_path = Path(wt) if wt else None
            worktree_exists = wt_path is not None and wt_path.exists() and (wt_path / ".git").exists()

            servers = []
            for srv in s.get("servers", []):
                pid = srv.get("pid")
                alive = (int(pid) in alive_pids) if pid is not None else False
                servers.append({
                    "name": srv.get("name", "?"),
                    "port": srv.get("port"),
                    "alive": alive,
                })

            # Determine effective status
            status = s.get("status", "unknown")
            if status == "running" and servers and all(not srv["alive"] for srv in servers):
                status = "dead"

            # Mark as ghost if worktree directory is gone
            if not worktree_exists:
                status = "ghost"

            sessions.append({
                "key": key,
                "branch": s.get("branch", "?"),
                "servers": servers,
                "status": status,
                "project_path": proj["path"],
                "project_name": proj["name"],
            })

        dashboard.append({"name": proj["name"], "path": proj["path"], "sessions": sessions})

    return dashboard


# ---------------------------------------------------------------------------
# Rich rendering
# ---------------------------------------------------------------------------

from rich.console import Console
from rich.table import Table
from rich.text import Text

console = Console()


def render_dashboard(data: list[dict], selected_idx: int, selectable_items: list[dict], status_msg: str = ""):
    """Render the full dashboard to the terminal."""
    console.clear()

    # Header
    w = min(console.width, 80)
    header = "[bold]Worktree Dashboard[/bold]"
    if status_msg:
        header += f"  {status_msg}"
    console.print(header)
    console.print("─" * w)

    if not data:
        console.print("\n[dim]No projects configured.[/dim]\n")
    else:
        for item_idx, item in enumerate(selectable_items):
            if item["type"] == "project":
                is_selected = item_idx == selected_idx
                marker = "▶" if is_selected else " "
                style = "reverse" if is_selected else ""
                console.print(f"\n  {marker} [bold cyan]{item['project_name']}[/bold cyan]", style=style, highlight=False)

                if item.get("warning"):
                    console.print(f"      [red]{item['warning']}[/red]")
                elif item_idx + 1 >= len(selectable_items) or selectable_items[item_idx + 1]["type"] == "project":
                    console.print("      [dim](no sessions)[/dim]")
            else:
                s = item
                is_selected = item_idx == selected_idx
                marker = "▶" if is_selected else " "
                style = "reverse" if is_selected else ""

                # Build server status string with hostname links
                srv_parts = []
                proj = s.get("project_name", "")
                sess = s.get("key", "")
                for srv in s["servers"]:
                    if srv["alive"]:
                        hostname = f"{sess}-{srv['name']}.{proj}.{DEFAULT_TLD}"
                        url = f"http://{hostname}:{DEFAULT_PROXY_PORT}"
                        srv_parts.append(f"[link={url}]{srv['name']}[/link] [green]✓[/green]")
                    else:
                        srv_parts.append(f"{srv['name']} [red]✗[/red]")
                srv_str = "  ".join(srv_parts)

                # Status color
                status_colors = {"running": "green", "stopped": "yellow", "dead": "red", "ghost": "dim red"}
                status_color = status_colors.get(s["status"], "white")
                status_str = f"[{status_color}]{s['status']}[/{status_color}]"

                branch = s['branch'][:16]
                if s["status"] == "ghost":
                    line = f"      {marker} {s['key']:3s} {branch:16s} [dim](worktree gone)[/dim]  {status_str}"
                else:
                    line = f"      {marker} {s['key']:3s} {branch:16s} {srv_str}  {status_str}"
                console.print(line, style=style, highlight=False)

    # Footer
    console.print("\n" + "─" * w)
    console.print("[dim]↑↓/jk[/dim] navigate  [dim]R[/dim] refresh  [dim]r[/dim] restart  [dim]x[/dim] kill  [dim]X[/dim] kill+remove  [dim]s[/dim] spawn  [dim]l[/dim] logs  [dim]c[/dim] cleanup  [dim]i[/dim] init  [dim]q[/dim] quit")


def build_selectable_items(data: list[dict]) -> list[dict]:
    """Flatten dashboard data into a list of selectable items (projects and sessions)."""
    items = []
    for proj in data:
        items.append({
            "type": "project",
            "project_name": proj["name"],
            "project_path": proj["path"],
            "warning": proj.get("warning"),
        })
        for s in proj["sessions"]:
            s["type"] = "session"
            items.append(s)
    return items


# ---------------------------------------------------------------------------
# Keypress handling
# ---------------------------------------------------------------------------

def get_key(timeout_s: float = 2.0) -> str | None:
    """Read a single keypress with timeout. Returns key name or None on timeout.

    Returns: 'UP', 'DOWN', 'ENTER', or a single character like 'r', 'q', etc.
    """
    if IS_WINDOWS:
        import msvcrt
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                ch = msvcrt.getch()
                if ch in (b'\x00', b'\xe0'):
                    # Special key — read scan code
                    if msvcrt.kbhit():
                        scan = msvcrt.getch()
                        if scan == b'H':
                            return 'UP'
                        elif scan == b'P':
                            return 'DOWN'
                    return None
                if ch == b'\r':
                    return 'ENTER'
                return ch.decode('utf-8', errors='replace')
            time.sleep(0.05)
        return None
    else:
        import select
        import tty
        import termios
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ready, _, _ = select.select([sys.stdin], [], [], timeout_s)
            if not ready:
                return None
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                # Escape sequence — try to read more
                ready2, _, _ = select.select([sys.stdin], [], [], 0.05)
                if ready2:
                    ch2 = sys.stdin.read(1)
                    if ch2 == '[':
                        ch3 = sys.stdin.read(1)
                        if ch3 == 'A':
                            return 'UP'
                        elif ch3 == 'B':
                            return 'DOWN'
                return None  # bare Escape
            if ch == '\r' or ch == '\n':
                return 'ENTER'
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def restore_terminal():
    """Restore terminal to cooked mode (Unix only, no-op on Windows)."""
    if not IS_WINDOWS:
        import termios
        fd = sys.stdin.fileno()
        # Get current settings and restore canonical mode
        settings = termios.tcgetattr(fd)
        settings[3] = settings[3] | termios.ECHO | termios.ICANON
        termios.tcsetattr(fd, termios.TCSADRAIN, settings)


def wait_for_key():
    """Block until a fresh key is pressed (drains any buffered input first)."""
    if IS_WINDOWS:
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getch()
        msvcrt.getch()
    else:
        import termios
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        get_key(timeout_s=300)


# ---------------------------------------------------------------------------
# Orchestrator subprocess helpers
# ---------------------------------------------------------------------------

def run_orchestrator(orch_script: Path, project_path: Path, args: list[str]) -> tuple[str, str, int]:
    """Run orchestrator.py with args, capturing output.

    Returns (stdout, stderr, returncode).
    """
    cmd = [sys.executable, str(orch_script)] + args
    result = subprocess.run(
        cmd,
        cwd=str(project_path),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    return result.stdout, result.stderr, result.returncode


def run_orchestrator_live(orch_script: Path, project_path: Path, args: list[str]) -> int:
    """Run orchestrator.py with args, streaming output live to the terminal.

    Returns the exit code.
    """
    cmd = [sys.executable, str(orch_script)] + args
    result = subprocess.run(
        cmd,
        cwd=str(project_path),
        stdin=subprocess.DEVNULL,
    )
    return result.returncode


def confirm(prompt: str) -> bool:
    """Show prompt, read single keypress, return True if 'y'."""
    console.print(prompt, end="")
    if IS_WINDOWS:
        import msvcrt
        ch = msvcrt.getch().decode("utf-8", errors="replace").lower()
    else:
        # Read in raw mode for single-keypress on Unix
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1).lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    console.print(ch)
    return ch == 'y'


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def do_restart(orch_script: Path, session: dict):
    """Restart the selected session."""
    restore_terminal()
    console.clear()
    name = session["key"]
    project = session["project_name"]

    if session["status"] == "ghost":
        console.print(f"[red]Cannot restart session {name} — worktree no longer exists.[/red]")
        console.print(f"[dim]Use [bold]c[/bold] to clean up ghost sessions, or [bold]s[/bold] to spawn a new one.[/dim]")
        console.print("\n[dim]Press any key to return...[/dim]")
        wait_for_key()
        return

    if not confirm(f"Restart session [bold]{name}[/bold] in [cyan]{project}[/cyan]? (y/n) "):
        console.print("[dim]Cancelled.[/dim]")
        time.sleep(0.5)
        return

    console.print(f"\n[dim]Restarting...[/dim]\n")
    stdout, stderr, rc = run_orchestrator(orch_script, session["project_path"], ["restart", name])
    console.print(stdout)
    if stderr:
        console.print(f"[red]{stderr}[/red]")
    console.print("\n[dim]Press any key to return...[/dim]")
    wait_for_key()


def do_kill(orch_script: Path, session: dict):
    """Kill the selected session."""
    restore_terminal()
    console.clear()
    name = session["key"]
    project = session["project_name"]

    if session["status"] == "ghost":
        console.print(f"[yellow]Session {name} is a ghost (worktree gone). Use [bold]c[/bold] to clean up or [bold]X[/bold] to remove it.[/yellow]")
        console.print("\n[dim]Press any key to return...[/dim]")
        wait_for_key()
        return

    if not confirm(f"Kill session [bold]{name}[/bold] in [cyan]{project}[/cyan]? (y/n) "):
        console.print("[dim]Cancelled.[/dim]")
        time.sleep(0.5)
        return

    console.print(f"\n[dim]Killing...[/dim]\n")
    stdout, stderr, rc = run_orchestrator(orch_script, session["project_path"], ["kill", name])
    console.print(stdout)
    if stderr:
        console.print(f"[red]{stderr}[/red]")
    console.print("\n[dim]Press any key to return...[/dim]")
    wait_for_key()


def do_kill_remove(orch_script: Path, session: dict):
    """Kill the selected session and remove its worktree."""
    restore_terminal()
    console.clear()
    name = session["key"]
    project = session["project_name"]

    if session["status"] == "ghost":
        # Ghost session — worktree already gone, route through orchestrator to clean up
        if not confirm(f"Remove ghost session [bold]{name}[/bold] from [cyan]{project}[/cyan]? (y/n) "):
            console.print("[dim]Cancelled.[/dim]")
            time.sleep(0.5)
            return
        stdout, stderr, rc = run_orchestrator(orch_script, session["project_path"], ["kill", name, "--remove"])
        if rc == 0:
            console.print(f"[green]Removed ghost session {name}.[/green]")
        else:
            console.print(f"[yellow]{stderr.strip() or stdout.strip()}[/yellow]")
        console.print("\n[dim]Press any key to return...[/dim]")
        wait_for_key()
        return

    if not confirm(f"Kill + remove session [bold]{name}[/bold] in [cyan]{project}[/cyan]? (y/n) "):
        console.print("[dim]Cancelled.[/dim]")
        time.sleep(0.5)
        return

    console.print(f"\n[dim]Killing and removing...[/dim]\n")
    stdout, stderr, rc = run_orchestrator(orch_script, session["project_path"], ["kill", name, "--remove"])
    console.print(stdout)
    if stderr:
        console.print(f"[red]{stderr}[/red]")
    console.print("\n[dim]Press any key to return...[/dim]")
    wait_for_key()


def do_spawn(orch_script: Path, data: list[dict], items: list[dict], selected_idx: int):
    """Spawn a new session in the currently selected project."""
    restore_terminal()
    console.clear()

    # Determine target project
    if items and 0 <= selected_idx < len(items):
        project_name = items[selected_idx]["project_name"]
        project_path = items[selected_idx]["project_path"]
    else:
        # No sessions — prompt user to pick a project
        projects_with_paths = [(proj["name"], proj["path"]) for proj in data if proj["path"].is_dir()]
        if not projects_with_paths:
            console.print("[red]No valid projects found.[/red]")
            time.sleep(1)
            return
        if len(projects_with_paths) == 1:
            project_name, project_path = projects_with_paths[0]
        else:
            console.print("[bold]Which project?[/bold]")
            for i, (name, _) in enumerate(projects_with_paths):
                console.print(f"  {i + 1}. {name}")
            try:
                choice = input("\nEnter number: ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(projects_with_paths):
                    project_name, project_path = projects_with_paths[idx]
                else:
                    console.print("Cancelled.")
                    time.sleep(0.5)
                    return
            except (ValueError, EOFError):
                console.print("Cancelled.")
                time.sleep(0.5)
                return

    console.print(f"Spawn in [cyan]{project_name}[/cyan]")
    try:
        name = input("Session name: ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("Cancelled.")
        time.sleep(0.5)
        return

    if not name:
        console.print("Cancelled.")
        time.sleep(0.5)
        return

    console.print(f"\n[dim]Spawning session {name}...[/dim]\n")
    run_orchestrator_live(orch_script, project_path, ["spawn", name])
    console.print("\n[dim]Press any key to return...[/dim]")
    wait_for_key()


def do_logs(orch_script: Path, session: dict):
    """Show logs for the selected session."""
    console.clear()
    name = session["key"]
    project = session["project_name"]

    if session["status"] == "ghost":
        console.print(f"[red]No logs available — session {name} is a ghost (worktree gone).[/red]")
        console.print("\n[dim]Press any key to return...[/dim]")
        wait_for_key()
        return

    console.print(f"[bold]Logs for session {name} ({project})[/bold]\n")

    stdout, stderr, rc = run_orchestrator(orch_script, session["project_path"], ["logs", name])
    console.print(stdout)
    if stderr:
        console.print(f"[red]{stderr}[/red]")
    console.print("\n[dim]Press any key to return...[/dim]")
    wait_for_key()


def do_init(orch_script: Path, data: list[dict], items: list[dict], selected_idx: int):
    """Initialize orchestrator in a project directory."""
    restore_terminal()
    console.clear()

    # Determine target project (same logic as spawn)
    if items and 0 <= selected_idx < len(items):
        project_name = items[selected_idx]["project_name"]
        project_path = items[selected_idx]["project_path"]
    else:
        projects_with_paths = [(proj["name"], proj["path"]) for proj in data if proj["path"].is_dir()]
        if not projects_with_paths:
            console.print("[red]No valid projects found.[/red]")
            time.sleep(1)
            return
        if len(projects_with_paths) == 1:
            project_name, project_path = projects_with_paths[0]
        else:
            console.print("[bold]Initialize orchestrator in which project?[/bold]")
            for i, (name, _) in enumerate(projects_with_paths):
                console.print(f"  {i + 1}. {name}")
            try:
                choice = input("\nEnter number: ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(projects_with_paths):
                    project_name, project_path = projects_with_paths[idx]
                else:
                    console.print("Cancelled.")
                    time.sleep(0.5)
                    return
            except (ValueError, EOFError):
                console.print("Cancelled.")
                time.sleep(0.5)
                return

    console.print(f"\n[dim]Initializing orchestrator in {project_name}...[/dim]\n")
    stdout, stderr, rc = run_orchestrator(orch_script, project_path, ["init"])
    console.print(stdout)
    if stderr:
        console.print(f"[red]{stderr}[/red]")
    console.print("\n[dim]Press any key to return...[/dim]")
    wait_for_key()


def do_cleanup(orch_script: Path, data: list[dict]):
    """Clean up ghost sessions across all projects."""
    restore_terminal()
    console.clear()

    # Count ghosts per project
    ghost_projects = []
    for proj in data:
        ghosts = [s for s in proj["sessions"] if s["status"] == "ghost"]
        if ghosts:
            ghost_projects.append((proj, ghosts))

    if not ghost_projects:
        console.print("[green]No ghost sessions to clean up.[/green]")
        console.print("\n[dim]Press any key to return...[/dim]")
        wait_for_key()
        return

    total = sum(len(g) for _, g in ghost_projects)
    console.print(f"[bold]Found {total} ghost session(s):[/bold]\n")
    for proj, ghosts in ghost_projects:
        console.print(f"  [cyan]{proj['name']}[/cyan]: {', '.join(g['key'] for g in ghosts)}")

    console.print()
    if not confirm(f"Remove all ghost sessions? (y/n) "):
        console.print("[dim]Cancelled.[/dim]")
        time.sleep(0.5)
        return

    removed = 0
    for proj, ghosts in ghost_projects:
        # Run orchestrator cleanup to also prune git worktrees
        stdout, stderr, rc = run_orchestrator(orch_script, proj["path"], ["cleanup", "--force"])
        console.print(stdout.strip())
        if stderr:
            console.print(f"[red]{stderr.strip()}[/red]")
        removed += len(ghosts)

    console.print(f"\n[green]Cleaned up {removed} ghost session(s).[/green]")
    console.print("\n[dim]Press any key to return...[/dim]")
    wait_for_key()


# ---------------------------------------------------------------------------
# Main event loop
# ---------------------------------------------------------------------------

def main():
    orch_script = find_orchestrator_script()
    projects = load_dashboard_config()
    ensure_proxy_running()

    selected_idx = 0
    status_msg = ""

    # Initial data load and render
    data = build_dashboard_data(projects)
    items = build_selectable_items(data)
    if items:
        selected_idx = min(selected_idx, len(items) - 1)
    render_dashboard(data, selected_idx, items)

    def refresh(show_indicator=True):
        nonlocal data, items, selected_idx, status_msg
        if show_indicator:
            status_msg = "[yellow]refreshing...[/yellow]"
            render_dashboard(data, selected_idx, items, status_msg)
        data = build_dashboard_data(projects)
        items = build_selectable_items(data)
        if not items:
            selected_idx = 0
        else:
            selected_idx = min(selected_idx, len(items) - 1)
        status_msg = "[green]refreshed[/green]"

    try:
        while True:
            key = get_key(timeout_s=300.0)

            if key is None:
                continue

            # Clear status on any keypress (except the refresh key itself)
            if key != 'R':
                status_msg = ""

            # Navigation
            if key in ('UP', 'k'):
                if items and selected_idx > 0:
                    selected_idx -= 1
            elif key in ('DOWN', 'j'):
                if items and selected_idx < len(items) - 1:
                    selected_idx += 1

            # Manual refresh
            elif key == 'R':
                refresh()

            # Actions — refresh data after each
            elif key in ('r', 'ENTER'):
                if items and items[selected_idx].get("type") == "session":
                    do_restart(orch_script, items[selected_idx])
                    refresh(show_indicator=False)
            elif key == 'x':
                if items and items[selected_idx].get("type") == "session":
                    do_kill(orch_script, items[selected_idx])
                    refresh(show_indicator=False)
            elif key == 'X':
                if items and items[selected_idx].get("type") == "session":
                    do_kill_remove(orch_script, items[selected_idx])
                    refresh(show_indicator=False)
            elif key == 's':
                do_spawn(orch_script, data, items, selected_idx)
                refresh(show_indicator=False)
            elif key == 'l':
                if items and items[selected_idx].get("type") == "session":
                    do_logs(orch_script, items[selected_idx])
            elif key == 'c':
                do_cleanup(orch_script, data)
                refresh(show_indicator=False)
            elif key == 'i':
                do_init(orch_script, data, items, selected_idx)
                refresh(show_indicator=False)

            # Quit
            elif key == 'q':
                break

            render_dashboard(data, selected_idx, items, status_msg)

    except KeyboardInterrupt:
        pass
    finally:
        if not IS_WINDOWS:
            restore_terminal()
        console.print("\n[dim]Dashboard closed.[/dim]")


if __name__ == "__main__":
    main()
