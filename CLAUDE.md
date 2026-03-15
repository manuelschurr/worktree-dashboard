# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Worktree Dashboard — a Python TUI for monitoring and managing worktree-orchestrator sessions across multiple projects. Keyboard-driven, cross-platform (Windows/macOS/Linux), uses `rich` for terminal rendering.

## Running

```bash
pip install rich            # only external dependency
python tui.py               # launch the dashboard
python orchestrator.py <command>  # use the engine directly
```

Orchestrator commands: `init`, `spawn <name>`, `status`, `logs <name> [server] [-n lines]`, `kill <name> [--remove]`, `restart <name>`, `cleanup [--force]`, `proxy [-p PORT]`.

No build step, no tests, no linter configured.

## Architecture

Two-file design at the repo root:

- **`orchestrator.py`** (~1200 lines) — The engine. Stdlib-only CLI (argparse) that manages git worktrees, spawns/kills server processes, tracks sessions in `.orchestrator/sessions.json`, and includes a built-in reverse proxy. Deterministic port allocation (hash of project:session:server), cross-platform process management, custom TOML parser (fallback for Python < 3.11), and template-based port substitution (`{port}`, `{backend.port}`). The reverse proxy (`proxy` subcommand) listens on port 1337 and routes by `Host` header using a shared route table at `~/.orchestrator/routes.json`. The proxy auto-starts as a detached background process on spawn/restart — `ensure_proxy_running()` checks the port and is idempotent. A companion copy of this file lives in the worktree-orchestrator skill repo — keep them in sync.

- **`tui.py`** (~700 lines) — The dashboard. Imports `parse_toml`, `is_process_alive`, `IS_WINDOWS`, `DEFAULT_PROXY_PORT`, `DEFAULT_TLD`, and `ensure_proxy_running` from `orchestrator.py`. Auto-starts the proxy on launch. Reads `config.toml` (adjacent to script) to discover projects, reads each project's `.orchestrator/sessions.json` for session data. All mutations delegate to `orchestrator.py` via subprocess. Uses platform-specific keypress handling (`msvcrt` on Windows, `tty`+`select` on Unix). Server links render as hostname URLs (e.g. `b1-frontend.myapp.localhost:1337`).

The TUI is read-only with respect to state — it never modifies session files or worktrees directly. Every action (spawn, kill, restart, cleanup) shells out to `orchestrator.py` as a subprocess.

## Configuration Layers

- `config.toml` (dashboard level) — lists project paths to monitor (gitignored, copy from `config.example.toml`)
- `.orchestrator.toml` (per-project) — defines servers, branches, remote
- `.orchestrator/.secrets` (per-project, dotenv format) — secrets injected into server env
- `.orchestrator/sessions.json` (per-project) — runtime session state (auto-managed)
- `~/.orchestrator/routes.json` (global) — shared proxy route table mapping hostnames to ports (auto-managed by spawn/kill/restart/cleanup)

## Cross-Platform Notes

Process management: Windows uses `tasklist`/`taskkill`, Unix uses `os.kill`/signals. Terminal spawning: Windows uses `wt`/`cmd`, macOS uses AppleScript, Linux tries `gnome-terminal`/`xfce4-terminal`/`konsole`/`xterm`. Keypress input: Windows uses `msvcrt`, Unix uses `tty`+`termios`.

## Requirements

Python 3.9+. `tui.py` uses `str | None` union syntax (3.10+ at runtime unless guarded by `from __future__ import annotations`).
