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

Orchestrator commands: `init`, `spawn <name>`, `status`, `logs <name> [server] [-n lines]`, `kill <name> [--remove]`, `restart <name>`, `cleanup [--force]`.

No build step, no tests, no linter configured.

## Architecture

Two-file design at the repo root:

- **`orchestrator.py`** (~1000 lines) — The engine. Stdlib-only CLI (argparse) that manages git worktrees, spawns/kills server processes, and tracks sessions in `.orchestrator/sessions.json`. Contains a custom TOML parser (fallback for Python < 3.11), cross-platform process management, port allocation via ephemeral sockets, and template-based port substitution (`{port}`, `{backend.port}`).

- **`tui.py`** (~700 lines) — The dashboard. Imports `parse_toml`, `is_process_alive`, and `IS_WINDOWS` from `orchestrator.py`. Reads `config.toml` (adjacent to script) to discover projects, reads each project's `.orchestrator/sessions.json` for session data. All mutations delegate to `orchestrator.py` via subprocess. Uses platform-specific keypress handling (`msvcrt` on Windows, `tty`+`select` on Unix).

The TUI is read-only with respect to state — it never modifies session files or worktrees directly. Every action (spawn, kill, restart, cleanup) shells out to `orchestrator.py` as a subprocess.

## Configuration Layers

- `config.toml` (dashboard level) — lists project paths to monitor (gitignored, copy from `config.example.toml`)
- `.orchestrator.toml` (per-project) — defines servers, branches, remote
- `.orchestrator/.secrets` (per-project, dotenv format) — secrets injected into server env
- `.orchestrator/sessions.json` (per-project) — runtime session state (auto-managed)

## Cross-Platform Notes

Process management: Windows uses `tasklist`/`taskkill`, Unix uses `os.kill`/signals. Terminal spawning: Windows uses `wt`/`cmd`, macOS uses AppleScript, Linux tries `gnome-terminal`/`xfce4-terminal`/`konsole`/`xterm`. Keypress input: Windows uses `msvcrt`, Unix uses `tty`+`termios`.

## Requirements

Python 3.9+. `tui.py` uses `str | None` union syntax (3.10+ at runtime unless guarded by `from __future__ import annotations`).
