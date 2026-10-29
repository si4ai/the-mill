/*
 * todo.pml - the card (todo) moves of 0.8.0, keyed on transition ids T1-T14.
 *
 * Sources (0.8.0 design and the code it changes):
 *   design  docs/requirements/beta/activity-states-080.md (PR #226, c2a91f9), section todo
 *   code    release/0.8.0 lane B (PR #224, ac136b8):
 *     sp_cmd.sql     cmd_claim (card row FOR UPDATE, claimed_by / stale_prior refusals),
 *                    cmd_unclaim (FOR UPDATE, who-may), cmd_pass (FOR UPDATE; ship, done, back)
 *     sp_todo.sql    mill_todo_write (one card write), mill_todo_retire / _reclaim (FOR UPDATE)
 *     api/mill/rpc.py _h_assign: find + _card_moves + volunteer check on an unlocked read,
 *                    then a blind mill_todo_update(status claimed, volunteer D)
 *                    _h_unpark: find, tree-parent check, then mill_todo_update(status open):
 *                    no status guard
 *                    find (records/todo.py): an unlocked read; the card SPs do not
 *                    re-check activity.deleted under the card lock
 *
 * The 0.8.0 rule modelled for the card write (design, not yet in code at ac136b8):
 * under the card row lock the write reads the old status and volunteer, writes the
 * new ones, and appends one move row on the card when the status or the volunteer
 * changed, with the move's act; the card's activity row takes the same act and the
 * actor. T12-T14 set the act and write no move row. Acts are keyed on transition ids
 * (act T4 = "claimed", ...), not on their spellings.
 *
 * A move row stores its act, the actor, and, for T4, T5 and T6, the volunteer it set
 * (for T5 the assignee is not the actor; the design does not say where that is kept).
 *
 * Switches (1 = the fix or the design, 0 = the code at ac136b8):
 *   ASSIGN_LOCKED  T5's guard (open, no volunteer) runs under the card lock (default 0)
 *   UNPARK_GUARD   T3 moves only a parked card, under the card lock (default 0)
 *   DELETED_GUARD  card SPs refuse a retired card under the card lock (default 0)
 *   MIGRATED       the card starts in any status from the 0.8.0 migration, with one seed row
 *   SEED_VOL       the seed row carries the card's volunteer (default 0)
 *   CHECK_EDGES    assert each committed move is an edge of the design's todo table
 *   K              commands per desk (default 3)
 * Mutations (each must fail its check):
 *   MUT_WAS_NOLOCK    the write reads the old status and volunteer before the card lock
 *   MUT_STATUS_ONLY   a move row only on a status change (the #214 draft's NOT (status <=> v_was))
 *   MUT_ACT_LATE      the activity act is put after the card lock is released
 */

#ifndef K
#define K 3
#endif
#ifndef ASSIGN_LOCKED
#define ASSIGN_LOCKED 0
#endif
#ifndef UNPARK_GUARD
#define UNPARK_GUARD 0
#endif
#ifndef DELETED_GUARD
#define DELETED_GUARD 0
#endif
#ifndef MIGRATED
#define MIGRATED 0
#endif
#ifndef SEED_VOL
#define SEED_VOL 0
#endif

#define DESKS 2          /* desk 0 is the asker (todo.creator_id) */
#define FREE 255

#define PARKED 1
#define OPEN 2
#define CLAIMED 3
#define SHIPPED 4
#define DONE 5

/* act codes = transition ids */
#define T1 1
#define T2 2
#define T3 3
#define T4 4
#define T5 5
#define T6 6
#define T7 7
#define T8 8
#define T9 9
#define T10 10
#define T11 11
#define T12 12
#define T13 13
#define T14 14

byte st, vol = FREE;     /* todo.status, todo.assigned_id */
bool retired;            /* activity.deleted IS NOT NULL */
byte lk = FREE;          /* the card row lock (FOR UPDATE): the desk that holds it */
byte act, actor;         /* activity.act, activity.desk_id */
/* ghosts */
byte rst, rvol = FREE;   /* status and volunteer replayed from the move rows alone */
byte nrows;              /* move rows on the card */
byte laststep;           /* act of the last committed step on the card */
byte pend;               /* activity puts not yet landed (MUT_ACT_LATE) */
byte stage;              /* reachability: filed -> claimed -> shipped -> done */

/* Replay one move row: the doc's rule (invariants 5 and 6). */
inline replay(ra, rrv) {
  if
  :: ra == T1 -> rst = OPEN
  :: ra == T2 -> rst = PARKED
  :: ra == T3 -> rst = OPEN
  :: ra == T4 || ra == T6 || ra == T5 -> rst = CLAIMED; rvol = rrv
  :: ra == T7 -> rst = OPEN; rvol = FREE
  :: ra == T8 || ra == T10 -> rst = SHIPPED
  :: ra == T9 -> rst = DONE
  :: ra == T11 -> if :: rvol != FREE -> rst = CLAIMED :: else -> rst = OPEN fi
  fi
}

/* The design's todo table: is (was, wasvol) -> (st, vol) under act a by desk d an edge? */
#define EDGE(a, was, wasvol, d) ( \
  (a == T3 && was == PARKED && st == OPEN) || \
  (a == T4 && was == OPEN && st == CLAIMED && vol == d) || \
  (a == T5 && was == OPEN && st == CLAIMED) || \
  (a == T6 && was == CLAIMED && wasvol != d && wasvol != FREE && st == CLAIMED && vol == d) || \
  (a == T7 && was == CLAIMED && st == OPEN && vol == FREE) || \
  (a == T8 && was == CLAIMED && st == SHIPPED) || \
  (a == T9 && was == SHIPPED && st == DONE) || \
  (a == T10 && was == DONE && st == SHIPPED) || \
  (a == T11 && was == SHIPPED && ((vol != FREE && st == CLAIMED) || (vol == FREE && st == OPEN))))

inline lock(d) { atomic { lk == FREE -> lk = d } }

/* the card SP's view of activity.deleted under the lock (DELETED_GUARD) */
#define LIVE (!(DELETED_GUARD && retired))

/* mill_todo_write under the card lock: old status read, write, move row when changed,
 * activity act. nst/nvol are the new status and volunteer; rv the row's volunteer. */
inline write(wd, wa, wnst, wnvol, wrv) {
  atomic {
#ifndef MUT_WAS_NOLOCK
    was = st; wasvol = vol;
#endif
    n0 = nrows;
    st = wnst; vol = wnvol;
#ifdef MUT_STATUS_ONLY
    if :: st != was -> nrows++; replay(wa, wrv)
#else
    if :: st != was || vol != wasvol -> nrows++; replay(wa, wrv)
#endif
       :: else -> skip
    fi;
#ifdef CHECK_EDGES
    assert(!(st != was || vol != wasvol) || (EDGE(wa, was, wasvol, wd) && !retired));
#endif
    /* invariant 3: a T1-T11 step that changes the card writes exactly one move row */
    assert((st != was || vol != wasvol) == (nrows == n0 + 1));
    assert((st == was && vol == wasvol) == (nrows == n0));
    assert(rst == st);          /* invariant 5 */
    assert(rvol == vol);        /* invariant 6 */
    if
    :: st != was || vol != wasvol ->
       laststep = wa;
#ifdef MUT_ACT_LATE
       pend++; defer = true
#else
       act = wa; actor = wd
#endif
    :: else -> skip
    fi;
    if
    :: stage == 0 && st == CLAIMED && (wa == T4 || wa == T5 || wa == T6) -> stage = 1
    :: stage == 1 && st == SHIPPED && wa == T8 -> stage = 2
    :: stage == 2 && st == DONE && wa == T9 -> stage = 3
    :: else -> skip
    fi;
    lk = FREE
  }
#ifdef MUT_ACT_LATE
  if :: defer -> atomic { act = wa; actor = wd; pend--; defer = false } :: else -> skip fi
#endif
}

/* T12 retire, T13 reclaim, T14 note: act on the activity row, no move row. */
inline flagstep(fd, fa) {
  atomic { laststep = fa; act = fa; actor = fd; lk = FREE }
}

proctype Desk(byte d) {
  byte k, was, wasvol, gst, gvol, tgt, n0;
  bool gret, take, defer;
  for (k : 1 .. K) {
    /* find: an unlocked read of the card (records/todo.py find) */
    atomic { gst = st; gvol = vol; gret = retired };
#ifdef MUT_WAS_NOLOCK
    atomic { was = st; wasvol = vol };
#endif
    if
    /* claim [--take-over] (cmd_claim): the take-over line names the volunteer read now */
    :: !gret -> if :: take = true :: take = false fi;
       lock(d);
       if
       :: (DELETED_GUARD && retired) || !(st == OPEN || st == CLAIMED) -> lk = FREE      /* card:moves */
       :: else -> if
          :: vol != FREE && vol != d && !take -> lk = FREE                              /* card:claimed_by */
          :: take && !(vol == gvol || (vol == d && gvol == d) || (vol == FREE && gvol == FREE)) -> lk = FREE  /* card:stale_prior */
          :: else -> if
             :: vol != FREE && vol != d -> write(d, T6, CLAIMED, d, d)
             :: else -> write(d, T4, CLAIMED, d, d)
             fi
          fi
       fi
    /* unclaim (cmd_unclaim) */
    :: !gret -> lock(d);
       if
       :: (DELETED_GUARD && retired) || !(st == OPEN || st == CLAIMED) -> lk = FREE
       :: vol != FREE && vol != d -> lk = FREE                                           /* card:who_may_unclaim */
       :: else -> write(d, T7, OPEN, FREE, FREE)
       fi
    /* assign R NEED D (_h_assign): guard on the find read, then a blind write */
    :: !gret -> if :: tgt = 0 :: tgt = 1 fi;
#if ASSIGN_LOCKED
       lock(d);
       if
       :: (DELETED_GUARD && retired) || !(st == OPEN) || vol != FREE -> lk = FREE
       :: else -> write(d, T5, CLAIMED, tgt, tgt)
       fi
#else
       if
       :: (gst == OPEN || gst == CLAIMED) && gvol == FREE ->
          lock(d);
          if :: DELETED_GUARD && retired -> lk = FREE :: else -> write(d, T5, CLAIMED, tgt, tgt) fi
       :: else -> skip                                                                    /* refused */
       fi
#endif
    /* unpark (_h_unpark): mill_todo_update(status open), volunteer kept */
    :: !gret ->
#if UNPARK_GUARD
       lock(d);
       if :: st != PARKED || (DELETED_GUARD && retired) -> lk = FREE :: else -> write(d, T3, OPEN, vol, vol) fi
#else
       lock(d);
       if :: DELETED_GUARD && retired -> lk = FREE :: else -> write(d, T3, OPEN, vol, vol) fi
#endif
    /* pass (cmd_pass, ship): claimed (or open with a volunteer) -> shipped, by the volunteer */
    :: !gret -> lock(d);
       if
       :: LIVE && (st == CLAIMED || (st == OPEN && vol != FREE)) && (vol == d || (vol == FREE && d == 0)) ->
          write(d, T8, SHIPPED, vol, vol)
       :: else -> lk = FREE
       fi
    /* pass --done: shipped -> done, by the asker */
    :: !gret -> lock(d);
       if
       :: LIVE && st == SHIPPED && d == 0 -> write(d, T9, DONE, vol, vol)
       :: else -> lk = FREE
       fi
    /* pass --back: done -> shipped; shipped -> claimed, or open with no volunteer */
    :: !gret -> lock(d);
       if
       :: LIVE && (st == DONE || st == SHIPPED) && (d == 0 || vol == d) ->
          if
          :: st == DONE -> write(d, T10, SHIPPED, vol, vol)
          :: st == SHIPPED && vol != FREE -> write(d, T11, CLAIMED, vol, vol)
          :: st == SHIPPED && vol == FREE -> write(d, T11, OPEN, vol, vol)
          fi
       :: else -> lk = FREE
       fi
    /* retire todo (mill_todo_retire, FOR UPDATE): T12 */
    :: !gret -> lock(d);
       if :: retired -> lk = FREE :: else -> retired = true; flagstep(d, T12) fi
    /* reclaim todo: T13 */
    :: gret -> lock(d);
       if :: !retired -> lk = FREE :: else -> retired = false; flagstep(d, T13) fi
    /* note: T14 */
    :: !gret -> lock(d); flagstep(d, T14)
    fi
  }
}

init {
  atomic {
#if MIGRATED
    /* 0.8.0 migration: any 0.7.19 card, one seed row whose act matches its status */
    if
    :: st = OPEN; vol = FREE; rst = OPEN
    :: st = PARKED; vol = FREE; rst = PARKED
    :: st = CLAIMED; vol = 1; rst = CLAIMED; rvol = 1
    :: st = SHIPPED; vol = 1; rst = SHIPPED;
#if SEED_VOL
       rvol = 1
#endif
    :: st = DONE; vol = 1; rst = DONE;
#if SEED_VOL
       rvol = 1
#endif
    fi;
    nrows = 1; act = 0;
#else
    /* T1 create todo (open) or T2 create --status parked, by the asker */
    if
    :: st = OPEN; rst = OPEN; act = T1; laststep = T1
    :: st = PARKED; rst = PARKED; act = T2; laststep = T2
    fi;
    nrows = 1; actor = 0;
#endif
    run Desk(0); run Desk(1)
  }
}

/* invariant 4: the activity act is the act of the item's last committed step */
ltl act_last { [] (pend == 0 -> act == laststep) }
/* reachability goal 1: a card goes filed -> claimed -> shipped -> done */
ltl reach_card { [] (stage != 3) }
