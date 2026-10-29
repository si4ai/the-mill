/*
 * doing.pml - a desk's doing (focus and move rows), its seat, holds, and reset and
 * retire, in 0.8.0. Keyed on transition ids D1-D12, H1-H5, N1.
 *
 * Sources:
 *   design  docs/requirements/beta/activity-states-080.md (PR #226, c2a91f9), sections doing,
 *           hold, seat focus and name retire; the Builder's handoff (lock order, invariants)
 *   code    release/0.8.0 lane B (PR #224, 413cdb8), and the box copy of sp_beta_name.sql:
 *     api/mill/rpc.py   _run_command: with --doing the command and its doing row are one
 *                       request transaction; without --doing a pass or drop still calls
 *                       _doing_finish after the command, but mill_doing_finish writes no
 *                       row (F186): the ship, done or drop move ends the entry on read
 *     sp_doing.sql      mill_doing_put (seat lock + live token, F186), mill_doing_finish
 *                       (no row; reads seat.doing_id), mill_doing_end (ship/done/drop)
 *     sp_join.sql       mill_join_upsert (D1), mill_join_reset (seat, clear, release holds),
 *                       heartbeats (connect, touch, socket, lan): seat.updated only
 *     sp_hold.sql       mill_hold_upsert / _delete: seat then hold (F183), live token (F186)
 *     sp_todo.sql       mill_todo_write: seat then card (F183)
 *     sp_beta_name.sql  sp_name_retire: name, seat (self check under the seat lock, F186),
 *                       holds; clear + drop rows
 *
 * The 0.8.0 rules modelled (code at 413cdb8): a focus row (joined, focused, cleared)
 * moves seat.doing_id; a move row never does. Every doing write takes the desk's seat
 * row lock first. Hold and card paths lock the seat, then the item; reset and retire
 * lock the seat, then the desk's hold rows. Heartbeats write the seat row only. A pass
 * or drop without --doing writes no finish row: the move ends the entry on read.
 *
 * Model: desk 0 has SHELLS0 shells (concurrent commands of one desk), desk 1 one shell;
 * one card, one hold, one letter; an Admin that resets or retires desk 0 once. Each
 * transaction is its lock steps (blocking, as InnoDB waits) then one atomic step that
 * writes and commits. A request authenticates its token first, in its own step.
 *
 * Switches (default = the code at 413cdb8; 0 keeps the pre-F183/F186 shape as a mutant):
 *   FINISH_SPLIT     0: no finish row; the move ends the entry on read (code)
 *                    1: a finish row in a second transaction after the move (pre-F186)
 *   HOLD_SEAT_FIRST  1: hold paths lock seat, then hold (code); 0: hold, then seat
 *   LIVE_CHECK       1: under the seat lock the request's token is the seat's (code)
 *                    0: a doing write checks only that the desk has joined
 *   CHECK_FIN        assert a finish ends only the focus that was current at its move
 *   SHELLS0, K       shells of desk 0 (default 2), commands per shell (default 2)
 * Mutations (each must fail its check):
 *   MUT_NO_SEATLOCK      a doing write inserts and moves seat.doing_id without the seat lock
 *   MUT_MOVE_FOCUS       a move row moves seat.doing_id
 *   MUT_FINISH_NEWEST    finish tests the desk's newest row (0.7.19), not the focus row
 *   MUT_END_ANY_EMPTY    the derived end counts any empty row on the item (0.7.19 mill_doing_end)
 *   MUT_HEARTBEAT_BUMP   a heartbeat writes an anchor row and bumps activity (pre-0.8.0)
 *   MUT_RETIRE_KEEPS     retire frees no hold
 */

#ifndef SHELLS0
#define SHELLS0 2
#endif
#ifndef K
#define K 2
#endif
#ifndef FINISH_SPLIT
#define FINISH_SPLIT 0
#endif
#ifndef HOLD_SEAT_FIRST
#define HOLD_SEAT_FIRST 1
#endif
#ifndef LIVE_CHECK
#define LIVE_CHECK 1
#endif

#define FREE 255
#define NULLING 254
#define DESKS 2
#define ON_NONE 0
#define ON_MAIL 1
#define ON_CARD 2
#define ON_HOLD 3

/* locks: the process that holds each row lock, or FREE */
byte seatlk[DESKS] = FREE;
byte cardlk = FREE, holdlk = FREE, namelk = FREE;

/* seat and name */
bool tok[DESKS];          /* seat.token_hash IS NOT NULL */
byte gen[DESKS];          /* which token: a join after a reset mints a new one */
bool retired[DESKS];      /* name.deleted */
bool joined[DESKS];       /* the desk has a doing row */

/* doing. Row ids are not kept (they would split every state); instead:
 * ptr_ok[d]  seat.doing_id is the desk's newest focus row (invariant 1)
 * fver[d]    how many focus rows the desk has written: the focus changed iff fver did */
bool ptr_ok[DESKS] = true;
byte fver[DESKS];
bool has_focus[DESKS];    /* seat.doing_id IS NOT NULL */
bool f_text[DESKS];       /* the row at seat.doing_id: text set */
byte f_on[DESKS];         /*                           on */
bool f_wait[DESKS];       /*                           waiting reference */
bool n_text[DESKS];       /* the desk's newest row of any kind (for MUT_FINISH_NEWEST) */
byte n_on[DESKS];
bool emptymove[DESKS];
bool rnew;                /* MUT_NO_SEATLOCK: the racer's row is the newest focus row */    /* an empty move row by the desk on its focus item, after the focus */
bool bump;                /* a heartbeat wrote a doing row or an activity row */

/* hold */
byte owner = FREE;        /* hold.desk_id, committed */
byte pend = FREE;         /* an uncommitted UPDATE of hold.desk_id: the new desk or NULLING */
byte rholder = FREE;      /* ghost: holder replayed from the hold's move rows */

/* reachability */
#ifdef REACH
byte fstage, hstage;
#define STAGE(x) x
#else
#define STAGE(x) skip
#endif

inline acq(L) { atomic { L == FREE -> L = _pid } }

/* invariants 1, 10 and 15's parts that hold at every commit */
inline check_all() {
  assert(ptr_ok[0] && ptr_ok[1]);                                      /* invariant 1 */
  assert(owner == rholder);                                            /* invariant 10 */
  assert(!retired[0] || (!tok[0]))
}

/* A focus row (D1, D4-D6, D8-D10): insert, then seat.doing_id moves to it. */
inline focus_row(fd, ftext, fon, fwait) {
  fver[fd]++; ptr_ok[fd] = true; has_focus[fd] = true; rnew = false;
  f_text[fd] = ftext; f_on[fd] = fon; f_wait[fd] = fwait;
  n_text[fd] = ftext; n_on[fd] = fon;
  emptymove[fd] = false; joined[fd] = true;
  STAGE(if
  :: fd == 0 && fstage == 0 && ftext && !fwait -> fstage = 1
  :: fd == 0 && fstage == 1 && ftext && fwait -> fstage = 2
  :: fd == 0 && fstage == 2 && !ftext -> fstage = 3
  :: else -> skip
  fi)
}

/* A move row (D12): the move's act lands on the item's activity row; the focus stays. */
inline move_row(md, mtext, mon) {
  d0 = fver[md];
  n_text[md] = mtext; n_on[md] = mon;
  if :: !mtext && f_text[md] && f_on[md] == mon -> emptymove[md] = true :: else -> skip fi;
#ifdef MUT_MOVE_FOCUS
  fver[md]++; f_text[md] = mtext; f_on[md] = mon; f_wait[md] = false;
#endif
  assert(fver[md] == d0);             /* invariant 2: a move never moves the focus */
  d0 = 0
}

/* The derived end of the focus (mill_doing_end): design reads the next focus row only. */
#ifdef MUT_END_ANY_EMPTY
#define ENDED(x) (emptymove[x])
#else
#define ENDED(x) (false)
#endif

/* Pre-F186 finish row (FINISH_SPLIT=1 mutant): under the seat lock, an empty focus row
 * on the item when seat.doing_id has text and is on the item. At 413cdb8 finish writes
 * no row; end_by_move marks the derived end instead. */
inline finish(xd, xon) {
#ifdef MUT_FINISH_NEWEST
  if :: n_text[xd] && n_on[xd] == xon ->
#else
  if :: f_text[xd] && f_on[xd] == xon ->
#endif
       assert(f_on[xd] == xon);                      /* invariant 12 */
#ifdef CHECK_FIN
       assert(fver[xd] == mvfocus);                  /* the focus current at the move */
#endif
       focus_row(xd, false, xon, false)
  :: else -> skip
  fi;
  /* the focus that was on the item at the move, still current, has ended */
  if :: fver[xd] == mvfocus && due -> assert(!f_text[xd]) :: else -> skip fi
}

/* 413cdb8: the ship, done or drop move ends the focus entry on read; no finish row. */
inline end_by_move(xd, xon) {
#ifdef MUT_FINISH_NEWEST
  if :: n_text[xd] && n_on[xd] == xon ->
#else
  if :: f_text[xd] && f_on[xd] == xon ->
#endif
     assert(f_on[xd] == xon);                            /* invariant 12 */
#ifdef CHECK_FIN
     assert(fver[xd] == mvfocus);                        /* the focus current at the move */
#endif
     STAGE(if
     :: xd == 0 && fstage == 2 -> fstage = 3
     :: xd == 0 && fstage == 1 -> fstage = 3
     :: else -> skip
     fi)
  :: else -> skip
  fi
}

/* The live check under the seat lock (LIVE_CHECK=1): the request's token is the seat's. */
#define LIVE(x) (!LIVE_CHECK || (tok[x] && gen[x] == mygen))

proctype Shell(byte d) {
  byte k, mygen, d0, mvfocus;
  bool doing, wait, ev, due;
  for (k : 1 .. K) {
    if :: retired[d] -> break :: else -> skip fi;
    if
    :: retired[d] -> break       /* retired while this shell was between commands */
    /* D1 join (mill_join_upsert): a seat with no token gets one; the first row is 'joined' */
    :: atomic { !tok[d] && !retired[d] };
       acq(seatlk[d]);
       atomic {
         if
         :: !tok[d] && !retired[d] ->
            tok[d] = true; gen[d]++;
            if :: !joined[d] -> focus_row(d, false, ON_NONE, false) :: else -> skip fi
         :: else -> skip
         fi;
         check_all(); seatlk[d] = FREE
       }
    :: atomic { tok[d] -> mygen = gen[d] };   /* the request's token authenticates */
       if :: doing = true :: doing = false fi;
       if
       /* D4/D5/D6: a mail command with --doing [--waiting-on] (send, mark, reply) */
       :: if :: wait = true :: wait = false fi;
          acq(seatlk[d]);
          atomic {
            if :: LIVE(d) -> focus_row(d, true, ON_MAIL, wait) :: else -> skip fi;
            check_all(); seatlk[d] = FREE
          }
       /* H1/H2 take, H3 refresh (mill_hold_upsert) [--doing] */
       :: 
#if HOLD_SEAT_FIRST
          acq(seatlk[d]); acq(holdlk);
#else
          acq(holdlk);
          atomic { if :: owner == FREE -> pend = d :: else -> skip fi };   /* UPDATE hold SET desk_id */
          if :: owner == FREE || doing -> acq(seatlk[d]) :: else -> skip fi;
#endif
          atomic {
            if
            :: owner == FREE && LIVE(d) ->                  /* H1/H2: took */
               owner = d; pend = FREE; rholder = d; move_row(d, false, ON_HOLD);
               if :: doing -> focus_row(d, true, ON_HOLD, false) :: else -> skip fi;
               STAGE(if :: hstage == 0 && d == 0 -> hstage = 1 :: hstage == 2 && d == 1 -> hstage = 3 :: else -> skip fi)
            :: owner == d && LIVE(d) ->                     /* H3: refresh, no row */
               if :: doing -> focus_row(d, true, ON_HOLD, false) :: else -> skip fi
            :: else -> pend = FREE                          /* refused, or rolled back */
            fi;
            check_all();
            holdlk = FREE; if :: seatlk[d] == _pid -> seatlk[d] = FREE :: else -> skip fi
          }
       /* H4 drop (mill_hold_delete) [--doing]; D9 finish without --doing */
       :: 
#if HOLD_SEAT_FIRST
          acq(seatlk[d]); acq(holdlk);
#else
          acq(holdlk);
          atomic { if :: owner == d -> pend = NULLING :: else -> skip fi };
          if :: owner == d -> acq(seatlk[d]) :: else -> skip fi;
#endif
          atomic {
            due = false;
            if
            :: owner == d && LIVE(d) ->
               mvfocus = fver[d]; due = f_text[d] && f_on[d] == ON_HOLD;
               owner = FREE; pend = FREE; rholder = FREE; move_row(d, false, ON_HOLD);
               STAGE(if :: hstage == 1 && d == 0 -> hstage = 2 :: else -> skip fi);
               if
               :: doing -> focus_row(d, true, ON_HOLD, false); due = false
               :: !doing && !FINISH_SPLIT -> end_by_move(d, ON_HOLD); due = false
               :: else -> skip
               fi
            :: else -> pend = FREE
            fi;
            check_all();
            holdlk = FREE; if :: seatlk[d] == _pid -> seatlk[d] = FREE :: else -> skip fi
          }
          if
          :: due && FINISH_SPLIT ->                         /* pre-F186: finish row in its own TX */
             acq(seatlk[d]);
             atomic { finish(d, ON_HOLD); check_all(); seatlk[d] = FREE }
          :: else -> skip
          fi
       /* T4 claim --doing / T7 unclaim / T8 pass [--doing]; seat then card (F183) */
       :: acq(seatlk[d]); acq(cardlk);
          atomic {
            due = false;
            if
            :: LIVE(d) ->
               if
               :: move_row(d, false, ON_CARD); focus_row(d, true, ON_CARD, false)      /* claim --doing */
               :: move_row(d, false, ON_CARD)                                         /* unclaim */
               :: if :: ev = true :: ev = false fi;                                   /* pass, evidence or not */
                  mvfocus = fver[d]; due = f_text[d] && f_on[d] == ON_CARD;
                  move_row(d, ev, ON_CARD);
                  if
                  :: doing -> focus_row(d, true, ON_CARD, false); due = false
                  :: !doing && !FINISH_SPLIT -> end_by_move(d, ON_CARD); due = false
                  :: else -> skip
                  fi
               fi
            :: else -> skip
            fi;
            check_all(); cardlk = FREE; seatlk[d] = FREE
          }
          if
          :: due && FINISH_SPLIT ->
             acq(seatlk[d]);
             atomic { finish(d, ON_CARD); check_all(); seatlk[d] = FREE }
          :: else -> skip
          fi
       /* D2/D3, touch, socket, LAN: the seat row only (invariant 13) */
       :: acq(seatlk[d]);
          atomic {
#ifdef MUT_HEARTBEAT_BUMP
            bump = true;      /* mill_doing_anchor + the activity bump of the newest row */
#endif
            assert(!bump);
            check_all(); seatlk[d] = FREE
          }
       fi
    fi;
    atomic {
      assert(!(f_text[d] && ENDED(d)));   /* an active focus row never reads as ended */
      mygen = 0; mvfocus = 0; doing = false; wait = false; ev = false; due = false   /* dead locals */
    }
  }
}

#ifdef MUT_NO_SEATLOCK
/* A shell of desk 0 whose focus write takes no seat lock: insert, then point. */
proctype Racer() {
  atomic { tok[0] -> rnew = true; ptr_ok[0] = false };            /* insert: the newest focus row */
  atomic { ptr_ok[0] = rnew; fver[0]++; f_text[0] = true; f_on[0] = ON_MAIL; f_wait[0] = false; check_all() }
}
#endif

/* Admin: mill reset seat D0 --yes (D11) or mill retire desk D0 --yes (N1), once. */
proctype Admin() {
  bool ret, hadtok;
  byte d0;
  if :: ret = true :: ret = false fi;
  if :: ret -> acq(namelk) :: else -> skip fi;
  acq(seatlk[0]);
  /* mill_hold_release_desk: UPDATE hold ... WHERE desk_id = D locks D's hold rows */
  if :: owner == 0 || pend == 0 -> acq(holdlk) :: else -> skip fi;
  atomic {
    if :: ret && retired[0] -> goto out :: else -> skip fi;
    hadtok = tok[0];
    tok[0] = false;
    /* D10: mill_doing_clear, unless the focus is already empty; retire only when the
     * seat had a token (sp_name_retire: IF ROW_COUNT() > 0) */
    if
    :: (!ret || hadtok) && (!has_focus[0] || f_text[0]) -> focus_row(0, false, ON_NONE, false)
    :: else -> skip
    fi;
#ifndef MUT_RETIRE_KEEPS
    /* H5: each freed hold, one 'dropped' row on the holder's doing */
    if :: owner == 0 -> owner = FREE; pend = FREE; rholder = FREE; move_row(0, false, ON_HOLD) :: else -> skip fi;
#endif
    if :: ret -> retired[0] = true :: else -> skip fi;
    /* invariant 15 at the retire's commit */
    assert(!ret || (!tok[0] && owner != 0 && rholder != 0 && !f_text[0]));
    check_all();
out:
    namelk = FREE; seatlk[0] = FREE; if :: holdlk == _pid -> holdlk = FREE :: else -> skip fi
  }
}

init {
  byte s;
  atomic {
    /* desk 0 is seated with its 'joined' row (or migrated: seat.doing_id = its newest row);
     * desk 1 has a seat row from its mint and has not joined */
    tok[0] = true; gen[0] = 1; joined[0] = true; has_focus[0] = true; fver[0] = 1;
    for (s : 1 .. SHELLS0) { run Shell(0) };
    run Shell(1);
    run Admin();
#ifdef MUT_NO_SEATLOCK
    run Racer();
#endif
  }
}

#ifdef REACH
/* reachability goal 2: a hold passes desk 0 -> free -> desk 1 */
ltl reach_hold { [] (hstage != 3) }
/* reachability goal 3: desk 0 goes idle -> active -> waiting -> idle */
ltl reach_focus { [] (fstage != 3) }
#endif
/* invariant 15 after the retire: a retired desk holds no hold and has no active focus */
ltl retire_clean { [] (retired[0] -> (owner != 0 && !f_text[0])) }
