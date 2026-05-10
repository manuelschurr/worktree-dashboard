# Dashboard config management + row tightening — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add in-TUI add/remove of projects, surface "last started X ago" on each session row, abbreviate `backend`/`frontend` to `BE`/`FE`, and drop the trailing status word.

**Architecture:** All display work + config-file mutation lives in `tui.py`. Two surgical edits in `orchestrator.py` add a `started_at` timestamp on spawn and restart. No new dependencies. No test framework — verification is via `python -c` snippets and live TUI runs.

**Tech Stack:** Python 3.9+, `rich` (already a dep), stdlib only otherwise. Spec at `docs/superpowers/specs/2026-05-10-dashboard-config-and-row-tightening-design.md`.

**Companion file:** `~/.claude/skills/worktree-orchestrator/scripts/orchestrator.py` is a copy of `worktree-dashboard/orchestrator.py` per `CLAUDE.md`. Task 8 mirrors the two orchestrator edits there.

---

## Task 1: Add `started_at` to `orchestrator.py`

**Files:**
- Modify: `C:/Users/schur/code/worktree-dashboard/orchestrator.py` (around line 849 in `cmd_spawn` and around line 1069 in `cmd_restart`)

- [ ] **Step 1: Edit `cmd_spawn` to record `started_at`**

Find the session-record dict in `cmd_spawn` (around line 842–850):

```python
    sessions[name] = {
        "name": name,
        "branch": branch,
        "worktree": str(wt_path),
        "servers": server_records,
        "ports": port_map,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
```

Replace with (adds one line):

```python
    now_iso = datetime.now(timezone.utc).isoformat()
    sessions[name] = {
        "name": name,
        "branch": branch,
        "worktree": str(wt_path),
        "servers": server_records,
        "ports": port_map,
        "status": "running",
        "created_at": now_iso,
        "started_at": now_iso,
    }
```

- [ ] **Step 2: Edit `cmd_restart` to bump `started_at`**

Find the post-spawn block in `cmd_restart` (around line 1067–1070):

```python
    s["servers"] = server_records
    s["ports"] = port_map
    s["status"] = "running"
    save_sessions(repo_root, sessions)
```

Replace with (adds one line before `save_sessions`):

```python
    s["servers"] = server_records
    s["ports"] = port_map
    s["status"] = "running"
    s["started_at"] = datetime.now(timezone.utc).isoformat()
    save_sessions(repo_root, sessions)
```

- [ ] **Step 3: Verify imports already cover `datetime`/`timezone`**

Run: `python -c "import ast,sys; t=ast.parse(open(r'C:/Users/schur/code/worktree-dashboard/orchestrator.py',encoding='utf-8').read()); names=[n.name for node in ast.walk(t) if isinstance(node, ast.ImportFrom) and node.module=='datetime' for n in node.names]; print(names)"`

Expected output includes `datetime` and `timezone`. (They're already imported at the top of the file alongside `created_at`'s usage — this is a sanity check.)

- [ ] **Step 4: Smoke-test by inspecting a fresh sessions.json after spawn**

If you have a project set up with the orchestrator (e.g. `C:/users/schur/code/scout`), pick an unused session name and run:

```bash
cd C:/users/schur/code/scout
python C:/Users/schur/code/worktree-dashboard/orchestrator.py spawn _plantest --no-claude
```

Then read the new entry:

```bash
python -c "import json; print(json.dumps(json.load(open(r'C:/users/schur/code/scout/.orchestrator/sessions.json'))['_plantest'], indent=2))"
```

Expected: the dict contains both `created_at` and `started_at` with the same ISO timestamp.

Restart it:

```bash
python C:/Users/schur/code/worktree-dashboard/orchestrator.py restart _plantest
```

Re-print the entry. Expected: `created_at` unchanged, `started_at` is newer.

Clean up:

```bash
python C:/Users/schur/code/worktree-dashboard/orchestrator.py kill _plantest --remove
```

If you don't have a project handy, skip this step — Task 4's TUI run will exercise it indirectly.

- [ ] **Step 5: Commit**

```bash
git -C C:/Users/schur/code/worktree-dashboard add orchestrator.py
git -C C:/Users/schur/code/worktree-dashboard commit -m "orchestrator: record started_at on spawn and restart"
```

---

## Task 2: Add `humanize_relative` helper to `tui.py`

**Files:**
- Modify: `C:/Users/schur/code/worktree-dashboard/tui.py` (insert near the top, after the existing imports block, before the `# Config & discovery` section header at line 28)

- [ ] **Step 1: Add `datetime`/`timezone` to the existing stdlib imports**

Find the imports block (lines 12–17):

```python
import json
import os
import subprocess
import sys
import time
from pathlib import Path
```

Replace with:

```python
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
```

- [ ] **Step 2: Add the `humanize_relative` helper**

Insert just before the line `# ---------------------------------------------------------------------------` that precedes `# Config & discovery` (line 28):

```python
def humanize_relative(iso_str: str | None) -> str:
    """Render an ISO 8601 timestamp as a short '5m ago' / '2h ago' / '3d ago' / '4w ago' string.

    Returns '—' for None or unparseable input. Naive datetimes are treated as UTC.
    """
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str)
    except (ValueError, TypeError):
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    secs = int(delta.total_seconds())
    if secs < 60:
        return "<1m ago"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    return f"{weeks}w ago"
```

- [ ] **Step 3: Scratch-test the helper**

Run:

```bash
python -c "import sys; sys.path.insert(0, r'C:/Users/schur/code/worktree-dashboard'); from tui import humanize_relative; from datetime import datetime, timezone, timedelta; now=datetime.now(timezone.utc); print(humanize_relative(None)); print(humanize_relative('not-a-date')); print(humanize_relative((now-timedelta(seconds=10)).isoformat())); print(humanize_relative((now-timedelta(minutes=5)).isoformat())); print(humanize_relative((now-timedelta(hours=3)).isoformat())); print(humanize_relative((now-timedelta(days=2)).isoformat())); print(humanize_relative((now-timedelta(days=21)).isoformat()))"
```

Expected output (one per line):

```
—
—
<1m ago
5m ago
3h ago
2d ago
3w ago
```

- [ ] **Step 4: Commit**

```bash
git -C C:/Users/schur/code/worktree-dashboard add tui.py
git -C C:/Users/schur/code/worktree-dashboard commit -m "tui: add humanize_relative helper"
```

---

## Task 3: Surface `started_at` in the data model

**Files:**
- Modify: `C:/Users/schur/code/worktree-dashboard/tui.py` — `build_dashboard_data` (around lines 146–153)

- [ ] **Step 1: Carry `started_at` through to the session dict**

Find this block in `build_dashboard_data` (around lines 146–153):

```python
            sessions.append({
                "key": key,
                "branch": s.get("branch", "?"),
                "servers": servers,
                "status": status,
                "project_path": proj["path"],
                "project_name": proj["name"],
            })
```

Replace with (adds one line):

```python
            sessions.append({
                "key": key,
                "branch": s.get("branch", "?"),
                "servers": servers,
                "status": status,
                "started_at": s.get("started_at") or s.get("created_at"),
                "project_path": proj["path"],
                "project_name": proj["name"],
            })
```

The fallback to `created_at` covers sessions spawned before Task 1 was applied. Both being absent yields `None`, which `humanize_relative` renders as `—`.

- [ ] **Step 2: Commit**

```bash
git -C C:/Users/schur/code/worktree-dashboard add tui.py
git -C C:/Users/schur/code/worktree-dashboard commit -m "tui: include started_at in session data model"
```

---

## Task 4: Update row rendering — BE/FE, drop status word, append relative time

**Files:**
- Modify: `C:/Users/schur/code/worktree-dashboard/tui.py` — add `SERVER_LABELS` constant; replace the session-row rendering inside `render_dashboard` (around lines 197–226)

- [ ] **Step 1: Add the `SERVER_LABELS` constant**

Insert this constant directly above the `def humanize_relative(...)` definition added in Task 2:

```python
SERVER_LABELS = {
    "backend": "BE",
    "frontend": "FE",
}
```

- [ ] **Step 2: Rewrite the session-row branch in `render_dashboard`**

Find this block (around lines 197–226 in the current file, the `else:` branch for non-project items):

```python
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
```

Replace with:

```python
            else:
                s = item
                is_selected = item_idx == selected_idx
                marker = "▶" if is_selected else " "
                style = "reverse" if is_selected else ""

                # Build server status string with hostname links and BE/FE labels
                srv_parts = []
                proj = s.get("project_name", "")
                sess = s.get("key", "")
                for srv in s["servers"]:
                    label = SERVER_LABELS.get(srv["name"], srv["name"])
                    if srv["alive"]:
                        hostname = f"{sess}-{srv['name']}.{proj}.{DEFAULT_TLD}"
                        url = f"http://{hostname}:{DEFAULT_PROXY_PORT}"
                        srv_parts.append(f"[link={url}]{label}[/link] [green]✓[/green]")
                    else:
                        srv_parts.append(f"{label} [red]✗[/red]")
                srv_str = "  ".join(srv_parts)

                age = humanize_relative(s.get("started_at"))
                age_str = f"[dim]{age}[/dim]"

                branch = s['branch'][:16]
                if s["status"] == "ghost":
                    line = f"      {marker} {s['key']:3s} {branch:16s} [dim](worktree gone)[/dim]  {age_str}"
                else:
                    line = f"      {marker} {s['key']:3s} {branch:16s} {srv_str}  {age_str}"
                console.print(line, style=style, highlight=False)
```

Notes for the implementer:
- The `link=...` markup keeps using the raw `srv["name"]` (full name) to build the URL — only the visible label is shortened.
- The `status_colors` dict and `status_str` string are gone. The `s["status"]` field is still read for the `== "ghost"` branch.
- Relative time is dimmed so it stays visually subordinate to the checkmarks.

- [ ] **Step 3: Run the TUI and eyeball a session**

Run:

```bash
python C:/Users/schur/code/worktree-dashboard/tui.py
```

Expected:
- Each session row ends with `BE ✓  FE ✓  5m ago` (or similar) — no `running` / `stopped` / `dead` word.
- Servers named anything other than `backend`/`frontend` (e.g. `web` in the c200v / portfolio projects) display under their full original name.
- Ghost sessions (if any) still show `(worktree gone)` and now show a relative time too.
- Press `q` to exit.

If you don't have any live sessions, that's fine — rows simply won't render. Spawn one to verify, then kill it, or trust the static review.

- [ ] **Step 4: Commit**

```bash
git -C C:/Users/schur/code/worktree-dashboard add tui.py
git -C C:/Users/schur/code/worktree-dashboard commit -m "tui: drop status word, abbreviate BE/FE, show last-started age"
```

---

## Task 5: Add `write_dashboard_config` helper

**Files:**
- Modify: `C:/Users/schur/code/worktree-dashboard/tui.py` — add a helper near the existing `load_dashboard_config` (around line 52)

- [ ] **Step 1: Add the writer**

Insert this function directly below `load_dashboard_config` in `tui.py` (after line 69, before the `# Session data` divider):

```python
def write_dashboard_config(project_paths: list[Path]) -> None:
    """Rewrite config.toml with the given project paths. Atomic via tmp+replace.

    Comments in the existing file are not preserved — the live config becomes a
    generated list. Documentation lives in config.example.toml.
    """
    lines = []
    for i, p in enumerate(project_paths):
        if i > 0:
            lines.append("")
        lines.append("[[projects]]")
        # Forward slashes match the existing convention and avoid TOML escape issues.
        normalized = str(p).replace("\\", "/")
        lines.append(f'path = "{normalized}"')
    lines.append("")  # trailing newline
    text = "\n".join(lines)

    tmp = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)
```

- [ ] **Step 2: Scratch-test the writer (and round-trip via `parse_toml`)**

Run:

```bash
python -c "import sys, tempfile, os; from pathlib import Path; sys.path.insert(0, r'C:/Users/schur/code/worktree-dashboard'); import tui; from orchestrator import parse_toml; tmp=Path(tempfile.mkdtemp())/'config.toml'; tui.CONFIG_PATH = tmp; tui.write_dashboard_config([Path('C:/users/schur/code/foo'), Path('C:/users/schur/code/bar')]); print(tmp.read_text(encoding='utf-8')); print('---'); parsed=parse_toml(tmp.read_text(encoding='utf-8')); print(parsed)"
```

Expected output:

```
[[projects]]
path = "C:/users/schur/code/foo"

[[projects]]
path = "C:/users/schur/code/bar"

---
{'projects': [{'path': 'C:/users/schur/code/foo'}, {'path': 'C:/users/schur/code/bar'}]}
```

- [ ] **Step 3: Commit**

```bash
git -C C:/Users/schur/code/worktree-dashboard add tui.py
git -C C:/Users/schur/code/worktree-dashboard commit -m "tui: add atomic config writer"
```

---

## Task 6: Add `do_add_project` action and `a` keybinding

**Files:**
- Modify: `C:/Users/schur/code/worktree-dashboard/tui.py` — add `do_add_project` near the other `do_*` actions (after `do_cleanup`, around line 645); wire it into the main loop (around line 715)

- [ ] **Step 1: Add `do_add_project`**

Insert this function after `do_cleanup` and before the `# Main event loop` divider:

```python
def do_add_project(projects: list[dict]) -> str:
    """Prompt for a project path and append it to config.toml.

    Returns a status message to surface in the dashboard header.
    """
    restore_terminal()
    console.clear()
    console.print("[bold]Add project[/bold]")
    try:
        raw = input("Project path: ").strip()
    except (EOFError, KeyboardInterrupt):
        return ""
    if not raw:
        return ""

    # Strip surrounding quotes and expand ~
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        raw = raw[1:-1]
    path = Path(os.path.expanduser(raw)).resolve()

    if not path.is_dir():
        console.print(f"[red]Not a directory: {path}[/red]")
        console.print("\n[dim]Press any key to return...[/dim]")
        wait_for_key()
        return "[red]add cancelled[/red]"

    # Duplicate check (case-insensitive on Windows)
    def norm(p: Path) -> str:
        s = str(p).replace("\\", "/")
        return s.lower() if IS_WINDOWS else s

    existing = [proj["path"] for proj in projects]
    if any(norm(p) == norm(path) for p in existing):
        console.print(f"[yellow]Already in config: {path}[/yellow]")
        console.print("\n[dim]Press any key to return...[/dim]")
        wait_for_key()
        return "[yellow]already in config[/yellow]"

    new_paths = existing + [path]
    write_dashboard_config(new_paths)
    return f"[green]added {path.name}[/green]"
```

- [ ] **Step 2: Wire `a` into the main loop**

Find this block in `main()` (around line 720–726):

```python
            elif key == 'c':
                do_cleanup(orch_script, data)
                refresh(show_indicator=False)
            elif key == 'i':
                do_init(orch_script, data, items, selected_idx)
                refresh(show_indicator=False)
```

Replace with:

```python
            elif key == 'c':
                do_cleanup(orch_script, data)
                refresh(show_indicator=False)
            elif key == 'i':
                do_init(orch_script, data, items, selected_idx)
                refresh(show_indicator=False)
            elif key == 'a':
                msg = do_add_project(projects)
                projects = load_dashboard_config()
                refresh(show_indicator=False)
                if msg:
                    status_msg = msg
```

The reload of `projects` is necessary because `build_dashboard_data` reads from the in-memory `projects` list, not from disk on every refresh.

- [ ] **Step 3: Manual smoke test**

Make a backup first:

```bash
copy C:\Users\schur\code\worktree-dashboard\config.toml C:\Users\schur\code\worktree-dashboard\config.toml.bak
```

Then run:

```bash
python C:/Users/schur/code/worktree-dashboard/tui.py
```

- Press `a`. Type a valid existing directory path (e.g. `C:/users/schur/code/llmwiki` if you have it). Hit Enter. Confirm the dashboard now lists it (likely with "no sessions").
- Press `a` again, type the same path. Confirm you see `already in config`.
- Press `a` again, type `C:/does/not/exist`. Confirm `Not a directory` message.
- Press `a` again, hit Enter on empty input. Confirm clean cancel.
- Quit with `q`.

Inspect `config.toml`. The added project should be appended; the file should still be valid TOML.

Restore your original config:

```bash
move /Y C:\Users\schur\code\worktree-dashboard\config.toml.bak C:\Users\schur\code\worktree-dashboard\config.toml
```

- [ ] **Step 4: Commit**

```bash
git -C C:/Users/schur/code/worktree-dashboard add tui.py
git -C C:/Users/schur/code/worktree-dashboard commit -m "tui: 'a' key adds a project to config.toml"
```

---

## Task 7: Add `do_remove_project` action and `D` keybinding

**Files:**
- Modify: `C:/Users/schur/code/worktree-dashboard/tui.py` — add `do_remove_project` next to `do_add_project`; wire `D` into the main loop with a guard for non-project rows

- [ ] **Step 1: Add `do_remove_project`**

Insert this function directly after `do_add_project`:

```python
def do_remove_project(projects: list[dict], item: dict) -> str:
    """Confirm and remove the selected project from config.toml.

    `item` must be a project-row item. Sessions and worktrees on disk are not
    touched. Returns a status message to surface in the dashboard header.
    """
    restore_terminal()
    console.clear()
    name = item["project_name"]
    target = item["project_path"]
    console.print(f"[bold]Remove project [cyan]{name}[/cyan] from config?[/bold]")
    console.print("[dim](Sessions and worktrees on disk are untouched.)[/dim]")
    if not confirm("Proceed? (y/n) "):
        console.print("[dim]Cancelled.[/dim]")
        time.sleep(0.5)
        return ""

    def norm(p: Path) -> str:
        s = str(p).replace("\\", "/")
        return s.lower() if IS_WINDOWS else s

    new_paths = [proj["path"] for proj in projects if norm(proj["path"]) != norm(target)]
    if len(new_paths) == len(projects):
        return "[yellow]not found in config[/yellow]"
    write_dashboard_config(new_paths)
    return f"[green]removed {name}[/green]"
```

- [ ] **Step 2: Wire `D` into the main loop with a project-row guard**

Add after the `'a'` branch you added in Task 6:

```python
            elif key == 'D':
                if items and 0 <= selected_idx < len(items) and items[selected_idx].get("type") == "project":
                    msg = do_remove_project(projects, items[selected_idx])
                    projects = load_dashboard_config()
                    refresh(show_indicator=False)
                    if msg:
                        status_msg = msg
                else:
                    status_msg = "[dim]select a project row to remove[/dim]"
```

- [ ] **Step 3: Manual smoke test**

```bash
copy C:\Users\schur\code\worktree-dashboard\config.toml C:\Users\schur\code\worktree-dashboard\config.toml.bak
```

Run:

```bash
python C:/Users/schur/code/worktree-dashboard/tui.py
```

- Navigate to a **session row** (not a project row). Press `D`. Confirm the header shows `select a project row to remove` and nothing changes.
- Navigate up to a **project row**. Press `D`. Answer `n`. Confirm `Cancelled.` and the project is still listed.
- Press `D` again. Answer `y`. Confirm the project disappears from the dashboard and the header shows `removed <name>`.
- Quit with `q`. Inspect `config.toml`: that project's `[[projects]]` block should be gone.

Restore:

```bash
move /Y C:\Users\schur\code\worktree-dashboard\config.toml.bak C:\Users\schur\code\worktree-dashboard\config.toml
```

- [ ] **Step 4: Commit**

```bash
git -C C:/Users/schur/code/worktree-dashboard add tui.py
git -C C:/Users/schur/code/worktree-dashboard commit -m "tui: 'D' key removes the selected project from config.toml"
```

---

## Task 8: Update the footer

**Files:**
- Modify: `C:/Users/schur/code/worktree-dashboard/tui.py` — `render_dashboard` footer (currently line 230)

- [ ] **Step 1: Replace the footer line**

Find:

```python
    console.print("[dim]↑↓/jk[/dim] navigate  [dim]R[/dim] refresh  [dim]r[/dim] restart  [dim]x[/dim] kill  [dim]X[/dim] kill+remove  [dim]s[/dim] spawn  [dim]l[/dim] logs  [dim]c[/dim] cleanup  [dim]i[/dim] init  [dim]q[/dim] quit")
```

Replace with:

```python
    console.print("[dim]↑↓/jk[/dim] nav  [dim]R[/dim] refresh  [dim]r[/dim] restart  [dim]x[/dim] kill  [dim]X[/dim] kill+rm  [dim]s[/dim] spawn  [dim]l[/dim] logs")
    console.print("[dim]c[/dim] cleanup  [dim]i[/dim] init  [dim]a[/dim] add-proj  [dim]D[/dim] rm-proj  [dim]q[/dim] quit")
```

- [ ] **Step 2: Eyeball the dashboard**

```bash
python C:/Users/schur/code/worktree-dashboard/tui.py
```

Confirm the footer is two lines, both fit on a typical terminal width (≥ 80 cols), and lists `a` and `D`. Quit with `q`.

- [ ] **Step 3: Commit**

```bash
git -C C:/Users/schur/code/worktree-dashboard add tui.py
git -C C:/Users/schur/code/worktree-dashboard commit -m "tui: footer lists add-proj/rm-proj keys"
```

---

## Task 9: Mirror orchestrator edits into the skill copy

**Files:**
- Modify: `C:/Users/schur/.claude/skills/worktree-orchestrator/scripts/orchestrator.py`

`CLAUDE.md` for this project says: "A companion copy of this file lives in the worktree-orchestrator skill repo — keep them in sync." This task applies the same two edits from Task 1 to that copy.

- [ ] **Step 1: Confirm the file exists**

Run: `python -c "import os; print(os.path.exists(r'C:/Users/schur/.claude/skills/worktree-orchestrator/scripts/orchestrator.py'))"`

Expected: `True`. If `False`, skip this task — there's nothing to sync on this machine.

- [ ] **Step 2: Diff the two files first**

```bash
git -C C:/Users/schur/code/worktree-dashboard diff --no-index -- C:/Users/schur/code/worktree-dashboard/orchestrator.py C:/Users/schur/.claude/skills/worktree-orchestrator/scripts/orchestrator.py
```

If the only differences are the Task 1 edits (i.e. the skill copy is otherwise in sync), proceed. If there are unrelated drifts, surface them and stop — they need a human call before mirroring.

- [ ] **Step 3: Apply the same two edits**

Edit A — in `cmd_spawn`, find:

```python
    sessions[name] = {
        "name": name,
        "branch": branch,
        "worktree": str(wt_path),
        "servers": server_records,
        "ports": port_map,
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
```

Replace with:

```python
    now_iso = datetime.now(timezone.utc).isoformat()
    sessions[name] = {
        "name": name,
        "branch": branch,
        "worktree": str(wt_path),
        "servers": server_records,
        "ports": port_map,
        "status": "running",
        "created_at": now_iso,
        "started_at": now_iso,
    }
```

Edit B — in `cmd_restart`, find:

```python
    s["servers"] = server_records
    s["ports"] = port_map
    s["status"] = "running"
    save_sessions(repo_root, sessions)
```

Replace with:

```python
    s["servers"] = server_records
    s["ports"] = port_map
    s["status"] = "running"
    s["started_at"] = datetime.now(timezone.utc).isoformat()
    save_sessions(repo_root, sessions)
```

- [ ] **Step 4: Verify**

Re-run the diff from Step 2. Expected: no output (files identical), or only the unrelated drifts you surfaced.

- [ ] **Step 5: Skill copy is outside this repo — no commit needed here**

If the skill copy lives in its own git repo, commit there using its conventions. Otherwise leave it as a working-tree edit.

---

## Verification — full pass

After all tasks, run the dashboard one more time and confirm:

- [ ] Each session row reads `BE ✓  FE ✓  Xm ago` (or similar) with no status word.
- [ ] A freshly spawned session shows `<1m ago`. After `r` (restart), it resets to `<1m ago`.
- [ ] An old session shows `Xh`/`Xd`/`Xw` correctly.
- [ ] `a` adds a project, `D` on a project row removes it, `D` on a session row shows the hint.
- [ ] `config.toml` after `a`/`D` round-trips through `parse_toml` cleanly (no syntax error on next launch).
- [ ] Footer fits on two lines and lists every keybinding.
