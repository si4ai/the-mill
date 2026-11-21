# SPIN models of the mill coordination design

Small models of two parts of the mill, written in the `spin` input language
and checked with the `spin` model checker (from the 1991 book on designing and
validating computer protocols that introduced it).
A test checks the cases someone wrote down. A model check tries every order
in which the steps of the model can interleave, inside the stated bounds.

| File | What it models |
| :--- | :--- |
| `wake.pml` | the wake path: push queue, webhook POST, the wake lease (card 886: ended by `mill wake-done` or its timeout, not by a connect), the trailing POST (#669), card 827's retry chain off the request (#300, live since 0.8.3), unread mail that resurfaces on connect and rings again (#297, card 949), wake-done inside a connect with no trailing POST to a sitting desk (#322, card 889, 0.8.5), connect sync, the seat rule (supersede, `-r` 4409), and the fixes for cards 831 and 832 (shipped; their switches default on); `LIVE`: the wake path at main 8bae076 and #416 for the live modes F1, F2, F7 (card 1144) |
| `holds.pml` | `mill hold` / `mill drop` (refuse at once, no TTL, only the owner drops, reset and retire free a desk's holds), with three desk policies for what to do after a refusal; `READ_DROP`: a connect sync against a committed drop (card 1144, F3); `RUNS`: card 1267, who owns a hold when one desk has two runs (`OWNER=0` today's desk-owned hold, the counterexample; `OWNER=2` the card's release-key design as PR #490 builds it; `OWNER=1` the run-token design of letter 6649, kept for comparison) |
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

Last full run: 194 checks on release/0.8.16 head 77ed251 plus the card 1267
`RUNS` block (`OWNER=2` checked against PR #490 head 047b9f5), 2026-11-20
(Pacific), in 965 s: 192 matched their expectation (78 `pass`, 114 `violated`
as expected: findings, mutants, reachability goals, the card 1125 design
expected-violations and mutations, the card 1144 live wake modes V01-V24, and
the card 1267 rows K01-K31 and M25-M37). W04 and W19 gave no result: `pan`
was killed by the out-of-memory killer on a shared run host. `wake.pml` is
unchanged by this pass: W04 passed when rerun alone the same night, and W19
passed in this pass's first full run (2026-11-20) but was killed again when
rerun alone. The wake checks store states compressed (`-DCOLLAPSE`), as the 0.8.0
and activity_history checks do.

All searches are exhaustive (no `-DBITSTATE`, no depth cut). Liveness checks
run with weak fairness (`pan -a -f`): every process that can always move
eventually moves (a named liveness claim uses the `liveltl:NAME` mode of
`run.sh`, the same `pan -a -f`). The receiver's choice to fail a POST is not covered by
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

## Card 1267: who owns a hold when one desk has two runs (RUNS)

Letter 6649 (builder): a hold is owned by the desk, so two runs of one desk
(a wake and a foreground job, or two wakes) both believe they own it; a
second take from the same desk returns `ok`, `held: true`, `refreshed: true`
and the same id. Card 1256's double drafts are the live trace. The `RUNS`
block of `holds.pml` models three runs (runs 0 and 1 of desk 0, run 2 of
desk 1) on one resource. Every command is a one-shot `--desk` borrow; a run
may be slow (any number of steps of the others between two of its commands);
and a run may run `mill drop` on its way out whether or not it believes it
holds. `-DRUNS=0`, the default, leaves the models above unchanged.

- `OWNER=0` is the code today: release/0.8.16 head 77ed251, hold code unchanged
  since v0.8.15 (`mill_hold_upsert`, `mill_hold_delete` in `sp_hold.sql`;
  `_h_hold` in `rpc.py`, `emit_refuse` through `_safe_put` in
  `hold_activity.py`).
- `OWNER=2` is card 1267 as the owner set it (2026-11-20, 10:09-10:12 PM
  Pacific), checked against PR #490 head 047b9f5 (landed as a9d5f2e): a take of a
  free hold is atomic and writes the key hash on its `hold_grant` row; a take
  of a held one is refused for every caller, same desk included, with a
  `hold_refuse` row in the same transaction (classed same-desk or cross-desk
  by `contention_view`); `mill hold X --key K` with the live key is the
  hand-off (the caller's desk becomes the holder and a new key hash goes on a
  `hold_refresh` row, so K is spent); `mill drop X --key K` (`mill_hold_drop`)
  frees it when K is the live key, any desk, and a refused keyed drop writes
  its row in the same transaction; a keyless drop is the admin.md override for
  every desk, its own included; no run or session is recorded; no expiry.
- `OWNER=1` is the run-token design in letter 6649 (run token plus desk on the
  row, same-run refresh, TTL with renewal). The owner chose the key design
  instead; the rows stay as the comparison and can be dropped.

`OWNER=1` is not built. `OWNER=2` describes PR #490 (letter 6666); the default
stays `OWNER=0` while release/0.8.16 still has today's code. When #490 lands,
flip the default to 2 and pin `SYNC` for the hold rows to the merge.

Assumptions:

- A1, A2, A3 (`OWNER=1` only): the owner is a run token; a live run's renewal
  beats the TTL (a heartbeat or the client renews; M28 shows a slow run loses
  its hold without it); expiry by a sweeper or any read.
- A4. The trust matrix: an Admin may drop a live hold (`ADMIN=1`). For
  `OWNER=2` the stale rule frees a hold only when the holder desk is not
  connected (`seat_connected` is per desk; `STALE=1`); the day count is
  abstracted to "eventually".
- A5. A refusal carries the reason and the next step; reply text is not
  modelled.
- A6 (`OWNER=2`). A keyless drop by the holder's own desk is the override
  (card point 4; `KEYLESS_OWN=0`, as #490 builds it: `mill_hold_release_other`
  lost its own-desk `kept` branch). `KEYLESS_OWN=1` lets it free the hold, as
  an own-desk drop does today.
- A7 (`OWNER=2`). A handoff by letter (`HANDOFF=1`) copies the key: the sender
  cannot unknow it. `REKEY=1` is #490: the receiver relies on the hold only
  once `mill hold X --key K` answered `handoff` (K spent, a new key, the holder
  desk moved, one transaction). `REKEY=0` is a receiver that relies on the
  copy as is; `REKEY=2` one that relies on it at once and re-keys later.
- A8 (`OWNER=2`). A refused keyless drop is the one refusal row #490 still
  writes outside its transaction (`_h_drop` calls `emit_refuse` through
  `_safe_put` after the decision). `DROP_LOG_TX=1` is the fix.

| Property | Result |
| :--- | :--- |
| At most one live run believes it owns a hold | **violated** today (K01, the counterexample): run 0 of desk 0 takes the free row; run 1 of desk 0 takes it again and the same-desk branch of `mill_hold_upsert` answers ok (refreshed, same id); both runs believe they own it. Proved for the key design (K15), also when runs die (K20) and with the #490 hand-off (K28); fails when the take reads then writes (M32) and when a same-desk take refreshes, as today (M33). Run-token design: proved (K05, K09); M25, M26, M27 fail |
| A live run that believes it owns a hold still owns it (a slow run never loses a hold it still uses) | **violated** today (K02): the losing run of the same desk runs `mill drop` on its way out, `mill_hold_delete` matches the desk, and the hold the other run still uses is freed. Proved for the key design (K16): nothing expires, and a losing run has no key; fails when the drop checks the desk and not the key (M34). **Violated** for the key design if a keyless own-desk drop freed (K24, A6; #490 makes it the override, so K16 holds) and when a receiver relies on a key copied by letter without `mill hold X --key K` first (K25: the sender's cleanup drop with its copy frees the receiver's hold), also when it relies on the copy at once and re-keys later (K26); proved with the #490 hand-off, where the receiver relies on the hold only after the `--key` take answered (K27), which fails when the key belongs to the resource and not to one take (M35) and when the hand-off writes no new key hash (M37). By design an Admin keyless drop takes a live run's hold (K29). Run-token design: proved (K06, K10); M28, M29 fail; Admin (K14) |
| A hold that no live run can use is freed | **violated** today (K03): no TTL, as H11. Key design: **violated by design** (K22), no expiry; and **violated** with the stale rule (K23, FINDING): the rule is per desk, so a run that died holding the key keeps the hold while another run of its desk lives, until an Admin acts. Run-token design: proved with the TTL (K07); M30 fails |
| Every refused take has its refusal row | **violated** today (K04, FINDING, modelled not measured): `_h_hold` writes the refusal transition (`emit_refuse`) after the procedure committed, through `_safe_put`, which swallows any error, so a refusal can go unrecorded (card 1271). Proved for the key design, which #490 builds: the row is written in the take's transaction (K17); fails when it is written after the commit (M36). Run-token design: K08, M31 |
| Every refused drop has its refusal row (`refused_drop_n`) | #490: a refused keyed drop writes its row in `mill_hold_drop`'s transaction, but a refused keyless drop is written by `_h_drop` through `emit_refuse` (`_safe_put`) after the decision: **violated** (K30, FINDING, card 1271); proved when that row is written in the drop's transaction (K31) |
| Same-desk and cross-desk refusals are both reachable and recorded apart (scored apart) | reachable for the key design: same-desk (K18; today a same-desk take is a refresh, so it never counts), cross-desk (K19). Run-token design: K12, K13. Each is a "never" rule expected to be violated |
| No invalid end state | proved (K21 key design, K11 run-token design): a take never waits |

| Id | Defines | Expect | Got | States | Depth | What it shows |
| :--- | :--- | :--- | :--- | ---: | ---: | :--- |
| K01 | `-DOWNER=0` | violated | violated | 120 | 253 | card 1267 COUNTEREXAMPLE (today): two runs of one desk both own the hold (the second take is refreshed, same id) |
| K02 | `-DOWNER=0` | violated | violated | 140 | 297 | card 1267 today: a losing run of the same desk drops the hold the other run still uses (drop checks the desk only) |
| K03 | `-DOWNER=0 -DDIE=1` | violated | violated | 743 | 1532 | card 1267 today: no TTL, a dead run keeps its hold forever (as H11) |
| K04 | `-DOWNER=0` | violated | violated | 136 | 288 | FINDING (modelled): today the refusal transition is written after the hold commit and soft-fails, so a refusal can go unrecorded |
| K05 | `-DOWNER=1` | pass | pass | 3227 | 1261 | run-token design (letter 6649): at most one live run believes it owns the hold (same desk or not) |
| K06 | `-DOWNER=1` | pass | pass | 3227 | 1261 | run-token design (letter 6649): a slow live run never loses a hold it keeps renewing (one-shot borrows between commands) |
| K07 | `-DOWNER=1 -DDIE=1` | pass | pass | 10140 | 1587 | run-token design (letter 6649): the hold of a dead run frees after the TTL |
| K08 | `-DOWNER=1` | pass | pass | 3227 | 1261 | run-token design (letter 6649): every refused take is logged in the same transaction |
| K09 | `-DOWNER=1 -DDIE=1` | pass | pass | 7916 | 1569 | run-token design (letter 6649): single owner also with dead runs and TTL expiry |
| K10 | `-DOWNER=1 -DDIE=1` | pass | pass | 7916 | 1569 | run-token design (letter 6649): TTL expiry never takes a hold from a live run |
| K11 | `-DOWNER=1 -DDIE=1` | pass | pass | 7916 | 916 | run-token design (letter 6649): no invalid end state (take never waits) |
| K12 | `-DOWNER=1` | violated | violated | 90 | 216 | run-token design, reachable: a same-desk refusal (two runs of one desk) is logged as same-desk |
| K13 | `-DOWNER=1` | violated | violated | 9 | 23 | run-token design, reachable: a cross-desk refusal is logged as cross-desk |
| K14 | `-DOWNER=1 -DADMIN=1` | violated | violated | 8 | 19 | run-token design, by design (trust matrix): an Admin force-drop takes the hold of a live run; the run learns only from refreshed:false on its next take |
| K15 | `-DOWNER=2` | pass | pass | 2665 | 110 | card 1267 key design: at most one live run believes it owns the hold (a held take is refused, same desk included) |
| K16 | `-DOWNER=2` | pass | pass | 2665 | 110 | card 1267 key design: a live run (slow or not) never loses a hold it holds the key for; a losing run cannot drop it on its way out |
| K17 | `-DOWNER=2` | pass | pass | 2665 | 110 | card 1267 key design: every refused take is recorded in the same transaction |
| K18 | `-DOWNER=2` | violated | violated | 14 | 30 | card 1267 key design, reachable: a same-desk collision is now a refusal, recorded as same-desk |
| K19 | `-DOWNER=2` | violated | violated | 16 | 36 | card 1267 key design, reachable: a cross-desk refusal is recorded as cross-desk |
| K20 | `-DOWNER=2 -DDIE=1` | pass | pass | 4348 | 114 | card 1267 key design: single owner also when runs die holding the key |
| K21 | `-DOWNER=2 -DDIE=1` | pass | pass | 4348 | 69 | card 1267 key design: no invalid end state (a take never waits) |
| K22 | `-DOWNER=2 -DDIE=1` | violated | violated | 162 | 142 | card 1267 key design, by design: no expiry; a hold whose key died with its run stays held until an override |
| K23 | `-DOWNER=2 -DDIE=1 -DSTALE=1` | violated | violated | 773 | 206 | FINDING (key design): the stale rule is per desk (seat_connected), so a dead run keeps its hold while another run of the same desk lives |
| K24 | `-DOWNER=2 -DKEYLESS_OWN=1` | violated | violated | 269 | 110 | A6 counterfactual: if a keyless drop by the own desk freed the hold, the losing run would free the hold of the winner again (as K02); #490 makes it the override (KEYLESS_OWN 0, K16) |
| K25 | `-DOWNER=2 -DHANDOFF=1` | violated | violated | 153 | 113 | key design: a receiver that relies on a key copied by letter, without mill hold X --key K first, loses the hold to the cleanup drop of the sender (the docs must say: take with --key first) |
| K26 | `-DOWNER=2 -DHANDOFF=1 -DREKEY=2` | violated | violated | 153 | 113 | key design: a receiver that relies on the copy at once and re-keys later still leaves the window open |
| K27 | `-DOWNER=2 -DHANDOFF=1 -DREKEY=1` | pass | pass | 339796 | 292 | PR #490 hand-off: the receiver relies on the hold once mill hold X --key K answered handoff (K spent, new kh, holder moved, one transaction); the copy of the sender frees nothing |
| K28 | `-DOWNER=2 -DHANDOFF=1 -DREKEY=1` | pass | pass | 339796 | 292 | PR #490 hand-off: still one owner |
| K29 | `-DOWNER=2 -DADMIN=1` | violated | violated | 8 | 18 | key design, by design (trust matrix): an Admin keyless drop takes the hold of a live run; its key is then spent |
| K30 | `-DOWNER=2` | violated | violated | 48 | 99 | FINDING (#490): a refused keyless drop is recorded by rpc.py _h_drop through emit_refuse (_safe_put, soft-fail) after the decision, so a refused drop can go unrecorded (card 1271) |
| K31 | `-DOWNER=2 -DDROP_LOG_TX=1` | pass | pass | 1368 | 103 | fix for K30: the keyless refusal row is written in the drop transaction, as #490 does for keyed drops and takes |
| M25 | `-DOWNER=1 -DMUT_SPLIT_TAKE` | violated | violated | 75 | 166 | mutation of the run-token design: read-then-write take (not atomic) gives two owners (keeps K05 from being vacuous) |
| M26 | `-DOWNER=1 -DMUT_TAKE_DESK` | violated | violated | 90 | 214 | mutation of the run-token design: the take checks the desk, not the run (the rule today) |
| M27 | `-DOWNER=1 -DMUT_DROP_DESK` | violated | violated | 145 | 351 | mutation of the run-token design: the drop checks the desk, not the run; a losing run frees the hold of the winner |
| M28 | `-DOWNER=1 -DMUT_RENEW_BY_COMMAND_ONLY` | violated | violated | 10 | 22 | mutation of the run-token design: only an explicit take renews; a slow live run loses its hold to the TTL (keeps K06 from being vacuous) |
| M29 | `-DOWNER=1 -DMUT_OWNER_IS_BORROW` | violated | violated | 8 | 18 | mutation of the run-token design: the owner is the one-shot borrow; the hold ends with the borrow |
| M30 | `-DOWNER=1 -DDIE=1 -DMUT_NO_TTL` | violated | violated | 657 | 1499 | mutation of the run-token design: no expiry (keeps K07 from being vacuous) |
| M31 | `-DOWNER=1 -DMUT_LOG_AFTER` | violated | violated | 77 | 171 | mutation of the run-token design: the refusal log is written after the commit and may fail (keeps K08 from being vacuous) |
| M32 | `-DOWNER=2 -DMUT_SPLIT_TAKE` | violated | violated | 2910 | 307 | mutation of the key design: read-then-write take gives two owners (keeps K15 from being vacuous) |
| M33 | `-DOWNER=2 -DMUT_SAME_DESK_REFRESH` | violated | violated | 150 | 104 | mutation of the key design: a same-desk take refreshes, as today (keeps K15 from being vacuous) |
| M34 | `-DOWNER=2 -DMUT_DROP_DESK` | violated | violated | 269 | 110 | mutation of the key design: the drop checks the desk, not the key (keeps K16 from being vacuous) |
| M35 | `-DOWNER=2 -DHANDOFF=1 -DREKEY=1 -DMUT_KEY_STATIC` | violated | violated | 3856 | 198 | mutation of the key design: one key per resource, not per take; an old copy still frees the hold (keeps K27 from being vacuous) |
| M36 | `-DOWNER=2 -DMUT_LOG_AFTER` | violated | violated | 35 | 75 | mutation of the key design: the refusal row is written after the commit and may fail (keeps K17 from being vacuous) |
| M37 | `-DOWNER=2 -DHANDOFF=1 -DREKEY=1 -DMUT_HANDOFF_SAME_KEY` | violated | violated | 172 | 142 | mutation of #490: the hand-off moves the holder but writes no new kh; the copy of the sender still frees the hold (keeps K27 from being vacuous) |

Each `pass` has a `violated` partner, so no pass is vacuous. Key design: K15,
K20 and K28 (M32, M33), K16 (M34), K27 (M35, M37), K17 (M36), K31 (K30). Run-token design:
K05 and K09 (M25, M26, M27), K06 and K10 (M28, M29), K07 (M30), K08 (M31).

What is not modelled here: the reply text and its next step (A5); the key
hash and its storage (`meta.kh`, anchored in `verify/hold-code`); a key
guessed or replayed by a desk that never saw it; the name-insert race path of
`mill_hold_upsert` (1062, 1213, 1644 answered as a refusal: if the hold row is
not there after the re-read, the refusal has no row, and a row freed in
between is refused as held); the override's `hold_force` row (written by
`emit_force` after the commit, card 941); the stale rule's day count; more
than one resource per run (H01-H13 cover lock order); the collision score
itself (`contention_view`, a read over the refusal rows).

## Product-edge sync (card 916)

Deterministic product tests name each covered edge as the token `SPIN <id>` (see `product_edges.txt`). On demand, not in CI:

```
python tools/check_spin_edges.py
```

Exit 0 only when every listed id is mapped. N03 stays on card 906.
