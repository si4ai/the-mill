/*
 * wake.pml - the mill wake path, as the code at the sync commit implements it
 * (SYNC in run.sh: PR #322's head, main 0.8.4 plus card 889).
 *
 * One desk D, armed with a webhook, and N items (letters or hints) for it.
 * Every step names the code it stands for. One atomic block here is one
 * indivisible step in the code (a lock held, or one stored procedure call).
 *
 * Code covered (paths from the repo root):
 *   agent_coord/server/push.py      emit (538-590), fanout (392-521),
 *                                   Hub.add (115-155), take_sync (622-630),
 *                                   connect_sync_frame (633-655)
 *   agent_coord/server/wake.py      _fire, _gate_open, _gate_take, lease_synced,
 *                                   _coalesced, _send_trailing, trail (lease end),
 *                                   lease_done (mill wake-done), post_desk
 *   agent_coord/server/api/mill/rpc.py  _h_wake_done
 *   agent_coord/server/asgi.py      ws_endpoint: add, then sync, then send (582-616);
 *                                   a command reply takes, then sends (633-636)
 *   agent_coord/server/sql/sp_push.sql  mill_push_take: SELECT + DELETE in one call
 *
 * Compile-time switches (run.sh sets them; defaults are current main):
 *   N            items for the desk (1..3)
 *   MAXFAIL      how many POSTs in a row the receiver may fail (0 = never fails,
 *                255 = may fail forever). This is the loss bound.
 *   SESSIONS     concurrent connects of D (2 lets a new connect supersede an old one)
 *   REFUSE       runs connect with -r: refused with 4409 while another holds the seat
 *   ATOMIC_EMIT  1 = treat emit/fanout as one step (hides the races, isolates loss)
 *   RETRY827     1 = card 827 / #300 (F232, in 0.8.3): post_desk makes ONE POST
 *                (_post_status); a retryable failure arms a retry chain off the
 *                request (_arm_retry): full jitter from 5 s, doubling, capped at
 *                10 min, about 1 h (RETRY_BUDGET_S) or RETRY_MAX attempts. Same
 *                body: same idem key, same lease, no new window. Armed only when
 *                the push queue is not empty (pending > 0). Stops when the push
 *                queue is drained (_queue_drained), when any later wake of the
 *                desk succeeds (_OK_GEN), or on a 401/404 (not modelled: a
 *                receiver that refuses for good is MAXFAIL=255).
 *                0 = before #300: _fire POSTs once and retries once at once.
 *   RETRIES      how many retries the chain makes (the code's budget is at
 *                least 12 and at most RETRY_MAX = 64; the model keeps it small)
 *   UNREAD       1 = card 949 / #297 (F-replay-unread, in 0.8.3): items 1..N-1 are
 *                letters, item 0 a hint. A letter is unread in the mailbox until the
 *                desk opens it. A connect sync merges unread mail not already in it
 *                (_merge_unread_into_sync); _send_trailing and ring_waiting also
 *                ring when the push queue is empty but unread mail remains.
 *                0 = before #297: only push rows ring or sync.
 *   MAXSKIP      UNREAD: how many times in all a run may leave without opening the
 *                letters it got (255 = a desk that never opens them)
 *   MUT_NO_RERING mutation of #297: letters still need opening, but neither the
 *                sync merge nor trailing nor ring-on-leave looks at unread mail
 *                (must fail all_handled)
 *   RETRY_UNREAD 1 = proposed: a failed wake also arms and keeps its retry while
 *                unread mail remains (the code reads only the push queue)
 *   DONE_IN_CONNECT 1 = a run may say mill wake-done inside its connect, while it
 *                still sits (the routine wrapper runs every command inside its
 *                connect); a run may also say it after the leave, or not at all.
 *                0 = done only after the last leave (the model before 0.8.5)
 *   SITTING_DONE 1 = card 889 / #322 (0.8.5): wake-done ends the lease, and when the
 *                desk still has a live /ws (desk_sitting) it sends no trailing POST
 *                (wake=sitting); held-back rows wait for that connect's sync or for
 *                ring-on-leave. An away desk keeps the F144 trailing POST.
 *                0 = before #322: the trailing POST goes out to a sitting desk.
 *   RECEIPT      1 = item 0 is a receipt: queued, never rings (push.py:573)
 *   RESTART      1 = the wall may restart once: windows and timers (memory) are lost
 *   PUTFIRST     1 = fix for card 832: rec_push.put (as missed) before the sitting
 *                read and the doorbell; a live frame that reached a socket marks
 *                its row sent afterwards (_broadcast -> _settle_row, a later step)
 *   RING_ON_LEAVE 1 = fix for card 832: when the last socket of D leaves
 *                (Hub.discard), or a live frame found no socket (_settle_row), and
 *                a missed row that rings waits, ring the webhook (ring_waiting)
 *   ACK_AFTER_SEND 1 = fix for card 831: a sync reads the rows without deleting
 *                them and deletes exactly those after its frame is sent
 *                (connect_sync_frame(hold=True), ack_sync); an unsent frame
 *                deletes nothing
 *   MUT_SPLIT_GATE  mutation: _gate_take is a peek then a separate set (must fail)
 *   MUT_SENT_EARLY  mutation of the 832 fix: mark the row sent when the frame is
 *                handed to the loop, not when a socket took it, and no ring when
 *                the frame finds no socket (must fail)
 *   LEASE        1 = card 886 / F144 wake lease: a connect sync no longer clears
 *                the gate (lease_synced only resets the held-back count); the run
 *                ends the lease with mill wake-done (lease_done), or it lapses
 *                (trail at lease end). Either end sends one trailing POST when the
 *                lease held items back and rows still wait (_send_trailing).
 *                0 = before 886: every connect sync calls gate_clear.
 *   MULTI        1 = a woken run may connect more than once (one connect per
 *                shell call, as routine runs do), then say done or stop;
 *                defaults to LEASE, so LEASE=0 is the model as it was before 886
 *   ONE_RUN      1 = also assert "no new POST while the last lease is held"
 *                (the storm the lease fixes); on by default with LEASE
 *   MUT_DONE_ANY mutation of the lease: wake-done never sends the trailing POST
 *                (must fail delivery)
 *   HOLD1        1 = card 887 / F144a: post_desk checks for a live lease and records
 *                the held-back item in one lock hold (_coalesced -> _hold_locked),
 *                and the take is the same single hold (_coalesced take=True: record
 *                under a lease that started meanwhile, else start one). 0 = the
 *                #216 order: peek, release, then record in a later hold.
 *   TOKEN        1 = card 888 / F144b: every lease has a token (wake.lease, _EPOCH);
 *                the run says mill wake-done --lease TOKEN, and a token that is not
 *                the current lease's ends nothing (stale). 0 = no token (an older
 *                client): the done ends whatever lease is current.
 *                The take's token rides on its POST (wake_body lease=); a 2xx
 *                hands that token to the run it starts (pend), so a run picked
 *                up after a newer lease began still holds its own, older token.
 *   MUT_RUN_CURRENT  mutation of card 888: the run binds the lease current when
 *                it starts, not the token its POST carried (must fail L01)
 *   LAPSE_FIRING 1 = card 890: the lease may lapse while its POSTs are still in
 *                flight (a slow or hung receiver, or a short wake_lease_s), so a
 *                newer lease can start before the older POST returns. 0 (default)
 *                = a lease always outlives its POSTs (900 s against at most 16 s).
 *                With it, the token a run holds and the lease that woke it are
 *                kept apart (pend carries both), so a token read late is seen.
 *   MUT_LATE_TOKEN  mutation of card 890: the POST body reads the current lease
 *                token when it is sent, not the token its take returned (must
 *                fail L06)
 */

#ifndef LAPSE_FIRING
#define LAPSE_FIRING 0
#endif
#ifndef N
#define N 2
#endif
#ifndef MAXFAIL
#define MAXFAIL 2
#endif
#ifndef SESSIONS
#define SESSIONS 1
#endif
#ifndef REFUSE
#define REFUSE 0
#endif
#ifndef ATOMIC_EMIT
#define ATOMIC_EMIT 0
#endif
#ifndef RETRY827
#define RETRY827 1
#endif
#ifndef UNREAD
#define UNREAD 1
#endif
#ifndef MAXSKIP
#define MAXSKIP 1
#endif
#ifndef RETRY_UNREAD
#define RETRY_UNREAD 0
#endif
#ifndef DONE_IN_CONNECT
#define DONE_IN_CONNECT 1
#endif
#ifndef SITTING_DONE
#define SITTING_DONE 1
#endif
#ifndef RETRIES
#define RETRIES 2
#endif
#ifndef RECEIPT
#define RECEIPT 0
#endif
#ifndef RESTART
#define RESTART 0
#endif
#ifndef PUTFIRST
#define PUTFIRST 1
#endif
#ifndef RING_ON_LEAVE
#define RING_ON_LEAVE 1
#endif
#ifndef ACK_AFTER_SEND
#define ACK_AFTER_SEND 1
#endif
#ifndef MAXRUNS
#define MAXRUNS 2
#endif
#ifndef LEASE
#define LEASE 1
#endif
#ifndef MULTI
#define MULTI LEASE
#endif
#ifndef ONE_RUN
#define ONE_RUN LEASE
#endif
#ifndef HOLD1
#define HOLD1 LEASE
#endif
#ifndef TOKEN
#define TOKEN LEASE
#endif

#define ALL ((1 << N) - 1)
#define BIT(i) (1 << (i))
#define RINGS(i) (!(RECEIPT && (i) == 0))
#if RECEIPT
#define RINGMASK (ALL & ~1)
#else
#define RINGMASK ALL
#endif
/* #297: items 1..N-1 are letters (a mailbox row, unread until opened); item 0 is
   a hint or a receipt */
#define MAILMASK (ALL & ~1)
#if UNREAD && !defined(MUT_NO_RERING)
#define UNREAD_LEFT (MAILMASK & ~opened)
#else
#define UNREAD_LEFT 0      /* MUT_NO_RERING: letters still need opening, nothing rings or syncs them */
#endif
/* _send_trailing: push rows wait, or (#297) unread mail remains */
#define WAITING (queued != 0 || UNREAD_LEFT != 0)
/* _arm_retry / _queue_drained read only the push queue (rec_push.pending) */
#if RETRY_UNREAD
#define RETRY_WAIT WAITING
#else
#define RETRY_WAIT (queued != 0)
#endif

/* push_queue rows for D: one bit per item (sp_push.sql). */
byte queued = 0;
/* items the desk has received, by live frame or by a sync reply. */
byte dlv = 0;
/* items taken off the queue by a sync whose reply never reached the desk. */
byte lost = 0;
byte created = 0;      /* bitmask of items whose emit finished */
byte sent = 0;         /* rows marked sent (a live frame reached a socket), 832 fix */
byte opened = 0;       /* #297: letters the desk opened (mail.opened set) */
byte skips = 0;        /* #297: leaves without opening, bounded by MAXSKIP */
/* ghost (#322): a trailing POST from wake-done went out while the run's own
   connect still sat */
bool dup_done = false;

/* wake.py _GATE / _TRAIL, kept in wall memory. */
byte gate_ep = 0;      /* the window's start time, as an epoch number; 0 = none */
bool gate_exp = false; /* the lease (lease_s(), 900 s) has run out since gate_ep */
byte ep_ctr = 0;
byte trail = 0;        /* _TRAIL[D]["at"]: the window a trailing POST belongs to */
byte firing = 0;       /* _fire calls in flight (<= 2 x 8 s each, far shorter than the window) */
/* ghost for "one wake per window": true once the last wake's window ran out
   or D connected (LEASE: once the lease ended by done or timeout).
   A new wake (a gate take) must find it true. */
bool since_ok = true;
/* ghost for "one woken run at a time": true once the last lease ended by
   wake-done or timeout. A connect never sets it, in either design. */
bool run_ok = true;
/* ghost: a wake-done ended a lease that was not the one its run was woken by */
bool stale_done = false;

/* the receiver (the routine behind the webhook URL) */
byte cf = 0;           /* POSTs failed in a row */
/* woken runs that have not connected yet, each with the lease token its POST
   carried (FIFO: runs start in POST order) */
#if LAPSE_FIRING
/* card 890: (token the POST body carried, ghost: the lease its take started) */
chan pend = [MAXRUNS] of { byte, byte };
#define PEND_PUT(c, t) pend!c,t
#define PEND_GET(c, t) pend?c,t
#else
chan pend = [MAXRUNS] of { byte };
#define PEND_PUT(c, t) pend!c
#define PEND_GET(c, t) pend?c; t = c
#endif
#ifdef MUT_LATE_TOKEN
#define SENT_TK(t) (gate_ep)     /* the lease current when the body is sent */
#else
#define SENT_TK(t) (t)           /* wake_body(lease=...) from the take */
#endif
byte posts = 0;        /* every POST attempted, for the record */

/* card 827 (#300): the retry chain */
bool chain = false;
byte chain_left = 0;
byte chain_gen = 0;    /* which failed wake the chain belongs to (see Retrier) */
byte chain_tk = 0;     /* the lease token its retries carry (same idem, same body) */

/* Hub.rooms[D]: which sessions sit; closed = kicked by a newer connect */
bool seat[SESSIONS];
bool closed[SESSIONS];
byte infl[SESSIONS];   /* rows a session took and has not yet sent */

bool restarted = false;

#define SITTING (seat[0] || (SESSIONS > 1 && seat[SESSIONS-1]))
#define GATE_OPEN (gate_ep == 0 || gate_exp)
/* a run's token matters only to wake-done (LEASE); without it every run
   carries 0, which keeps the pre-886 searches (W14-W16, W19, W22, W24) small */
#if LEASE
#define RUNTK(t) (t)
#else
#define RUNTK(t) 0
#endif

/* One HTTP POST (wake.py _post_status). The receiver may fail it while the
   loss bound allows; success is always possible. A 2xx starts one run. */
inline post(ok, tk) {
  posts++;
  if
  :: cf < MAXFAIL -> cf++; ok = false
  :: atomic { true -> cf = 0; ok = true; if :: nfull(pend) -> PEND_PUT(RUNTK(SENT_TK(tk)), RUNTK(tk)) :: full(pend) -> skip fi;
#if RETRY827
              chain = false        /* _wake_ok: a later success stops every older retry */
#endif
            }
  fi
}

/* RETRY827 (#300): post_desk and each retry POST once (_post_status).
   Before #300, wake.py _fire: POST once; a body with idem retries a failure
   once, at once, with no delay. */
inline fire(ok, tk) {
  post(ok, tk);
#if !RETRY827
  if
  :: !ok -> post(ok, tk)
  :: else -> skip
  fi
#endif
}

/* wake.py _coalesced: the first item held back in a window schedules the
   window-end check; at is _GATE[D] read under the lock (None -> nothing). */
inline coalesce() {
  atomic {
    if
    :: gate_ep != 0 && trail != gate_ep -> trail = gate_ep
    :: else -> skip
    fi
  }
}

/* wake.py post_desk, from the peek on. Steps between atomics interleave. */
inline post_desk(ok, took, tk) {
  took = false;
#if HOLD1 && !defined(MUT_SPLIT_GATE)
  /* _coalesced(take=False): live lease -> record the item in the same hold */
  if
  :: atomic { !GATE_OPEN -> if :: trail != gate_ep -> trail = gate_ep :: else -> skip fi }
  :: atomic { GATE_OPEN -> skip };
     /* check_url + public_host assumed to pass: an armed, valid URL */
     atomic {                     /* _coalesced(take=True): record, or start a lease */
       if
       :: !GATE_OPEN -> if :: trail != gate_ep -> trail = gate_ep :: else -> skip fi
       :: GATE_OPEN -> ep_ctr++; gate_ep = ep_ctr; gate_exp = false; took = true; tk = gate_ep;
                       assert(since_ok); since_ok = false;
                       assert(!ONE_RUN || run_ok); run_ok = false;
                       firing++
       fi
     };
     if
     :: took ->
        fire(ok, tk);
        atomic {
          firing--;
#if RETRY827
          if :: !ok && RETRY_WAIT -> chain = true; chain_left = RETRIES; chain_gen++; chain_tk = tk :: else -> skip fi
#endif
        }
     :: else -> skip
     fi
  fi
#else
  if
  :: atomic { !GATE_OPEN -> skip }; coalesce()                    /* 620-624 */
  :: atomic { GATE_OPEN -> skip };                                 /* peek open */
     /* check_url + public_host (625-632) assumed to pass: an armed, valid URL */
#ifdef MUT_SPLIT_GATE
     if :: GATE_OPEN -> skip :: else -> goto coal fi;
     atomic { ep_ctr++; gate_ep = ep_ctr; gate_exp = false; took = true; tk = gate_ep;
              assert(since_ok); since_ok = false;
              assert(!ONE_RUN || run_ok); run_ok = false; firing++ }
#else
     atomic {                                                      /* _gate_take 636 */
       if
       :: GATE_OPEN -> ep_ctr++; gate_ep = ep_ctr; gate_exp = false; took = true; tk = gate_ep;
                       assert(since_ok); since_ok = false;               /* one wake per lease */
                       assert(!ONE_RUN || run_ok); run_ok = false;       /* one run at a time */
                       firing++
       :: else -> skip
       fi
     }
#endif
     if
     :: took ->
        fire(ok, tk);                                               /* 648 */
        atomic {
          firing--;
#if RETRY827
          /* 827: a failed wake starts (or refreshes) the backoff chain */
          if :: !ok && RETRY_WAIT -> chain = true; chain_left = RETRIES; chain_gen++; chain_tk = tk :: else -> skip fi
#endif
        }
     :: else ->
#ifdef MUT_SPLIT_GATE
coal:
#endif
        coalesce()                                                  /* 637-639 */
     fi
  fi
#endif
}

/* 832 fix, push.py ring_waiting: not sitting and a missed row that rings
   waits -> post_desk (window, wake_on and checks as for any wake). */
inline ring_waiting(ok, took, tk) {
  if
  :: atomic { !SITTING && ((queued & ~sent & RINGMASK) != 0 || UNREAD_LEFT != 0) -> skip }; post_desk(ok, took, tk)
  :: else -> skip
  fi
}

/* One letter or hint for D (push.py emit / fanout, outside a request tx). */
proctype Emitter(byte i) {
  bool s, ok, took, got;
  byte tk;
#if ATOMIC_EMIT
  atomic {
#endif
#if PUTFIRST
  atomic { queued = queued | BIT(i) };
#endif
  s = SITTING;                                     /* HUB.rooms read, 565 / 453 */
  if
  :: s ->
     /* _notify_rooms -> Hub.notify -> _broadcast later on the loop: the frame
        reaches whoever sits in the room at send time (176-200). */
#ifdef MUT_SENT_EARLY
     atomic { sent = sent | (queued & BIT(i)) };
#endif
     atomic { if :: SITTING -> dlv = dlv | BIT(i); got = true :: else -> got = false fi };
#if PUTFIRST && RING_ON_LEAVE && !defined(MUT_SENT_EARLY)
     /* _settle_row, off the loop: mark the row sent, or ring when no socket took it */
     if
     :: got -> atomic { sent = sent | (queued & BIT(i)) }
     :: !got -> ring_waiting(ok, took, tk)
     fi
#else
     skip
#endif
  :: !s && RINGS(i) -> post_desk(ok, took, tk)        /* 573-581 / 470-481 */
  :: !s && !RINGS(i) -> skip                       /* a receipt never rings */
  fi;
  /* rec_push.put after the doorbell (587 / 489): the row is queued last. */
#if !PUTFIRST
  atomic { queued = queued | BIT(i); created = created | BIT(i) }
#else
  created = created | BIT(i);
#endif
#if ATOMIC_EMIT
  }
#endif
}

/* wake.py trail: the window-end timer thread (538-567). It fires once the
   window has run out; a stale one (another window took the gate) is a no-op. */
proctype Timer() {
  bool ok, took;
  byte tk;
end_t:
  do
  :: atomic { trail != 0 && trail == gate_ep && gate_exp ->
              trail = 0; gate_ep = 0; gate_exp = false };
#if LEASE
     /* _send_trailing(lease-expired): POST only when rows still wait */
     if
     :: atomic { WAITING -> skip }; post_desk(ok, took, tk)
     :: else -> skip                               /* wake=none reason=drained */
     fi
#else
     post_desk(ok, took, tk)                       /* trailing=True, rows all queued */
#endif
  :: atomic { trail != 0 && trail != gate_ep -> trail = 0 }
  od
}

/* Wall time: a running lease ends lease_s() after it starts. A POST pair takes
   at most 16 s, so a window never ends during the POSTs that opened it. */
proctype Clock() {
end_c:
  do
  :: atomic { gate_ep != 0 && !gate_exp && (LAPSE_FIRING || firing == 0) -> gate_exp = true; since_ok = true; run_ok = true }
  od
}

#if RETRY827
/* Card 827 (#300, live since 0.8.3): retry a failed wake off the request with
   backoff, the same idem key and lease, bounded. Retries are the same wake: they
   take no window. The delay is abstract (some time passes; an hour of retries
   outlives the 900 s lease, which Clock allows between POSTs). Each attempt
   first checks _stopped: the push queue drained ends the chain with no POST; a
   later success elsewhere already ended it (post). */
proctype Retrier() {
  bool ok;
  byte g, tk;
end_r:
  do
  :: atomic { chain && chain_left > 0 && !RETRY_WAIT -> chain = false }   /* _queue_drained */
  :: atomic { chain && chain_left > 0 && RETRY_WAIT -> chain_left--; firing++; g = chain_gen; tk = chain_tk };
     fire(ok, tk);
     /* A retry ends only its own chain. Without the g check (MUT_827_NOGEN),
        a late answer to an old retry cancels the chain of a newer failed wake. */
     atomic { firing--;
#ifdef MUT_827_NOGEN
              if :: ok || chain_left == 0 -> chain = false :: else -> skip fi
#else
              if :: g == chain_gen && (ok || chain_left == 0) -> chain = false :: else -> skip fi
#endif
            }
  od
}
#endif

#if RESTART
/* A wall restart: _GATE, _TRAIL and the timer threads live in memory and are
   gone; push_queue rows survive. Taken only between emits (a restart inside
   an emit is the after_commit gap, not modelled). */
proctype Restart() {
  atomic { firing == 0 && !restarted -> restarted = true;
           gate_ep = 0; gate_exp = false; trail = 0; chain = false }
}
#endif

/* One woken run of D: mill connect D (asgi.py /ws handler). */
inline deliver(s) {
  atomic {
    if
#if ACK_AFTER_SEND
    :: !closed[s] -> dlv = dlv | infl[s] | UNREAD_LEFT; queued = queued & ~infl[s]   /* sent, then ack; #297 merge */
    :: else -> skip                                 /* not sent: rows stay queued */
#else
    :: !closed[s] -> dlv = dlv | infl[s] | UNREAD_LEFT
    :: else -> lost = lost | (infl[s] & ~dlv)      /* rows already deleted */
#endif
    fi;
    infl[s] = 0
  };
#if UNREAD
  /* the run opens (mill mark) the letters it got, or, at most MAXSKIP times in
     all, leaves them unread (a short connect that only drained the push queue) */
  atomic { if :: skips < MAXSKIP -> skips++ :: true -> opened = opened | (dlv & MAILMASK) fi }
#endif
}

#if ACK_AFTER_SEND
#define TAKE(s) infl[s] = queued                  /* peek: read, no delete */
#else
#define TAKE(s) infl[s] = queued; queued = 0      /* mill_push_take */
#endif

/* mill wake-done (rpc _h_wake_done -> wake.lease_done): pop the lease and its
   held-back items under the lock (TOKEN: only when the run's token is the
   current lease's, else stale: nothing ends, no POST); when the popped
   items belong to that lease and rows still wait, one trailing POST. */
inline wake_done(ep, own, ok, took, t, tk, s) {
  atomic {
#if TOKEN
    /* --lease TOKEN: a token that is not the current lease's ends nothing */
    if
    :: gate_ep != ep -> t = false
    :: else ->
#endif
    /* ghost: own is the token this run's POST carried */
    if :: gate_ep != 0 && !gate_exp && gate_ep != own -> stale_done = true :: else -> skip fi;
    t = (trail != 0 && trail == gate_ep);
    gate_ep = 0; gate_exp = false; trail = 0; since_ok = true; run_ok = true
#if TOKEN
    fi
#endif
  };
#ifndef MUT_DONE_ANY
  if
#if SITTING_DONE
  :: atomic { t && SITTING -> skip }                            /* #322: wake=sitting, no POST */
  :: atomic { t && !SITTING && WAITING -> skip }; post_desk(ok, took, tk)   /* _send_trailing */
#else
  :: atomic { t && WAITING -> if :: seat[s] -> dup_done = true :: else -> skip fi };
     post_desk(ok, took, tk)                                    /* _send_trailing */
#endif
  :: else -> skip                                               /* none / drained */
  fi
#else
  skip
#endif
}

proctype Session(byte s) {
  byte o, ep, own, tk;
  bool ok, took, t, dn;
end_s:
  do
  :: atomic { nempty(pend) && !seat[s] -> PEND_GET(ep, own); dn = false;   /* ep = wake.lease from the POST body */
#ifdef MUT_RUN_CURRENT
                ep = gate_ep                 /* the lease current at run start */
#endif
              };
     /* one connect per shell call; MULTI lets the run make more than one */
     do
     :: /* Hub.add: check and sit with no await between (115-155) */
        atomic {
          if
          :: REFUSE && SITTING -> goto refused                      /* 4409, exit 6 */
          :: else ->
             seat[s] = true; closed[s] = false;
             o = 0;
             do
             :: o < SESSIONS -> if :: o != s && seat[o] -> seat[o] = false; closed[o] = true
                                    :: else -> skip fi; o++
             :: o >= SESSIONS -> o = 0; break
             od
          fi
        };
        /* connect_sync_frame: mill_push_take selects and deletes the rows
           (ACK_AFTER_SEND: reads them; deliver deletes them after the send) */
        atomic { TAKE(s) };
#if !LEASE
        /* gate_clear: a new hint may ring again */
        atomic { gate_ep = 0; gate_exp = false; trail = 0; since_ok = true;
#if RETRY827
                 chain = false;
#endif
               };
#endif
        /* LEASE: lease_synced only resets the held-back count (pending_count),
           which no POST decision reads: no model step. */
        /* websocket.send_text(sync frame): fails on a kicked socket */
        deliver(s);
        /* up: it may run commands (each one takes and replies), then it exits */
        do
        :: atomic { !closed[s] -> TAKE(s) }; deliver(s)
#if LEASE && DONE_IN_CONNECT
        :: !dn && !closed[s] -> wake_done(ep, own, ok, took, t, tk, s); dn = true; break   /* done inside the connect */
#endif
        :: break
        od;
        atomic { seat[s] = false; closed[s] = false };              /* Hub.discard */
#if RING_ON_LEAVE
        ring_waiting(ok, took, tk);                                   /* 832: last leave */
#endif
#if MULTI
        if :: dn -> break :: !dn -> skip :: !dn -> break fi           /* another shell call? */
#else
        break
#endif
     od;
#if LEASE
     /* the run's last step: mill wake-done, or none (crash, old client) */
     if :: !dn -> wake_done(ep, own, ok, took, t, tk, s) :: skip fi;
#endif
refused:
     skip
  od
}

init {
  byte k;
  atomic {
    k = 0;
    do :: k < N -> run Emitter(k); k++ :: k >= N -> break od;
    run Timer(); run Clock();
#if RETRY827
    run Retrier();
#endif
#if RESTART
    run Restart();
#endif
    k = 0;
    do :: k < SESSIONS -> run Session(k); k++ :: k >= SESSIONS -> break od
  }
}

/* No item ever taken off the queue without reaching the desk. */
ltl no_loss { [] (lost == 0) }

/* LEASE: a wake-done ends only the lease that woke its own run. */
ltl no_stale_done { [] (!stale_done) }

/* Every item is eventually received by the desk. Checked with weak
   fairness (pan -a -f); the receiver's failures are bounded by MAXFAIL. */
ltl all_delivered { <> (dlv == ALL) }

/* #297: every item reaches the desk and every letter is eventually opened (a
   run leaves letters unread at most MAXSKIP times). */
ltl all_handled { <> (dlv == ALL && (!UNREAD || (opened & MAILMASK) == MAILMASK)) }

/* #322: wake-done never sends its trailing POST while the run's own connect sits. */
ltl no_dup_done { [] (!dup_done) }
