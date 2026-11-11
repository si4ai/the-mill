/*
 * activity_history.pml - card 1125 (targeted at 0.8.13): text edits on mail and todo,
 * one text version (rev) per activity, stale checks on acts, debounced edited hints,
 * unread-again, done and retired items. DESIGN MODEL: nothing is built yet.
 *
 * Sources:
 *   letters 5294, 5296 (builder): activity_history table, default reads current text only,
 *           edited hint with the new text to everyone on the activity, unread again for
 *           anyone who already handled it, every read returns a fingerprint and acts carry it.
 *   code    the-mill main e028bac (card 1113): mill_mail_update (seat then letter FOR UPDATE,
 *           sender or Admin), mill_todo_write (seat then card FOR UPDATE, card:deleted under
 *           the lock), mill_mail_open (mail_to row FOR UPDATE, first open kept, one receipt),
 *           mill_mail_insert (a reply locks nothing on the parent).
 *
 * Desks: A author/asker (may edit, may close), B addressee/claimer (reads, then a reply or
 * claim carrying the rev it saw), W watcher with Admin (reads, may edit from what it saw).
 * A Hub delivers edited hints. Each atomic block is one stored procedure under the item row
 * lock (FOR UPDATE), as in todo.pml and mail.pml.
 *
 * Text is abstract: the text written by the edit that made rev k has id k, so the text a desk
 * saw is saw[d] and the rev its client will send is knows[d]. They differ only under the
 * mutations below; the design says the client sends the rev of the text it last showed.
 *
 * Switches (defaults are the proposed design in docs/dev/card-1125-activity-history.md):
 *   ACT_MODE    0 = a stale reply/claim applies with stale=true and the current text (default)
 *               1 = a stale reply/claim is refused; the desk re-reads and retries (MAXTRY tries)
 *   SEEN_REV    1 = unread is derived: seen_rev < rev on the per-desk row (default)
 *               0 = unread-again by clearing mail_to.opened (the reuse temptation)
 *   EDITS_A     edits the author tries (default 2); W tries one
 *   CLOSE       0 none, 1 the author may mark the item done, 2 may retire it (default 1)
 *   EDIT_DONE   1 = edits on a done item apply and notify (default), 0 = refused
 *   HINT_DROP   1 = the Hub may drop a hint (sit FIFO overflow, failed wake)
 *   INFLIGHT    1 = a hint is taken, then lands later (a read may come in between)
 *   MAXTRY      act attempts in refuse mode (default 2)
 *   CHECK_P5    also assert at rest that every desk was told the final rev (P5; no drops)
 *   SKIP_P7     leave out the one-receipt assert, to see P2 on its own with SEEN_REV=0
 * Mutations (each must fail its check, so the checks are not vacuous):
 *   MUT_CHECK_SPLIT    the act compares its rev before taking the item lock
 *   MUT_READ_SPLIT     a read returns body and rev from two selects
 *   MUT_SILENT         a stale act applies with no flag and no current text
 *   MUT_EDIT_NOCAS     a text edit ignores its base rev (last writer wins)
 *   MUT_EDIT_SPLIT     a text edit compares its base before taking the lock
 *   MUT_HIST_SPLIT     the history row is written after commit, in its own step
 *   MUT_DEB_FIRST      debounce keeps the first pending rev, not the last
 *   MUT_SEEN_ON_HINT   queuing an edited hint marks the desk seen (the hint "is" the read)
 *   MUT_KNOWS_MAX      the client keeps the highest rev it ever heard, even from an older hint
 *   MUT_EDIT_RETIRED   an edit on a retired item applies
 *   MUT_NO_UNREAD_W    with SEEN_REV=0: unread-again clears only addressee rows, not watchers
 */

#ifndef ACT_MODE
#define ACT_MODE 0
#endif
#ifndef SEEN_REV
#define SEEN_REV 1
#endif
#ifndef EDITS_A
#define EDITS_A 2
#endif
#ifndef CLOSE
#define CLOSE 1
#endif
#ifndef EDIT_DONE
#define EDIT_DONE 1
#endif
#ifndef HINT_DROP
#define HINT_DROP 0
#endif
#ifndef INFLIGHT
#define INFLIGHT 0
#endif
#ifndef MAXTRY
#define MAXTRY 2
#endif

#define A  0
#define B  1
#define W  2
#define ND 3
#define MAXH (EDITS_A + 2)        /* create row + every edit */

#define LIVE    0
#define DONE    1
#define RETIRED 2

/* item */
byte rev = 1;            /* the text version on the payload row (mail.rev / todo.rev) */
byte cur = 1;            /* the current text (abstract id) */
byte st = LIVE;
byte ret_rev = 0;        /* ghost: rev at retire */
byte last_ed = A;        /* ghost: who made the current rev */

/* activity_history: row i holds the rev it produced; row 0 is the create */
byte hlen = 1;
byte hist[MAXH];
byte from_cnt[MAXH];     /* ghost: text edits applied from base b */

/* per desk */
byte saw[ND];            /* text id the desk last saw (read, hint, stale or refuse reply) */
byte knows[ND];          /* the rev its client will send as --rev */
byte seen[ND];           /* SEEN_REV=1: seen_rev on mail_to / watcher */
bool opened[ND];         /* mail_to.opened set (first open kept) */
bool handled[ND];
byte receipts[ND];       /* receipts pushed for this desk's row */
byte pend[ND];           /* debounced edited hint waiting for the Hub: the rev, 0 = none */
byte fly[ND];            /* INFLIGHT: hint taken by the Hub, not landed yet */

/* ghosts for the properties */
byte silent;             /* P1: an act accepted while the desk's text was older, with no flag */
byte stale_flags;
byte refusals;
bool gaveup;             /* refuse mode: the act never landed */
bool landed;

#if SEEN_REV
#define UNREAD(d) (seen[d] < rev)
#else
#define UNREAD(d) (!opened[d])
#endif

/* P4: history is the payload's log: one row per rev, the newest row is the current text. */
#define HIST_OK (hlen == rev && hist[hlen-1] == rev && cur == rev)

/* A read: mill show / mill mail N / inbox open. One SELECT returns body and rev. */
inline read(d) {
#ifdef MUT_READ_SPLIT
  atomic { saw[d] = cur };
  atomic {
#else
  atomic {
    saw[d] = cur;
#endif
    knows[d] = rev;
    seen[d] = rev;
    if
    :: !opened[d] -> opened[d] = true;
       if :: d == B -> receipts[d]++ :: else -> skip fi   /* B's row asked for a receipt */
    :: else -> skip
    fi;
#ifndef SKIP_P7
    assert(receipts[d] <= 1);       /* P7: one receipt per recipient row (mail invariant 7) */
#endif
    handled[d] = true;
    assert(HIST_OK)                 /* P4 seen by every reader: --history ends at the current text */
  }
}

/* Edited hint: one pending slot per (item, desk); a later edit replaces the rev (debounce). */
inline queue_hints(ed) {
  byte q = 0;
  do
  :: q < ND ->
     if
     :: q != ed ->
#ifdef MUT_DEB_FIRST
        if :: pend[q] == 0 -> pend[q] = rev :: else -> skip fi;
#else
        pend[q] = rev;
#endif
#ifdef MUT_SEEN_ON_HINT
        seen[q] = rev;
#endif
#if !SEEN_REV
        /* unread again: clear opened on rows that were handled */
#ifdef MUT_NO_UNREAD_W
        if :: handled[q] && q == B -> opened[q] = false :: else -> skip fi;
#else
        if :: handled[q] -> opened[q] = false :: else -> skip fi;
#endif
#endif
        skip
     :: else -> skip
     fi;
     q++
  :: else -> break
  od
}

/* A text edit (mill mail N --edit / mill edit CARD) from base b = knows[ed]: compare-and-set. */
inline edit(ed) {
  byte b, ok;
  b = knows[ed];
#ifdef MUT_EDIT_SPLIT
  ok = (b == rev);
#endif
  atomic {
#ifndef MUT_EDIT_SPLIT
    ok = (b == rev);
#endif
#ifdef MUT_EDIT_NOCAS
    ok = 1;
#endif
    if
#ifndef MUT_EDIT_RETIRED
    :: st == RETIRED -> saw[ed] = cur; knows[ed] = rev; refusals++   /* deleted: next command mill reclaim */
#endif
#if !EDIT_DONE
    :: st == DONE -> saw[ed] = cur; knows[ed] = rev; refusals++
#endif
    :: else ->
       if
       :: ok ->
          from_cnt[b]++;
          assert(from_cnt[b] <= 1);           /* P3: no lost edit: one edit per base */
          rev++; cur = rev; last_ed = ed;
#ifndef MUT_HIST_SPLIT
          assert(hist[hlen] == 0);            /* P4: append only */
          hist[hlen] = rev; hlen++;
#endif
          saw[ed] = cur; knows[ed] = rev; seen[ed] = rev;
          queue_hints(ed)
       :: else ->                              /* refused: stale base; reply has the current text and the diff */
          saw[ed] = cur; knows[ed] = rev; refusals++
       fi
    fi
  };
#ifdef MUT_HIST_SPLIT
  atomic { assert(hist[hlen] == 0); hist[hlen] = rev; hlen++ }   /* after-commit history write */
#endif
  skip
}

/* A reply, claim or pass carrying --rev b = knows[d]. Returns accepted, stale, text. */
inline act(d, res) {
  byte b, ok;
  b = knows[d];
#ifdef MUT_CHECK_SPLIT
  ok = (b == rev);
#endif
  atomic {
#ifndef MUT_CHECK_SPLIT
    ok = (b == rev);
#endif
    if
    :: st == RETIRED -> saw[d] = cur; knows[d] = rev; res = 2       /* refused: deleted */
    :: else ->
       if
       :: ok ->
          if :: saw[d] != cur -> silent++ :: else -> skip fi;
          seen[d] = rev; handled[d] = true; res = 0                   /* clean */
       :: else ->
#if ACT_MODE == 0
#ifdef MUT_SILENT
          silent++; res = 0                                           /* applied, nothing said */
#else
          stale_flags++; saw[d] = cur; knows[d] = rev; seen[d] = rev; handled[d] = true; res = 0
#endif
#else
          refusals++; saw[d] = cur; knows[d] = rev; res = 1           /* refused: re-read, retry */
#endif
       fi
    fi;
    assert(silent == 0)                 /* P1: no act at an old rev is accepted silently */
  }
}

proctype Author() {
  byte i = 0;
  do
  :: i < EDITS_A -> edit(A); i++
  :: i < EDITS_A -> read(A)
#if CLOSE == 1
  :: st == LIVE -> atomic { st = DONE }
#endif
#if CLOSE == 2
  :: st == LIVE -> atomic { st = RETIRED; ret_rev = rev }
#endif
  :: i == EDITS_A -> break
  od
}

proctype Watcher() {
  read(W);
  if :: edit(W) :: skip fi
}

proctype Replier() {
  byte res, n = 0;
  read(B);
  do
  :: n < MAXTRY ->
     act(B, res); n++;
     if :: res == 1 -> skip                /* refused: knows is fresh now, try again */
        :: else -> landed = true; break
     fi
  :: n == MAXTRY -> gaveup = true; break
  od;
  if :: read(B) :: skip fi                 /* re-reads after an edited hint (opens the letter again) */
}

/* The Hub lands a hint: the client keeps it only when it is not older than the text it has. */
inline land(d, r) {
#ifdef MUT_KNOWS_MAX
  saw[d] = r; if :: knows[d] < r -> knows[d] = r :: else -> skip fi
#else
  if
  :: knows[d] <= r -> saw[d] = r; knows[d] = r
  :: else -> skip                                   /* older than what it read: dropped by rev */
  fi
#endif
}

#if INFLIGHT
#define TAKE(d) atomic { pend[d] != 0 && fly[d] == 0 -> fly[d] = pend[d]; pend[d] = 0 }
#if HINT_DROP
#define LAND(d) atomic { fly[d] != 0 -> if :: land(d, fly[d]) :: skip fi; fly[d] = 0 }
#else
#define LAND(d) atomic { fly[d] != 0 -> land(d, fly[d]); fly[d] = 0 }
#endif
#elif HINT_DROP
#define TAKE(d) atomic { pend[d] != 0 -> if :: land(d, pend[d]) :: skip fi; pend[d] = 0 }
#define LAND(d) skip
#else
#define TAKE(d) atomic { pend[d] != 0 -> land(d, pend[d]); pend[d] = 0 }
#define LAND(d) skip
#endif

proctype Hub() {
end:
  do
  :: TAKE(0)
  :: TAKE(1)
  :: TAKE(2)
#if INFLIGHT
  :: LAND(0)
  :: LAND(1)
  :: LAND(2)
#endif
  od
}

/* Quiescence: every desk is done and the Hub is idle. */
active proctype Check() {
  timeout ->
  atomic {
    byte d = 0;
    /* P4 at rest: rows 0..rev-1 hold revs 1..rev in order */
    assert(HIST_OK);
    d = 0;
    do :: d < hlen -> assert(hist[d] == d + 1); d++ :: else -> break od;
    /* P6: a retired item's text never changes */
    assert(st != RETIRED || rev == ret_rev);
    d = 0;
    do
    :: d < ND ->
       /* P2: every desk on the activity was told the last rev, or still sees it unread */
       assert(knows[d] == rev || UNREAD(d));
#ifdef CHECK_P5
       /* P5 (no drops): debounce delivered the final rev to everyone but the editor */
       assert(knows[d] == rev);
#endif
       d++
    :: else -> break
    od
  }
}

init {
  atomic {
    hist[0] = 1;
    /* create/send: every desk on the activity got the text (rev 1) in the create hint */
    saw[A] = 1; knows[A] = 1; seen[A] = 1; opened[A] = true; handled[A] = true;
    saw[B] = 1; knows[B] = 1;
    saw[W] = 1; knows[W] = 1;
#if !SEEN_REV
    opened[W] = false;
#endif
    run Author(); run Watcher(); run Replier(); run Hub()
  }
}

/* refuse mode: the reply/claim lands (it is not refused MAXTRY times in a row) */
ltl act_lands { [] (!gaveup) }
