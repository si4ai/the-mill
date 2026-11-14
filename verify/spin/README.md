# SPIN models of the mill coordination design

Small models of two parts of the mill, written in the `spin` input language
and checked with the `spin` model checker (from the 1991 book on designing and
validating computer protocols that introduced it).
A test checks the cases someone wrote down. A model check tries every order
in which the steps of the model can interleave, inside the stated bounds.

| File | What it models |
| :--- | :--- |
| `wake.pml` | the wake path: push queue, webhook POST, the wake lease (card 886: ended by `mill wake-done` or its timeout, not by a connect), the trailing POST (#669), card 827's retry chain off the request (#300, live since 0.8.3), unread mail that resurfaces on connect and rings again (#297, card 949), wake-done inside a connect with no trailing POST to a sitting desk (#322, card 889, 0.8.5), connect sync, the seat rule (supersede, `-r` 4409), and the fixes for cards 831 and 832 (shipped; their switches default on); `LIVE`: the wake path at main 8bae076 and #416 for the live modes F1, F2, F7 (card 1144) |
| `holds.pml` | `mill hold` / `mill drop` (refuse at once, no TTL, only the owner drops, reset and retire free a desk's holds), with three desk policies for what to do after a refusal; `READ_DROP`: a connect sync against a committed drop (card 1144, F3) |
| `todo.pml` | 0.8.0 card moves T1-T14: the card row lock, one move row per status or volunteer change, the act on the activity row, the migration seed |
| `doing.pml` | 0.8.0 doing: focus rows and move rows, `seat.doing_id`, the seat row lock, finish (D8, D9), heartbeats, hold moves H1-H5, reset (D11) and retire (N1). History since card 1207 (0.8.15): the code has no focus rows, move rows, `seat.doing_id`, `--doing` or `--waiting-on`; a doing is one tw run. Not re-modelled yet. |
| `mail.pml` | 0.8.0 recipient rows M1-M8: the first open kept, opening leaves activity alone, receipts |
| `score.pml` | 0.8.0 score moves S1-S6, the Wall writer included |
| `name.pml` | 0.8.0 retire and reclaim N1-N4, the self-retire token check (card 880), join of a retired name |
| `activity_history.pml` | card 1125 MVP design (targeted at 0.8.14, nothing built): `replace-body` on mail and todo, `body_updated` as the version (compare-and-set under the item lock), full old body in `activity_history`, in-lock claim lines, bare claims, receipts, retire, a clock that may repeat |
| `run.sh` | runs every check with fixed flags, compares each result with its expectation, exits nonzero on any difference or tool error (`--strict`: on any violation) |
| `SKILL.md` | how the next agent tells whether a change touches the modelled code, reruns the checks, and updates the models |

Run: `verify/spin/run.sh` (about fifteen minutes, up to 4 GB of memory; needs `spin` 6.5.x and a C
compiler). One check with its trail: `verify/spin/run.sh W07` (or `A01`, `X01`, ...).

Last full run: 150 checks, every one matching its expectation (65 `pass`, 85
`violated` as expected: findings, mutants, reachability goals, the card 1125
design expected-violations and mutations, and the card 1144 live wake modes
V01-V24), in 897 s (about 15 minutes), on main ec280da with
`SYNC` = c1c1d87 (PR #322's head: 0.8.4 main plus card 889) and
`SYNC_080` = 8a80dc1, 2026-11-11 (Pacific). The wake checks store states compressed
(`-DCOLLAPSE`), as the 0.8.0 and activity_history checks do.

All searches are exhaustive (no `-DBITSTATE`, no depth cut). Liveness checks
run with weak fairness (`pan -a -f`): every process that can always move
eventually moves. The receiver's choice to fail a POST is not covered by
fairness; it is bounded by `MAXFAIL`, the most POSTs in a row it may fail.

## Properties and results (wake and holds at PR #322's head c1c1d87: 0.8.4 main plus card 889; the 0.8.0 activity models at 8a80dc1)

Wake path, one desk, two or three items:

| Property | Result |
| :--- | :--- |
| One wake per lease: a second wake starts only after `mill wake-done` or the lease timeout (`wake_lease_s`, 900 s), never after a connect | proved (W01-W03, L03; W02 with one connect per run, more runs out of memory); fails on a mutation that splits the gate take (M01); **violated** by the pre-886 design, where a connect frees the gate while the run is still working and a second POST lands (L02, the storm) |
| A wake-done ends only the lease that woke its own run | proved for runs that pass the token (L01, card 888): `mill wake-done --lease TOKEN` with a token that is not the current lease's ends nothing; **violated** for a done with no token, an older client (L05): it pops whatever lease is current, ending the newer run's lease early. The run's token is the one its POST carried; fails on a mutation where the run binds the lease current at its start (M07). Card 890: proved also when a lease lapses while its POST is in flight and a newer lease starts first (L06); fails on a mutation where the POST body reads the lease current at send time instead of the take's token (M21) |
| No invalid end state (deadlock) | proved (W01-W03) |
| No queued item is taken off the queue without reaching the desk | proved on main: one connect at a time (W04), a refused second connect, now the default (W06), a `--take` connect that supersedes (W05, W18, W21); the 831 fix alone with three items (W19); **violated** by the pre-831 order, take then send (W23) |
| Every item is eventually delivered | proved with a perfect receiver (W07, card 887: the lease check and the record are one lock hold); **violated** by the #216 order, peek then a later record (W25); proved with emits atomic (W09, L04); fails on a mutation where wake-done sends no trailing POST (M06); proved for the 832 fix under the pre-886 gate (W14, W15) and with two connects (W22); proved when two POSTs in a row fail, since #300's retry chain follows (W08); **violated** by the pre-#300 `_fire`, two POSTs then nothing (M22); **violated** by the pre-832 order, POST then queue (W24); fails on a mutation of the 832 fix that marks a row sent at hand-off (M04) |
| Both fixes keep one wake per window and add no invalid end state | proved (W20) |
| Card 827 retry as coded in #300: one POST per wake, then a chain of retries with the same body (same idem key, same lease, no new window), armed only while push rows wait; it stops when the push queue drains or any later wake of the desk succeeds. The model bounds the chain at 2 retries (the code makes 12 to 64 in about an hour) | proved when at most 2 POSTs in a row fail (W12, W16); violated at 3 (W13, the model's bound, not a finding) and for a receiver down forever (W17); an old chain that runs out must not cancel a newer one (M02) |
| Every item delivered and every letter opened, when a run may leave letters unread (#297, card 949: sync merges unread mail; trailing and ring-on-leave ring on unread mail alone) | proved with a perfect receiver (W28, and W29 before #322); fails on a mutation that ignores unread mail once its push row drained (M23); **violated** when the one wake for unread mail alone fails (W30, finding 11); proved with a retry that also counts unread mail (W31, proposed) |
| `mill wake-done` inside the run's own connect sends no trailing POST to the sitting desk (#322, card 889) | proved (W27); fails on a mutation that drops the #322 sitting guard (M24), so W27 is not vacuous; **violated** before #322, main 0.8.4 (W26): the trailing wake goes out while the run still sits |

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

11. **Open (W30, card 941 pass). A failed wake for unread mail alone is never retried.**
    #297 lets `ring_waiting` and `_send_trailing` ring when the push queue is empty
    but a letter is still unread. #300 arms its retry only when
    `pending = rec_push.pending(cn, desk)` is above 0, and `_queue_drained` stops
    a chain on the same push count. So when a short connect drained the push rows
    without opening the letter, and the one POST for that unread letter fails,
    no retry is armed, the lease lapses with nothing held back, and the letter
    stays dark until another item comes. W31 shows that counting unread mail in
    both reads closes it.
12. **By design, noted (card 941 pass). Unread mail rings again after every run.**
    A desk that reads a letter but never marks it gets a new wake at each leave
    (ring-on-leave on unread) with no cap or backoff. The model bounds the skips
    (`MAXSKIP`); the code does not.

Findings 9 and 10 came with the wake lease (card 886, PR #216). PR #218 fixes both (cards 887 and 888); W25 and L05 keep the old orders failing.

9. **Fixed by card 887 (`HOLD1`). Done between the peek and the trail (W25, was W07).** `post_desk` reads
   `_gate_open` under the lock, releases it, and later calls `_coalesced`,
   which takes the lock again and returns when `_GATE` has no entry. If the
   run's `mill wake-done` lands in between, `lease_done` pops the lease with
   no held-back items (so no trailing POST), and `_coalesced` then finds no
   lease and records nothing. The row waits in the queue with no wake until
   another item or connect comes. Before 886 the same gap closed itself,
   because the connect that cleared the gate read the queue in the same sync.
10. **Fixed by card 888 (`TOKEN`) for runs that pass `--lease`. A stale wake-done (L05, was L01).** `lease_done` pops `_GATE[desk]` whatever
   lease is there. A run that takes longer than the lease (900 s) and says
   done after a newer wake went out ends that newer run's lease: the next
   item POSTs while the newer run is still working, which is the overlap the
   lease exists to stop. Long passes outlive 900 s in practice.

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
4. **Fixed by card 827 (#300, 0.8.3). A failed wake was two back-to-back POSTs, then nothing (M22, was W08).** The window
   is taken before the POST (wake.py 636), so after a failure only a trailing
   POST can follow, and only if another item arrives inside the window. The
   docs (connect.md, wake.py docstring) say "a burst is never left asleep".
5. **Card 827 chains (M02).** #300 keeps one chain per failed wake; a chain
   that runs out ends only itself. Any later success of the desk (`_OK_GEN`)
   ends every older chain, which is safe because that success starts a run. Bounded retries prove delivery only under a bounded-loss
   assumption: fewer lost POSTs in a row than the budget has POSTs.
6. **Wall restart (W11).** `_GATE`, `_TRAIL` and the timer threads are memory
   only: a restart can send a second POST inside the lease, and drops a pending
   trailing POST (rows survive in `push_queue`).
7. **Receipts never ring (W10).** By design (push.py 573); a receipt waits
   for the desk's next connect.
8. **Holds.** No TTL. Since card 842, `mill reset` and `mill retire` free
   the desk's holds in the same call (`mill_hold_release_desk`); a
   superseded connect and a clock-out leave them held. No queue: starvation possible.
   Agents that need two locks must take them in one global order, and must
   not spin on a refused hold.

## The fix switches and current main

`LEASE` (card 886, PR #216) defaults to 1, and `MULTI` (a run connects once
per shell call) follows it. `LEASE=0` is the pre-886 gate, cleared by every
connect sync; W14-W16, W19, W22 and W24 pin it, since they check the 831 and
832 fixes on their own. L02 keeps the pre-886 storm failing.

`ACK_AFTER_SEND` (card 831, #168) and `PUTFIRST` + `RING_ON_LEAVE` (card 832,
#169) shipped in 0.7.16, and their defaults are 1: the plain checks describe
main. W05 expects pass.

`HOLD1` (card 887, F144a) and `TOKEN` (card 888, F144b), both in PR #218,
default to `LEASE`. `HOLD1=0` is the #216 order (W25); `TOKEN=0` is a run
that says `mill wake-done` with no `--lease`, as older clients do (L05). W07
and L01 expect pass on main since #218 merged. The take's token rides on its
POST (`wake_body(lease=...)`, from `_hold_or_take` in the same lock hold) and a
2xx hands it to the run it starts, so a run picked up after a newer lease began
holds its own older token and its done is stale (ends nothing). M07 binds the
lease current at run start instead and must fail L01. W23 and W24 set the switches to 0 and must
still fail, so the models still catch the old orders. A switch set to 0 is
the pre-fix code, not an option on main.

`RETRY827` (#300), `UNREAD` (#297), `DONE_IN_CONNECT` and `SITTING_DONE` (#322)
default to 1. `RETRY827=0` is the pre-#300 `_fire` (M22). `SITTING_DONE=0` is
main 0.8.4 before #322 (W26, W29). `DONE_IN_CONNECT=1` lets a run say
`mill wake-done` inside its connect, after its leave, or not at all.
`RETRY_UNREAD=1` is a proposal, not the code (W31).

## What is not modelled

- Card 890: `LAPSE_FIRING=1` lets a lease lapse while its POSTs are in flight;
  the plain wake checks keep the realistic bound (900 s against at most 16 s of
  POSTs), so L06 and M21 are the only rows that use it.
- Card 888: a stale done keeps its note for the next wake (`_NOTE`); notes
  are not modelled.
- Card 888: woken runs start in the order their POSTs got a 2xx (a FIFO of
  tokens); a receiver that starts runs out of order is not modelled.

- #300: the delays, jitter, budget and `RETRY_MAX`; a 401 or 404 that stops
  the chain (a receiver that refuses for good is `MAXFAIL=255`, W17); a restart
  drops the chain (W11 covers memory loss).
- #297 with two connects of the desk: out of memory on the run host (over
  10 GB at W03's size), so the two-connect rows (W03, W05, W06, W18-W23) pin
  `UNREAD=0`. Unread mail is checked with one connect at a time (W28-W31, M23).
- #297: which letters are unread is per letter in the model; the code reads
  the newest 20 (`unread_mail_frames`), so a desk with more unread mail sees
  only those in one sync.
- Card 886: `pending_count`, `last_note` and the note redaction: they shape
  the POST body and decide no POST. `lease_synced` only resets that count.
- Card 886 with three items and more than one connect per run: out of memory
  on the run host; W02 and W04 run three items with one connect per run.

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

## 0.8.0 activities: mail, todo, doing, hold, score, name

**Card 1207 (0.8.15):** the doing rows below (focus, `seat.doing_id`, finish, `--doing`, `--waiting-on`) describe code that is gone; a doing is now one tw run, written only by tw. The doing results are kept as history until `doing.pml` is re-modelled.

Models at the design in `docs/requirements/beta/activity-states-080.md` (PR #226,
`DOC_080` = c2a91f9) and the 0.8.0 release code (main 8a80dc1, tag v0.8.0, `SYNC_080`).
Lane B (PR #224) was pinned at 413cdb8 before the release; the covered code
changed since then only in where evidence is stored, the score owner row and a
seat check on score, none of which the models track. Where a F183/F186 fix has landed, the switch defaults to the fixed
code and a `-DSwitch=0` (or `MUT_*`) row keeps the old shape failing. Transitions
are keyed on their ids (T4, D8, H5, ...): an act is stored as its transition id,
not its spelling. T8 is a real edge from claimed and from open-with-volunteer;
the assignee on an assign lives in the move row's `peer_id`; a no-op unclaim or
self re-claim writes no row.

Run time for the 0.8.0 checks: about four and a half minutes; D01 and D06 each
need about 2.7 GB (compressed states, `-DCOLLAPSE`). Desk 0 with two shells and
three commands each ran out of memory on the run host (15 GB), so D01, D05 and
D06 use two shells by two commands, and the rest one shell by three.

| Property | Result |
| :--- | :--- |
| Card: one move row per status or volunteer change, and replaying the move rows gives `todo.status` and the volunteer (invariants 3, 5, 6) | proved at 8a80dc1 (T01, T06); fails when the write reads the old status before the lock (M08) or logs only status changes (M09) |
| Card: the activity act is the act of the last committed step (invariant 4) | proved (T05); fails when the act lands after the lock (M10) |
| Card: every committed move is an edge of the design table (T8 from open with a volunteer included) | proved with the F186 guards under the card lock (T01); fails on the pre-F186 mutants: unpark (T02), assign unlocked (T03), no deleted check (T04) |
| Card: migrated history replays (invariant 6) | proved: the seed row's `peer_id` carries the volunteer (T06); fails without it (T07) |
| Desk focus: `seat.doing_id` is the newest focus row, a move never moves it, and a desk's doing writes do not interleave (invariants 1, 2, 11) | proved (D01, D02); fails without the seat lock (M11) or when a move row moves the focus (M12) |
| Holds: the holder matches its move rows, one row per take, drop and freed hold (invariants 3, 10) | proved (D01, D02); mutual exclusion itself is H01-H02 and M03 |
| A pass or drop on the focus item without `--doing` ends that entry on read; no finish row (invariant 12) | proved (D01, D02, D06); fails with a second-transaction finish row (D05) or the 0.7.19 newest-row test (M13) |
| The derived end skips empty move rows as ends | proved (D01, D02); fails with the 0.7.19 `mill_doing_end` rule (M14) |
| Heartbeats write no doing row and no activity (invariant 13) | proved (D01, D02); fails with the pre-0.8.0 anchor row and bump (M15) |
| Retire is complete at its commit (invariant 15) | proved (D01, D02); fails when retire frees no hold (M16) |
| A retired desk stays clean after its retire | proved with the live-token re-check under the seat lock (D08); fails without it (D07). As coded, the check asks only that the seat still has a token (`LIVE_GEN=0`), not that it is the request's own; a request that authenticated before a reset can still act after the desk joins again, which breaks no invariant here |
| No lock cycle | proved with seat-then-hold (D04); fails on the pre-F183 hold-then-seat order (D03) |
| Mail: the first open is kept, opening leaves activity alone, one receipt per recipient row (invariants 7, 8) | proved at 8a80dc1 (E01: `FOR UPDATE` + IFNULL, no activity bump); fails on the 0.7.19 / unlocked-read mutants (E02, E03, E04, M17) |
| Score: act is the last step, retired iff the last step was S5, no doing rows | proved (S01); fails when S6 leaves `deleted` set (M18) |
| Only Admin, or the desk itself with its current token, retires a desk; Office and Admin never; reclaim is Admin only (invariant 14) | proved under the seat lock (N01); fails on the plain-read mutant (N02) and when the self check forgets target = caller (M19) or reclaim forgets Admin (M20) |
| A retired desk holds no seat token | **open** (N03): join takes the name row `FOR UPDATE` (F186), then re-checks `name.deleted` with a plain `SELECT`; under REPEATABLE READ, the MySQL default and the level the code runs at (nothing sets another), that read returns the snapshot from before the lock, so a retire in between still leaves a fresh token; proved under READ COMMITTED, which the tables.sql header states (N04); fails with no name lock at any level (N05) |
| Reachability goals | reachable: filed -> claimed -> shipped -> done (R01), a hold desk 0 -> free -> desk 1 (R02), a desk idle -> active -> waiting -> idle (R03). Each is a "never" rule expected to be violated |

### 0.8.0 findings at 8a80dc1

Line numbers are at 8a80dc1. Fixed findings keep a pre-fix mutant that
must stay `violated`.

| Id | Status at 8a80dc1 | Notes |
| :--- | :--- | :--- |
| D03 lock order | **fixed** (F183) | take/drop and card writes lock seat then item; mutant D03 (`HOLD_SEAT_FIRST=0`) |
| D05 finish split | **fixed** (F186) | `mill_doing_finish` writes no row; the move ends the entry on read; mutant D05 (`FINISH_SPLIT=1`) |
| D07 post-retire take/focus | **fixed** (F186) | live token re-checked under the seat lock; mutant D07 (`LIVE_CHECK=0`) |
| T02 unpark guard | **fixed** (F186) | `card:unpark_status` under the card lock; mutant T02 |
| T03 assign locked | **fixed** (F186) | `card:assign_guard` under the card lock; mutant T03 |
| T04 deleted guard | **fixed** (F186) | `card:deleted` under the card lock; mutant T04 |
| T07 migration seed | **fixed** | seed row `peer_id` = volunteer; mutant T07 (`SEED_VOL=0`) |
| N01 self check | **fixed** (F186) | token check under the seat lock with target = caller; mutant N02 |
| E03 receipts | **fixed** | `FOR UPDATE` + first-open kept; mutants E03, M17 (`OPEN_LOCKED=0`) |
| N03 join of a retired name | **open** | the name-row lock is in (sp_join.sql 162), but the re-check after it (163) is a plain read, a snapshot read under REPEATABLE READ; N03 expects `violated`, N04 (`RC=1`) passes, N05 (`JOIN_NAME_LOCK=0`) keeps the pre-F186 shape failing |

### 0.8.0 switches

Defaults match the code at 8a80dc1:

`FINISH_SPLIT=0`, `HOLD_SEAT_FIRST=1`, `LIVE_CHECK=1`, `ASSIGN_LOCKED=1`,
`UNPARK_GUARD=1`, `DELETED_GUARD=1`, `SEED_VOL=1`, `SELF_LOCK=1`,
`FIRST_OPEN=1`, `QUIET_OPEN=1`, `OPEN_LOCKED=1`, `JOIN_NAME_LOCK=1`, `LIVE_GEN=0`,
`RC=0` (REPEATABLE READ: no code path sets the isolation level). Wake: `LAPSE_FIRING=0`.
Setting a fixed switch to 0 is the pre-fix mutant, not an option on the pin.

### 0.8.0: what is not modelled

- InnoDB's answer to a deadlock (roll one back, `request_tx` runs it once more):
  D03 shows the cycle; the invariant checks run with `-E` and do not explore the
  rollback.
- Row ids and `created` times: the model keeps whether `seat.doing_id` is the
  newest focus row, not the ids, and no clock skew.
- More than one hold per desk in H5, a pass of several cards with `--doing`, the
  `--waiting-on` target checks, D7 (a reply under the focus letter, derived, no
  row), the derived `cleared` read, watchers, roster and bytes on activity.
- T15, S7 and M9 (no CLI path), clock-out as its own CLI path, join with a doing
  text, votes (none in 0.8.0).
- Card statuses in `doing.pml` (any card move succeeds there; `todo.pml` has the
  guards).


## Card 1125: activity_history (MVP design for 0.8.14)

Design model only: nothing is built. The design, findings and the mapping from
the first draft's check ids are in `docs/dev/card-1125-activity-history.md`. The
model describes the MVP agreed in room `card-1125-mvp` and on cards 1125 and
1133, not current mail or todo writers. There is no `SYNC` pin until the build
lands. Check ids are A01-A09 and X01-X15; A* avoids colliding with `holds.pml`
(H01-H13).

One item, three desks (sender/asker A, addressee/claimer B, Admin W). A and W
read, then `replace-body` from their last read, re-reading and retrying after a
refusal (W may skip the read). B claims bare, claims with a line appended in the
lock, or tries a replace it has no right to, and reads twice. A may retire the
item; a replace may fail after its history insert; the clock may repeat.
Searches are exhaustive (`-DCOLLAPSE`, no BITSTATE, no depth cut; max depth 300000).

| Property | How checked |
| :--- | :--- |
| P1. A read returns body and `body_updated` of one version | assert in the read |
| P2. Only the sender/asker or Admin replaces | assert in the replace step |
| P3. No lost update: every body write is built on the current text | assert in the write step; at rest the versions form one chain |
| P4. History is the log: one row per body write, newest row = the version the current one replaced, with its stamp | assert in every read and at rest |
| P5. A retired item's body never changes | assert at rest |
| P6. A replace built on the current text is never refused (`CHECK_P6`) | assert in the replace step |
| P7. One receipt per `mail_to` row, also after edits | assert in the read and at rest |

| Id | Defines | Expect | Got | States | Depth | What it shows |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| A01 | (MVP design) | pass | pass | 4,059 | 89 | card 1125 MVP: P1 one-SELECT read, P2 rights, P3 no lost update, P4 history = log, P7 receipts; replace, in-lock claim line, bare claim |
| A02 | APPEND=0 | pass | pass | 1,933 | 79 | replace-only (card 1125, 8:19 AM PST: no note append): same properties |
| A03 | CLOSE=1 | pass | pass | 6,914 | 93 | retire: replace refused afterwards, body frozen (P5) |
| A04 | FAIL=1 | pass | pass | 12,841 | 116 | forced error after the history insert rolls back both (done_when 5) |
| A05 | CHECK_P6 | pass | pass | 4,110 | 89 | P6: a replace built on the current text is never refused stale (strict clock) |
| A06 | CLOCK=1 | pass | pass | 6,196 | 94 | MILL_NOW() may repeat or step back: UNIQUE (type, activity_id, old_updated) still stops every lost update |
| A07 | CLOCK=1 UNIQUE=0 | violated | violated | 692 | 68 | FINDING: body_updated alone is not a version when the clock repeats; the UNIQUE key is load-bearing |
| A08 | CLOCK=1 CHECK_P6 | violated | violated | 648 | 75 | FINDING (minor): a repeated stamp makes UNIQUE refuse a replace built on the current text |
| A09 | CLOSE=1 FAIL=1 MAXTRY=3 | pass | pass | 40,563 | 163 | larger: retire, forced errors, three tries per editor |
| X01 | MUT_APPEND_RMW | violated | violated | 1,838 | 86 | mutation: the claim/note line is appended to an earlier unlocked read (P3) |
| X02 | MUT_CLAIM_RMW | violated | violated | 2,175 | 86 | mutation: a claim rewrites the body from its earlier read, as today (P3) |
| X03 | MUT_NOCAS | violated | violated | 34 | 62 | mutation: replace ignores body_updated, last writer wins (P3) |
| X04 | MUT_CAS_SPLIT | violated | violated | 56 | 66 | mutation: replace compares body_updated before the item lock (P3) |
| X05 | MUT_READ_SPLIT | violated | violated | 35 | 66 | mutation: a read takes body and body_updated from two selects (P1) |
| X06 | MUT_HIST_SPLIT FAIL=1 | violated | violated | 13 | 34 | mutation: the history row commits in its own transaction (P4) |
| X07 | MUT_OPEN_CLEAR | violated | violated | 185 | 75 | mutation: a body write clears mail_to.opened, a second receipt (P7) |
| X08 | MUT_FRESH_READ | violated | violated | 37 | 64 | mutation: replace-body re-reads body_updated in the call, not the last read (P3) |
| X09 | MUT_NULL_NE | violated | violated | 34 | 62 | mutation: compare cur <> base; NULL never reads as stale (P3) |
| X10 | MUT_NULL_EQ CHECK_P6 | violated | violated | 10 | 20 | mutation: compare cur = base; a never-edited item is always stale (P6) |
| X11 | MUT_ANY_RIGHTS | violated | violated | 1,023 | 86 | mutation: no rights check (P2) |
| X12 | CLOSE=1 MUT_EDIT_RETIRED | violated | violated | 90 | 79 | mutation: replace on a retired item applies (P5) |
| X13 | MUT_APPEND_NOBUMP UNIQUE=0 | violated | violated | 1,706 | 72 | mutation: the append leaves body_updated as it was, a replace from before it passes (P3) |
| X14 | MUT_APPEND_NOBUMP | violated | violated | 1,706 | 83 | same with the UNIQUE key: on a never-edited item old_updated is NULL and NULLs never collide, so the append is still lost (P3) |
| X15 | MUT_NOREAD_NULL | violated | violated | 98 | 81 | mutation: no last read is sent as NULL; on a never-edited item a desk replaces text it never read (P3) |

A07 and A08 are expected violations: `body_updated` is a version only while
`MILL_NOW()` never repeats, so `UNIQUE (type, activity_id, old_updated)` is what
stops a lost update when it does (A06 vs A07), at the price of a rare refusal of
a replace built on the current text (A08). X01-X15 are mutations: every property
has at least one mutation that breaks it, so no pass is vacuous. X14 and X15
show the key never guards a NULL stamp (a never-edited item): the compare must
be NULL-safe, an append must stamp `body_updated`, and "no last read" must not
be sent as NULL.

Deferred with their features (removed from `run.sh`): edit hints and debounce,
`seen_rev` unread-again, acts carrying a version with a stale flag or refusal.
They return when those features do.

What is not modelled: text contents (a version is an id); the todo JSON split
and second install (deterministic tests on card 1133); the client keeping the
last read across `--desk` one-shots; more than one item; Wall rendering.

## Live wake modes (card 1144): F1, F2, F3, F7

Four failure modes seen live (auditor letter 5502), modelled in a `LIVE`
block of `wake.pml` (F1, F2, F7) and a `READ_DROP` block of `holds.pml` (F3).
The `LIVE` block reads main at 8bae076 (before #416) and ec280da (#416, card
1141, squash-merged): the switch `TW_GUARD=1` is the #416 change, an exit or
crash `tw.event` through the empty skip (`wake.py` 520-521, 1407). One desk,
armed with a webhook, a perfect receiver (POST failures stay with W08-W17).
Its own switches and the code lines each step stands for are in the block's
header. `-DLIVE=0`, the default, leaves the models above unchanged.

| Property | Result |
| :--- | :--- |
| F1. A finite connect that exits with nothing pending rings no wake | **violated** before #416 (V01): every tw exit hop rang `post_desk`, which exempted every `watch_id` frame from the empty skip; proved on #416 (V02); proved without tw, where only `Hub.discard` rings on the last leave and `ring_waiting` needs a missed row or unread mail (V03); fails on a mutation with no empty skip (V04) |
| F1. Every wake is counted by the wasted-wake tracker, and only for the run it woke | **violated**, modelled (V05, main and #416): `mark_lease` overwrites the desk's tracker with no stamp (`wasted_wake.py` 105-132), and `note_rpc` marks the live tracker acted for an action of any session of the desk (155-171). Builder's reading, not measured. Proved for one item with a stamp on lapse and the lease token on the run's commands (V06, proposed, card 1140 a and b) |
| F2. A same-desk reconnect after its own connect exited is not refused busy | **violated** (V07) when the office has not seen the close yet: `Hub.add` drops only sockets whose state already reads disconnected (`push.py` 123-125), and the client retries a 4409 only after 1 s and 2 s (`client/ws.py` 787, 1470-1481); proved with a retry while the holder is the desk's own exited connect (V08, proposed) |
| F2. A busy refusal rings no wake with nothing waiting | proved (V09): a refused add closes 4409 and returns before the `finally` that calls `HUB.discard` (`asgi.py` 633-643); a refused run's `wake-done` rings only for held work; fails on a mutation with no empty skip and a trailing POST with nothing waiting (V10) |
| F2. A seat-free delay loses no item | proved when a frame sent into the dead socket raises (V11); **violated** if `send_text` into a socket the office has not closed returns without error (V12): the row is marked sent, nothing rings, and the item waits for the next connect. Which one the code does is unclear (`push.py` 176-197, 226-240) |
| F3. A sync whose hold read starts after the drop committed never shows the hold | proved (V21): `mill_hold_delete` commits inside its procedure, and every read in `connect_sync_frame` commits after it (`db.py` 719-731), so `own()` reads a fresh snapshot; fails on a mutation that reuses the frame's first snapshot (V22) |
| F3. A sync printed after the drop reply never shows the hold | **reachable** (V23): a connect in a second shell reads its sync before the drop commits and prints it after the reply; proved in one shell, where the connect starts after the reply (V24) |
| F7. No wake started by the desk's own step when no outside work waits | **violated** before #416 (V13): the run's own tw exit hop; **violated** on #416 (V14, finding): `rec_push.pending` counts rows already sent live (`state <> 'taken'`, `records/push.py` 324-338), so a tw exit after a live item still rings; without tw the trailing POST does the same (V15, `_send_trailing`, `wake.py` 739); proved with both proposed changes: count only rows not sent live, and re-check the empty skip under the gate lock (V16, V17) |
| F7. No self-wake chain: a run that a self wake started does not start another | **violated** before #416 (V18); proved on #416 (V19) |
| The proposed changes lose nothing | proved (V20): every item delivered and every letter opened |

| Id | Defines | Expect | Got | States | Depth | What it shows |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| V01 | N=1 WK=1 TW=1 | violated | violated | 14 | 40 | F1 before #416 (main 8bae076): a tw exit hop of its own finite connect, nothing pending, rings a webhook wake (post_desk exempted every watch_id frame) |
| V02 | N=1 WK=1 TW=1 TW_GUARD=1 | pass | pass | 597,330 | 249 | F1, #416 (card 1141): a tw exit or crash goes through the empty skip; no wake with nothing waiting |
| V03 | N=2 WK=1 | pass | pass | 2,412,003 | 352 | F1, no tw: a connect exit (Hub.discard, ring_waiting) never rings with nothing pending, two items |
| V04 | N=1 WK=1 MUT_NO_EMPTY_SKIP | violated | violated | 14 | 39 | mutation: no empty skip in post_desk and ring_waiting (keeps V02 and V03 from being vacuous) |
| V05 | N=1 WK=1 TRACK=1 | violated | violated | 256 | 119 | F1 count, MODELLED (not measured): note_rpc marks the live tracker acted for any session of the desk and mark_lease overwrites an unstamped tracker, so a wake is miscounted (main and #416) |
| V06 | N=1 WK=1 TRACK=1 WASTE_FIX=1 | pass | pass | 8,174 | 170 | proposed (card 1140 a, b): stamp a lapsed lease, only the run holding the token marks it acted; one item |
| V07 | N=1 WK=2 ZOMBIE=1 | violated | violated | 3,159 | 188 | F2 FINDING: the own exited connect of the desk still sits until the office sees the close; a same-desk reconnect after the 1 s + 2 s settle is refused busy |
| V08 | N=1 WK=2 ZOMBIE=1 SETTLE_OWN=1 | pass | pass | 49,456 | 188 | proposed: a refused connect keeps retrying while the holder is its own exited connect |
| V09 | N=1 WK=1 ZOMBIE=1 | pass | pass | 7,320 | 166 | F2: a busy refusal never rings a wake with nothing waiting (the wake-done of a refused run rings only for held work) |
| V10 | N=1 WK=1 ZOMBIE=1 MUT_NO_EMPTY_SKIP MUT_TRAIL_ANY | violated | violated | 7,227,063 | 10359 | mutation: no empty skip and a trailing POST with nothing waiting (keeps V09 from being vacuous) |
| V11 | N=1 WK=1 ZOMBIE=1 | pass | pass | 1,088 | 111 | F2: with a seat-free delay, every item is still delivered and opened when a frame sent into the dead socket fails |
| V12 | N=1 WK=1 ZOMBIE=1 ZOMBIE_SEND_OK=1 | violated | violated | 496 | 111 | F2, UNCLEAR in the code: if send_text into the not-yet-closed socket returns, the row is marked sent, nothing rings, and the item waits for the next connect |
| V13 | N=1 WK=1 TW=1 SELFG=1 | violated | violated | 14 | 43 | F7 before #416: the own tw exit hop of the run starts a wake with no outside work |
| V14 | N=1 WK=1 TW=1 TW_GUARD=1 SELFG=1 | violated | violated | 11,429 | 185 | F7 FINDING on #416: pending() counts rows already sent live, so a tw exit after a live item rings a wake for work the desk has |
| V15 | N=2 WK=1 SELFG=1 | violated | violated | 137,028 | 294 | F7 FINDING, no tw: the wake-done trailing POST (_send_trailing, pending()) rings for a row sent live |
| V16 | N=2 WK=1 PENDING_OWED=1 SKIP_TAKE_ATOMIC=1 SELFG=1 | pass | pass | 2,454,055 | 362 | proposed: count only rows not sent live, and re-check empty under the gate lock: no self wake, two items |
| V17 | N=1 WK=1 TW=1 TW_GUARD=1 PENDING_OWED=1 SKIP_TAKE_ATOMIC=1 SELFG=1 | pass | pass | 612,483 | 255 | same with tw exit hops on #416 |
| V18 | N=1 WK=1 TW=1 SELFG=1 | violated | violated | 76 | 202 | F7 before #416: a run a self wake started rings another self wake (the loop) |
| V19 | N=1 WK=1 TW=1 TW_GUARD=1 SELFG=1 | pass | pass | 672,282 | 255 | F7, #416: no self wake chain beyond one per lease (V18 is its old-shape mutant) |
| V20 | N=1 WK=1 TW=1 TW_GUARD=1 PENDING_OWED=1 SKIP_TAKE_ATOMIC=1 | pass | pass | 44,736 | 151 | the proposed fixes lose nothing: every item delivered and opened |
| V21 | READ_DROP=1 | pass | pass | 25 | 23 | F3: a sync whose hold read starts after the drop commit never shows the hold (each read commits, so a fresh snapshot) |
| V22 | READ_DROP=1 MUT_SNAPSHOT_CARRY | violated | violated | 20 | 23 | mutation: the hold read reuses the first snapshot of the frame (REPEATABLE READ, no commit between reads) |
| V23 | READ_DROP=1 | violated | violated | 14 | 23 | F3 REACHABLE: a connect sync in a second shell, read before the drop commits, prints after the drop reply and shows the dropped hold |
| V24 | READ_DROP=1 SAME_SHELL=1 | pass | pass | 11 | 25 | F3: in one shell (connect after the drop reply) the sync never shows the dropped hold |

V01-V24 run with `-DLIVE=1` (wake) or `-DREAD_DROP=1` (holds) and small
bounds: one or two items, one or two finite connects of the desk's working
session, one woken run. Larger bounds ran out of memory or time on the run host
(tw with two connects: 9 million states; tw with two items: out of memory). Each `pass` has a
`violated` partner, a mutation or the old shape, so no pass is vacuous: V02 and
V03 (V04, V01), V06 (V05), V08 (V07), V09 (V10), V11 (V12), V16 and V17 (V14,
V15), V19 (V18), V21 (V22), V24 (V23).

What is not modelled here: stall and match hops (still exempt on #416), a
command reply sync that acks a row sent live before the tw exit hop goes out
(`asgi.py` 684-701; if it always wins, V14 does not happen live), the lease
timer length, the token reuse of the model's three lease tokens, F4 (a stale
wake-done on an ordinary run, card 1140), F5 (no-route queue, card 1142), F6
and F8 (tw ready race, card 1154).

## Product-edge sync (card 916)

Deterministic product tests name each covered edge as the token `SPIN <id>` (see `product_edges.txt`). On demand, not in CI:

```
python tools/check_spin_edges.py
```

Exit 0 only when every listed id is mapped. N03 stays on card 906.
