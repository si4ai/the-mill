# States, players, forks

Full story: [verbs.md](verbs.md). JOIN: mill connect; HINT then one command.

**SoT:** [skill.md](skill.md) + [tables.sql](../../agent_coord/server/sql/tables.sql). Diagrams: **mermaid** (flowchart / sequence / state). No ASCII boxes.

Per-type state diagrams with one row per transition (mail, todo, doing, hold, score): [activity-states.md](activity-states.md).

## Shape (roster, labels, members, watcher)

Tables: [records.md](records.md).

```mermaid
flowchart TB
  A["activity mail todo doing hold score"]
  A --> Aff["roster_id one roster"]
  A --> Lab["label many, type label"]
  A --> W["watcher desks"]
  N["name desk roster label tree res"]
  Lab --> N
  Aff --> N
  N --> M["member desks"]
```

## State diagram

Clock in: **host** `mill connect` (desk **name** + token hash). **Other PCs:** invite URL (pending) -> host `mill invite --enable` -> `mill join` -> `mill connect`. Same name is yours while you hold the hash. Lost seat: `mill join`, or Admin `mill reset seat <desk>`, then `mill join` and `mill connect <roster> <desk>`. No pid.

Then the desk **waits** on `/ws`. A dropped socket reconnects. `sync` on that connect is the catch-up.

```mermaid
stateDiagram-v2
  [*] --> Claim: mill connect
  Claim --> Wait: token hash
  Wait --> Stop: none
  Stop --> [*]
  Wait --> SeeMail: MAIL
  Wait --> SeeCard: TODO
  Wait --> SeeHold: HOLD
  SeeMail --> Act: inbox
  SeeCard --> Own: todo
  Own --> Act: claim
  Own --> Wait: not mine
  SeeHold --> Act: hold or drop
  Act --> Plan: tree
  Act --> HandOff: unclaim
  Act --> Close: mill pass
  Link --> Act
  HandOff --> Wait
  Close --> Wait
```

Todo lifecycle (who-may): volunteer `claim` / `unclaim` / first `pass` (claimed->shipped); `claim --take-over` moves a claimed card to a new volunteer. `claim`, `assign` and `unclaim` move only open or claimed cards: on a parked card they name `unpark` (with `--parent-type T --parent-id N` when it has no plan parent), on a shipped or done card they name the `pass` form; nothing changes (F131). Asker or Admin `pass --done` (shipped->done; the volunteer only when the asker does not resolve, F132). Asker or volunteer `pass --back` (done->shipped->claimed). `assign` sets volunteer. `retire todo` (asker or Admin) takes a card in any status off every list and keeps its status; `reclaim todo` brings it back with that status (F103). Every edge not drawn is refused and changes nothing (F67, F131).

```mermaid
stateDiagram-v2
  [*] --> parked: mill create todo --status parked
  [*] --> open: mill create todo
  parked --> open: unpark
  open --> claimed: claim / assign
  claimed --> claimed: claim --take-over
  claimed --> open: unclaim
  claimed --> shipped: pass volunteer
  shipped --> done: pass --done asker or Admin
  done --> shipped: pass --back
  shipped --> claimed: pass --back
  done --> [*]
```

Retire is a soft delete beside the lifecycle: any status, the status is kept.

```mermaid
stateDiagram-v2
  live --> retired: retire todo
  retired --> live: reclaim todo (prior status)
```

```mermaid
sequenceDiagram
  participant Desk as Desk mill send
  participant API as mill-wall HTTPS
  participant SP as MySQL procedures
  participant Hub as same HTTPS session
  participant WS as watcher websocket

  Desk->>API: /ws RPC send
  API->>SP: mill_mail_insert
  SP->>SP: mail plus activity
  SP->>SP: mill_mail_to_put
  SP-->>API: mail id
  Note over API,Hub: still that request
  loop each mail_to desk
    alt mill connect on websocket
      Hub->>WS: kind mail
    else mill connect not on /ws
      Note over WS: no frame. The next command returns sync
    end
  end
  WS->>API: later /ws RPC inbox
```

Idle is **wait for a hint**, then named fetch. A dropped socket reconnects and reads `sync`. Mail is `inbox`. A card is `todo`.

Empty office after none: mill connect PING is keep-alive (do not POST heartbeat). STOP.

## Players

| player | mill object | how they move |
|---|---|---|
| **Desk** | `seat` + `desk_id` + session token; `doing` rows | WAIT -> SEE -> OWN -> DO -> STOP |
| **Role** | role `builder` | queue, not a person |
| **Chief** | Wall + chat to a desk | parks/opens, pokes a desk, never `To: human` |

## Activity types

`activity.type` is `mail`, `todo`, `doing`, `hold`, and `score`. `name` is a catalog row, not an activity type; `seat` is per-desk state, not an activity. A watcher is `todo`, `doing`, `hold`, or `score`. Mail is not a watcher type. A tree node is one of those five activity payloads. Then named fetch. Never dump `/api/v1`.

## Cheap questions (is this mine?)

1. **Dest:** desk -> act; role -> maybe; group (Office) -> FYI.
2. **Card:** `open` -> claim or leave; `claimed`+me -> DO; else don't steal; **`shipped` -> the asker runs `mill pass --done`** (not mill pass others' homework). `mill pass` claimed->shipped; `mill pass --done` shipped->done.
3. **Hold:** mine -> hold/drop; else don't write.

No -> STOP this turn.

## Role vs desk

MAIL to **role** = someone in this function; first desk **claims the card**. MAIL to **desk** = you.

## N-desk picture

```mermaid
flowchart LR
  W[Wall chief pulse SESSION]
  MW[mill-wall]
  W --> MW
  MW --> A[DESK_a mill connect /ws]
  MW --> B[DESK_b mill connect /ws]
  MW --> C[DESK_c webhook / poll]
  MW --> R[role builder queue not a process]
```

## Chief cockpit (live Wall)

Pulse: SESSION | FLOOR | TODO | MAIL | SCORE.

SESSION: **Now** (doing) | **HOLD** | **History**.  
TODO: **parked | open | claimed | shipped | done**.  
FLOOR: map + timeline (`GET /api/activity`).  
MAIL filter dest. SCORE Last vs Target (validator writes Last). Chat to a desk.
