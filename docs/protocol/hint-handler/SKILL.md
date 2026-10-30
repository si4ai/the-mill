---
name: hint-handler
description: >
  Cold-desk playbook: customize one watcher HINT, write a deterministic handler,
  arm it with mill route. Use after the human approves background mode.
  Not a second mill CLI. Cite connect/route/hints.
metadata:
  short-description: "HINT handler: program, mill route, watcher recipe, drop"
---

# HINT handler - background program map

**Cold desk:** read [COLD.md](COLD.md) and `examples/stub_handler.py` only. Do not open the rest of this file, or philosophy, hints, route, connect, or JOIN, unless a command there exits non-zero.

**When:** human asks a task -> collab needed -> agent explains modes (incl. background HINT handler) -> **human approves background**. Then this skill.

**Cite when a step failed:** `docs/protocol/philosophy.md`, `connect.md`, `route.md`, `hints.md`, `JOIN.md`. Chat inbound stays mill-desk / skill.md.

**Not this skill:** chat inbound (mill-desk). Default vendor poke when no route hits (route.md). Inventing mill commands.

## Lifecycle (program -> route -> watcher -> trigger -> drop)

### Guards

No poll. No invented mill commands. Exit **0**. `heartbeat:PING` and `doing:DOING` are dropped on receive, before any route program. Do not arm `doing:DOING`. A missing route does not vendor-poke DOING.

A watcher is one desk on one of `todo`, `doing`, `hold`, or `score`. Mail is not a watcher type. Nothing emits `name:NAME`. Mail arrives as `{kind: mail}`. Trees, labels, and memberships organize work. They are not watch targets. `roster_id` is only the project or role collection. Another desk attaches its own watcher. Do not expect every project member to be watched.

Vendor poke, when no route hits, is the fallback. It is not this playbook. A future vendor webhook is that same fallback, not a second router.

### 1. Write the handler first

Copy `examples/stub_handler.py` to `~/.mill/handlers/DESK_<desk>/on_mail.py`. Import `tools.hint_handler`. Call `parse_stdin()` with **no argument**. Passing `sys.stdin` raises `TypeError`.

`ev.detail` is this desk's `watcher.hint` string, or the cheap default `{what,id,when,state,watchers,tree}` when that hint is empty. A letter has no `detail`. The wire `hint` on a watcher frame stays `TYPE`. The route key stays `mail:MAIL`, `todo:TODO`, and so on. A recipe does not change the key.

`log()` writes stderr. mill connect reads the route child's stdout: a last line of `not-mine` tries the next redirector, and any other exit 0 is handled. stderr is discarded. A print is not evidence. The stub appends one line to `hint-evidence.jsonl` beside the program (`detail_kind` is `recipe` or `default`). Replace that write with the mill command the task needs.

Keep the program. Reuse it. It is not package code.

### 2. Arm

The desk is the sitting connect. One shell arms, attaches, and stays up to deliver frames. Run it in a call allowed to keep running:

```text
bash -c 'mill connect <desk> --vendor <vendor> >/dev/null 2>&1 & trap "kill $!" EXIT
mill route add mail:MAIL -- python ~/.mill/handlers/DESK_<desk>/on_mail.py
mill route add todo:TODO -- python path/to/on_todo.py
mill add todo:<id> --hint "need,status"
wait'
```

`mill route` waits for that connect to sit. Everything after the key is the program. The catch-all key is `"*"`, quoted so the shell does not expand it. The list is a chain in add order. Exit 0 with any last stdout line other than `not-mine` means handled (stop). Print `not-mine` last and exit 0 to pass to the next redirector. mill connect re-reads the chain on every frame. No restart. The route file stays after the shell exits.

Every other `mill connect` for this desk is refused as busy while this one is up; `mill connect --take` takes the seat from this one (`superseded (4000)`), and this one does not come back. Run later desk commands before `wait`, or stop this shell first.

`--session` on connect is the Grok session id for a grok-build poke. Omit it unless that poke needs it.

### 3. Customize the HINT, then trigger

The `mill add` line in the arm shell attaches this desk to **that activity**.

Empty hint restores the cheap default. The recipe is a short field list for **your** program. mill does not parse it.

The trigger is a **later write** on that same activity (claim, hold refresh, score the same name, or `mill label` on that id). A write from before connect is up is a missed push. It is not replayed.

`mill send` pushes `{kind: mail}` to each dest. It does not use `watcher`. `mill create todo` pokes inside the insert. That first poke is before a custom `--hint` can exist on the new id. Read the id from the insert JSON, set `mill add`, then a second write on that same id. `mill label <type> <id> bug` is that second write.

### 4. Run (on each HINT)

stdin is one JSON object. A watcher frame is `{type,id,hint,detail?}`. A letter is `{id,idem,kind,desk}` with `kind` `mail` and no `type` or `hint`. Its route key is `mail:MAIL`.

1. `parse_stdin()` -> if `ev.ignore`, exit 0.
2. Read `ev.detail`. mill-fetch leftovers only when the recipe still needs the book (MAIL inbox, that one TODO - no full board).
3. Task mill commands only. **STOP**.
4. Exit **0**. mill connect does not mill-update for exit 0.

### 5. Drop

Stop the arm shell, then:

```text
bash -c 'mill connect <desk> >/dev/null 2>&1 & trap "kill $!" EXIT; mill route rm mail:MAIL'
```

## Worked paths (short)

| Path | Arm | Customize | On HINT |
| :--- | :--- | :--- | :--- |
| MAIL | `mill route add mail:MAIL -- python .../on_mail.py` (arm shell) | no watcher. The send push is the trigger | parse -> detail -> inbox leftovers only if needed -> STOP -> exit 0 |
| TODO | `mill route add todo:TODO -- python .../on_todo.py` (arm shell) | `mill add todo:<id> --hint "need,status"` | parse -> detail -> that card only -> STOP -> exit 0 |

See `HINT-HANDLER.TEMPLATE.md`, `examples/stub_handler.py`, `tools/hint_handler/`. Cold steps that ship in the pack: `COLD.md`.
