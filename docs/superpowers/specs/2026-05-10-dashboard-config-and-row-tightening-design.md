# Dashboard config management + row tightening — design

Date: 2026-05-10

## Goal

Three small, related changes to the worktree dashboard:

1. Manage the project list from inside the TUI (add / remove projects).
2. Show "last started X ago" on each session row.
3. Tighten each row: drop the status word, abbreviate `backend`/`frontend` to `BE`/`FE`.

All three are about getting more useful information into a denser row and removing one external editor round-trip from the workflow.

## Out of scope

- A CLI surface for project management (`python tui.py add ...`). TUI keys only.
- Killing or removing worktrees when a project is unlisted — unlist is purely an edit to `config.toml`. Sessions and worktrees on disk are untouched.
- Preserving comments inside `config.toml` after a programmatic edit. The example/docs live in `config.example.toml`; the live `config.toml` becomes a generated list.
- Any change to ghost detection or the cleanup flow.

## Changes

### 1. Row rendering (`tui.py`)

The current line is:

```
   ▶ b1  feature/foo      backend ✓  frontend ✓  running
```

Becomes:

```
   ▶ b1  feature/foo      BE ✓  FE ✓  5m ago
```

For ghost sessions:

```
   ▶ b1  feature/foo      (worktree gone)  3d ago
```

Specifics:

- **Server name display map**: `backend` → `BE`, `frontend` → `FE`. Any other server name (e.g. `web`) is shown unchanged. Implemented as a small `SERVER_LABELS` dict in `tui.py`.
- **Server status glyph**: keep the existing green `✓` / red `✗` on each server entry. Only the trailing status word (`running` / `stopped` / `dead`) is removed.
- **Status colors**: the `status_colors` dict and `status_str` rendering are deleted. Status is no longer in the row.
- **Ghost handling**: still rendered as `(worktree gone)`. The `do_restart` / `do_kill` / `do_kill_remove` / `do_logs` ghost guards continue to read `session["status"] == "ghost"` — that field stays in the data model, only its rendering goes away.
- **Relative time**: appended after the server list (or after `(worktree gone)` for ghosts). Sourced from `started_at` (see §2). If both `started_at` and `created_at` are missing, render `—`.

### 2. `started_at` field (`orchestrator.py`)

Two one-line additions:

- `cmd_spawn`: when building the session record (around line 842), add `"started_at": datetime.now(timezone.utc).isoformat()` next to the existing `"created_at"`.
- `cmd_restart`: after the new `server_records` are written and before `save_sessions(...)` (around line 1070), set `s["started_at"] = datetime.now(timezone.utc).isoformat()`.

`created_at` is left alone — it remains the original spawn time. `started_at` reflects the most recent spawn or restart.

The TUI reads `started_at`, falling back to `created_at` for sessions created before this change, falling back to `None` (rendered as `—`).

### 3. Relative-time helper (`tui.py`)

New small helper, no new dependency:

```python
def humanize_relative(iso_str: str | None) -> str:
    """Return a short '5m ago' / '2h ago' / '3d ago' / '4w ago' string."""
```

Rules:
- Parse ISO 8601 (`datetime.fromisoformat`). Treat naive datetimes as UTC.
- Compute delta vs `datetime.now(timezone.utc)`.
- < 60 s → `<1m ago`
- < 60 min → `Xm ago`
- < 24 h → `Xh ago`
- < 7 d → `Xd ago`
- otherwise → `Xw ago` (no month/year cap — sessions older than that are unusual; `Xw` is fine)
- Returns `—` on parse failure or `None` input.

### 4. Add / remove projects (`tui.py`)

Two new keybindings:

- **`a`** — add a project. Clears the screen, prompts `Project path: ` via `input()` (same pattern as `do_spawn` / `do_init`). Empty input or Ctrl-C cancels.
- **`D`** — remove a project. Only valid when a **project row** is selected. On a session row it does nothing and sets `status_msg` to `select a project row to remove` (uses the existing one-shot status line below the header).

#### Add (`do_add_project`)

1. Read the path from `input()`.
2. Strip surrounding whitespace and surrounding quotes (`"..."` or `'...'`).
3. Expand `~` and resolve to an absolute path.
4. Reject if not an existing directory.
5. Reject if the path (compared case-insensitively on Windows, exactly on Unix) is already in the project list.
6. Append a new entry to the in-memory project list and rewrite `config.toml` (see "Config writer" below).
7. Refresh.

No requirement that the project has a `.orchestrator.toml` — the dashboard already shows a "no sessions" line for projects that don't, which is fine for first-time setup.

#### Remove (`do_remove_project`)

1. Confirm: `Remove project <name> from config? (sessions on disk are untouched) (y/n)`.
2. On `y`, drop the matching entry from the in-memory list and rewrite `config.toml`.
3. Refresh. Reset `selected_idx` if it now points past the end.

The session data and worktrees are not touched. Re-adding the same path brings everything back instantly.

#### Config writer

The custom `parse_toml` in `orchestrator.py` is parse-only. We add a tiny writer in `tui.py` that emits the canonical layout:

```toml
[[projects]]
path = "C:/users/schur/code/foo"

[[projects]]
path = "C:/users/schur/code/bar"
```

Implementation:
- Build the text in memory.
- Atomic write: write to `config.toml.tmp` next to the target, then `os.replace` over the original. Prevents a half-written file on crash.
- Paths are quoted with double quotes. Backslashes in Windows paths are normalized to forward slashes (matches the existing entries in `config.toml`) — TOML basic strings would otherwise need escaping.

Comments in the existing `config.toml` are not preserved. The trade-off is accepted: the documentation lives in `config.example.toml`, and the live config becomes a generated list of paths.

### 5. Footer

Adds the two new keys; line wraps to two lines:

```
↑↓/jk nav  R refresh  r restart  x kill  X kill+rm  s spawn  l logs
c cleanup  i init  a add-proj  D rm-proj  q quit
```

Minor wording trims (`navigate` → `nav`, `kill+remove` → `kill+rm`) to keep the footer compact.

## Files touched

- `tui.py` — the bulk of the work: new helpers (`humanize_relative`, `SERVER_LABELS`, `write_dashboard_config`), new actions (`do_add_project`, `do_remove_project`), render changes, key handlers, footer, `D` no-op hint when on a session row.
- `orchestrator.py` — two additions: set `started_at` in `cmd_spawn` (next to `created_at`) and in `cmd_restart` (before `save_sessions`).

No new dependencies.

## Risks / considerations

- **Atomic config write**: `os.replace` on Windows works as long as no other process holds the file open. The TUI is the only writer, and `parse_toml` reads-then-closes, so this is safe.
- **`started_at` on existing sessions**: missing until a session is restarted or a new one is spawned. Falls back to `created_at`, then to `—`. No migration step.
- **Server label collisions**: if a project ever names a server literally `BE` or `FE`, no behavior changes — the dict only maps the long form to short. Unmapped names render as-is.
- **Ghost rows + relative time**: `started_at` may be far in the past for a ghost. We still render `Xd ago` / `Xw ago` — informative, not misleading.
- **`D` discoverability**: the footer lists it, and it mirrors the existing destructive-uppercase pattern (`X` for kill+remove). The y/n confirm protects against accidents.
