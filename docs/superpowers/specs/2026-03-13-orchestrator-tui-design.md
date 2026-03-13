# Orchestrator TUI — Design Spec

## Overview

A single-file Python TUI (`tui.py`) that provides a live dashboard for managing worktree-orchestrator sessions across multiple projects. Uses `rich` for rendering. Delegates all mutations (spawn, restart, kill) to the existing `orchestrator.py` script.

## Goals

- Show all worktree sessions across all configured projects in one view
- Navigate and manage sessions with single keypresses
- Auto-refresh health status every ~2 seconds
- Zero coupling to orchestrator.py internals — reads `sessions.json` for display, shells out for actions

## Discovery & Configuration

### Config file: `~/.config/orchestrator-tui.toml`

```toml
[[projects]]
path = "C:/Users/schur/code/waidplan"

[[projects]]
path = "C:/Users/schur/code/other-project"
```

The TUI reads this file on startup. Each `path` must be a git repo root containing `.orchestrator.toml` and `.orchestrator/sessions.json`.

If the config file doesn't exist, the TUI prints a message explaining how to create it and exits.

### Orchestrator script discovery

The TUI needs to find `orchestrator.py` to shell out to it. Resolution order:
1. `ORCHESTRATOR_SCRIPT` environment variable (explicit override)
2. Check if `orchestrator.py` exists adjacent to `tui.py` (bundled together)
3. Well-known path: `~/.claude/skills/worktree-orchestrator/scripts/orchestrator.py`

If not found, exit with an error message.

## Display Layout

```
 Orchestrator Dashboard                        Auto-refresh: ON
 ────────────────────────────────────────────────────────────────
 waidplan
   ▶ 1  b1   backend ✓ 64785  frontend ✓ 64786   running
     2  b2   backend ✓ 56925  frontend ✓ 56926   running
     3  b3   backend ✓ 60140  frontend ✓ 60141   running

 other-project
     5  b5   web ✗ —                              stopped
 ────────────────────────────────────────────────────────────────
 ↑↓/jk navigate  r restart  k kill  K kill+remove  s spawn  l logs  q quit
```

### Rendering

- `rich.console.Console` for output
- `rich.table.Table` for the session list, grouped by project
- `rich.text.Text` for the header and footer
- Screen cleared and redrawn on every keypress or auto-refresh tick
- Green `✓` for alive servers, red `✗` for dead servers
- `▶` marker on the currently selected row
- Session status shown as colored text: green "running", yellow "stopped", red "dead"

## Health Checks

For each server in each session, check PID liveness:
- **Windows:** `tasklist /FI "PID eq {pid}" /NH` and check if PID appears in output
- **Unix:** `os.kill(pid, 0)` — no signal sent, just checks existence

This is the same logic as `orchestrator.py`'s `is_process_alive()`. Re-implemented in the TUI (3 lines) to avoid importing from orchestrator.py.

## Input Handling

### Platform-specific keypress reading

- **Windows:** `msvcrt.kbhit()` + `msvcrt.getch()` — non-blocking poll
- **Unix:** `tty.setraw()` + `select.select()` with timeout + `sys.stdin.read(1)`

Both wrapped in a `get_key(timeout_ms)` function that returns:
- A character (`'r'`, `'k'`, `'q'`, `'s'`, `'l'`, `'a'`, `'j'`) for regular keys
- `'UP'`/`'DOWN'` for arrow keys (decoded from escape sequences on Unix, `\xe0` prefix on Windows)
- `None` on timeout (triggers auto-refresh)

### Keybindings

| Key | Action |
|-----|--------|
| `↑` / `k` | Move selection up |
| `↓` / `j` | Move selection down |
| `r` / `Enter` | Restart selected session |
| `k` | Kill selected session (when not navigating — see note) |
| `K` (shift-k) | Kill + remove worktree for selected session |
| `s` | Spawn new session — prompts for session name, then runs spawn |
| `l` | Show logs for selected session (last 30 lines, press any key to return) |
| `a` | Toggle auto-refresh on/off |
| `q` | Quit |

**Note on `k` ambiguity:** `k` is both "navigate up" (vim) and "kill". Resolution: `k` means navigate up. Kill is only available via the dedicated `x` key instead. This avoids accidental kills.

Revised:

| Key | Action |
|-----|--------|
| `↑` / `k` | Move selection up |
| `↓` / `j` | Move selection down |
| `r` / `Enter` | Restart selected session |
| `x` | Kill selected session |
| `X` (shift-x) | Kill + remove worktree |
| `s` | Spawn new session |
| `l` | Show logs |
| `a` | Toggle auto-refresh |
| `q` | Quit |

## Actions (shelling out to orchestrator.py)

All mutations run via subprocess:

```python
subprocess.run(
    ["python", ORCHESTRATOR_SCRIPT, command, session_name, *extra_args],
    cwd=project_path,
    capture_output=True, text=True
)
```

The TUI always sets `cwd` to the project's repo root so that `orchestrator.py` finds the correct `.orchestrator.toml` and `.orchestrator/.secrets`.

### Spawn flow

1. TUI prompts for session name (simple `input()` after restoring terminal to cooked mode)
2. Runs `orchestrator.py spawn <name> --no-claude` in the selected project's directory
3. Shows output briefly, then returns to dashboard

`--no-claude` is used because the user is already in a terminal managing things. They can manually open Claude in the worktree if needed.

### Restart / Kill / Kill+remove

1. Confirm with a brief "Restart session 1? (y/n)" prompt
2. Run the command, show output, return to dashboard

### Logs

1. Run `orchestrator.py logs <name> -n 30`
2. Display output in a pager-like view (just print it, "press any key to return")

## Data Model

The TUI reads `sessions.json` from each project's `.orchestrator/` directory. The schema (from orchestrator.py):

```json
{
  "1": {
    "name": "1",
    "branch": "feature/issue-1",
    "worktree": "C:\\Users\\schur\\code\\worktrees\\waidplan\\1",
    "servers": [
      {"name": "backend", "port": 64785, "pid": 86288, "command": "...", "directory": "server"},
      {"name": "frontend", "port": 64786, "pid": 88008, "command": "...", "directory": ""}
    ],
    "ports": {"backend": 64785, "frontend": 64786},
    "status": "running",
    "created_at": "2026-03-12T15:37:36.687574+00:00"
  }
}
```

The TUI reads this but never writes to it — all writes go through orchestrator.py.

## File Structure

```
~/code/orchestrator/
├── tui.py                # Single-file TUI application
├── requirements.txt      # rich
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-03-13-orchestrator-tui-design.md
```

## Error Handling

- Missing config file → clear error message with example config
- Missing orchestrator.py → error with resolution steps
- Project directory doesn't exist → skip it, show warning in dashboard
- sessions.json missing or empty → show project with "(no sessions)"
- orchestrator.py command fails → show stderr output, return to dashboard
- Terminal resize → re-render on next refresh cycle (rich handles this)

## Non-Goals

- No mouse support (keep it keyboard-only for simplicity)
- No live log streaming / split panes (that's the "Full dashboard" tier)
- No editing of .orchestrator.toml or .secrets from the TUI
- No auto-discovery of projects (explicit config only)
