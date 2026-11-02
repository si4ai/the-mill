# State instrumentation map (0.8.5 / ce115f8)

State map for card 1001 children (0.8.6). Sync: `origin/main` `ce115f8`.

**Sources:** `docs/protocol/activity-states.md`; `verify/spin/{wake,mail,holds,doing,todo}.pml`; verify packages wake/mail/hold/doing-code (PRs #330-#334) and todo-code (#270); code under `agent_coord/server/{wake,push,hold_blocked,score_tick,score_series}.py`, `api/mill/rpc.py`, `sql/*.sql`.

**Rule:** one durable server event per protocol transition.

**0.8.6 plan (letter 4317 / 980-plan.md):** feature events land in shared `transition` (card **1022**); performance/health in metric stream (**1023**); opt-in `share.transitions` (**1024**) and `share.metrics` separate; emitters **980/981/982/970/1002**; desk score writes out (**1021**); `seat.doing_id` drop after 970 (**1025**).

**Design layers:** *current* = shipped 0.8.5 at `ce115f8`. *0.8.6 target, per plan* (plan today): (a) doing comes only from tw (970), never a hand-set `--doing` column - optional context is tw flags only (title, `--card`); (b) a desk may run several tw tasks at once, each with its own doing lifecycle - `seat.doing_id` single pointer and D6 supersede are current-only; (c) score stays an activity, but desks no longer write it - the server writes every score from real state changes (new card score-read-only under 1001). Findings 1019/1020 stay on score.

**1001 children (emit targets):**

| Card | Need | Activity |
|------|------|----------|
| 980 | mail-activity-score | mail (+ wake latencies that touch mail) |
| 981 | hold-activity-score | hold |
| 982 | open-cards-queue-score | todo (card state ages / flow) |
| 970 | TaskWrapper (tw) | doing (sole writer in 0.8.6 target) |
| 1002 | wasted-wake-score | wake (measurement only; claimed) |
| (new) | score-read-only | score (server-written from other activities) |

**Legend:** *Stamp* = server timestamp column or log field that marks the transition today (`path:line` at ce115f8). *Child* = which 1001 child should emit a dedicated event if missing or incomplete. *Cov* = already named on that child vs **gap**.

---

## Summary counts

| Activity | States | Transitions | Stamp today | Emit gaps | Live cards |
|----------|--------|-------------|--------------------|------------------|----------------|
| wake | 8 | 18 | 11 (mostly log-only) | 7 | 1005 -> 1002 |
| mail | 5 | 14 | 9 | 5 | size-limit -> 980; retries cross-cut |
| todo | 6 (+ retired) | 15 | 12 | 3 | feeds 982 |
| doing (current) | 7 (seat+one entry) | 14 | 10 | 4 | 1017, 1018 -> 970 |
| doing (0.8.6 target) | seat + **N task** lifecycles | 12 per task (+ seat) | tw events TBD | see §4 | 1017/1018 **per task** -> 970 |
| hold | 3 | 9 | 6 | 3 | 1013 -> 981 |
| score (0.8.6 target) | 4 | 7 server-triggered | tick/admin today | desk CLI write drops | 1019, 1020 |
| **Total (current five + wake)** | **29** | **70** | **48** | **22** | |

983 / 1029 are dev tooling (card 1051), see docs/dev/regression/README.md.

---

## 1. Wake (delivery path; not `activity.type`)

Wake is middleware delivery: push queue -> webhook POST -> lease -> connect sync -> wake-done / lease timeout / retry. States from `verify/spin/wake.pml` + `verify/wake-code` view labels.

### States

| State | Meaning |
|-------|---------|
| idle | no lease, no retry, no pending work |
| push_pending | `push_queue` row waits (`outcome` missed/error) |
| unread_owed | unread `mail_to` with no successful wake yet |
| lease_live | `_GATE[desk]` held (`wake.py` lease) |
| retry_armed | `_arm_retry` chain alive |
| sitting | desk has a live socket |
| lost_unread | failed unread-only wake never retried (**1005**) |
| drained | queue empty after connect / drain stop |

### Transitions

| # | From | To | Trigger | Stamp today | Cov / child |
|---|------|----|---------|-------------|-------------|
| W1 | idle | push_pending | item queued (`emit` / fanout) | `push_queue.created` `sp_push.sql:31-32` | partial -> **1002** (need kind+reason on row or event) |
| W2 | * | unread_owed | mail_to unread exists | `mail_to.created` + `opened IS NULL` `tables.sql:224-229` | derived; **1002** / 980 for owed-wake clock |
| W3 | push/unread | lease_live + sent | `post_desk` POST 2xx | log `_wake_log` ... `wake=sent` `wake.py:1161` via `826-834` | log-only -> **1002** durable event |
| W4 | push/unread | lease_live + fail | `post_desk` POST fail | log `wake=fail` `wake.py:1166` | log-only -> **1002** |
| W5 | fail + push | retry_armed | `_arm_retry` when `pending > 0` `wake.py:1170` | log on arm/retry `wake.py:1032,1060` | **1002**; **gap** for unread-only (**1005**) |
| W6 | retry_armed | drained/idle | `_queue_drained` stops chain `wake.py:1018` | log outcome `wake.py:1032` | **1002** |
| W7 | lease_live | trail fire | `_send_trailing` after done/expire `wake.py:695-723` | log + optional post | **1002** |
| W8 | leave + missed | ring fire | `ring_waiting` `push.py:251-273` | log via `post_desk` | **1002** |
| W9 | lease_live | idle (done) | `mill wake-done` `lease_done` `wake.py:770-823` | log `wake=done` / return string; **no DB column** | **1002** (pair with action-or-not for waste) |
| W10 | lease_live | idle stale | stale token `wake.py:788-801` | return `"stale"`; log | **1002** recovery |
| W11 | lease_live | idle sitting | done while sitting -> no trailing `wake.py:812-818` | return `"sitting"` | **1002** |
| W12 | lease_live | expire | lease timeout -> trail `wake.py:746` reason=`lease-expired` | log `wake.py:748` | **1002** recovery |
| W13 | * | coalesced | item during live lease `wake.py:1118,1134` | log `coalesced reason=lease` | **1002** (held-back count) |
| W14 | * | skipped | room-only / not-allowed / not-public `wake.py:1113-1126` | log skipped | **1002** |
| W15 | * | sitting | first socket | `seat.time_connect` `sp_join.sql:386` | covered as connect stamp |
| W16 | sitting | left | last socket leave | `seat.time_disconnect` `sp_join.sql:388` | covered |
| W17 | push_pending | drained | connect sync take/ack | push rows deleted / outcome sent `records/push.py` + `sp_push` take | partial -> **1002** deliver stamp |
| W18 | unread_owed | lost_unread | fail with no arm (**1005**) | **none** (finding) | **gap -> 1002** (and fix 1005) |

### Failure / recovery transitions

| Event | Exists? | Stamp | Child |
|-------|---------|-------|-------|
| retried | yes (push-pending only) | log `reason=retry` `wake.py:1060` | 1002 |
| re-rung | yes (trail / ring) | log trailing/ring tags | 1002 (+ 980 re-ring count) |
| expired (lease) | yes | log `lease-expired` `wake.py:746-748` | 1002 |
| owed never fired | **no durable event** | none | **1002 / 1005** |
| why fired (hold_release / room_or_fyi / rering_handled / version_notice / other) | **no** | none | **1002** (in progress) |
| wasted wake (done with no action) | **no** | none | **1002** |

### Already on 1002 vs gaps

- **Covered by 1002 scope:** wasted wake; why-fired tags; measure-only.
- **Gaps to emit:** W3/W4/W9 durable (not only `_bc_log`); W5 unread arm (**1005**); W18 owed-never-fired; W1 reason on queue row; retry count+outcome per wake attempt.

---

## 2. Mail (`activity.type=mail`)

States from `docs/protocol/activity-states.md` + `mail.pml` (M1-M8).

### States

Letter: **none -> live -> deleted**. Per recipient (`mail_to`): **unread -> handled -> removed**.

### Transitions

| # | From | To | Trigger | Stamp today | Cov / child |
|---|------|----|---------|-------------|-------------|
| M1 | none | live + unread rows | `mill send` | `mail.created` `sp_mail.sql:271`; `activity` act=`send` `:273`; `mail_to.created` via `mill_mail_to_put` `:15-39` | **980 sent** |
| M2 | none | reply live; parent handled | `mill reply` | new `mail.created` + parent `mail_to.opened` via open path | **980 sent/answered** |
| M3 | unread | handled | `mill mark` | `mail_to.opened` `sp_opened.sql:35-36` (first kept) | **980 read** |
| M4 | unread | handled | whole `mail-thread` | same `opened` via `_mark_shown` | **980 read** |
| M5 | unread | unread | preview inbox / room | **none** (no write) | n/a |
| M6 | handled | handled | mark/reply again | `opened` not rewritten when set (`AND opened IS NULL`) | first-open kept; no new event needed |
| M7 | not recipient | unread (+ subtree handled) | `add mail:N` | `mail_to.created` | **980** (recipient add) |
| M8 | recipient | removed | `remove mail:N` | row delete (no tombstone stamp on mail_to) | **gap -> 980** remove event |
| M9 | live | deleted | no CLI | `activity.deleted` if SP runs | gap (no CLI) |
| M10 | live | delivered to desk | push row / live frame | `push_queue.created` `sp_push.sql:31`; outcome later | **980 delivered** (partial: outcome not a time series event) |
| M11 | delivered | woken | wake POST for mail | log `_wake_log` only | **980 woken** + **1002** |
| M12 | handled/unread | answered | reply under thread | reply `mail.created` | **980 answered** |
| M13 | * | refused | body `len>4096` | raise only `rpc.py:1557-1558`, `1914-1915` (**no event**) | **gap -> 980** size-limit hit |
| M14 | insert | rolled back | no recipients | SIGNAL `sp_mail.sql` orphan guard | refuse path; **980** should count refuses |

### Failure / recovery

| Event | Exists? | Stamp | Child |
|-------|---------|-------|-------|
| refused (size) | yes (error to client) | **no counter/event** | **980** |
| truncated into store | no (refused) | n/a | keep refusing; still emit hit count |
| receipt pushed | code path exists; CLI send forces receipt=0 | `push_receipt` `sp_opened.sql:41` | 980 if receipts enabled |
| never-answered | derivable | `mail_to.opened` null / no reply child | **980** |
| re-rings | wake path | wake logs | **980** + **1002** |

### 980 coverage vs gaps

- **Named on 980:** sent, delivered, woken, read, answered; send-to-wake; wake-to-answer; re-rings; never-answered.
- **Gaps:** size-limit hit event; remove (M8) event; durable wake-delivery join key; retry counts on send/reply (cross-cut).

---

## 3. Todo / cards (`activity.type=todo`) -> child **982**

States: `parked | open | claimed | shipped | done` + flag `retired` (`activity.deleted`). Transitions T1-T14 from activity-states + `todo.pml`.

### Transitions

| # | From | To | Trigger | Stamp today | Cov / child |
|---|------|----|---------|-------------|-------------|
| T1 | none | open | create | `todo.created` `tables.sql:256`; `activity` act create `sp_todo.sql:49` | **982** open |
| T2 | none | parked | create --status parked | same + act park | **982** |
| T3 | parked | open | unpark | `todo.updated` + move row `mill_doing_move` `sp_todo.sql:265` | **982** |
| T4 | open | claimed | claim | `todo.claimed_at` `sp_todo.sql:214-219`; act claim | **982** |
| T5 | open | claimed | assign | `claimed_at` + move peer | **982** |
| T6 | claimed | claimed (other) | claim --take-over | `claimed_at` refresh | **982** |
| T7 | claimed | open | unclaim | `claimed_at` NULL; act unclaim | **982** |
| T8 | claimed | shipped | pass | `todo.updated` + act ship + evidence | **982** |
| T9 | shipped | done | pass --done | `updated` + act done | **982** |
| T10 | done | shipped | pass --back | `updated` | **982** |
| T11 | shipped | claimed/open | pass --back | `claimed_at` if claimed | **982** |
| T12 | any | retired | retire | `activity.deleted` `sp_todo.sql:392-394` | **982** (exclude/flag fixtures) |
| T13 | retired | prior status | reclaim | `activity.deleted` cleared `:423` | **982** |
| T14 | any | same | note / done-when | `todo.updated` / body; often no status move | diary; optional **982** |
| T15 | live | deleted | probe only | tombstone | n/a CLI |

### 982 coverage vs gaps

- **Named on 982:** open/claimed counts; age in current state; open vs closed/day; median open->claimed->shipped->done; oldest stuck.
- **Have stamps:** status+`updated`/`claimed_at`/`created`/`deleted` enough to derive ages for T1-T13.
- **Gaps:** explicit per-transition event id (act is on `activity.act` / doing move - usable); force-take-over marked as contention; retire/reclaim excluded from speed medians; **cross-cut retries** on claim/pass.

Liveness: stuck ages feed process health; pairs with **1018** (desk crash leaves card claimed) via desk+card join on 970/982.

---

## 4. Doing (+ tw card **970**)

### Current (ce115f8)

Seat + **one** focus entry via `seat.doing_id`. Hand-set `--doing` / `--waiting-on` on any command. Sources: activity-states D1-D11, `doing.pml`, verify/doing-code (single pointer).

**States (current):** seat `no_seat|seated|connected|reset`; entry `idle|active|waiting|finished|cleared`.

**Transitions (current):** D1 join; D2/D3 connect/leave (`seat.time_connect`/`time_disconnect` `sp_join.sql:386/388`); D4 `--doing` -> active (`doing.created` `sp_doing.sql:170`, `seat.doing_id`); D5 `--waiting-on`; **D6 newer `--doing` supersedes** (current-only); D7-D9 derived finish; D10 clear on reset/retire; D11 reset; D12 cycle undetected (**1017**); D13 stale after crash (**1018**); D14 heartbeat (`seat.updated` only).

Counts (current): **7 states, 14 transitions, 10 stamped, 4 gaps.**

### 0.8.6 target, per plan

Doing comes **only from tw** (970). No hand-set column. Optional context: tw flags only (title, `--card`). A desk may run **N concurrent tw tasks**; each task has its own lifecycle. `seat.doing_id` single pointer and **D6 supersede do not apply**.

#### Per-task states (N ≥ 1)

| State | Meaning |
|-------|---------|
| idle | slot free / not started |
| active | tw running (optional `--card`, title) |
| waiting | tw blocked (stall, `--idle`, or wait cause) |
| finished | tw exited ok (end reason finished) |
| failed | tw exited non-zero / crash detected by tw |
| stale | tw dead or desk gone; task row not cleared (**1018 per task**) |
| cleared | admin reset/retire cleared this task |

Seat states D1-D3/D11 remain desk-level (join/connect), not per-task.

#### Per-task transitions (0.8.6 target)

| # | From | To | Trigger | Stamp (target) | Child |
|---|------|----|---------|----------------|-------|
| Tsk1 | idle | active | `tw` start (title / `--card`) | tw register event (new) | **970** |
| Tsk2 | active | waiting | stall / wait cause | tw wait event | **970** (**1017** if cycle) |
| Tsk3 | waiting | active | wait cleared | tw resume | **970** |
| Tsk4 | active/waiting | finished | tw exit 0 | tw end + reason=finished | **970** |
| Tsk5 | active/waiting | failed | tw exit ≠0 / child crash | tw end + reason=failed | **970** |
| Tsk6 | active/waiting | stale | process gone, no end | **none today** | **970 / 1018 per task** |
| Tsk7 | * | cleared | reset/retire desk | clear all tasks | **970** |
| Tsk8 | waiting↔waiting | cycle | task A waits on B waits on A (desks or tasks) | **none** (self-wait only today) | **970 / 1017 per task** |
| - | - | - | **D6 supersede** | n/a | **dropped in target** (current-only) |

Concurrent start: Tsk1 on slot 2 while slot 1 is active - **allowed in target**; forbidden/implicitly serialized by D6 in current.

Counts (0.8.6 target, per task): **7 task states, 8 transitions** (+ 4 seat transitions shared). Gaps: all tw durable events; cycle detect; stale auto-clear.

#### 1017 / 1018 restated (per task)

- **1017:** a **task** waiting-on another desk/task that waits back forms a cycle with no product signal. Detect **per task edge**, not per seat.fix: refuse or surface the cycle when task A waits on B and B waits on A.
- **1018:** a **task** whose tw process died (or desk crashed) stays active/waiting forever. Bound and auto-clear **per task id**, not only the single `seat.doing_id` focus.

#### Metrics (970)

1. Dwell in idle/active/waiting **per task**.
2. Stale tasks past bound (**1018**).
3. Wait chains/cycles across tasks and desks (**1017**).
4. Waits by cause.
5. End reason: finished | failed | cleared | stale (no superseded in target).

---

## 5. Hold -> child **981**

States: **no_row | free | held** (desk_id null vs set). No TTL in code (`holds.pml`, activity-states).

### Transitions

| # | From | To | Trigger | Stamp today | Cov / child |
|---|------|----|---------|-------------|-------------|
| H1 | no_row | held | hold NAME (insert) | `hold.created`/`updated` `sp_hold.sql:61`; `activity` act hold `:65` | **981** granted |
| H2 | free | held | hold NAME | `updated` + activity `:73-79` | **981** |
| H3 | held | held (refresh) | hold by owner | `hold.updated` `:96`; since=activity.updated `:90-92` | **981** held duration |
| H4 | held | free | drop by owner | `desk_id` NULL + `updated` `:136`; act drop `:141` | **981** released |
| H5 | held | free | reset/retire desk | `mill_hold_release_desk` `:168-170` | **981** force-taken / admin release |
| H6 | * | same | peek | none | n/a |
| H7 | * | refused | hold while other owns | ok=0; **in-process** wait clock starts `hold_blocked.py:52-99` | **981** wait/contention |
| H8 | refused -> held | acquired after wait | later hold ok | perf log `op=hold.blocked` `hold_blocked.py:123` (ms); **not durable DB** | partial -> **981** |
| H9 | held | expired | TTL | **does not exist** | **gap -> 981 / 1013** |

### Failure / recovery

| Event | Exists? | Stamp | Child |
|-------|---------|-------|-------|
| refused | yes | reply only; wait map memory | 981 |
| force-taken | only via admin reset/retire (H5) | activity drop by admin | 981 |
| expired | **no** | none | **981 + fix 1013** |
| crash leaves hold | yes (stuck) | hold.updated stale | 981 / 1013 |

### 981 coverage vs gaps

- **Named on 981:** wait, contention, held duration, expired, force-taken.
- **Have today:** grant/release stamps; deny->acquire ms in log only (`hold_blocked.py`).
- **Gaps:** durable wait/blocked event; **expired transition (1013)**; force-taken distinct from owner drop; crash-stale hold gauge.

---

## 6. Score (`activity.type=score`) - 0.8.6 target, per plan

Score **stays an activity**. Desks **no longer write** it; the **server** writes every point/definition from real state changes in wake/mail/todo/doing/hold (new card **score-read-only** under 1001). Current ce115f8 still has desk `mill score` (`rpc.py:3108` `_h_score`) and SPIN `Writer` desks in `verify/spin/score.pml`.

### States (unchanged shape)

`none -> defined|live -> retired` (+ revive). Trend/gap on read.

### Transitions (0.8.6 target: server-triggered)

| # | From | To | Trigger (server) | Stamp today (current may still be desk) | Notes |
|---|------|----|------------------|-------------------------------------------|-------|
| S1 | none | live | state-change KPI first point | `score_point.created`; `mill_score_point_add` | target: tick/activity hook, not desk CLI |
| S2 | none | defined | define target from policy | `mill_score_define` | server |
| S3 | defined/live | live | further point from measured change | point row | server |
| S4 | live | live | target/better/unit update | score row `updated` | server/admin |
| S5 | live/defined | retired | retire policy / admin | `activity.deleted` | who-may changes when desks stop recording |
| S6 | retired | live/defined | revive on new server write | clear `deleted` | server |
| S7 | * | refused | bad value | SQL refuse | keep |

### Findings (stay on score)

| Finding | Issue | Stamp today | Requirement |
|---------|-------|-------------|-------------|
| **1019** | empty sample published as 0 | `_p50` empty->0; publish `counts.get(kpi) or 0` `score_tick.py:204-206`, `:665-670`, `:719` | missing -> missing |
| **1020** | silent truncation | `pts[:limit]` `score_series.py:159-161`; `sp_score.sql:398` | label `truncated` |

Desk-side publish paths to revisit for score-read-only are listed for the build desk (letter); #335 not changed in this pass.

---

## Four extra events (Q4)

| Event | Fits on | Notes |
|-------|---------|-------|
| Owed wake never fired | **1002** (and fix **1005**) | unread/push owed with no successful wake in bound |
| Size-limit hit | **980** | send + reply refuse `rpc.py:1557-1558`, `1914-1915`; also read/notice paths if capped |
| Retries per command | **cross-cut** | every child records client/server retry count+outcome on its commands |
| Why wake fired | **1002** | hold_release \| room_or_fyi_mail \| rering_handled \| version_notice \| other |

---

## Liveness findings ↔ transitions

| Card | Finding | Transition gap |
|------|---------|----------------|
| 1005 | unread-only failed wake not retried | W5/W18 |
| 1013 | holds never expire | H9 |
| 1017 | invisible wait-cycle | D12 current / Tsk8 per task (0.8.6) |
| 1018 | stale doing after crash | D13 current / Tsk6 per task (0.8.6) |
| 1019 | empty score as zero | score publish |
| 1020 | silent truncation | score_series shape |

---

## What 1001 already listed vs this map

Already on 1001 / children: mail pipeline; hold wait/held/expired/force-taken; tw(970); todo timing via **982**; wasted wake **1002** (983/1029 moved to dev tooling, card 1051).

Added by plan -> auditor (not originally on 1001 detail): instrument **at state transitions** (one event each); instrumentation -> score -> decisions; mill is **middleware**, CLI is API; graceful **bounded** recovery; outcomes over proxies; **missing ≠ zero**.

