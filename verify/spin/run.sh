#!/usr/bin/env bash
# run.sh - run every SPIN check of the wake path, holds and 0.8.0 activity models with fixed flags.
#
# Each check has an expected result: pass, or violated (a known finding or a
# mutation that must fail). The run exits nonzero when any check differs from
# its expectation, when spin or the C compiler fails, or when a search is not
# exhaustive (depth limit hit, out of memory). --strict also exits nonzero on
# any violation, expected or not.
#
#   verify/spin/run.sh            all checks
#   verify/spin/run.sh --strict   all checks; any violation fails the run
#   verify/spin/run.sh W06        one check by id (prints its trail)
#   OUT=DIR verify/spin/run.sh    keep pan output and trails in DIR
#
# Needs spin (6.5.x) and a C compiler. Searches are exhaustive: no BITSTATE.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
STRICT=0; ONLY=""
for a in "$@"; do case "$a" in --strict) STRICT=1;; -h|--help) sed -n 2,16p "$0"; exit 0;; *) ONLY="$a";; esac; done
command -v spin >/dev/null || { echo "run.sh: spin not found (apt-get install spin, or build github.com/nimble-code/Spin)"; exit 2; }
CC="${CC:-gcc}"; command -v "$CC" >/dev/null || { echo "run.sh: no C compiler ($CC)"; exit 2; }
OUT="${OUT:-$(mktemp -d)}"; mkdir -p "$OUT"
DEPTH=300000

# The commit at which these models were last confirmed to describe the code.
SYNC=8a80dc1
COVERED="agent_coord/server/wake.py agent_coord/server/push.py agent_coord/server/asgi.py
agent_coord/server/records/push.py agent_coord/server/sql/sp_push.sql
agent_coord/server/sql/sp_hold.sql agent_coord/server/records/hold.py
agent_coord/server/api/mill/rpc.py agent_coord/client/http.py
agent_coord/client/ws.py agent_coord/__main__.py agent_coord/server/sql/sp_join.sql agent_coord/server/sql/sp_name.sql agent_coord/server/sql/sp_beta_name.sql"
ROOT="$(git -C "$HERE" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$ROOT" ] && git -C "$ROOT" cat-file -e "$SYNC^{commit}" 2>/dev/null; then
  # shellcheck disable=SC2086
  changed=$(cd "$ROOT" && git diff --name-only "$SYNC" -- $COVERED | tr '\n' ' ')
  [ -n "$changed" ] && echo "note: covered code changed since $SYNC: $changed- recheck the models (SKILL.md)"
fi

# The 0.8.0 activity models (todo, doing, mail, score, name) describe the design in
# docs/requirements/beta/activity-states-080.md at DOC_080 and the code at SYNC_080
# (the 0.8.0 release, main 8a80dc1). Move both when that code changes.
DOC_080=c2a91f9
SYNC_080=8a80dc1
COVERED_080="agent_coord/server/sql/sp_todo.sql agent_coord/server/sql/sp_cmd.sql
agent_coord/server/sql/sp_doing.sql agent_coord/server/sql/sp_join.sql agent_coord/server/sql/sp_hold.sql
agent_coord/server/sql/sp_opened.sql agent_coord/server/sql/sp_score.sql agent_coord/server/sql/sp_beta_name.sql
agent_coord/server/sql/fn_name.sql agent_coord/server/api/mill/rpc.py"
if [ -n "$ROOT" ] && git -C "$ROOT" cat-file -e "$SYNC_080^{commit}" 2>/dev/null; then
  # shellcheck disable=SC2086
  changed=$(cd "$ROOT" && git diff --name-only "$SYNC_080" -- $COVERED_080 | tr '\n' ' ')
  [ -n "$changed" ] && echo "note: 0.8.0 covered code in this checkout differs from $SYNC_080: $changed- recheck todo, doing, mail, score, name"
fi

# id | model | defines | mode | expect | what it shows
CHECKS='
W01|wake|-DN=2 -DSESSIONS=1 -DMAXFAIL=2|safety|pass|one wake per lease; no invalid end state (main)
W02|wake|-DN=3 -DSESSIONS=1 -DMAXFAIL=0 -DMULTI=0|safety|pass|same, three items, one connect per run (more runs out of memory)
W03|wake|-DN=2 -DSESSIONS=2 -DMAXFAIL=1|safety|pass|same, two connects of the desk
W04|wake|-DN=3 -DSESSIONS=1 -DMAXFAIL=0 -DMULTI=0|no_loss|pass|no taken row is lost, one connect at a time, three items
W05|wake|-DN=2 -DSESSIONS=2 -DMAXFAIL=0|no_loss|pass|main (831 fix shipped): a superseded connect (--take) loses no rows
W06|wake|-DN=2 -DSESSIONS=2 -DREFUSE=1 -DMAXFAIL=0|no_loss|pass|connect -r (4409) never supersedes, so nothing is lost
W07|wake|-DN=2 -DMAXFAIL=0|live|pass|card 887 fix (PR #218): lease check and record in one hold: every item delivered
W08|wake|-DN=2 -DMAXFAIL=2 -DATOMIC_EMIT=1|live|violated|EXPECTED: both POSTs fail, no later try (current main)
W09|wake|-DN=2 -DMAXFAIL=0 -DATOMIC_EMIT=1|live|pass|no loss and no races: every item delivered
W10|wake|-DN=2 -DMAXFAIL=0 -DATOMIC_EMIT=1 -DRECEIPT=1|live|violated|BY DESIGN: a receipt never rings; it waits for a connect
W11|wake|-DN=2 -DMAXFAIL=2 -DRESTART=1|safety|violated|minor: a wall restart forgets the window; a 2nd POST inside the lease
W12|wake|-DN=2 -DATOMIC_EMIT=1 -DRETRY827=1 -DRETRIES=2 -DMAXFAIL=5|live|pass|card 827: up to 5 lost POSTs in a row, delivered
W13|wake|-DN=2 -DATOMIC_EMIT=1 -DRETRY827=1 -DRETRIES=2 -DMAXFAIL=6|live|violated|card 827: 6 in a row outlast the 6 POSTs of the budget
W14|wake|-DN=2 -DLEASE=0 -DPUTFIRST=1 -DRING_ON_LEAVE=1 -DMAXFAIL=0|live|pass|pre-886 gate, fix 832: queue first, mark sent after a live send, ring on leave: no strand
W15|wake|-DN=3 -DLEASE=0 -DPUTFIRST=1 -DRING_ON_LEAVE=1 -DMAXFAIL=0|live|pass|same, three items
W16|wake|-DN=2 -DLEASE=0 -DPUTFIRST=1 -DRING_ON_LEAVE=1 -DRETRY827=1 -DRETRIES=2 -DMAXFAIL=5|live|pass|827 + fix 832, real interleaving, lossy receiver
W17|wake|-DN=2 -DPUTFIRST=1 -DRING_ON_LEAVE=1 -DRETRY827=1 -DRETRIES=2 -DMAXFAIL=255|live|violated|EXPECTED: a receiver down forever; no bounded retry helps
W18|wake|-DN=2 -DSESSIONS=2 -DMAXFAIL=0 -DACK_AFTER_SEND=1|no_loss|pass|fix 831: read, send, then delete: a superseded connect loses nothing
W19|wake|-DN=3 -DLEASE=0 -DSESSIONS=2 -DMAXFAIL=1 -DACK_AFTER_SEND=1 -DPUTFIRST=0 -DRING_ON_LEAVE=0|no_loss|pass|fix 831 alone, three items, a lossy receiver (both fixes at N=3: the search ran out of memory)
W20|wake|-DN=2 -DSESSIONS=2 -DMAXFAIL=1 -DACK_AFTER_SEND=1 -DPUTFIRST=1 -DRING_ON_LEAVE=1|safety|pass|both fixes: still one wake per window, no invalid end state
W21|wake|-DN=2 -DSESSIONS=2 -DMAXFAIL=0 -DACK_AFTER_SEND=1 -DPUTFIRST=1 -DRING_ON_LEAVE=1|no_loss|pass|both fixes, two connects: nothing lost
W22|wake|-DN=2 -DLEASE=0 -DSESSIONS=2 -DMAXFAIL=0 -DACK_AFTER_SEND=1 -DPUTFIRST=1 -DRING_ON_LEAVE=1|live|pass|both fixes, two connects, pre-886 gate: every item delivered
W23|wake|-DN=2 -DSESSIONS=2 -DMAXFAIL=0 -DACK_AFTER_SEND=0|no_loss|violated|pre-831 order (take, then send): a superseded connect loses taken rows
W24|wake|-DN=2 -DLEASE=0 -DMAXFAIL=0 -DPUTFIRST=0 -DRING_ON_LEAVE=0|live|violated|pre-832 order (POST, then queue): perfect receiver, still stranded
W25|wake|-DN=2 -DMAXFAIL=0 -DHOLD1=0|live|violated|pre-887 order (#216): peek sees the lease, wake-done ends it, the record finds none: no POST
L01|wake|-DN=2 -DMAXFAIL=0|no_stale_done|pass|card 888 fix (PR #218): wake-done --lease TOKEN ends only its own lease
L02|wake|-DN=2 -DMAXFAIL=1 -DLEASE=0 -DMULTI=1 -DONE_RUN=1|safety|violated|pre-886 design: a connect frees the gate mid-run, a second POST lands (the storm)
L03|wake|-DN=2 -DMAXFAIL=1|safety|pass|lease: no new POST while the last lease is held (done or timeout ends it)
L04|wake|-DN=2 -DMAXFAIL=0 -DATOMIC_EMIT=1|live|pass|lease with emits atomic: done or timeout, every item delivered
L06|wake|-DN=2 -DMAXFAIL=0 -DLAPSE_FIRING=1|no_stale_done|pass|card 890: a lease lapses while its POST is in flight and a newer lease starts; the run still holds the token of its own take
L05|wake|-DN=2 -DMAXFAIL=0 -DTOKEN=0|no_stale_done|violated|no token (older client): a run that outlives its lease ends the lease of the next run
M06|wake|-DN=2 -DMAXFAIL=0 -DATOMIC_EMIT=1 -DMUT_DONE_ANY|live|violated|mutation of the lease: wake-done sends no trailing POST
M07|wake|-DN=2 -DMAXFAIL=0 -DMUT_RUN_CURRENT|no_stale_done|violated|mutation of card 888: the run binds the lease current at its start, not the token its POST carried
M21|wake|-DN=2 -DMAXFAIL=0 -DLAPSE_FIRING=1 -DMUT_LATE_TOKEN|no_stale_done|violated|mutation of card 890: the POST body reads the lease current at send time, not the token its take returned
M01|wake|-DN=2 -DMUT_SPLIT_GATE|safety|violated|mutation: peek-then-set gate gives two wakes in one window
M02|wake|-DN=2 -DATOMIC_EMIT=1 -DRETRY827=1 -DRETRIES=2 -DMAXFAIL=5 -DMUT_827_NOGEN|live|violated|mutation: an old retry cancels a newer chain
M04|wake|-DN=2 -DPUTFIRST=1 -DRING_ON_LEAVE=1 -DMAXFAIL=0 -DMUT_SENT_EARLY|live|violated|mutation of fix 832: mark sent at hand-off, no ring when no socket took it
H01|holds|-DDESKS=2 -DPOLICY=0|mutex|pass|mutual exclusion, 2 desks
H02|holds|-DDESKS=3 -DPOLICY=1|mutex|pass|mutual exclusion, 3 desks
H03|holds|-DDESKS=3 -DPOLICY=0 -DROUNDS=1|safety|pass|the mill never blocks: no invalid end state
H04|holds|-DDESKS=2 -DPOLICY=0|np|violated|FINDING: keep-and-retry in a cycle: desks spin forever (deadlock as a busy loop)
H05|holds|-DDESKS=3 -DPOLICY=0|np|violated|same, 3 desks in a cycle
H06|holds|-DDESKS=2 -DPOLICY=1|np|violated|FINDING: drop-all-and-retry can livelock
H07|holds|-DDESKS=2 -DPOLICY=2|np|pass|one global lock order: no deadlock or livelock
H08|holds|-DDESKS=3 -DPOLICY=2|np|pass|same, 3 desks
H09|holds|-DDESKS=2 -DPOLICY=2|starve|violated|FINDING: no queue: a desk can lose every race (starvation)
H10|holds|-DDESKS=2 -DPOLICY=2 -DROUNDS=1|starve|pass|finite work: every desk gets its locks
H11|holds|-DDESKS=2 -DPOLICY=2 -DDIE=1|np|violated|FINDING: no TTL: a dead desk nobody resets keeps its holds forever
H12|holds|-DDESKS=2 -DPOLICY=2 -DDIE=1 -DRESET=1|np|pass|card 842: reset or retire of a dead desk frees its holds; the others progress
H13|holds|-DDESKS=2 -DPOLICY=2 -DDIE=1 -DRESET=1|mutex|pass|card 842: the release keeps mutual exclusion
M05|holds|-DDESKS=2 -DPOLICY=2 -DDIE=1 -DRESET=1 -DMUT_RESET_KEEPS|np|violated|mutation of card 842: reset that keeps the holds leaves the others stuck
M03|holds|-DDESKS=2 -DPOLICY=0 -DMUT_HOLD_NOLOCK|mutex|violated|mutation: no FOR UPDATE breaks mutual exclusion
T01|todo|-DCHECK_EDGES|inv|pass|0.8.0 todo at 8a80dc1: every committed move is an edge (guards under the card lock; T8 from open with a volunteer)
T02|todo|-DCHECK_EDGES -DUNPARK_GUARD=0|inv|violated|mutation (pre-F186): unpark has no status guard; a claimed, shipped or done card goes open
T03|todo|-DCHECK_EDGES -DASSIGN_LOCKED=0|inv|violated|mutation (pre-F186): assign checks an unlocked read, then writes blind
T04|todo|-DCHECK_EDGES -DDELETED_GUARD=0|inv|violated|mutation (pre-F186): no deleted check under the card lock
T05|todo||ltl:act_last|pass|invariant 4: activity.act is the act of the last committed step
T06|todo|-DMIGRATED=1|inv|pass|migration seed carries the volunteer in peer_id (invariants 3, 5, 6)
T07|todo|-DMIGRATED=1 -DSEED_VOL=0|inv|violated|mutation: a seed row for a shipped or done card without its volunteer
R01|todo||ltl:reach_card|violated|REACHABLE (goal 1): filed -> claimed -> shipped -> done
M08|todo|-DMUT_WAS_NOLOCK|inv|violated|mutation: the card write reads the old status before the lock (invariant 5)
M09|todo|-DMUT_STATUS_ONLY|inv|violated|mutation (#214 draft filter): no move row for a volunteer change (invariant 3)
M10|todo|-DMUT_ACT_LATE|ltl:act_last|violated|mutation: the activity act lands after the card lock is released (invariant 4)
D01|doing||inv|pass|0.8.0 doing, holds, reset, retire at 8a80dc1: invariants 1, 2, 3, 10-13, 15 at commit (desk 0: 2 shells x 2 commands)
D02|doing|-DSHELLS0=1 -DK=3|inv|pass|same, desk 0: 1 shell x 3 commands
D03|doing|-DSHELLS0=1 -DK=3 -DHOLD_SEAT_FIRST=0|safety|violated|mutation (pre-F183): take or drop (hold, then seat) vs reset or retire (seat, then holds) deadlock
D04|doing|-DSHELLS0=1 -DK=3|safety|pass|hold paths lock the seat first: no deadlock
D05|doing|-DCHECK_FIN -DFINISH_SPLIT=1|inv|violated|mutation (pre-F186): the finish is a second transaction; it can end a focus written after the move
D06|doing|-DCHECK_FIN|inv|pass|no finish row: the move ends only the focus current at its move (invariant 12)
D07|doing|-DSHELLS0=1 -DK=3 -DLIVE_CHECK=0|ltl:retire_clean|violated|mutation (pre-F186): a request authenticated before the retire takes a hold or sets a focus after it
D08|doing|-DSHELLS0=1 -DK=3|ltl:retire_clean|pass|a live token re-checked under the seat lock (any live token, as coded: LIVE_GEN=0), seat first: a retired desk stays clean
R02|doing|-DSHELLS0=1 -DK=3 -DREACH|ltl:reach_hold|violated|REACHABLE (goal 2): a hold passes desk 0 -> free -> desk 1
R03|doing|-DSHELLS0=1 -DK=3 -DREACH|ltl:reach_focus|violated|REACHABLE (goal 3): desk 0 idle -> active -> waiting -> idle
M11|doing|-DSHELLS0=1 -DK=3 -DMUT_NO_SEATLOCK|inv|violated|mutation: a focus write without the seat lock points seat.doing_id at an older row (invariants 1, 11)
M12|doing|-DSHELLS0=1 -DK=3 -DMUT_MOVE_FOCUS|inv|violated|mutation: a move row moves the focus (invariant 2)
M13|doing|-DSHELLS0=1 -DK=3 -DFINISH_SPLIT=1 -DMUT_FINISH_NEWEST|inv|violated|mutation (0.7.19 test): finish reads the newest row, the move row: a drop never finishes (invariant 12)
M14|doing|-DSHELLS0=1 -DK=3 -DMUT_END_ANY_EMPTY|inv|violated|mutation (0.7.19 mill_doing_end): an empty move row on the item reads as finished
M15|doing|-DSHELLS0=1 -DK=3 -DMUT_HEARTBEAT_BUMP|inv|violated|mutation (pre-0.8.0): a heartbeat writes an anchor row and bumps activity (invariant 13)
M16|doing|-DSHELLS0=1 -DK=3 -DMUT_RETIRE_KEEPS|inv|violated|mutation: retire frees no hold (invariant 15)
E01|mail||safety|pass|0.8.0 mail at 8a80dc1: first open kept, opening leaves activity alone, one receipt per row (invariants 7, 8)
E02|mail|-DFIRST_OPEN=0|safety|violated|mutation (0.7.19): a second open re-stamps opened (invariant 7)
E03|mail|-DOPEN_LOCKED=0 -DFIRST_OPEN=0 -DSKIP_INV7|safety|violated|mutation (pre-F186): two concurrent opens both read v_prev NULL and push two receipts
E04|mail|-DQUIET_OPEN=0|safety|violated|mutation (0.7.19): an open bumps the activity of the letter (invariant 8)
M17|mail|-DOPEN_LOCKED=0 -DMUT_RC_MATCHED|safety|violated|mutation: unlocked v_prev + matched-row ROW_COUNT allows two receipts even with IFNULL
S01|score||safety|pass|0.8.0 score S1-S6, Wall writer included: act is the last step, retired iff the last step was S5, no doing rows
M18|score|-DMUT_REVIVE_KEEPS|safety|violated|mutation: S6 leaves activity.deleted set
N01|name||safety|pass|self check under the seat lock: only Admin or the desk with its current token retires it (invariant 14)
N02|name|-DSELF_LOCK=0|safety|violated|mutation (pre-F186): the self check is a plain read; a reset in between, and a revoked token still retires the desk
N03|name||ltl:retired_no_token|violated|FINDING (open at 8a80dc1): join locks the name row, but its re-check is a plain read; under REPEATABLE READ (the MySQL default) it reads the snapshot from before the lock, and a retire in between leaves a retired desk with a token
N04|name|-DRC=1|ltl:retired_no_token|pass|same join under READ COMMITTED (as tables.sql states): the re-check after the lock sees the retire; a retired desk holds no token
N05|name|-DJOIN_NAME_LOCK=0 -DRC=1|ltl:retired_no_token|violated|mutation (pre-F186): no name-row lock, only the plain read in MILL_NAME_PUT: a retired desk keeps a token at any isolation
M19|name|-DMUT_SELF_ANY|safety|violated|mutation: the self check forgets target = caller (invariant 14)
M20|name|-DMUT_RECLAIM_ANY|safety|violated|mutation: reclaim forgets the Admin check
'

fail=0; n=0; t0=$(date +%s)
printf '%-4s %-9s %-9s %-6s %12s %7s %6s  %s\n' id expect got mode states depth secs what
while IFS='|' read -r id model defs mode expect what; do
  [ -z "$id" ] && continue
  [ -n "$ONLY" ] && [ "$ONLY" != "$id" ] && continue
  n=$((n+1)); d="$OUT/$id"; rm -rf "$d"; mkdir -p "$d"; cp "$HERE/$model.pml" "$d/"
  ( cd "$d"
    # shellcheck disable=SC2086
    spin $defs -a "$model.pml" > spin.txt 2>&1 || exit 3
    case "$mode" in
      safety) flags="-DNOCLAIM -DSAFETY"; run="-m$DEPTH";;
      no_loss|mutex|no_stale_done) flags="-DSAFETY"; run="-m$DEPTH -N $mode";;
      live) flags="-DNFAIR=3"; run="-a -f -m$DEPTH -N all_delivered";;
      starve) flags="-DNFAIR=3"; run="-a -f -m$DEPTH -N no_starve0";;
      np) flags="-DNP -DNOCLAIM -DNFAIR=3"; run="-l -f -m$DEPTH";;
      inv) flags="-DNOCLAIM -DSAFETY"; run="-m$DEPTH -E";;       # assertions only (a lock cycle is D03's)
      ltl:*) flags="-DSAFETY"; run="-m$DEPTH -N ${mode#ltl:}";;  # a safety claim named after ltl:
    esac
    # The 0.8.0 models store states compressed (their vectors are larger).
    case "$model" in wake|holds) ;; *) flags="$flags -DCOLLAPSE";; esac
    # shellcheck disable=SC2086
    "$CC" -O2 $flags -o pan pan.c > cc.txt 2>&1 || exit 4
    s=$(date +%s.%N)
    # shellcheck disable=SC2086
    ./pan $run > pan.txt 2>&1
    awk -v a="$(date +%s.%N)" -v b="$s" 'BEGIN{printf "%.2f", a-b}' > secs.txt
    if grep -q "errors: [1-9]" pan.txt; then
      # shellcheck disable=SC2086
      spin $defs -t -p -g "$model.pml" > trail.txt 2>&1 || true
    fi ) ; rc=$?
  if [ $rc -ne 0 ]; then echo "$id: spin or cc failed (rc $rc), see $d"; fail=1; continue; fi
  if grep -qE "max search depth too small|out of memory|BITSTATE" "$d/pan.txt"; then
    echo "$id: search not exhaustive, see $d/pan.txt"; fail=1; fi
  # pan killed (e.g. by the OOM killer) prints no result line: a tool failure, not a violation.
  if ! grep -q "errors: [0-9]" "$d/pan.txt"; then
    echo "$id: pan gave no result (killed?), see $d/pan.txt"; fail=1; continue; fi
  if grep -q "errors: 0" "$d/pan.txt"; then got=pass; else got=violated; fi
  states=$(grep -m1 "states, stored" "$d/pan.txt" | awk '{print $1}')
  depth=$(grep -m1 "depth reached" "$d/pan.txt" | sed 's/.*depth reached \([0-9]*\).*/\1/')
  secs=$(printf '%.2f' "$(cat "$d/secs.txt")")
  mark=""
  if [ "$got" != "$expect" ]; then mark=" <-- differs from expectation"; fail=1; fi
  if [ "$STRICT" = 1 ] && [ "$got" = violated ]; then fail=1; fi
  printf '%-4s %-9s %-9s %-6s %12s %7s %6s  %s%s\n' "$id" "$expect" "$got" "$mode" "$states" "$depth" "$secs" "$what" "$mark"
  if [ -n "$ONLY" ] && [ -f "$d/trail.txt" ]; then echo "--- trail ($d/trail.txt)"; grep -E "^ *[0-9]+:|CYCLE" "$d/trail.txt" | grep -v "proc  0 " ; fi
done <<< "$CHECKS"
echo "checks: $n, seconds: $(( $(date +%s) - t0 )), output: $OUT"
[ "$n" -gt 0 ] || { echo "run.sh: no check named $ONLY"; exit 2; }
exit $fail
