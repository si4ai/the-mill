/*
 * activity_history.pml - card 1125 MVP (targeted at 0.8.14): `mill replace-body mail|todo ID`
 * with the full old body kept in activity_history. DESIGN MODEL: nothing is built yet.
 *
 * Sources (room card-1125-mvp on the office, and the cards):
 *   5384  MVP write-up: one procedure per body write, lock seat then item, compare the
 *         caller's body_updated, insert the history row, write body + body_updated +
 *         body_updater_id; a read returns body and body_updated from one SELECT; a body
 *         write never touches opened or receipts.
 *   5390  builder: appends happen inside the item lock from the current text (never a
 *         client read-modify-write); a bare claim writes no body; body-replace carries the
 *         desk's last read, and with none it is refused with the read command.
 *   5392, 5393, card 1125 done_when: only body-replace can be refused body:stale.
 *   card 1133 decisions 1-8: activity_history(old_body, old_updated, old_updater_id,
 *         replaced_at, replaced_by), UNIQUE (type, activity_id, old_updated), one transaction
 *         under the item lock; the version is body_updated DATETIME(6) from MILL_NOW().
 *   card 1125 (8:19 AM PST): note appends and --supersedes leave the card; text changes only
 *         through replace-body. APPEND=0 is that path; APPEND=1 keeps one in-lock append
 *         (a claim's take-over or --msg line, which the done_when still names).
 *
 * Desks: A author (letter sender / card asker), B addressee or claimer (no edit right),
 * W an Admin desk. One item. Each atomic block is one stored procedure under the item row
 * lock (FOR UPDATE), as in todo.pml and mail.pml.
 *
 * Text is abstract: body version k (1 = as created) with stamp ts[k] (0 = NULL, never
 * edited), updater upd[k] and parent par[k] (the version it replaced). A desk's last read is
 * rb[d] (the version whose text it saw) and lr[d] (the body_updated the client keeps and
 * sends with body-replace). They differ only under the mutations below.
 *
 * Switches:
 *   APPEND   1 = B's claim may append one line inside the lock (default), 0 = replace only
 *   CLOSE    1 = the author may retire the item (replace refused afterwards)
 *   FAIL     1 = a replace may fail after its history insert (forced error; rolls back)
 *   CLOCK    0 = MILL_NOW() strictly increases (default); 1 = it may repeat an earlier value
 *            (clock stepped back, or two writes in one microsecond)
 *   UNIQUE   1 = UNIQUE (type, activity_id, old_updated) on activity_history (default)
 *   MAXTRY   replace attempts per editor, re-reading after each refusal (default 2)
 *   CHECK_P6 also assert: a replace based on the current text is never refused
 * Mutations (each must fail its check, so the passes are not vacuous):
 *   MUT_APPEND_RMW    the append is built from the desk's earlier unlocked read
 *   MUT_CLAIM_RMW     a claim rewrites the body from its earlier unlocked read (today's path)
 *   MUT_NOCAS         replace ignores the caller's body_updated (last writer wins)
 *   MUT_CAS_SPLIT     replace compares body_updated before taking the item lock
 *   MUT_READ_SPLIT    a read returns body and body_updated from two selects
 *   MUT_HIST_SPLIT    the history row is written in its own transaction before the body
 *   MUT_OPEN_CLEAR    a body write clears mail_to.opened (unread again)
 *   MUT_FRESH_READ    body-replace re-reads body_updated inside the call, not the last read
 *   MUT_NULL_NE       the compare is `cur <> base` (NULL <> x is NULL, so never stale)
 *   MUT_NULL_EQ       the compare is `cur = base` (NULL = NULL is NULL, so always stale)
 *   MUT_ANY_RIGHTS    the rights check is missing
 *   MUT_EDIT_RETIRED  replace on a retired item applies
 *   MUT_APPEND_NOBUMP the append writes the body but leaves body_updated as it was
 *   MUT_NOREAD_NULL   the client sends NULL when it has no last read (None for both cases)
 */

#ifndef APPEND
#define APPEND 1
#endif
#ifndef CLOSE
#define CLOSE 0
#endif
#ifndef FAIL
#define FAIL 0
#endif
#ifndef CLOCK
#define CLOCK 0
#endif
#ifndef UNIQUE
#define UNIQUE 1
#endif
#ifndef MAXTRY
#define MAXTRY 2
#endif

#define A  0
#define B  1
#define W  2
#define ND 3
#define NOONE  3          /* body_updater_id NULL */
#define NULLTS 0          /* body_updated NULL */
#define NOREAD 255        /* no last read recorded for this desk */
#define MAXV 6            /* create + A + W + B (+ one spare for mutations) */
#define MAXH 6

#define LIVE    0
#define RETIRED 1

/* result of a replace */
#define OK      0
#define STALE   1         /* body:stale: edited by DESK at TIME; re-read with ..., then retry */
#define NOLAST  2         /* no last read: refused with the read command */
#define DENIED  3         /* not the sender/asker or Admin, or retired */
#define DUP     4         /* UNIQUE (type, activity_id, old_updated): insert fails, rolled back */
#define ABORT   5         /* forced error after the history insert: rolled back */

/* item: mail or todo row */
byte cur = 1;             /* the version on the row */
byte nv = 1;              /* versions created so far */
byte ts[MAXV];            /* body_updated of version k */
byte upd[MAXV];           /* body_updater_id of version k */
byte par[MAXV];           /* ghost: version k replaced par[k] */
byte st = LIVE;
byte ret_cur = 0;         /* ghost: version at retire */
bool claimed = false;
byte now = 0;             /* MILL_NOW() */

/* activity_history: row i holds the replaced version (old_body) and its stamp (old_updated) */
byte hlen = 0;
byte hold[MAXH];
byte hts[MAXH];

/* per desk */
byte rb[ND];              /* ghost: version whose text the desk last saw */
byte lr[ND];              /* the body_updated its client keeps as the last read */
bool opened[ND];          /* mail_to.opened (first open kept) */
byte receipts[ND];

/* P4: history is the log of the row: one row per body write, the newest row is the version
   the current one replaced, with its stamp. */
#define HIST_OK (hlen == nv - 1 && (hlen == 0 || (hold[hlen-1] == par[cur] && hts[hlen-1] == ts[par[cur]])))

inline stamp(s) {
#if CLOCK
  if
  :: now < 3 -> now++; s = now
  :: now > 0 -> s = now                      /* same microsecond, or a step back to now */
  :: now > 1 -> s = now - 1                  /* clock stepped back */
  fi
#else
  now++; s = now
#endif
}

/* A read: mill mail-thread N / mill todo ID --full / glance. One SELECT returns body,
   body_updated and body_updater_id; the client records (type, id) -> body_updated. */
inline read(d) {
#ifdef MUT_READ_SPLIT
  atomic { rb[d] = cur };
  atomic {
#else
  atomic {
    rb[d] = cur;
#endif
    lr[d] = ts[cur];
    assert(ts[rb[d]] == lr[d]);                /* P1: body and body_updated are one version */
    if
    :: d == B && !opened[d] -> opened[d] = true; receipts[d]++   /* first open: one receipt */
    :: else -> skip
    fi;
    assert(receipts[d] <= 1);                  /* P7: one receipt per mail_to row */
    assert(HIST_OK)                            /* P4 seen by every reader */
  }
}

/* The one body-write step: history row and body in one transaction under the item lock. */
inline write_body(d, base) {
  byte s;
  assert(base == cur);                         /* P3: the text written was built on the current text */
#ifndef MUT_HIST_SPLIT
  assert(hold[hlen] == 0 && hlen < MAXH);      /* append-only */
  hold[hlen] = cur; hts[hlen] = ts[cur]; hlen++;
#endif
  nv++; par[nv] = cur;
  stamp(s); ts[nv] = s;
  upd[nv] = d; cur = nv;
#ifdef MUT_OPEN_CLEAR
  opened[B] = false;
#endif
  skip
}

/* UNIQUE (type, activity_id, old_updated): the history insert for old_updated = ts[cur] fails
   when an earlier row has the same old_updated. NULLs never collide in a MySQL UNIQUE key. */
inline dup_key(r) {
  byte i = 0;
  r = 0;
#if UNIQUE
  do
  :: i < hlen -> if :: ts[cur] != NULLTS && hts[i] == ts[cur] -> r = 1 :: else -> skip fi; i++
  :: else -> break
  od
#endif
  i = 0
}

/* mill replace-body mail|todo ID TEXT: the agent's text is built on rb[d]; the client sends
   lr[d]. The procedure compares it with body_updated under the lock (NULL-safe, <=>). */
inline replace(d, res) {
  byte b, ok, dup;
  b = lr[d];
#ifdef MUT_NOREAD_NULL
  if :: b == NOREAD -> b = NULLTS :: else -> skip fi;   /* no last read sent as NULL */
#endif
#ifdef MUT_FRESH_READ
  atomic { b = ts[cur] };                      /* re-read inside the call: the agent's text is older */
#endif
#ifdef MUT_CAS_SPLIT
  ok = (ts[cur] == b);
#endif
#ifdef MUT_HIST_SPLIT
  atomic {                                     /* own transaction: commits before the body write */
    if
    :: b != NOREAD && (d != B) && st == LIVE && ts[cur] == b ->
       hold[hlen] = cur; hts[hlen] = ts[cur]; hlen++
    :: else -> skip
    fi
  };
#endif
  atomic {
#ifndef MUT_CAS_SPLIT
#if defined(MUT_NULL_NE)
    ok = (ts[cur] == NULLTS || b == NULLTS || ts[cur] == b);
#elif defined(MUT_NULL_EQ)
    ok = (ts[cur] != NULLTS && b != NULLTS && ts[cur] == b);
#else
    ok = (ts[cur] == b);
#endif
#endif
#ifdef MUT_NOCAS
    ok = 1;
#endif
    if
    :: b == NOREAD -> res = NOLAST             /* refused with the exact read command */
#ifndef MUT_ANY_RIGHTS
    :: b != NOREAD && d == B -> res = DENIED
#endif
#ifndef MUT_EDIT_RETIRED
    :: b != NOREAD && st == RETIRED -> res = DENIED
#endif
    :: else ->
       if
       :: ok ->
          dup_key(dup);
          if
          :: dup -> res = DUP                  /* insert fails; nothing changes */
          :: else ->
#if FAIL
             if
             :: res = ABORT                    /* error after the history insert: rollback */
             :: write_body(d, rb[d]); res = OK
             fi
#else
             write_body(d, rb[d]); res = OK
#endif
          fi
       :: else -> res = STALE                  /* nothing changes */
       fi
    fi;
    assert(res != OK || d != B);               /* P2: only the sender/asker or Admin replaces */
#ifdef CHECK_P6
    /* P6: a replace whose text was built on the current text, by a desk with the right, on a
       live item, is not refused (no false body:stale) */
    assert(!(b != NOREAD && rb[d] == cur && d != B && st == LIVE && res != OK && res != ABORT));
#endif
    if :: res == OK -> rb[d] = cur; lr[d] = ts[cur] :: else -> skip fi   /* the reply has the new stamp */
  }
}

/* An editor: read (W may skip it), replace; after a refusal re-read and retry. */
proctype Editor(byte d) {
  byte res = 255, n = 0;
  if
  :: read(d)
  :: d == W -> skip                            /* no last read: replace-body is refused (5392 b) */
  fi;
  do
  :: n < MAXTRY ->
     replace(d, res); n++;
     if
     :: res == OK || res == DENIED -> break
     :: else -> read(d)
     fi
  :: n == MAXTRY -> break
  od;
#if CLOSE
  if :: d == A -> atomic { st = RETIRED; ret_cur = cur } :: else -> skip fi;
#endif
  skip
}

/* The addressee / claimer: reads, claims (with or without a line), tries a replace it has no
   right to make, reads again (opened stays, one receipt). */
proctype Claimer() {
  byte res = 255;
  read(B);
  if
  :: atomic { claimed = true }                 /* bare claim: status only, no body write */
#if APPEND
  :: atomic {                                  /* claim --msg / take-over line, in the lock */
       claimed = true;
       if
       :: st == LIVE ->
#if defined(MUT_APPEND_RMW)
          write_body(B, rb[B])                 /* built from the earlier unlocked read */
#elif defined(MUT_APPEND_NOBUMP)
          assert(hold[hlen] == 0); hold[hlen] = cur; hts[hlen] = ts[cur]; hlen++;
          nv++; par[nv] = cur; ts[nv] = ts[cur]; upd[nv] = B; cur = nv
#else
          write_body(B, cur)                   /* built from the current text under the lock */
#endif
       :: else -> skip
       fi
     }
#endif
#ifdef MUT_CLAIM_RMW
  :: atomic { claimed = true; write_body(B, rb[B]) }   /* claim writes back its old read */
#endif
  :: replace(B, res)
  fi;
  read(B)
}

/* Quiescence: every desk is done. */
active proctype Check() {
  timeout ->
  atomic {
    byte k = 2;
    assert(HIST_OK);
    /* P3 at rest: the versions form one chain; P4: history row i is version i+1 and its stamp */
    do
    :: k <= nv -> assert(par[k] == k - 1);
       assert(hold[k-2] == k - 1 && hts[k-2] == ts[k-1]); k++
    :: else -> break
    od;
    assert(st != RETIRED || cur == ret_cur);   /* P5: a retired item's body never changes */
    assert(receipts[B] <= 1)                   /* P7 */
  }
}

init {
  atomic {
    ts[1] = NULLTS; upd[1] = NOONE; par[1] = 0;
    rb[A] = 1; lr[A] = NOREAD; rb[B] = 0; lr[B] = NOREAD; rb[W] = 0; lr[W] = NOREAD;
    run Editor(A); run Editor(W); run Claimer()
  }
}
