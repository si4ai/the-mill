/*
 * score.pml - a score's moves in 0.8.0: S1-S6, keyed on transition ids.
 *
 * Sources:
 *   design  docs/requirements/beta/activity-states-080.md (PR #226, c2a91f9), section score:
 *           act on the activity row only, no doing rows; S6 clears activity.deleted
 *   code    release/0.8.0 lane B (PR #224, ac136b8) sp_score.sql:
 *           mill_score_point_add, mill_score_define: score row FOR UPDATE, insert when none,
 *           mill_activity_put, then activity.deleted = NULL (S6)
 *           mill_score_retire: the live score row FOR UPDATE; only a desk that recorded on
 *           it, or Admin; activity.deleted stamped
 *           mill_wall_event and the host writers: the same point write (act scored); not
 *           heartbeats under decision 6
 *
 * Model: desk A (records first), desk B and the Wall writer each make up to K moves on
 * one score name; Admin may retire it. Each procedure is one atomic step under the
 * score row lock (two first writes race on the unique key; one wins, the other then
 * finds the row: the same result as serial order).
 *
 * Mutation:
 *   MUT_REVIVE_KEEPS  a point or a target on a retired score leaves activity.deleted set
 */

#ifndef K
#define K 2
#endif

#define S1 1
#define S2 2
#define S3 3
#define S4 4
#define S5 5
#define S6 6
#define WALL 2
#define ADMIN 3

bool exists, deleted;   /* score row; activity.deleted */
byte points;            /* score_point rows (capped at 2) */
bool recorded[4];       /* desks that recorded on it (who may retire) */
byte act, actor, laststep;
byte drows;             /* doing rows written by score moves: none */

inline put(a, d) { act = a; actor = d; laststep = a }

proctype Writer(byte d) {
  byte k;
  for (k : 1 .. K) {
    if
    /* S1 / S3 / S6: mill score R NAME V (also the Wall's mill_wall_event) */
    :: atomic {
         if
         :: !exists -> exists = true; points = 1; put(S1, d)
         :: exists && deleted -> if :: points < 2 -> points++ :: else -> skip fi; put(S6, d);
#ifndef MUT_REVIVE_KEEPS
            deleted = false
#endif
         :: exists && !deleted -> if :: points < 2 -> points++ :: else -> skip fi; put(S3, d)
         fi;
         recorded[d] = true
       }
    /* S2 / S4 / S6: mill score R NAME --target T */
    :: d != WALL -> atomic {
         if
         :: !exists -> exists = true; put(S2, d)
         :: exists && deleted -> put(S6, d);
#ifndef MUT_REVIVE_KEEPS
            deleted = false
#endif
         :: exists && !deleted -> put(S4, d)
         fi;
         recorded[d] = true
       }
    /* S5: mill retire score R NAME --yes */
    :: d != WALL -> atomic {
         if
         :: exists && !deleted && (recorded[d] || d == ADMIN) -> deleted = true; put(S5, d)
         :: else -> skip                          /* refused */
         fi
       }
    fi;
    /* the checks hold after every committed step */
    assert(deleted == (exists && laststep == S5));          /* retired iff the last move was S5 */
    assert(!exists || act == laststep);                      /* invariant 4 */
    assert(drows == 0)                                       /* invariant 3: no score doing rows */
  }
}

init {
  atomic { run Writer(0); run Writer(1); run Writer(WALL); run Writer(ADMIN) }
}
