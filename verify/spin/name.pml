/*
 * name.pml - name retire and reclaim in 0.8.0: N1-N4, with the seat token they read.
 *
 * Sources:
 *   design  docs/requirements/beta/activity-states-080.md (PR #226, c2a91f9), section seat
 *           focus and name retire; the Builder's handoff, invariant 14
 *   code    the box copy of lane B's sp_beta_name.sql (card 880 self-retire; not yet pushed;
 *           the pushed lane B head ac136b8 is Admin only):
 *     sp_name_retire   name row FOR UPDATE; self check = target is the caller AND
 *                      EXISTS (SELECT 1 FROM seat WHERE desk_id = caller AND token_hash = hash),
 *                      a plain read; else Admin; Office (1) and Admin (2) never; then
 *                      UPDATE seat SET token_hash = NULL ... (the seat row lock)
 *     sp_name_reclaim  Admin; name row FOR UPDATE; refused while a live seat is that desk
 *                      (a plain EXISTS read)
 *     sp_join.sql      mill_join_upsert: MILL_NAME_PUT refuses a retired name on a plain read
 *                      (fn_name.sql), then UPDATE seat SET token_hash = IFNULL(new, old)
 *     sp_join.sql      mill_join_reset: UPDATE seat SET token_hash = NULL; no name lock
 *
 * Model: names Office, Admin, desks D and E. Admin retires, reclaims and resets; D and E
 * each retire themselves, try to retire the other, try to reclaim, and join again. Each
 * request first authenticates its token (rpc), in its own step.
 *
 * Switches (1 = a fix, 0 = the code):
 *   SELF_LOCK       the self check reads the seat FOR UPDATE, with the seat write (default 0)
 *   JOIN_NAME_LOCK  join reads the name row with a lock that waits for a retire (default 0)
 *   K               requests per process (default 2)
 * Mutations:
 *   MUT_SELF_ANY     the self check forgets "target is the caller": any seated desk retires any desk
 *   MUT_RECLAIM_ANY  reclaim forgets the Admin check
 */

#ifndef K
#define K 2
#endif
#ifndef SELF_LOCK
#define SELF_LOCK 0
#endif
#ifndef JOIN_NAME_LOCK
#define JOIN_NAME_LOCK 0
#endif

#define OFFICE 0
#define ADMIN 1
#define D 2
#define E 3
#define NN 4
#define FREE 255

bool del[NN];             /* name.deleted */
byte tok[NN];             /* seat.token_hash: 0 = NULL, else which token */
byte mint = 2;            /* the next token value */
byte namelk[NN] = FREE;
byte seatlk[NN] = FREE;

inline acq(L) { atomic { L == FREE -> L = _pid } }

/* sp_name_retire(by me, hash mytok, target t) */
inline retire(rme, rt) {
  admin = (rme == ADMIN);
  acq(namelk[rt]);
#if !SELF_LOCK
  seen = tok[rme];                                 /* EXISTS (SELECT ... token_hash = hash): a plain read */
#endif
  if :: rt == D || rt == E -> acq(seatlk[rt]) :: else -> skip fi;
  atomic {
#if SELF_LOCK
    seen = tok[rme];                               /* read under the seat lock */
#endif
#ifdef MUT_SELF_ANY
    self = (rt == D || rt == E) && mytok != 0 && seen == mytok;
#else
    self = (rt == rme) && mytok != 0 && seen == mytok;
#endif
    if
    :: (self || admin) && rt != OFFICE && rt != ADMIN && !del[rt] ->
       /* invariant 14: Admin, or the desk itself while its token is the seat's */
       assert(admin || (rt == rme && tok[rme] == mytok));
       del[rt] = true;
       if :: rt == D || rt == E -> tok[rt] = 0 :: else -> skip fi
    :: else -> skip                               /* refused */
    fi;
    assert(!del[OFFICE] && !del[ADMIN]);
    namelk[rt] = FREE; if :: seatlk[rt] == _pid -> seatlk[rt] = FREE :: else -> skip fi
  }
}

/* sp_name_reclaim(by me, target t) */
inline reclaim(cme, ct) {
  acq(namelk[ct]);
  atomic {
    if
#ifdef MUT_RECLAIM_ANY
    :: del[ct] && tok[ct] == 0 ->
#else
    :: cme == ADMIN && del[ct] && tok[ct] == 0 ->
#endif
       assert(cme == ADMIN);                       /* reclaim is Admin only */
       del[ct] = false
    :: else -> skip
    fi;
    namelk[ct] = FREE
  }
}

/* mill_join_upsert for desk me: a retired name refuses; a seat with no token gets one */
inline join(jme) {
#if JOIN_NAME_LOCK
  acq(namelk[jme]);
#endif
  live = !del[jme];                                /* MILL_NAME_PUT: a plain read */
  if
  :: live -> acq(seatlk[jme]);
     atomic {
       if :: tok[jme] == 0 -> tok[jme] = mint; mint++ :: else -> skip fi;
       seatlk[jme] = FREE
     }
  :: else -> skip
  fi;
#if JOIN_NAME_LOCK
  namelk[jme] = FREE
#endif
}

proctype Desk(byte me) {
  byte k, mytok, other, seen;
  bool self, admin, live;
  other = (me == D -> E : D);
  for (k : 1 .. K) {
    if
    :: atomic { tok[me] != 0 -> mytok = tok[me] };   /* the request's token authenticates */
       if
       :: retire(me, me)                             /* N2: self-retire */
       :: retire(me, other)                          /* refused: not Admin */
       :: reclaim(me, other)                         /* refused: not Admin */
       fi
    :: atomic { tok[me] == 0 -> mytok = 0 };
       join(me)
    fi;
    mytok = 0
  }
}

proctype Admin() {
  byte k, t, mytok, seen;
  bool self, admin;
  for (k : 1 .. K) {
    if :: t = OFFICE :: t = ADMIN :: t = D :: t = E fi;
    if
    :: retire(ADMIN, t)                              /* N1, N3 */
    :: reclaim(ADMIN, t)                             /* N4 */
    :: t == D || t == E -> acq(seatlk[t]);           /* mill reset seat t --yes */
       atomic { tok[t] = 0; seatlk[t] = FREE }
    fi
  }
}

init {
  atomic { tok[D] = 1; tok[E] = 1; run Desk(D); run Desk(E); run Admin() }
}

/* a retired desk holds no seat token (a reclaimed desk has none until reset and join) */
ltl retired_no_token { [] ((del[D] -> tok[D] == 0) && (del[E] -> tok[E] == 0)) }
