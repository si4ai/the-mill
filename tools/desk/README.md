# desk-start (workstation)

Fresh-start launcher for Grok Build desks. One config file describes an office
and its desks; the script never hard-codes desk names, paths, models, or
office names. Real config lives **outside** the repo (for example
`%USERPROFILE%\.config\mill-desk\desks.json`). This folder ships only an
example and the launcher.

## Requirements

- Windows workstation with Grok Build CLI (`grok` on PATH). Verified against
  `grok --help` on grok **1.0.70**: usage is `grok [OPTIONS] [PROMPT] [COMMAND]`,
  where `[PROMPT]` is the initial interactive prompt.
- Per-desk secrets in **Windows Credential Manager** (target name in config;
  the script never prints or embeds a secret).
- Run as a normal user when you can. If you must run elevated, stay
  conservative: the script never deletes sessions and never writes outside
  each desk's `work_dir` / `export_dir`.

## Install

1. Copy `desks.example.json` to a path outside any git checkout.
2. Edit office + desk entries (paths, credential targets, labels).
3. Create each Credential Manager target named in the config (UI or `cmdkey`).
4. Create each desk's `work_dir` and `export_dir` folders.

## Usage

```powershell
# Plan only (no launch)
.\desk-start.ps1 -Config $env:USERPROFILE\.config\mill-desk\desks.json -Desk example-desk -DryRun

# One desk
.\desk-start.ps1 -Config ...\desks.json -Desk example-desk

# Several desks
.\desk-start.ps1 -Config ...\desks.json -Desk desk-a -Desk desk-b

# Every desk in the config
.\desk-start.ps1 -Config ...\desks.json -Desk all
```

Flags: `-Config <path>` (required), `-Desk <name>` (repeatable, or `all`),
`-DryRun`.

## What it launches

```
grok --cwd <work_dir> [--agent <agent_file>] [--add-dir ...] [-m model]
     [--reasoning-effort ...] -s <new-uuid> "<first message>"
```

- Permission mode defaults to `default`. `bypassPermissions` is refused unless
  the config sets `allow_bypass_permissions: true` (emits a warning).
- Never passes `-r` / `--resume`, `-c` / `--continue`, `--fork-session`, or `-p`.
- Optionally runs `grok export <prior-id> <export_dir>/<id>.md` when
  `export_before_restart` is true. Old sessions are **kept** (never deleted).
- Writes `session.json` only under the desk folder (new session id for a later
  resume).

## Config schema (summary)

**office:** `mill_office`, `roster`, `mill_connect_template` (placeholders
`{mill_office}`, `{roster}`, `{desk}`), `export_before_restart` (bool).

**defaults:** `permission_mode`, `allow_bypass_permissions`, lesson/handoff
caps, `first_message_template`.

**desks[]:** `name`, `work_dir`, `export_dir`, `agent_file`, `model`,
`reasoning_effort`, `permission_mode`, `credential_target`, `lessons_label`,
`lessons_byte_cap`, `lessons_count_cap`, `handoff_letter_id` or
`handoff_query`, `add_dirs[]`, `first_message_template` (placeholders
`{desk}`, `{lessons_label}`, `{mill_office}`, `{roster}`).

Validation fails closed with a clear error (missing file, unknown desk,
empty required path, unsafe permission mode without the allow flag).

## Safety

- No deletes of Grok sessions or desk files.
- Writes only under each desk's `work_dir` parent (session.json) and
  `export_dir`.
- Secrets: Credential Manager **target names** only in config, plans, and logs.
- Seat busy: refuse; never `--take`.

## CI / plan logic

`desk_start_plan.py` is the pure planner used by tests and by `-DryRun`
consumers. It loads the same JSON shape. Outside teams can call:

```bash
python desk_start_plan.py --config desks.example.json --desk example-desk
```
