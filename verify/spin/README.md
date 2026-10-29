# SPIN models of the mill coordination design

Small models of two parts of the mill, written in the `spin` input language
and checked with the `spin` model checker (from the 1991 book on designing and
validating computer protocols that introduced it).
A test checks the cases someone wrote down. A model check tries every order
in which the steps of the model can interleave, inside the stated bounds.

| File | What it models |
| :--- | :--- |
| `wake.pml` | the wake path: push queue, webhook POST, the 120 s window, the trailing POST (#669), the one immediate retry, connect sync, the seat rule (supersede, `-r` 4409); plus card 827's proposed backoff retry, and the fixes for cards 831 and 832 (shipped; their switches default on) |
| `holds.pml` | `mill hold` / `mill drop` (refuse at once, no TTL, only the owner drops, reset and retire free a desk's holds), with three desk policies for what to do after a refusal |
| `todo.pml` | 0.8.0 card moves T1-T14: the card row lock, one move row per status or volunteer change, the act on the activity row, the migration seed |
| `doing.pml` | 0.8.0 doing: focus rows and move rows, `seat.doing_id`, the seat row lock, finish (D8, D9), heartbeats, hold moves H1-H5, reset (D11) and retire (N1) |
| `mail.pml` | 0.8.0 recipient rows M1-M8: the first open kept, opening leaves activity alone, receipts |
| `score.pml` | 0.8.0 score moves S1-S6, the Wall writer included |
| `name.pml` | 0.8.0 retire and reclaim N1-N4, the self-retire token check (card 880), join of a retired name |
| `run.sh` | runs every check with fixed flags, compares each result with its expectation, exits nonzero on any difference or tool error (`--strict`: on any violation) |
| `SKILL.md` | how the next agent tells whether a change touches the modelled code, reruns the checks, and updates the models |

Run: `verify/spin/run.sh` (about seven minutes; needs `spin` 6.5.x and a C
compiler). One check with its trail: `verify/spin/run.sh W07`.

All searches are exhaustive (no `-DBITSTATE`, no depth cut). Liveness checks
run with weak fairness (`pan -a -f`): every process that can always move
eventually moves. The receiver's choice to fail a POST is not covered by
fairness; it is bounded by `MAXFAIL`, the most POSTs in a row it may fail.

## Properties and results (models at commit 1d9fffe)

Wake path, one desk, two or three items:

| Property | Result |
| :--- | :--- |
| One wake per window: a second wake starts only after 120 s or a connect | proved (W01-W03); fails on a mutation that splits the gate take (M01) |
| No invalid end state (deadlock) | proved (W01-W03) |
| No queued item is taken off the queue without reaching the desk | proved on main: one connect at a time (W04), a refused second connect, now the default (W06), a `--take` connect that supersedes (W05, W18, W21); the 831 fix alone with three items (W19); **violated** by the pre-831 order, take then send (W23) |
| Every item is eventually delivered | proved on main with a receiver that never fails (W07, W14, W15) and with two connects (W22); **violated** when both POSTs of a wake fail (W08); **violated** by the pre-832 order, POST then queue (W24); fails on a mutation of the 832 fix that marks a row sent at hand-off (M04) |
| Both fixes keep one wake per window and add no invalid end state | proved (W20) |
| Card 827 retry, bounded at 2 retries (6 POSTs) | proved when at most 5 POSTs in a row fail (W12, W16); violated at 6 (W13) and for a receiver down forever (W17) |

Holds, two or three desks each needing two locks in a cycle:

| Property | Result |
| :--- | :--- |
| Mutual exclusion | proved (H01, H02); fails without `FOR UPDATE` (M03) |
| The mill itself never blocks (no invalid end state) | proved (H03): `mill hold` refuses, it never waits |
| No deadlock as a busy loop, keep-and-retry policy | **violated** (H04, H05) |
| No livelock, drop-all-and-retry policy | **violated** (H06) |
| No deadlock or livelock, one global lock order | proved (H07, H08) |
| No starvation | **violated** (H09): no queue, a desk can lose every race; proved for finite work (H10) |
| A dead desk's holds | **violated** while nobody resets it (H11): no TTL; proved once someone runs `mill reset` or `mill retire` on it (H12), and the release keeps mutual exclusion (H13); fails on a mutation where reset keeps the holds (M05) |

## Findings in the code's words

Findings 1 to 3 are fixed on main (cards 831 and 832); they are kept as
the record of what W23 and W24 still catch.

1. **Fixed by card 832. Row queued after the wake (W24, was W07).** `emit` and `fanout` read
   `HUB.rooms`, call `post_desk`, and only then `rec_push.put`
   (push.py 565-587, 453-489). A woken run can connect and sync in between
   (likely when the first POST times out after the receiver got it, and the
   immediate retry takes up to 8 s more). Its sync finds no row, clears the
   window, and the row lands after it: no later POST, the desk never hears of
   the item until something else connects it.
2. **Sitting read vs. leave (W07 with `PUTFIRST`).** An item that finds the
   desk sitting gets no POST; if the desk's last socket leaves before the
   broadcast or the desk's next sync, the row waits with no wake.
   `PUTFIRST` + `RING_ON_LEAVE` close both races (W14-W16). They model the
   card 832 fix as coded: the row goes in as missed first, a live frame that
   reached a socket marks it sent (a later step), and the last socket leaving,
   or a frame that found no socket, rings when a missed row that rings waits.
   Marking the row sent at hand-off instead strands the item (M04).
3. **Fixed by card 831. Take before send (W23, was W05).** `connect_sync_frame` deletes the rows
   (`mill_push_take`) and the handler sends the frame after (asgi.py 609-616).
   A newer connect of the same desk supersedes the old socket in between; the
   old send fails and those rows are gone. Any failed send after the take
   does the same; a command reply (asgi.py 633-636) has the same order.
   sync.md says "A deleted list is not sent again"; connect.md says
   "Nothing is lost". `ACK_AFTER_SEND` models the card 831 fix: the sync reads
   the rows, sends, then deletes exactly those; an unsent frame deletes
   nothing (W18, W19, W21). A put-back on a failed send was not chosen: it
   still deletes first, so a row is in neither place until the put-back.
4. **A failed wake is two back-to-back POSTs, then nothing (W08).** The window
   is taken before the POST (wake.py 636), so after a failure only a trailing
   POST can follow, and only if another item arrives inside the window. The
   docs (connect.md, wake.py docstring) say "a burst is never left asleep".
5. **Card 827 needs a job id (M02).** A retry must stop only its own chain;
   otherwise a late success of an old retry cancels the chain of a newer
   failed wake. Bounded retries prove delivery only under a bounded-loss
   assumption: fewer lost POSTs in a row than the budget has POSTs.
6. **Wall restart (W11).** `_GATE`, `_TRAIL` and the timer threads are memory
   only: a restart can send a second POST inside 120 s, and drops a pending
   trailing POST (rows survive in `push_queue`).
7. **Receipts never ring (W10).** By design (push.py 573); a receipt waits
   for the desk's next connect.
8. **Holds.** No TTL. Since card 842, `mill reset` and `mill retire` free
   the desk's holds in the same call (`mill_hold_release_desk`); a
   superseded connect and a clock-out leave them held. No queue: starvation possible.
   Agents that need two locks must take them in one global order, and must
   not spin on a refused hold.

## The fix switches and current main

`ACK_AFTER_SEND` (card 831, #168) and `PUTFIRST` + `RING_ON_LEAVE` (card 832,
#169) shipped in 0.7.16, and their defaults are 1: the plain checks describe
main. W05 and W07 now expect pass. W23 and W24 set the switches to 0 and must
still fail, so the models still catch the old orders. A switch set to 0 is
the pre-fix code, not an option on main.

## What is not modelled

- Time beyond "the window has ended or not"; the 30-day expiry sweep.
- A crash between a commit and its `after_commit` pokes (push.py 421, 550):
  the row is never queued.
- The client's 256-frame sit buffer and `note_drop` put-back.
- `--wake-on addressed`, the default since card 836 (room-only items skip the POST), refused or
  non-public URLs (no window taken), the join test POST (never takes a window).
- InnoDB. Two first-time holds of a new resource can deadlock on gap locks
  (1213); #818 retries once (records/db.py 193-199, 498-520) and the unique
  `idx_hold` keeps one owner. The model treats each stored procedure as one step.
- A receiver that answers 2xx is assumed to start a run that connects.
- Card 834's busy rule on the client: `connect` refuses a held seat by
  default and looks again after 1 s and 2 s. The model's `REFUSE` is the
  server side of it (W06); `SESSIONS=2` without `REFUSE` is `--take`, or an
  old client.
- Card 838's failure count (`wake._FAILS`, memory only) and its Admin
  letter: they report failed POSTs and add no POST, so delivery is unchanged.
- A reset or retire of a desk whose session is still running: the model
  frees holds only of a dead desk.
- Both fixes with three items and two connects: the search ran out of memory
  on the run host; W19 checks the 831 fix alone at that size.

## 0.8.0 activities: mail, todo, doing, hold, score, name (draft)

Models at the design in `docs/requirements/beta/activity-states-080.md` (PR #226,
c2a91f9) and the release/0.8.0 lane B code it changes (PR #224, ac136b8, plus the
lane B copy of `sp_beta_name.sql` with the card 880 self-retire, not yet pushed).
The change pass that writes the 0.8.0 procedures had not landed when these were
written, so where the design adds a rule (move rows, `seat.doing_id`, the act) the
model follows the design, and where the code already decides (guards, lock order,
transactions) it follows the code. Re-pin `SYNC_080` and `DOC_080` in `run.sh` when
the lanes land. Transitions are keyed on their ids (T4, D8, H5, ...): an act is
stored as its transition id, not its spelling.

Run time for the 0.8.0 checks: about four and a half minutes; D01 and D06 each need about
2.7 GB (compressed states, `-DCOLLAPSE`). Desk 0 with two shells and three
commands each ran out of memory on the run host (15 GB), so D01, D05 and D06 use
two shells by two commands, and the rest one shell by three.

| Property | Result |
| :--- | :--- |
| Card: one move row per status or volunteer change, and replaying the move rows gives `todo.status` and the volunteer (invariants 3, 5, 6) | proved for cards made in 0.8.0 (T01); fails when the write reads the old status before the lock (M08) or logs only status changes, as the #214 draft did (M09) |
| Card: the activity act is the act of the last committed step (invariant 4) | proved (T06); fails when the act lands after the lock (M10) |
| Card: every committed move is an edge of the design table | **violated** by unpark with no status guard (T02), by assign's unlocked guard (T03), and by a move on a card retired after `find` (T04); proved with all three guards under the card lock (T05) |
| Card: migrated history replays (invariant 6) | **violated** when the seed row of a shipped or done card has no volunteer (T07); proved with it (T08) |
| Desk focus: `seat.doing_id` is the newest focus row, a move never moves it, and a desk's doing writes do not interleave (invariants 1, 2, 11) | proved (D01, D02); fails without the seat lock (M11) or when a move row moves the focus (M12) |
| Holds: the holder matches its move rows, one row per take, drop and freed hold (invariants 3, 10) | proved (D01, D02); mutual exclusion itself is H01-H02 and M03 |
| Finish fires only on the focus item, and a pass or drop on the focus item without `--doing` ends it (invariant 12) | proved (D01, D02); fails with the 0.7.19 newest-row test (M13) |
| A finish ends only the focus current at its move | **violated** with the finish as its own transaction, as the code runs it (D05); proved in one transaction with the move (D06) |
| The derived end skips move rows | proved (D01, D02); fails with the 0.7.19 `mill_doing_end` rule, any empty row on the item (M14) |
| Heartbeats write no doing row and no activity (invariant 13) | proved (D01, D02); fails with the lane B anchor row and bump (M15) |
| Retire is complete at its commit (invariant 15) | proved (D01, D02); fails when retire frees no hold (M16) |
| A retired desk stays clean after its retire | **violated** (D07): a request authenticated before the retire commits a take or a focus after it; proved with the token re-checked under the seat lock, seat first (D08) |
| No lock cycle | **violated** (D03): take or drop locks hold then seat, reset and retire lock seat then holds; proved with the seat first on hold paths (D04) |
| Mail: the first open is kept, opening leaves activity alone, one receipt per recipient row (invariants 7, 8) | proved for the 0.8.0 design (E01); **violated** by the code at ac136b8 and 0.7.19: re-stamp (E02), two receipts from two concurrent opens (E03), activity bump (E04); fails when `ROW_COUNT()` counts matched rows (M17) |
| Score: act is the last step, retired iff the last step was S5, no doing rows | proved (S01); fails when S6 leaves `deleted` set (M18) |
| Only Admin, or the desk itself with its current token, retires a desk; Office and Admin never; reclaim is Admin only (invariant 14) | **violated** with the self check as a plain read (N01); proved under the seat lock (N02); fails when the self check forgets target = caller (M19) or reclaim forgets Admin (M20) |
| A retired desk holds no seat token | **violated** (N03): join checks the name on a plain read; proved when join waits on the name row (N04) |
| Reachability goals | reachable: filed -> claimed -> shipped -> done (R01), a hold desk 0 -> free -> desk 1 (R02), a desk idle -> active -> waiting -> idle (R03). Each is a "never" rule expected to be violated |

### 0.8.0 findings in the code's words

Line numbers are at lane B ac136b8 unless named otherwise.

11. **D8, D9: finish is a second transaction (D05).** Without `--doing`,
    `_run_command` runs the handler, which commits, and then `_doing_finish`
    calls `mill_doing_finish` in its own transaction (rpc.py 998-1011, 922-948).
    A `--doing` on the same item from another shell of the desk, in between,
    is then ended by the earlier pass or drop. A failure of the finish is
    logged, and the move stands with the focus still active.
12. **Lock order (D03).** The design locks the hold row, then the seat, for a
    take or a drop; `mill_join_reset` (sp_join.sql 206-238) and `sp_name_retire`
    (sp_beta_name.sql 143-172) lock the seat, then the desk's hold rows through
    `mill_hold_release_desk` (sp_hold.sql 113-124, `idx_desk`). A drop or take
    by a desk while Admin resets or retires it is an InnoDB deadlock; one side
    rolls back.
13. **A retired desk gets a hold or a focus after its retire (D07).** The
    request authenticates its token, then writes; `mill_doing_put`'s joined
    check (sp_doing.sql 101) passes after a reset or retire because
    `time_disconnect` is set, and the hold take has no token check.
14. **T3 unpark has no status guard (T02).** `_h_unpark` (rpc.py 2432-2462, the
    same on main) calls `mill_todo_update(status open)` on any card; the
    volunteer stays, and `cmd_pass` ships an open card that has a volunteer
    (sp_cmd.sql 207-208).
15. **T5 assign guards an unlocked read (T03).** `_h_assign` (rpc.py 2141-2163)
    checks status and volunteer on `find`'s read, then writes claimed and the
    assignee without a lock-held check; a claim or a pass in between is
    overwritten.
16. **T4-T11 move a retired card (T04).** `find` is an unlocked read and
    `cmd_claim`, `cmd_unclaim` and `cmd_pass` do not check `activity.deleted`
    under the card lock (sp_cmd.sql 120-239).
17. **Migration seed (T07).** A seed row for a shipped or done card does not
    give its volunteer back under the replay rule (claimed, took_over and
    assigned set the volunteer). The seed row must carry it, or invariant 6
    starts after the seed.
18. **N2 self check is a plain read (N01).** `sp_name_retire` checks the
    caller's token with `EXISTS (SELECT ... FROM seat ...)` (sp_beta_name.sql
    149-151) before it locks the seat; a reset that commits in between does
    not stop a self-retire with the revoked token. Minor.
19. **Join of a retired name (N03).** `MILL_NAME_PUT` refuses a retired name on
    a plain read (fn_name.sql 61-85); a retire that commits before the join's
    seat write leaves a retired desk with a live token, and reclaim then says
    the name is in use.
20. **Receipts (E03).** `mill_mail_open` reads `v_prev` with a plain read and
    decides the receipt from `ROW_COUNT()` (sp_opened.sql 27-47). With the
    re-stamp of 0.7.19 and lane B, two concurrent opens both push a receipt.
    The 0.8.0 `IFNULL` closes it only while `ROW_COUNT()` counts changed rows
    (the connector does not set `CLIENT_FOUND_ROWS`); `opened IS NULL` in the
    UPDATE's WHERE would not depend on that (M17).

### 0.8.0 switches

Each switch named in a check is set to the code at ac136b8 by default where the
code decides (`FINISH_SPLIT=1`, `HOLD_SEAT_FIRST=0`, `LIVE_CHECK=0`,
`ASSIGN_LOCKED=0`, `UNPARK_GUARD=0`, `DELETED_GUARD=0`, `SELF_LOCK=0`,
`JOIN_NAME_LOCK=0`) and to the design where only the design decides
(`FIRST_OPEN=1`, `QUIET_OPEN=1`). Setting a code switch to 1 models a fix, not
the code.

### 0.8.0: what is not modelled

- InnoDB's answer to a deadlock (roll one back, `request_tx` runs it once more):
  D03 shows the cycle; the invariant checks run with `-E` and do not explore the
  rollback.
- Row ids and `created` times: the model keeps whether `seat.doing_id` is the
  newest focus row, not the ids, and no clock skew.
- More than one hold per desk in H5, a pass of several cards with `--doing`, the
  `--waiting-on` target checks, D7 (a reply under the focus letter, derived, no
  row), the derived `cleared` read, watchers, roster and bytes on activity.
- No-op writes: a claim of a card the desk already holds, unclaim or unpark of an
  open card. The model writes no row and no act for them; the design does not say.
- Where an `assigned` row keeps the assignee (the actor is the row's desk).
- T15, S7 and M9 (no CLI path), clock-out (not wired), join with a doing text,
  votes (none in 0.8.0).
- Card statuses in `doing.pml` (any card move succeeds there; `todo.pml` has the
  guards).
