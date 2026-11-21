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

#ifndef READ_DROP
#define READ_DROP 0
#endif
#ifndef RUNS
#define RUNS 0
#endif
#if READ_DROP
/*
 * READ_DROP (card 1144, F3): can a sync after a committed drop still show the
 * hold? One desk D holds one resource. Its drop runs in one shell; a connect
 * sync (connect_sync_frame) runs in another shell of the same desk, or in the
 * same shell after the drop reply.
 *
 * Code read (main ec280da):
 *   rpc.py _h_drop (3197-3226) -> records/hold.py drop (241-) -> delete (19-22):
 *          mill_hold_delete, one procedure with its own COMMIT (no --doing:
 *          _run_command 1086-1087 runs no request_tx); the reply goes out after
 *          the call returns, so after the commit
 *   push.py connect_sync_frame (854-883): take_sync (peek, rows_done), the
 *          unread merge, then rec_hold.own (records/hold.py 78-99) -> find
 *          (53-75) -> rows_done (db.py 719-731), which commits after each read,
 *          so every read starts a fresh snapshot, even under REPEATABLE READ
 *   asgi.py ws_endpoint (669-676): the frame is read in a worker, then sent;
 *          the desk prints it when it arrives (client/ws.py 884-897)
 *
 * Ghosts: committed (the drop's COMMIT ran), replied (the desk saw the drop
 * reply). A sync is stale_commit when its hold read started after the commit
 * and still shows the hold; stale_reply when it is printed after the drop
 * reply and shows the hold.
 *
 * Switches: SAME_SHELL 1 = the sync's connect starts only after the drop reply
 *   (one shell, commands in order); MUT_SNAPSHOT_CARRY mutation: the hold read
 *   uses the snapshot of the frame's first read (no commit between reads, the
 *   REPEATABLE READ default)
 */
#ifndef SAME_SHELL
#define SAME_SHELL 0
#endif
#define D 0
#define FREE 255

byte owner = D;
bool committed = false;
bool replied = false;
bool stale_commit = false;
bool stale_reply = false;

proctype Drop() {
  atomic { owner == D -> owner = FREE; committed = true };   /* mill_hold_delete COMMIT */
  replied = true                                             /* the reply reaches the desk */
}

proctype Sync() {
  bool shown, fresh;
  byte snap;
#if SAME_SHELL
  replied;                                                   /* the connect starts after the reply */
#endif
#ifdef MUT_SNAPSHOT_CARRY
  atomic { snap = owner };                                   /* take_sync's read opens the snapshot */
  atomic { shown = (snap == D); fresh = committed };         /* own() reads that snapshot */
#else
  atomic { snap = owner };                                   /* take_sync (rows_done commits) */
  atomic { shown = (owner == D); fresh = committed };        /* own(): a fresh snapshot */
#endif
  atomic {                                                   /* send_text; the desk prints it */
    if :: shown && fresh -> stale_commit = true :: else -> skip fi;
    if :: shown && replied -> stale_reply = true :: else -> skip fi
  }
}

init { atomic { run Drop(); run Sync() } }

ltl sync_fresh { [] !stale_commit }
ltl sync_after_reply { [] !stale_reply }

#elif RUNS
/*
 * RUNS (card 1267 hold-session-safe, SPIN pass of builder letter 6649): who
 * owns a hold when one desk has two runs (a wake and a foreground job, or two
 * wakes)? Three runs: runs 0 and 1 belong to desk 0, run 2 to desk 1. One
 * resource. Each mill command a run issues is a one-shot `--desk` borrow (the
 * seat is held only for that command); a run may be slow: any number of steps
 * of the others may pass between two of its commands. A run may also run
 * `mill drop` on its way out whether or not it believes it holds the lock.
 *
 * OWNER 0 = today (release/0.8.16 head 77ed251, same hold code as v0.8.15):
 *   sp_hold.sql mill_hold_upsert takes the row FOR UPDATE; a free row is taken,
 *     the same DESK refreshes (ok 1, refreshed 1, same id; #194, card 853),
 *     another desk is refused (ok 0). No run, no TTL.
 *   sp_hold.sql mill_hold_delete frees only when desk_id = the caller's DESK,
 *     so any run of the owning desk drops it.
 *   rpc.py _h_hold: the refusal transition (hold_activity.emit_refuse via
 *     _safe_put) is written after the procedure committed, and an error in it
 *     is swallowed (soft-fail).
 * OWNER 2 = card 1267 as the owner set it (2026-11-20 10:09-10:12 PM PT),
 *   checked against PR #490 head 047b9f5 (not merged; release/0.8.16 is still
 *   OWNER 0, so OWNER 0 stays the default until #490 lands):
 *   sp_hold.sql mill_hold_upsert locks seat, name row, hold row (FOR UPDATE);
 *     a free X is taken and the take's kh (sha256 of the one-use release key)
 *     goes on its hold_grant transition in the same transaction; a held X is
 *     refused for every caller, the same desk included (no refresh), and the
 *     hold_refuse row {op take, asker, holder} is written in that transaction
 *     (classed same-desk or cross-desk by hold_activity.contention_view).
 *   `mill hold X --key K` (old_kh = MILL_HOLD_KH, the newest grant or
 *     hand-off kh) is the hand-off: the caller's desk becomes the holder, a
 *     new kh goes on a hold_refresh row, so K is spent. REKEY 1 below.
 *   sp_hold.sql mill_hold_drop frees X when kh matches MILL_HOLD_KH, any
 *     desk; a wrong, spent or free drop is refused with a hold_refuse
 *     {op drop} row in the same transaction.
 *   records/hold.py drop without --key is the admin.md override for every
 *     desk, the holder's own desk included (KEYLESS_OWN 0, K24); its refusal
 *     row is written by rpc.py _h_drop through hold_activity.emit_refuse
 *     (_safe_put, soft-fail) after the decision (K30).
 *   No run or session is recorded; no expiry: the admin.md stale rule covers
 *   abandoned holds (seat_connected, per desk: K23).
 * OWNER 1 = the run-token design in letter 6649 (before the card was reset):
 *   the row records the owner run and the desk; the same run refreshes; any
 *   other run is refused; a non-owner drop is refused; the token survives
 *   one-shot borrows; a hold expires after TTL without renewal. Kept as the
 *   comparison: the owner chose the key design instead.
 *
 * ASSUMPTIONS (the field contract is not settled; builder mails it):
 *   A1 (OWNER 1) the owner field is a run token; hr stands for it.
 *   A2 (OWNER 1) a live run's renewal beats the TTL (a heartbeat carrying the
 *      token, or the client); MUT_RENEW_BY_COMMAND_ONLY drops it (M28).
 *   A3 (OWNER 1) expiry by a sweeper or any read (the Clock below).
 *   A4 the trust matrix row for a non-owner or keyless drop: Admin may drop a
 *      live hold (ADMIN=1). OWNER 2: the stale rule frees a hold only when the
 *      holder DESK has no live run (seat_connected is per desk; STALE=1); the
 *      day count is abstracted to "eventually".
 *   A5 a refused reply carries the reason and next step; text not modelled.
 *   A6 (OWNER 2) a keyless drop by the holder's own desk: KEYLESS_OWN 0 = it
 *      is the override (refused for a live hold unless Admin; card point 4),
 *      KEYLESS_OWN 1 = it frees, as an own-desk drop does today.
 *   A7 (OWNER 2) a handoff (HANDOFF=1) by letter copies the key: the sender
 *      cannot unknow it. REKEY 0 = the receiver relies on the copy as is;
 *      REKEY 2 = the receiver relies on it at once and re-keys later;
 *      REKEY 1 = PR #490: the receiver relies on the hold only once
 *      `mill hold X --key K` answered handoff (K spent, K' minted, holder
 *      desk moved, one transaction).
 *   A8 (OWNER 2) a refused keyless drop is the only refusal row written
 *      outside its transaction (rpc.py _h_drop); DROP_LOG_TX 1 = the fix.
 *   Not modelled: the name-insert race path of mill_hold_upsert (1062, 1213,
 *      1644 answered as a refusal), the override's hold_force row (written by
 *      emit_force after the commit, card 941), reply text, the score read.
 *
 * Switches: OWNER 0/1/2 (above); DIE 1 = a run may die for good while it holds;
 *   ADMIN 1; STALE 1; KEYLESS_OWN; HANDOFF; REKEY; DROP_LOG_TX (OWNER 2);
 *   TTL (OWNER 1, default 2);
 *   MAXK (OWNER 2) the most keys minted in one search (a model bound).
 * Mutations (each must fail a property that passes):
 *   MUT_SPLIT_TAKE  the take reads the holder, then writes it in a second step
 *   MUT_TAKE_DESK   (OWNER 1) the take compares the desk, not the run
 *   MUT_DROP_DESK   the drop compares the desk, not the run or the key
 *   MUT_OWNER_IS_BORROW  (OWNER 1) the hold ends when the one-shot borrow ends
 *   MUT_RENEW_BY_COMMAND_ONLY  (OWNER 1) no renewal between commands
 *   MUT_NO_TTL      (OWNER 1) no expiry
 *   MUT_LOG_AFTER   the refusal row is written after the commit and may fail
 *   MUT_SAME_DESK_REFRESH  (OWNER 2) a same-desk take refreshes, as today
 *   MUT_KEY_STATIC  (OWNER 2) the key belongs to the resource, not to one
 *                   take: an old copy still matches after a new take
 *   MUT_HANDOFF_SAME_KEY  (OWNER 2) `mill hold X --key K` moves the holder
 *                   but writes no new kh, so K stays live after the hand-off
 */
#ifndef OWNER
#define OWNER 0
#endif
#ifndef DIE
#define DIE 0
#endif
#ifndef ADMIN
#define ADMIN 0
#endif
#ifndef STALE
#define STALE 0
#endif
#ifndef KEYLESS_OWN
#define KEYLESS_OWN 0
#endif
#ifndef HANDOFF
#define HANDOFF 0
#endif
#ifndef REKEY
#define REKEY 0
#endif
#ifndef DROP_LOG_TX
#define DROP_LOG_TX 0
#endif
#ifndef TTL
#define TTL 2
#endif
#ifndef MAXK
#define MAXK 4
#endif
#define NR 3
#define FREE 255
#define DESK_OF(r) ((r) / 2)            /* runs 0, 1: desk 0; run 2: desk 1 */

byte hd = FREE;          /* hold.desk_id; FREE = NULL */
byte hr = FREE;          /* OWNER 1: the owner run (A1) */
byte ttl = 0;            /* OWNER 1: ticks left before expiry */
byte hk = 0;             /* OWNER 2: the live key of the hold (0 = none) */
byte gen = 0;            /* OWNER 2: keys minted so far */
byte keyof[NR];          /* OWNER 2: the key each run knows (0 = none) */
bool mine[NR];           /* what each run believes it owns (from its replies) */
bool alive[NR];          /* the run's process lives */
bool unlogged = false;   /* a refusal reply went out with no refusal row */
bool unlogged_drop = false; /* OWNER 2: a refused drop with no refusal row */
bool ref_same = false;   /* a same-desk refusal was recorded (scored apart) */
bool ref_cross = false;  /* a cross-desk refusal was recorded */

inline log_refusal(r) {
  if :: hd == DESK_OF(r) -> ref_same = true
     :: else -> ref_cross = true fi
}

#if OWNER == 2
#ifdef MUT_KEY_STATIC
#define KEYMATCH(r) (hd != FREE)
#else
#define KEYMATCH(r) (keyof[r] == hk)
#endif
#ifdef MUT_SAME_DESK_REFRESH
#define REFUSE(r) (hd != FREE && hd != DESK_OF(r))
#else
#define REFUSE(r) (hd != FREE)
#endif
#endif

/* mill hold NAME from run r: one one-shot borrow, one procedure call. */
inline take(r, ok) {
#if OWNER == 1
#ifdef MUT_SPLIT_TAKE
  seen = hr;                                         /* read, no lock held */
  atomic {
    if
    :: seen == FREE || seen == r -> hr = r; hd = DESK_OF(r); ttl = TTL; ok = true
    :: else -> ok = false; log_refusal(r)
    fi;
#else
  atomic {
    if
    :: hr == FREE -> hr = r; hd = DESK_OF(r); ttl = TTL; ok = true   /* take a free row */
#ifdef MUT_TAKE_DESK
    :: hr != FREE && hd == DESK_OF(r) -> hr = r; ttl = TTL; ok = true /* desk check only */
#else
    :: hr == r -> ttl = TTL; ok = true                                /* same run refreshes */
#endif
    :: else -> ok = false;                                            /* other run: refused */
#ifdef MUT_LOG_AFTER
       skip
#else
       log_refusal(r)                                                 /* recorded in the same tx */
#endif
    fi;
#endif
    mine[r] = ok
  }
#if defined(MUT_LOG_AFTER) && !defined(MUT_SPLIT_TAKE)
  if :: !ok -> if :: log_refusal(r) :: unlogged = true fi :: else -> skip fi
#endif
#ifdef MUT_OWNER_IS_BORROW
  atomic { if :: hr == r -> hr = FREE; hd = FREE :: else -> skip fi }   /* the borrow ends */
#endif

#elif OWNER == 2
#ifdef MUT_SPLIT_TAKE
  seen = hd;                                         /* read, no lock held */
  atomic {
    if
    :: seen == FREE && gen < MAXK -> gen++; hd = DESK_OF(r); hk = gen; keyof[r] = gen; mine[r] = true; ok = true
    :: seen != FREE -> ok = false; log_refusal(r)
    :: else -> ok = false                            /* model bound: no more keys */
    fi
  }
#else
  atomic {
    if
    :: hd == FREE && gen < MAXK ->                   /* take a free row, return a new key */
       gen++; hd = DESK_OF(r); hk = gen; keyof[r] = gen; mine[r] = true; ok = true
#ifdef MUT_HANDOFF_SAME_KEY
    :: hd != FREE && keyof[r] != 0 && KEYMATCH(r) ->
       hd = DESK_OF(r); mine[r] = true; ok = true    /* hand-off keeps K live */
#else
    :: hd != FREE && keyof[r] != 0 && KEYMATCH(r) && gen < MAXK ->
       gen++; hd = DESK_OF(r); hk = gen; keyof[r] = gen; mine[r] = true; ok = true
                                                     /* --key K: hand-off, K spent, K' minted */
#endif
#ifdef MUT_SAME_DESK_REFRESH
    :: hd == DESK_OF(r) -> mine[r] = true; ok = true /* refreshed, as today: no key */
#endif
    :: REFUSE(r) -> ok = false;                      /* held: refused, same desk included */
#ifdef MUT_LOG_AFTER
       skip
#else
       log_refusal(r)                                /* recorded in the same tx */
#endif
    :: hd == FREE && gen >= MAXK -> ok = false       /* model bound: no more keys */
    fi
  }
#ifdef MUT_LOG_AFTER
  if :: !ok && hd != FREE -> if :: log_refusal(r) :: unlogged = true fi :: else -> skip fi
#endif
#endif

#else  /* OWNER 0: today */
  atomic {
    if
    :: hd == FREE -> hd = DESK_OF(r); ok = true       /* take a free row */
    :: hd == DESK_OF(r) -> ok = true                   /* same desk: refreshed true, same id */
    :: else -> ok = false                              /* another desk: ok = 0, exit 1 */
    fi;
    mine[r] = ok
  }
  /* rpc.py _h_hold: emit_refuse after the commit, _safe_put swallows errors */
  if
  :: !ok -> if :: skip :: unlogged = true fi
  :: else -> skip
  fi
#endif
}

/* mill drop NAME from run r (also the losing run's cleanup on its way out). */
inline drop(r) {
  atomic {
#if OWNER == 1
#ifdef MUT_DROP_DESK
    if :: hr != FREE && hd == DESK_OF(r) -> hr = FREE; hd = FREE :: else -> skip fi;
#else
    if :: hr == r -> hr = FREE; hd = FREE :: else -> skip fi;   /* non-owner: refused */
#endif
#elif OWNER == 2
    if
    :: keyof[r] != 0 && KEYMATCH(r) -> hd = FREE; hk = 0       /* --key K matches: freed, K spent */
    :: keyof[r] == 0 && KEYLESS_OWN && hd == DESK_OF(r) -> hd = FREE; hk = 0   /* A6 */
#ifdef MUT_DROP_DESK
    :: hd != FREE && hd == DESK_OF(r) -> hd = FREE; hk = 0
#endif
    :: keyof[r] != 0 && !KEYMATCH(r) -> skip                 /* wrong or spent key: refused, row in tx */
    :: keyof[r] == 0 && !(KEYLESS_OWN && hd == DESK_OF(r)) && hd != FREE ->
#if DROP_LOG_TX
       skip                                                   /* A8 fixed: row in the drop's tx */
#else
       if :: skip :: unlogged_drop = true fi                  /* A8: emit_refuse after, soft-fail */
#endif
    :: keyof[r] == 0 && hd == FREE -> skip                    /* nothing to drop */
    fi;
    keyof[r] = 0;
#else
    if :: hd == DESK_OF(r) -> hd = FREE :: else -> skip fi;     /* mill_hold_delete: desk only */
#endif
    mine[r] = false
  }
}

proctype Run(byte r) {
  bool ok;
#if defined(MUT_SPLIT_TAKE)
  byte seen;
#endif
#if OWNER == 2 && HANDOFF
  byte b;
#endif
end_run:
  do
  :: skip; take(r, ok)                                  /* one command, one borrow */
  :: skip; drop(r)
#if OWNER == 2 && HANDOFF
  :: atomic { mine[r] && keyof[r] != 0 ->               /* hand the hold to another run */
       if :: b = (r + 1) % NR :: b = (r + 2) % NR fi;
#if REKEY == 1
       keyof[b] = keyof[r]; mine[r] = false              /* PR #490: the receiver relies on it */
                                                         /* only after its mill hold X --key K */
#else
       keyof[b] = keyof[r]; mine[b] = true; mine[r] = false   /* the letter carries a copy */
#endif
     }
#endif
#if OWNER == 2 && REKEY == 2
  :: atomic { mine[r] && keyof[r] != 0 && keyof[r] == hk && gen < MAXK ->
       gen++; hk = gen; keyof[r] = gen }                  /* the receiver re-keys later */
#endif
#if DIE
  :: atomic { mine[r] -> alive[r] = false }; break      /* dies while it holds */
#endif
  od;
end_dead:
  false
}

#if OWNER == 1
/* The TTL (A2, A3). A tick to 0 needs the owner run dead (its renewal stops),
 * unless MUT_RENEW_BY_COMMAND_ONLY. */
proctype Clock() {
end_clock:
  do
  :: atomic { hr != FREE && ttl > 1 -> ttl-- }
#ifdef MUT_RENEW_BY_COMMAND_ONLY
  :: atomic { hr != FREE && ttl == 1 -> ttl = 0 }
#else
  :: atomic { hr != FREE && ttl == 1 && !alive[hr] -> ttl = 0 }
#endif
#ifndef MUT_NO_TTL
  :: atomic { hr != FREE && ttl == 0 -> hr = FREE; hd = FREE }   /* expiry frees the row */
#endif
  od
}
#endif

#if OWNER == 2
/* OWNER 2: no live run knows the hold's key (the hold is abandoned). */
#define KEYLIVE(r) (alive[r] && keyof[r] == hk)
#define ABANDONED (hd != FREE && !(KEYLIVE(0) || KEYLIVE(1) || KEYLIVE(2)))
#define DESK_DEAD ((hd == 0 && !alive[0] && !alive[1]) || (hd == 1 && !alive[2]))
#if STALE
/* admin.md stale rule (A4): a keyless drop of a hold whose holder desk is not
 * connected (seat_connected is per desk), after hold_stale_days. */
proctype Stale() {
end_stale:
  do
  :: atomic { hd != FREE && DESK_DEAD -> hd = FREE; hk = 0 }
  od
}
#endif
#endif

#if ADMIN && OWNER
/* Trust matrix row: an Admin may drop a live hold (A4). */
proctype Admin() {
end_admin:
  do
#if OWNER == 2
  :: atomic { hd != FREE -> hd = FREE; hk = 0 }
#else
  :: atomic { hr != FREE -> hr = FREE; hd = FREE }
#endif
  od
}
#endif

init {
  atomic {
    alive[0] = true; alive[1] = true; alive[2] = true;
    run Run(0); run Run(1); run Run(2);
#if OWNER == 1
    run Clock();
#endif
#if OWNER == 2 && STALE
    run Stale();
#endif
#if ADMIN && OWNER
    run Admin();
#endif
  }
}

#define LB(r) (mine[r] && alive[r])
/* At most one live run believes it owns the hold. */
ltl one_owner { [] !((LB(0) && LB(1)) || (LB(0) && LB(2)) || (LB(1) && LB(2))) }
/* A live run that believes it owns the hold still owns it: a slow live run
 * never loses a hold it still uses. */
#if OWNER == 1
#define OWN(r) (hr == r)
#define ORPHAN (hr != FREE && !alive[hr])
#elif OWNER == 2
#define OWN(r) (hd != FREE && keyof[r] != 0 && keyof[r] == hk)
#define ORPHAN ABANDONED
#else
#define OWN(r) (hd == DESK_OF(r))
#define ORPHAN ((hd == 0 && !alive[0] && !alive[1]) || (hd == 1 && !alive[2]))
#endif
ltl keep { [] ((LB(0) -> OWN(0)) && (LB(1) -> OWN(1)) && (LB(2) -> OWN(2))) }
/* A hold that no live run can use is freed (liveness, weak fairness). */
ltl dead_frees { [] (ORPHAN -> <> !ORPHAN) }
/* Every refused take has its refusal row. */
ltl refusals_logged { [] !unlogged }
/* OWNER 2: every refused drop has its refusal row (refused_drop_n score). */
ltl drop_refusals_logged { [] !unlogged_drop }
/* Reachability goals: both refusal classes are reachable (scored apart). */
ltl no_same_refusal { [] !ref_same }
ltl no_cross_refusal { [] !ref_cross }

#else  /* !READ_DROP, !RUNS: the hold and drop model */


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

#endif /* READ_DROP, RUNS */
