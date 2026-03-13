# Worktree Dashboard — Design Spec

## Overview

A standalone Python TUI for managing git worktree sessions across multiple projects. Bundles the orchestrator engine (`orchestrator.py`) so it works out of the box — no Claude Code skill required. Uses `rich` for rendering.

## Goals

- **Standalone:** Ships with everything needed — orchestrator engine, config templates, and the dashboard TUI. Users clone the repo, `pip install rich`, and go.
- Show all worktree sessions across all configured projects in one view
- Navigate and manage sessions with single keypresses
- Auto-refresh health status every ~2 seconds
- The TUI reads `sessions.json` for display and shells out to the bundled `orchestrator.py` for actions

## Discovery & Configuration

### Config file: `~/.config/worktree-dashboard.toml`

```toml
[[projects]]
path = "C:/Users/schur/code/waidplan"

[[projects]]
path = "C:/Users/schur/code/other-project"
```

The TUI reads this file on startup. Each `path` must be a git repo root containing `.orchestrator.toml` and `.orchestrator/sessions.json`.

If the config file doesn't exist, the TUI prints a message explaining how to create it and exits.

### Orchestrator script discovery

The TUI finds `orchestrator.py` via:
1. `ORCHESTRATOR_SCRIPT` environment variable (explicit override)
2. `orchestrator.py` adjacent to `tui.py` (the default — bundled in the same repo)

If not found, exit with an error message.

## Display Layout

```
 Worktree Dashboard                            Auto-refresh: ON
 ────────────────────────────────────────────────────────────────
 waidplan
   ▶ 1  b1   backend ✓ 64785  frontend ✓ 64786   running
     2  b2   backend ✓ 56925  frontend ✓ 56926   running
     3  b3   backend ✓ 60140  frontend ✓ 60141   running

 other-project
     5  b5   web ✗ —                              stopped
 ────────────────────────────────────────────────────────────────
 ↑↓/jk navigate  r restart  x kill  X kill+remove  s spawn  l logs  q quit
```

### Navigation

- The cursor moves only between session rows. Project headers are not selectable — `↑`/`↓` skip over them.
- If no sessions exist across any project, all action keys (`r`, `x`, `X`, `l`) are no-ops.
- Spawn (`s`) targets the project that the cursor is currently within (the nearest project group header above the cursor). If there are no sessions at all and the cursor has no project context, the TUI prompts the user to pick a project from the configured list.

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
| `x` | Kill selected session |
| `X` (shift-x) | Kill + remove worktree |
| `s` | Spawn new session (targets current project group) |
| `l` | Show logs (last 50 lines, press any key to return) |
| `a` | Toggle auto-refresh on/off |
| `q` | Quit |

`k` is reserved for vim-style navigation up. Kill uses `x` to avoid accidental kills.

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

**Terminal mode:** Any action requiring `input()` or line-buffered I/O (spawn name prompt, confirmation prompts) must first restore the terminal to cooked mode. After the action completes, raw mode is re-entered for the keypress loop.

**After every action:** The TUI shows the subprocess output and waits for a keypress ("press any key to return"). The session list is re-read immediately after returning to the dashboard (not waiting for the next auto-refresh tick).

### Spawn flow

1. Targets the project of the currently selected session (or prompts if ambiguous)
2. Restores terminal to cooked mode, prompts for session name via `input()`
3. Runs `orchestrator.py spawn <name> --no-claude` in the project's directory
4. Shows output, press any key to return

`--no-claude` is used because the user is already in a terminal managing things.

### Restart / Kill / Kill+remove

1. Restores terminal to cooked mode
2. Confirms with "Restart session 1? (y/n)" prompt (single keypress)
3. Runs the command, shows output, press any key to return

### Logs

1. Run `orchestrator.py logs <name>` (uses orchestrator's default of 50 lines)
2. Shows output, press any key to return

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

The TUI reads this but never writes to it — all writes go through orchestrator.py. The JSON keys are the canonical session identifiers passed to orchestrator.py commands.

**Concurrent access:** If `orchestrator.py` is writing `sessions.json` while the TUI reads it, the read may fail. The TUI wraps JSON parsing in try/except and retries on the next refresh cycle.

## File Structure

```
~/code/worktree-dashboard/
├── tui.py                # Dashboard TUI
├── orchestrator.py       # Worktree orchestrator engine (bundled from claude skill)
├── requirements.txt      # rich
├── templates/
│   ├── orchestrator.toml # Example .orchestrator.toml for new projects
│   └── secrets           # Example .orchestrator/.secrets
└── docs/
    └── superpowers/
        └── specs/
            └── 2026-03-13-orchestrator-tui-design.md
```

### Bundled files

- **`orchestrator.py`** — The full worktree orchestrator engine, copied from the Claude Code skill. This is the same script that manages worktrees, starts/stops servers, and handles spawn/kill/restart. Bundled so the dashboard works standalone.
- **`templates/orchestrator.toml`** — Example project config that users copy into their repo as `.orchestrator.toml`. Shows the `[project]` and `[servers.*]` sections with commented examples.
- **`templates/secrets`** — Example secrets file that users copy into `.orchestrator/.secrets`. Shows the format with placeholder values.

### Setup flow for a new user

1. Clone `worktree-dashboard`
2. `pip install rich`
3. Copy `templates/orchestrator.toml` → `<your-repo>/.orchestrator.toml`, edit server config
4. Copy `templates/secrets` → `<your-repo>/.orchestrator/.secrets`, fill in real values
5. Create `~/.config/worktree-dashboard.toml` listing your project paths
6. Run `python tui.py`

Users can also use `orchestrator.py` directly from the CLI (`python orchestrator.py spawn 1`, etc.) without the TUI.

## Error Handling

- Missing config file → clear error message with example config
- Missing orchestrator.py → error saying it should be adjacent to tui.py
- Project directory doesn't exist → skip it, show warning in dashboard
- sessions.json missing or empty → show project with "(no sessions)"
- orchestrator.py command fails → show stderr output, return to dashboard
- Terminal resize → re-render on next refresh cycle (rich handles this)

## Non-Goals

- No mouse support (keep it keyboard-only for simplicity)
- No live log streaming / split panes (that's the "Full dashboard" tier)
- No editing of .orchestrator.toml or .secrets from the TUI
- No auto-discovery of projects (explicit config only)
- No `cleanup` command — batch removal of stopped sessions is better suited to the CLI directly
- No `status` command passthrough — the TUI does its own PID health checks directly for speed (avoids subprocess overhead every 2 seconds)
