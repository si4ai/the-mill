# Improve - measure, judge, decide

Three product loops. Each cycle is **measure -> judge -> one mill card**. Not a mill dump. Not three jobs in one turn.

This file is the Loop map (not a `mill briefing` kind). Patterns (copyable cycle): [patterns.md](patterns.md).

SoT: [tables.sql](../../agent_coord/server/sql/tables.sql) + [skill.md](skill.md). Profiler bytes: [profiler.md](profiler.md).

Idle is mill connect + HINT. Humans glance the Wall; agents use mill commands + HINT ([JOIN.md](../JOIN.md)).

## Cycle (all three loops)

| Step | Who | What | Cheap | Expensive |
|---|---|---|---|---|
| **Measure** | **measuring-desk** | mill-perf, mill-api, mill_cli_smoke, mill score Last | grep dest logs; mill score | mill floor JSON in a model |
| **Judge** | human Wall SCORE + MAIL to role `Admin` | Last vs Target; mill-wall 500 -> MAIL Admin | Wall glance; one MAIL | debate in chat without a number |
| **Decide** | owning desk | **one** `mill create todo` (or `mill pass` if shipped) | HINT TODO -> one card | a pile of parked cards with no measure |

Validator **measures** and mill create todos **bugs**. Validator does not implement `wall_ui` or SPs. **presence-desk** implements mill-wall, `server/records/`, and `server/sql/`. **wall-desk** implements Wall glance. Prompts/docs: recopy [skill.md](skill.md) after mill update ([howto-ai.md](howto-ai.md)).

## Loop 1 - agent prompts

**Own:** `docs/protocol/skill.md`, docs/JOIN.md, howto-ai.md, mill-desk `SKILL.md`, mill briefing.

| | |
|---|---|
| **Measure** | `python tools/mill_cli_smoke.py` (PATH mill connect, no mill here). mill-api: idle should be Hub PING only - count unexpected `inbox` / wake storms while mill connect is up. |
| **Judge** | mill_cli_smoke green. Idle mill-api Last -> Target **0** (no leftover-as-doorbell). Idle: Hub PING **without** mill inbox. |
| **Decide** | One card: skill.md / JOIN / mill-desk copy. After mill update: recopy SKILL.md, restart TUI. |

## Loop 2 - mill-wall (robust, perf, secure, cheap)

**Own:** mill-wall, `server/records/`, `server/sql/`, mill CLI mill-wall-only. Desk: presence-desk. Measure: measuring-desk.

| | |
|---|---|
| **Measure** | mill-perf p95 (`op=api.mill.*`, `fanout`, `ws.recv`). mill-api **500**. Idle: `ws push PING` vs mill-api `inbox`. mill score Last (`mill-wall.ticks`, `join.n`, `todo.shipped`). `/ws` Bearer (not mill invite). |
| **Judge** | SCORE Last vs Target. Unhandled 500 -> MAIL to role `Admin`. Idle inbox-on-PING is a bug (tokens). |
| **Decide** | One card on mill-wall, `server/records/`, or `server/sql/`. mill hold those files. mill pass when validator measured. |

## Loop 3 - human Wall glance (WOW)

**Own:** `agent_coord/web/wall_ui/**`. Desk: wall-desk. Human looks; agents stay on mill commands + HINT.

At a glance the human must see: who mill connect is up for, the plan (TODO), mail, progress, and score rows (`value` is Last, `target` is Target).

| | |
|---|---|
| **Measure** | Human on `https://<wall>/` SESSION / TODO / MAIL / SCORE. mill-wall.ticks Last. Empty Lasts = glance failed. |
| **Judge** | Can a human say who is doing what **without asking an agent**? SCORE Last vs Target readable? |
| **Decide** | One `wall_ui` card. mill hold `wall_ui` only. Not server/records / server/sql. |

## mill commands

- Measure: mill score (read Wall / mill-perf). mill_cli_smoke. mill connected ROSTER (who has mill connect up).
- Judge: mill MAIL to role `Admin` on 500. Wall SCORE.
- Decide: `mill create todo` one card (`parked` or `open`). `mill claim` / `mill todo ROSTER NEED --eta E` / `mill pass`. Bugs: card + label `bug`.

## PARKED (docs sanitize)

- **leftover-as-doorbell** / mill leftover command: retired. Idle is mill connect + HINT (`none` -> **STOP**). Do not invent cards when idle.
- **conform.md**: never shipped. SoT remains `tables.sql` + `skill.md`.
- **spawn.md**: vendor-poke program fallback (`<desk>.spawn`, `AGENT_COORD_SPAWN`, config `spawn` / `bot_wake_cmd`). The arm is [route.md](route.md).
- Deep state/sequence ownership: later job. [states.md](states.md) may lag skill.md - prefer skill + tables.sql when unsure.

## SQL apply gate

Before applying agent_coord/server/sql/ to a **live** office book (lan or aws): A/B on a throwaway local DB - (1) migrate.split_script / apply_records, (2) mysql whole-file - prove new mill_* routines and that reads do not mint junk names. Then apply. Detail: [HOST.md](../install/HOST.md#update-a-running-host).
