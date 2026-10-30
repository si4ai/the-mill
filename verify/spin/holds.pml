/*
 * holds.pml - mill hold / mill drop, as the code at the sync commit implements them.
 *
 * Code covered (paths from the repo root):
 *   agent_coord/server/sql/sp_hold.sql   mill_hold_upsert: SELECT ... FOR UPDATE on the
 *                                        resource row, take it only when desk_id IS NULL,
 *                                        same desk refreshes, another desk: ok = 0 (refused)
 *                                        mill_hold_delete: desk_id = NULL only for the owner
 *   agent_coord/server/records/hold.py   upsert / drop
 *   agent_coord/server/api/mill/rpc.py   _h_hold (2551-2595), _h_drop (2598-2609)
 *   agent_coord/client/http.py           _refused_hold: a refused hold exits 1 (545-559)
 *   agent_coord/server/sql/tables.sql    hold rows are release-only (441-447)
 *   agent_coord/server/sql/sp_join.sql   mill_join_reset: frees the desk's holds (card 842)
 *   agent_coord/server/sql/sp_name.sql   mill_name_delete (retire): same (card 842)
 *
 * What the code does, and so what this model does:
 *   - mill hold never waits: it takes the lock or is refused at once (exit 1).
 *   - no TTL, no expiry, no lease: a hold lasts until its owner runs mill drop.
 *   - only the owner can drop it, with one exception: mill reset and mill retire
 *     of a desk free every hold it owns in the same call as the seat change
 *     (card 842: mill_join_reset and mill_name_delete call
 *     mill_hold_release_desk, sp_hold.sql). A superseded connect and a clock-out
 *     leave holds held (holds belong to the desk name; connect_sync_frame only
 *     lists them, push.py).
 *   - what a desk does after a refusal is not in the code. It is the desk's
 *     policy, and the model checks three:
 *       POLICY 0  keep what you hold and try the next lock again (spin-retry)
 *       POLICY 1  on a refusal drop everything you hold and start over
 *       POLICY 2  take locks in one global order (by name), keep, retry
 *
 * Switches:
 *   DESKS      2 or 3 desks; each needs 2 locks, chosen to form a cycle
 *              (2 desks: d0 r0 then r1, d1 r1 then r0; 3 desks: d_i r_i then r_(i+1))
 *   POLICY     0, 1 or 2 (above)
 *   ROUNDS     0 = each desk repeats its work forever; k = k rounds each
 *   DIE        1 = a desk may stop for good while it holds locks (a dead session)
 *   RESET      1 = (with DIE) someone runs mill reset or mill retire on a dead
 *              desk: mill_hold_release_desk frees all its holds in one step
 *   MUT_RESET_KEEPS  mutation of card 842: reset frees the seat but not the holds;
 *                    must leave the other desks stuck (H12 fails)
 *   MUT_HOLD_NOLOCK  mutation: the upsert reads desk_id and writes it in two steps
 *                    (no FOR UPDATE); must break mutual exclusion
 */

#ifndef DESKS
#define DESKS 2
#endif
#ifndef POLICY
#define POLICY 0
#endif
#ifndef ROUNDS
#define ROUNDS 0
#endif
#ifndef DIE
#define DIE 0
#endif
#ifndef RESET
#define RESET 0
#endif

#define FREE 255
#define RES DESKS            /* one lock per desk, needed in a cycle */

byte owner[RES];             /* hold.desk_id; FREE = NULL */
bool mine[DESKS * RES];      /* what each desk believes it holds (from the replies) */
#define MINE(d, r) mine[(d) * RES + (r)]
byte inside = 0;             /* desks doing the work that needs both locks */
byte done[DESKS];            /* finished rounds per desk */
bool waiting[DESKS];         /* a desk wants its two locks and has not got them yet */
bool dead[DESKS];            /* the desk's session stopped for good (DIE) */

/* mill_hold_upsert, one stored procedure call (one transaction). */
inline hold(d, r, ok) {
#ifdef MUT_HOLD_NOLOCK
  byte seen;
  seen = owner[r];
  atomic {
    if
    :: seen == FREE || seen == d -> owner[r] = d; ok = true
    :: else -> ok = false
    fi
  }
#else
  atomic {
    if
    :: owner[r] == FREE -> owner[r] = d; ok = true      /* take a free row */
    :: owner[r] == d -> ok = true                       /* same holder refreshes (#194) */
    :: else -> ok = false                               /* refused: ok = 0, exit 1 */
    fi
  }
#endif
  if :: ok -> MINE(d, r) = true :: else -> skip fi
}

/* mill_hold_delete: only the owning desk releases. */
inline drop(d, r) {
  atomic {
    if :: owner[r] == d -> owner[r] = FREE :: else -> skip fi;
    MINE(d, r) = false
  }
}

proctype Desk(byte d) {
  byte a, b, t;
  bool ok;
  a = d; b = (d + 1) % RES;
#if POLICY == 2
  if :: a > b -> t = a; a = b; b = t :: else -> skip fi   /* one global order */
#endif
end_idle:
  do
  :: ROUNDS == 0 || done[d] < ROUNDS ->
     waiting[d] = true;
again:
     do
     :: hold(d, a, ok); if :: ok -> break :: else -> skip fi
     od;
     do
     :: hold(d, b, ok);
        if
        :: ok -> break
        :: !ok && POLICY == 1 -> drop(d, a); goto again
        :: !ok && POLICY != 1 -> skip
        fi
     od;
     /* the work: this desk holds both locks */
     atomic { inside++; waiting[d] = false; assert(owner[a] == d && owner[b] == d) };
#if DIE
     if :: true -> dead[d] = true; end_dead: false :: true -> skip fi   /* the session may die here */
#endif
progress_work:
     atomic { inside--; if :: ROUNDS > 0 -> done[d]++ :: else -> skip fi };
     drop(d, b); drop(d, a)
  :: ROUNDS > 0 && done[d] >= ROUNDS -> break
  od
}

#if RESET
/* mill reset / mill retire of a dead desk: mill_hold_release_desk frees every
 * hold that desk owns, in the same transaction as the seat change (card 842).
 * The dead session does nothing more, so its belief is cleared with the rows. */
proctype Admin() {
  byte k, r;
end_admin:
  do
  :: atomic {
       (dead[0] || dead[1] || (DESKS == 3 && dead[DESKS-1])) ->
       k = 0;
       do
       :: k < DESKS && !dead[k] -> k++
       :: k < DESKS && dead[k] -> break
       od;
       r = 0;
       do
#ifdef MUT_RESET_KEEPS
       :: r < RES -> skip;
#else
       :: r < RES -> if :: owner[r] == k -> owner[r] = FREE :: else -> skip fi;
#endif
                     MINE(k, r) = false; r++
       :: r >= RES -> break
       od;
       dead[k] = false            /* reset done: the seat is free again */
     }
  od
}
#endif

init {
  byte k;
  atomic {
    k = 0;
    do :: k < RES -> owner[k] = FREE; k++ :: k >= RES -> break od;
    k = 0;
    do :: k < DESKS -> run Desk(k); k++ :: k >= DESKS -> break od;
#if RESET
    run Admin()
#endif
  }
}

/* Mutual exclusion: no two desks believe they hold the same lock. */
#define EXCL01(r) !(MINE(0, r) && MINE(1, r))
#if DESKS == 3
#define EXCL(r) (EXCL01(r) && !(MINE(0, r) && MINE(2, r)) && !(MINE(1, r) && MINE(2, r)))
ltl mutex { [] (EXCL(0) && EXCL(1) && EXCL(2)) }
ltl no_starve0 { [] (waiting[0] -> <> !waiting[0]) }
#else
ltl mutex { [] (EXCL01(0) && EXCL01(1)) }
ltl no_starve0 { [] (waiting[0] -> <> !waiting[0]) }
#endif
