# Setup Command — Design

**Date:** 2026-05-22
**Status:** Approved

## Problem

`cmd_spawn` and `cmd_restart` start each server by going straight from port
substitution to `subprocess.Popen(start_command)`. There is no hook for a
preparation step. A freshly spawned worktree has no resolved packages, and a
worktree whose `pubspec.yaml` (or `package.json`, etc.) changed has stale ones,
so the server fails to compile — e.g. `Couldn't resolve the package 'latlong2'`.

The user must currently run `dart pub get` / `flutter pub get` by hand in each
worktree. This should be declarable in the run config and run automatically.

## Solution

Add an optional per-server `setup_command` to `.orchestrator.toml`. It runs
synchronously before `start_command`, on both `spawn` and `restart`.

```toml
[servers.backend]
setup_command = "dart pub get"          # NEW — runs before start_command
start_command = "dart run bin/server.dart"
directory = "server"
```

Single string, mirroring `start_command`. Multiple steps chain with `&&`
(`dart pub get && dart run build_runner build`), which works in both `cmd.exe`
and POSIX `sh` since the command runs with `shell=True`. A string (not a TOML
array) avoids changes to the stdlib-fallback `parse_toml`, which does not parse
arrays.

## Behaviour

- **When:** before `start_command`, on both `spawn` and `restart`.
- **Where:** same `cwd` as the server (`worktree / directory`), so a backend
  setup with `directory = "server"` runs `dart pub get` in `server/`.
- **Env:** same environment as the server — inherited env + secrets +
  `[servers.<name>.env]` overrides — with `{port}` / `{url}` placeholder
  substitution applied to `setup_command` too.
- **Logging:** setup stdout/stderr is captured into the server's log file
  (`<server>.log`) under a `=== setup: <cmd> ===` header, then `start_command`
  output is appended to the same file. `orchestrator logs` and the TUI show it.
- **Failure:** if `setup_command` exits non-zero, print a prominent error
  pointing at the log file, **skip** starting that server, and record it with
  `pid: None` so `status` and the TUI show it `DOWN` rather than omitting it.
  Other servers in the session proceed independently. The `spawn` / `restart`
  command exits non-zero overall if any server's setup failed.
- **Absent:** when `setup_command` is empty/unset, behaviour is unchanged.

## Changes

- `load_config` — parse `setup_command` into each server dict (`""` when absent).
- `cmd_spawn` / `cmd_restart` — in the per-server loop, run the setup step
  before `Popen`; share the log handle; apply the failure handling above.
- `init` template + `references/config-schema.md` — document `setup_command`.
- Sync the companion copy at
  `~/.claude/skills/worktree-orchestrator/scripts/orchestrator.py`
  (CLAUDE.md mandates the two copies stay identical).

## Out of scope

- No TUI changes — the TUI already shells out to `orchestrator.py`, so it
  inherits the behaviour.
- No standalone `setup` subcommand — setup runs only as part of spawn/restart.
- No per-command timeout — setup steps (network installs) block as long as
  they need.
