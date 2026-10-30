# HINT-HANDLER template

Copy into a **task-local** program. Arm it per `SKILL.md`. Call `parse_stdin()` with no argument.

## Contract (from protocol docs - do not invent)

| Item | Rule |
| :--- | :--- |
| stdin | One JSON object. Watcher frame `{type,id,hint,detail?}` (+ optional `desk`/`route`). A letter is `{id,idem,kind,desk}` with `kind` `mail` |
| route_key | `type:hint` (for example `todo:TODO`), or `mail:MAIL` for `{kind: mail}` |
| detail | This desk's `watcher.hint`, or cheap default when NULL (hints.md). A letter has no detail |
| mill-fetch | Leftovers only - MAIL->`mill inbox`; TODO->that card (no full board dump) |
| exit | **0** after STOP - mill connect does **not** mill-update for exit 0 (connect.md) |
| stdout | Read by mill connect. Last line `not-mine` means next. Any other exit 0 is handled. stderr is discarded |
| ignore | `heartbeat:PING`, `doing:DOING` -> exit 0 |

Copy `examples/stub_handler.py`. Do not keep a second skeleton here.

The stub sets its import root to `parents[1]`, which is `docs/protocol/hint-handler` only while the file stays in `examples/`. A task-local copy must set that root to `docs/protocol/hint-handler` or `tools.hint_handler` does not import.

A print is not evidence. The stub appends `hint-evidence.jsonl` beside the program. Replace that write with your task commands. `mill send` pushes the letter. `mill label` / `mill unlabel` on a watched todo, doing, hold, or score are a later write. A mail label does not push another letter.

## Arm and drop

Arm, attach, and drop commands: `SKILL.md` sections 2 and 5. Do not keep a second copy here.
