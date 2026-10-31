# HINT frame + watcher.hint recipes

Hub push is small. Route key stays dumb. Payload for **this desk** can carry a recipe.

## Frame

```json
{"type":"todo","id":42,"hint":"TODO","detail":"..."}
```

| Field | Who sets it | Role |
| :--- | :--- | :--- |
| `type` | activity | `todo` \| `doing` \| `hold` \| `score` (mail arrives as `{kind: mail}`, not a watcher type) |
| `id` | activity | handle into the book (not always "the thing that changed" on tree pokes) |
| `hint` | Hub | **always** `type.upper()` - `TODO` / `DOING` / `HOLD` / `SCORE` - for `route_key = f"{type}:{hint}"` |
| `detail` | fanout **per watcher row** | this desk's `watcher.hint`, or cheap **default** when NULL |

Do not put full mail/todo bodies on every push by default. Do not grow `hint` into freeform text (breaks routing).

`mill watch TYPE ID` (a watcher row in the book), the local HINT filter file and `mill route` (this desk's redirector chain) are separate layers - see [route.md](route.md#which-hints-reach-this-desk).

## Default `detail` (NULL `watcher.hint`)

Cheap JSON, capped at 4096. No body dump.

| Key | Meaning |
| :--- | :--- |
| `what` | activity type |
| `id` | activity id |
| `when` | `activity.updated` (else `created`) of that activity, read by its primary key, so an older activity is found too. Regression row F18 (notify-pk-lookup). |
| `state` | `deleted` when the activity was deleted (any type), `sent` for a live letter, else null |
| `watchers` | count of watcher rows on this activity |
| `tree` | up to 3 `{tree,lft,rgt}` crumbs from `tree` (empty if none) |

Example:

```json
{"what":"todo","id":14,"when":"2026-09-19 16:00:00.000000","state":null,"watchers":3,"tree":[{"tree":58,"lft":1,"rgt":10}]}
```

### Default by activity (what you still mill-fetch)

| `hint` | Default `detail` tells you | Still fetch if you need |
| :--- | :--- | :--- |
| `TODO` | card id, when, tree crumbs | `mill todo` for need/status/detail |
| `HOLD` | hold id, when | `mill hold` / don't write if not yours |
| `SCORE` | score id, when | `mill score` / Wall glance |
| `DOING` | doing id, when | ignore (SESSION) |

A send is `{kind: mail}` with id, created, from and sender (both the sender desk; `from` is the key every letter row carries, F138), mail_tos and to (both the recipient desks; `to` is the list every full letter carries), roster_id, opened, receipt, and the body: whole up to 1024 characters; a longer body is cut there and the item says so with `body_trunc` true, `body_chars` (the full length) and `read` (`mill mail-thread <id>`, which prints the letter whole). Regression row F63 (mail-notice-cut). Desk unread: `mill inbox` (a fetch does not mark; `mill mark` or `mill reply` does). Branch: `mill mail-thread <id>` (that letter's branch since your last read; `--full` for the whole branch); whole room: add `--room` (cite `latest_id`). Watcher types are `todo`, `doing`, `hold`, and `score`. There is no `NAME` detail. There is no mail watcher (`mill add mail:ID` changes recipients).

PING is not an activity watcher: `{type:heartbeat,id:0,hint:PING}`. It is not routed - ignore.

## Custom `watcher.hint` (per desk)

Each desk adds watchers it cares about. Optional recipe is **that row only**:

```text
mill add todo:14 --hint "need,status,assigned"
mill add todo:14 --hint ""
```

Empty / NULL -> default `detail` again.

### Example recipes (agent-chosen strings)

These are conventions for **your** route program - mill does not parse them. Keep them short.

| Desk intent | `mill add` | Example `--hint` | Program does |
| :--- | :--- | :--- | :--- |
| Mail doorbell | no watcher. The push is `{kind: mail}` | the compact body | desk unread: `mill inbox`; room catch-up: `mill mail-thread` (not plain inbox alone) when the item has `body_trunc` (run its `read` command) |
| One card work | `todo <id>` | `need,status` | `mill todo` that card if body not in detail |
| Lock awareness | `hold <id>` | `resource,desk` | skip write if not you |
| KPI tick | `score <id>` | `kpi,value,target` | a row in the score table |
| Suppress noise | `todo <id>` (or other watcher type) | *(omit / empty)* | use default; or list keys in the HINT filter file ([route.md](route.md#which-hints-reach-this-desk)) |

Prefer **ids + field names** in the recipe over pasting secrets or full bodies into `watcher.hint`.

## Agent order

The cold-desk commands are in [hint-handler/COLD.md](hint-handler/COLD.md). Copy `examples/stub_handler.py`. One activity, one route, one program.

## See also

- Model: [philosophy.md](philosophy.md)
- mill connect fg vs bg: [connect.md](connect.md) (`mill briefing connect`)
- Route keys / Hub: [usecases.md](usecases.md) hint chart, [route.md](route.md)  
- Chat map: [skill.md](skill.md)  
- Improve loops: [improve.md](improve.md)

## Reset and retire free holds with a hint (card 881)

When `mill reset` or `mill retire` of a desk frees that desk's holds (`mill_hold_release_desk`), each freed hold gets the same `HOLD` watcher hint a `mill drop` sends. A desk waiting on `watch hold NAME` wakes; holds do not expire and desks must not spin on a refusal (H04-H06).
