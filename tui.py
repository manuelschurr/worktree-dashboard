#!/usr/bin/env python3
"""
Worktree Dashboard — manage worktree-orchestrator sessions across projects.

Usage:
    python tui.py

Requires: pip install rich
Config:   ~/.config/worktree-dashboard.toml
"""

import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

# Fix stdout encoding on Windows cp1252 consoles
if hasattr(sys.stdout, "reconfigure") and sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure") and sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

IS_WINDOWS = platform.system() == "Windows"

# ---------------------------------------------------------------------------
# TOML parser (stdlib-only, supports nested tables and [[array]] syntax)
# ---------------------------------------------------------------------------

def parse_toml(text: str) -> dict:
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        pass

    result = {}
    current_path = []
    current_array_key = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # [[array.of.tables]]
        if line.startswith("[[") and line.endswith("]]"):
            section = line[2:-2].strip()
            parts = section.split(".")
            current_array_key = parts[-1]
            parent = result
            for part in parts[:-1]:
                if part not in parent:
                    parent[part] = {}
                parent = parent[part]
            if current_array_key not in parent:
                parent[current_array_key] = []
            parent[current_array_key].append({})
            current_path = parts
            continue

        # [table]
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            current_path = section.split(".")
            current_array_key = None
            d = result
            for part in current_path:
                if part not in d:
                    d[part] = {}
                elif isinstance(d[part], list):
                    # nested table inside array item — target last element
                    pass
                d = d[part] if not isinstance(d[part], list) else d[part][-1]
            continue

        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Strip inline comments
            if "#" in val:
                in_str = False
                for i, ch in enumerate(val):
                    if ch == '"':
                        in_str = not in_str
                    elif ch == "#" and not in_str:
                        val = val[:i].strip()
                        break
            if val.startswith('"') and val.endswith('"'):
                parsed = val[1:-1]
            elif val.isdigit():
                parsed = int(val)
            elif val.lower() in ("true", "false"):
                parsed = val.lower() == "true"
            else:
                parsed = val

            # Navigate to the correct target dict
            d = result
            for part in current_path:
                if isinstance(d.get(part), list):
                    d = d[part][-1]
                else:
                    d = d[part]
            d[key] = parsed

    return result


# ---------------------------------------------------------------------------
# Config & discovery
# ---------------------------------------------------------------------------

CONFIG_PATH = Path.home() / ".config" / "worktree-dashboard.toml"


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
        print(f'  path = "C:/Users/you/code/your-project"', file=sys.stderr)
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

def is_process_alive(pid: int) -> bool:
    """Check if a process is running."""
    try:
        if IS_WINDOWS:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True
            )
            return str(pid) in result.stdout
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError):
        return False


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
    dashboard = []
    for proj in projects:
        if not proj["path"].is_dir():
            dashboard.append({"name": proj["name"], "path": proj["path"], "sessions": [], "warning": "directory not found"})
            continue

        raw_sessions = load_sessions(proj["path"])
        sessions = []
        for key, s in raw_sessions.items():
            # Filter out ghost sessions (killed+removed but still in sessions.json)
            wt = s.get("worktree", "")
            if s.get("status") == "stopped" and wt and not Path(wt).exists():
                continue

            servers = []
            for srv in s.get("servers", []):
                pid = srv.get("pid")
                alive = is_process_alive(pid) if pid else False
                servers.append({
                    "name": srv.get("name", "?"),
                    "port": srv.get("port"),
                    "alive": alive,
                })

            # Determine effective status
            status = s.get("status", "unknown")
            if status == "running" and servers and all(not srv["alive"] for srv in servers):
                status = "dead"

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


def render_dashboard(data: list[dict], selected_idx: int, selectable_items: list[dict], auto_refresh: bool):
    """Render the full dashboard to the terminal."""
    console.clear()

    # Header
    refresh_text = "[green]ON[/green]" if auto_refresh else "[red]OFF[/red]"
    console.print(f"[bold]Worktree Dashboard[/bold]                            Auto-refresh: {refresh_text}")
    console.print("─" * console.width)

    if not any(proj["sessions"] for proj in data):
        console.print("\n[dim]No sessions found across any project.[/dim]\n")
    else:
        item_idx = 0
        for proj in data:
            console.print(f"\n[bold cyan]{proj['name']}[/bold cyan]")

            if proj.get("warning"):
                console.print(f"  [red]{proj['warning']}[/red]")

            if not proj["sessions"]:
                console.print("  [dim](no sessions)[/dim]")
                continue

            for s in proj["sessions"]:
                is_selected = item_idx == selected_idx
                marker = "▶" if is_selected else " "
                style = "reverse" if is_selected else ""

                # Build server status string (format: "backend ✓ 64785")
                srv_parts = []
                for srv in s["servers"]:
                    if srv["alive"]:
                        srv_parts.append(f"{srv['name']} [green]✓[/green] {srv['port']}")
                    else:
                        srv_parts.append(f"{srv['name']} [red]✗[/red]")
                srv_str = "  ".join(srv_parts)

                # Status color
                status_colors = {"running": "green", "stopped": "yellow", "dead": "red"}
                status_color = status_colors.get(s["status"], "white")
                status_str = f"[{status_color}]{s['status']}[/{status_color}]"

                line = f"  {marker} {s['key']:4s} {s['branch']:20s} {srv_str}   {status_str}"
                console.print(line, style=style, highlight=False)
                item_idx += 1

    # Footer
    console.print("\n" + "─" * console.width)
    console.print("[dim]↑↓/jk[/dim] navigate  [dim]r[/dim] restart  [dim]x[/dim] kill  [dim]X[/dim] kill+remove  [dim]s[/dim] spawn  [dim]l[/dim] logs  [dim]i[/dim] init  [dim]a[/dim] auto-refresh  [dim]q[/dim] quit")


def build_selectable_items(data: list[dict]) -> list[dict]:
    """Flatten dashboard data into a list of selectable session items."""
    items = []
    for proj in data:
        for s in proj["sessions"]:
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
    """Block until any key is pressed."""
    if IS_WINDOWS:
        import msvcrt
        msvcrt.getch()
    else:
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
    run_orchestrator_live(orch_script, project_path, ["spawn", name, "--no-claude"])
    console.print("\n[dim]Press any key to return...[/dim]")
    wait_for_key()


def do_logs(orch_script: Path, session: dict):
    """Show logs for the selected session."""
    console.clear()
    name = session["key"]
    project = session["project_name"]
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


# ---------------------------------------------------------------------------
# Main event loop
# ---------------------------------------------------------------------------

def main():
    orch_script = find_orchestrator_script()
    projects = load_dashboard_config()

    selected_idx = 0
    auto_refresh = True

    # Initial data load and render
    data = build_dashboard_data(projects)
    items = build_selectable_items(data)
    if items:
        selected_idx = min(selected_idx, len(items) - 1)
    render_dashboard(data, selected_idx, items, auto_refresh)

    try:
        while True:
            key = get_key(timeout_s=2.0 if auto_refresh else 300.0)

            # On timeout (auto-refresh) or any key, reload data
            data = build_dashboard_data(projects)
            items = build_selectable_items(data)

            if not items:
                selected_idx = 0
            else:
                selected_idx = min(selected_idx, len(items) - 1)

            if key is None:
                # Auto-refresh tick — just re-render
                render_dashboard(data, selected_idx, items, auto_refresh)
                continue

            # Navigation
            if key in ('UP', 'k'):
                if items and selected_idx > 0:
                    selected_idx -= 1
            elif key in ('DOWN', 'j'):
                if items and selected_idx < len(items) - 1:
                    selected_idx += 1

            # Toggle auto-refresh
            elif key == 'a':
                auto_refresh = not auto_refresh

            # Actions
            elif key in ('r', 'ENTER'):
                if items:
                    do_restart(orch_script, items[selected_idx])
                    data = build_dashboard_data(projects)
                    items = build_selectable_items(data)
            elif key == 'x':
                if items:
                    do_kill(orch_script, items[selected_idx])
                    data = build_dashboard_data(projects)
                    items = build_selectable_items(data)
            elif key == 'X':
                if items:
                    do_kill_remove(orch_script, items[selected_idx])
                    data = build_dashboard_data(projects)
                    items = build_selectable_items(data)
                    if items:
                        selected_idx = min(selected_idx, len(items) - 1)
            elif key == 's':
                do_spawn(orch_script, data, items, selected_idx)
                data = build_dashboard_data(projects)
                items = build_selectable_items(data)
            elif key == 'l':
                if items:
                    do_logs(orch_script, items[selected_idx])
            elif key == 'i':
                do_init(orch_script, data, items, selected_idx)
                data = build_dashboard_data(projects)
                items = build_selectable_items(data)

            # Quit
            elif key == 'q':
                break

            render_dashboard(data, selected_idx, items, auto_refresh)

    except KeyboardInterrupt:
        pass
    finally:
        if not IS_WINDOWS:
            restore_terminal()
        console.print("\n[dim]Dashboard closed.[/dim]")


if __name__ == "__main__":
    main()
