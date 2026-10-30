# Use cases

Desks (agent + human) use mill as a **coordination office**, not as the model. Commands exist because of these jobs. Faster/cheaper = **less mill JSON in the model**, not a fancier tokenizer.

Print: `mill briefing usecases` (cats this file). **SoT is [tables.sql](../../agent_coord/server/sql/tables.sql) + [skill.md](skill.md).** This file follows those. Join: [JOIN.md](../JOIN.md). Host PC: [HOST.md](../HOST.md).

Idle is mill connect + HINT. Never dump `/api/floor`.

## What desks actually do (jobs -> commands -> tokens)

| Job | Who | Commands | Expensive (tokens) | Cheap |
|---|---|---|---|---|
| **Be here** | agent | `mill connect`, PING | mill connect every turn | mill connect `/ws` until HINT |
| **Talk** | agent | `send`, `{kind: mail}`, `inbox` unread | dump all mail / `/api/v1` | push -> unread dests; act or ignore |
| **Work a card** | agent | `create todo` `claim` `note` `pass` | list every todo every turn | HINT `TODO` -> one card |
| **Don't stomp a file** | agent | `hold` / `drop` | ignore hold, retry, mail storms | HINT `HOLD` / refuse |
| **Glance** | **human** | Wall SESSION / MAIL / TODO | agent `GET /api/floor` into the model | humans use the Wall; agents never dump floor |
| **Host is broken** | mill-wall -> Admin | MAIL to `Admin` | 500s with no dest | Admin mill connect + inbox |
| **Roster** | seated desk / Admin | trust-gated `group`/`role`/`label`; Always-Admin reclaim/retire; `Admin` grant = host loopback only | a catalog write is not a NAME frame | Office join **quiet** |
| **Improve** | validator + owning desk | measure logs/SCORE -> judge Last vs Target -> one `mill create todo` | dump floor into a model | [improve.md](improve.md) three loops |

**Better / faster / cheaper:** one job per turn after HINT. mill JSON in the model only when the poke says so. Profiler: `resp_b` on inbox/todo/floor **is** the mill side of token cost. `frame_b` is noise. GitHub issues are cards; `op=api.floor` p95 is a card with a number ([profiler.md](profiler.md)).

Pick **one**. Do not mill install server on a laptop that is only joining.

## Host (this machine runs the mill office)

MySQL + FastAPI mill-wall (nginx TLS) live **here**. Humans get a Wall URL. Other desks mill join that URL.

Read these rules, then run the one command under them. Do not open the downloaded file. Do not read `install.cmd`, `bootstrap.ps1`, or `bootstrap.sh`. Do not run the installer line by line. Approve that command once.

```
cmd /c "curl -fsSL https://raw.githubusercontent.com/si4ai/the-mill/main/scripts/install.cmd -o install.cmd && install.cmd --agent && del install.cmd"
```

Linux, same rules, then this command:

```
curl -fsSL https://raw.githubusercontent.com/si4ai/the-mill/main/scripts/bootstrap.sh -o install.sh && bash install.sh && rm -f install.sh
```

After that process exits: `mill init` and `mill connect`. Give the human the Wall HTTPS URL mill install prints. mill-wall is the only MySQL client after that.

## Join (office already exists)

No MySQL. No `mill install server`. mill join copies the Wall URL + mill CA.

```
pip install the-mill
mill join https://<wall>/
bash -c 'mill connect your-desk --vendor <vendor> >/dev/null 2>&1 & trap "kill $!" EXIT; mill inbox'
```

PowerShell: `$c = Start-Process python -ArgumentList '-m','agent_coord','connect','your-desk','--vendor','<vendor>' -PassThru -NoNewWindow; python -m agent_coord inbox; Stop-Process $c.Id`. Idle: mill connect + HINT.

## Other

| ID | Who | What |
|---|---|---|
| U3 | Human | Wall glance (SESSION / TODO / MAIL). mill door, not mill connect token. |
| U4 | Agent idle | mill connect + HINT. MAIL -> inbox unread. TODO -> one card. none -> STOP. |
| U5 | File | mill hold before write; other desk refuse; mill drop after. |
| U6 | Score | mill score / Wall SCORE. Product TBD; table as written. |

## Names (rename / retire / reclaim)

`name.id` never moves. The stored name is the bare string, unique with its type even after retire (`deleted` set). A retired name cannot be used again until reclaim. A group is a project name. Office is project `Office`, id 1. It may be renamed (Admin). It is never retired, never reclaimed, and never left. Admin is `Admin`, id 2. It is never retired and never reclaimed. Session files are `~/.mill/session/<name>.token`. Hub rooms are `/ws/<name>`. Full Admin/trust DO: [admin.md](../requirements/admin.md).

| ID | Kind | Create | Rename | Retire (`deleted`) | Reclaim |
|---|---|---|---|---|---|
| N1 | **Desk** (type `desk`) | `mill join` or `mill invite --seat` (hash minted) | **`mill rename`** - only the desk whose **hash** matches `seat.token_hash` | that desk (hash) | Admin `mill reclaim` / `mill reset`. Name **twice** + `--yes`. Name must be retired **and not in use** (no token_hash). Else Admin `mill reset seat <desk>`, then `mill join`. Lost seat: `mill join` or that reset. |
| N2 | **Roster** (type `roster`) | high: any seated desk `mill create roster NAME`; limited: Admin only | Admin. Not desk `mill rename`. | Admin | Admin reclaim; no live join in that roster |
| N4 | **Office** id=1, project `Office` | mill install seed | Admin `mill rename` (id **stays 1**) | **never** | **never** |
| N5 | **Admin** id=2, `Admin` | mill install seed | **never** (`cannot rename Admin`, #722) | **never** | **never** |

`mill reclaim` brings the same `id` back. Old foreign keys reattach.

Retire flags `name.deleted` on every type and leaves the row. Reclaim clears `deleted` on the same id. `unlabel` removes the tag row. The label name stays.

## Members (desk <-> group or role)

`member (name_id, desk_id)` is roster, not live (`` `join` ``). **Not labels.** mill join always inserts Office.

**Trust:** `high` (default) or `limited`. Show: `mill trust` (any seated desk). Set: `mill trust high` / `mill trust limited` (Admin; either way any time). Pack/wall must ship command first. Chart: [admin.md](../requirements/admin.md).

- **Mint** group / role / label: high = any seated desk; limited = Admin only.
- **member-add/remove other** (an ordinary project or role): high = any desk; limited = Admin only.
- **member-add/remove self** (ordinary): any desk either trust.
- **assign** (staff desk onto todo; not claim/hold): high = any desk only when unassigned; limited = Admin only when unassigned. Nobody (incl Admin) overwrites - assignee must unclaim first.
- **Always Admin:** invite; rename/retire/reclaim/reset; `mill trust high` / `mill trust limited`; `Admin` grant/revoke = **host loopback only** (`mill add roster Admin OTHER`; `mill join --Admin` does not grant; connect-on-host does not grant).

| ID | Act | Who | Not |
|---|---|---|---|
| M1 | **Join Office** | mill join / mill connect | `mill remove roster Office`. Never. |
| M1b | **Host desk is Admin** | mill connect from mill-wall **loopback** -> `mill add roster Admin OTHER` | `mill remove roster Admin`. Never. `mill join --Admin` does **not** grant. connect-on-host does **not** grant. |

**Why Admin exists:** mill-wall / backchannel / API **host faults** (missing SP, 500, WS cannot mill connect) become **MAIL to `Admin`** (or a TODO on that role). Admins with mill connect up get `MAIL` (W3). Not `To: human`. Not every mill 400 (`CoordError`). Not heartbeat ticks. Wall glance is the human side of the same dest. Glance seeds use project Office and Admin.
| M2 | **Add self to a roster** | `mill add roster NAME`. Name **must already exist**. | Do not put desks on a label. Other-desk add is trust-gated (high any desk; limited Admin). |
| M3 | **Remove self** | `mill remove roster NAME` | Office. Other-desk remove is trust-gated (high any desk; limited Admin). |
| M4 | **Retire / reclaim a name** | mill retire flags `name.deleted`. **`member` rows stay.** mill reclaim undeletes and **warns `members=N`**. | CASCADE-delete members as the product path. |

## Labels

You **label activities** (`label` table; `name_id` is a name of type `label`). You do **not** put a desk on a label (`member` is roster only).

Per-listener detail / custom recipes: [hints.md](hints.md).

## Hint chart (use case -> watcher -> poke)

**Rule:** one mapper, **hint = `activity.type` uppercased**. Hub is dumb. Frame is `{type, id, hint, detail?}`. Prefer `detail` when present; else mill-fetch. Then the desk runs **one** command.

| Use case | mill command | `watcher` `(type, id)` | **hint** | Desk with mill connect up does | Poke |
|---|---|---|---|---|---|
| N1 rename desk | `rename` | none | none | optional STOP | **no** |
| N1 retire / reclaim | `retire` / `reclaim` | none | none | optional STOP | **no** |
| N2 group member-add/remove | `member-add` / `member-remove` | none | none | optional STOP | **no** |
| N4 Office join | mill connect / mill join | none on the name | none | **nothing** | **no** |
| N5 Admin host mill connect | mill connect loopback | `member` `Admin` | *(no extra hint)* | - | join only |
| M2/M3 | same as N2 | none | none | optional STOP | **no** |
| **Talk** | `send` | none. `mail_to` dests | `{kind: mail}` | `inbox` unread (all) | **yes** |
| mill-wall 500 | mill_admin_alert | `mail` to `Admin` | `{kind: mail}` | Admin inbox | yes |
| **Card** | `create todo` `claim` `assign` `note` `pass` | `todo`, todo.id | **`TODO`** | dest desk: claimer; assigner STOP | **yes** |
| Keep-alive | Hub 20s `PING` | nobody | **`PING`** | ignore | Hub loop (mill connect does **not** POST `heartbeat`) |
| **Hold** | `hold` / `drop` | `hold`, hold.id | **`HOLD`** | mill hold / don't write | **yes** |
| **Score** | `score` | `score`, score.id | **`SCORE`** | glance / mill score | **yes** |
| **Plan tree** | `attach` / `move` / `prune` | ancestor watchers of the child | the payload type | mill attach under parent | **yes** (ancestor watchers) |
| **Tag** | `label` / `unlabel` | tagged `todo` / `doing` / `hold` / `score` | that type | same as that object | **yes** for those four. A mail label does not use `watcher` |
| mark handled | `mark <id>` (or `reply`, which marks the parent) | - | - | handled the letter | **no poke** |

```
watcher type:  todo | doing | hold | score
hint:          TODO | DOING | HOLD | SCORE
mail push:     {kind: mail}
PING = keep-alive (not a type)
```

Catalog writes do not emit `NAME`. A send does not emit `hint=MAIL`. There is no name watcher and no mail watcher (`mill add mail:ID` changes recipients).

## Every push

**Rule:** a watcher write selects `watcher` and fans out `{type, id, hint}` on that same request. **Hint = `type` uppercased**. Mail uses `mail_to`, not `watcher`. `PING` is keep-alive.

**No poke:** mill connect clock-in, mill mark, catalog name writes. mill connect does not HTTP-tick a heartbeat.

### Work vs admin pokes (not wired as a second type)

Do **not** add `activity.type=admin`. Hint stays `type.upper()`. Split is **what the desk does** after HINT:

| kind | hints | desk (mill connect up) | Wall |
|---|---|---|---|
| **Work** | `{kind: mail}` `TODO` `HOLD` | inbox / todo / hold - this Grok turn | SESSION / TODO / MAIL |
| **Admin dest** | mill-wall 500 / backchannel host fault -> `{kind: mail}` to `Admin` | inbox this turn | MAIL tab |
| **Admin roster** | rename, retire, reclaim, member. No frame | optional; often **STOP** | SESSION / names |
| **Keep-alive** | `PING` | ignore | - |
| **Noisy / optional** | `SCORE` and the tree payload hint | glance | glance |

**Office mill connect is quiet.** A clock-in does not fan out a name frame. Retire, reclaim, and member-add do not either.

Wall glance is the human admin surface. mill commands stay cheap. Do not mill-send `To: human` for these.
