/*
 * mail.pml - a letter's recipient rows in 0.8.0: M1-M8, keyed on transition ids.
 *
 * Sources:
 *   design  docs/requirements/beta/activity-states-080.md (PR #226, c2a91f9), section mail:
 *           mail_to.opened is set once (IFNULL(opened, now)); opening does not touch activity
 *   code    release/0.8.0 lane B (PR #224, 413cdb8) sp_opened.sql mill_mail_open:
 *           SELECT opened ... FOR UPDATE into v_prev; UPDATE only when v_prev IS NULL
 *           (IFNULL / opened IS NULL); push_receipt from v_prev IS NULL; no activity bump.
 *
 * Model: desk S sends one letter to desk R with a receipt (M1). R opens it from two
 * shells at once (M3 mark, M4 whole read, M6 again, M2 reply, which stamps its parent);
 * the sender adds desk Q (M7) and removes it (M8). Each open takes the row lock, then
 * reads and updates in one atomic step (OPEN_LOCKED=1).
 *
 * Switches (1 = the code at 413cdb8, 0 = the 0.7.19 / pre-F186 shape):
 *   FIRST_OPEN   opened = IFNULL(opened, now)            (default 1)
 *   QUIET_OPEN   an open does not touch activity          (default 1)
 *   OPEN_LOCKED  v_prev is read under the row lock        (default 1)
 *   SKIP_INV7    leave out invariant 7's assert, to see the receipt check on its own
 * Mutations:
 *   OPEN_LOCKED=0     v_prev is a plain read before the lock
 *   MUT_RC_MATCHED    ROW_COUNT counts matched rows: with OPEN_LOCKED=0, two concurrent
 *                     opens that both read v_prev NULL both push a receipt even with IFNULL
 */

#ifndef FIRST_OPEN
#define FIRST_OPEN 1
#endif
#ifndef QUIET_OPEN
#define QUIET_OPEN 1
#endif
#ifndef OPEN_LOCKED
#define OPEN_LOCKED 1
#endif

#define R 0
#define Q 1
#define NR 2

bool row[NR];          /* a mail_to row for the recipient */
byte opened[NR];       /* mail_to.opened: 0 = NULL, else the stamp */
byte first[NR];        /* ghost: the first stamp since the row was made */
byte receipts[NR];     /* receipts pushed to the sender */
byte now = 1;          /* the clock: each open stamps a new value */
byte actv;             /* activity writes on the letter */
byte rowlk = 255;      /* the mail_to row lock (UPDATE) */

/* mill_mail_open(p_mail, desk x), called by M3, M4, M6 and M2 (on the parent). */
inline open_mail(x) {
  byte prev, n, a0;
#if !OPEN_LOCKED
  prev = opened[x];                     /* pre-F186: plain read before the lock */
#endif
  atomic { rowlk == 255 -> rowlk = _pid };
  atomic {
#if OPEN_LOCKED
    prev = opened[x];                   /* 413cdb8: v_prev under FOR UPDATE */
#endif
    a0 = actv;
    if
    :: row[x] ->
#if FIRST_OPEN
       if :: opened[x] == 0 -> opened[x] = now; n = 1
          :: else -> n = 0
       fi;
#ifdef MUT_RC_MATCHED
       n = 1;                               /* matched-row ROW_COUNT: still "changed" */
#endif
#else
       opened[x] = now; n = 1;
#endif
       now++;
       if :: first[x] == 0 -> first[x] = opened[x] :: else -> skip fi;
#ifndef SKIP_INV7
       assert(opened[x] == first[x]);                 /* invariant 7: the first open is kept */
#endif
#if !QUIET_OPEN
       if :: n > 0 -> actv++ :: else -> skip fi;
#endif
       if :: prev == 0 && n > 0 -> receipts[x]++ :: else -> skip fi;
       assert(receipts[x] <= 1)                       /* one receipt per recipient row */
    :: else -> skip
    fi;
    assert(actv == a0);                               /* invariant 8: opening leaves activity alone */
    rowlk = 255
  }
}

proctype Shell() {
  /* M3 mark, M4 mail-thread whole read, M6 mark again, or M2 reply (opens the parent) */
  if :: skip :: skip fi;
  open_mail(R);
  if :: open_mail(R) :: skip fi      /* M6: a second open */
}

proctype Sender() {
  /* M7 add mail:N Q (unread), M8 remove mail:N Q, then add again */
  atomic { rowlk == 255 -> row[Q] = true; opened[Q] = 0; first[Q] = 0 };
  if
  :: atomic { rowlk == 255 -> row[Q] = false; opened[Q] = 0; first[Q] = 0; receipts[Q] = 0 };
     atomic { rowlk == 255 -> row[Q] = true }
  :: skip
  fi
}

proctype Q_desk() {
  open_mail(Q)
}

init {
  atomic {
    /* M1: the letter is live (act sent), R unread with a receipt */
    row[R] = true; actv = 1;
    run Shell(); run Shell(); run Sender(); run Q_desk()
  }
}
