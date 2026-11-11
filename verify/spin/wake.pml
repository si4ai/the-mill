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
 *   MUT_SIT_NOGUARD mutation of #322: drop the sitting guard, so wake-done sends
 *                the trailing POST even while the run's own connect sits (must fail)
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

#ifndef LIVE
#define LIVE 0
#endif
#if LIVE
/*
 * LIVE: the wake path as main 8bae076 runs it today, cut down to the four
 * failure modes seen live (card 1144): F1 exit ring, F2 seat-free delay,
 * F7 self-ring loop, and the wasted-wake counter. (F3, sync read after a
 * drop, is in holds.pml.) The model above this block is pinned at SYNC;
 * this block reads main and has its own switches. One desk D, armed with a
 * webhook; a perfect receiver (POST failures and #300 retries are W08-W17's).
 *
 * Code read (main 8bae076; on ec280da, #416, wake.py lines after 520 move
 * down by 2 and TW_GUARD=1 is the change):
 *   push.py      emit (641-715) and fanout (541-579): put as queued, sitting
 *                read, live notify or mark missed then post_desk; Hub.add
 *                refuse (106-146); Hub.discard (148-167): the last socket out
 *                rings ring_waiting off the loop; _broadcast (169-197) and
 *                _settle_row (226-240): a frame no socket took marks the row
 *                missed and rings; ring_waiting (253-291): not sitting, and a
 *                waiting() row (state missed/error/retry_armed) or unread mail
 *   records/push.py  pending (324-338): every row with state <> 'taken',
 *                'sent' rows included; waiting (277-282, 305-321)
 *   wake.py      post_desk (1355-1555): the empty skip (1403-1421) is skipped
 *                for a frame with watch_id (a tw.event); no sitting read of
 *                its own; _coalesced, then _hold_or_take (694-710);
 *                mark_lease on a 2xx (1490-1514); lease_done (805-866):
 *                stale token ends nothing and stamps nothing, a live token
 *                pops the lease, calls finish_lease, and sends the trailing
 *                POST only when not sitting; trail (761-790) and
 *                _send_trailing (729-758): pending() > 0 or unread mail
 *   wasted_wake.py  mark_lease (105-132) overwrites the desk's tracker with
 *                no stamp; note_rpc (155-171) marks the desk's live tracker
 *                acted for any action command of the desk; finish_lease
 *                (185-) is called only from lease_done
 *   api/mill/rpc.py  _h_tw_event (4311-4375): a tw exit, stall, match or
 *                crash calls post_desk after commit, unless the hop says
 *                wake=False (tw never sets it: client/tw/proc.py 597-617);
 *                _poke (217-231): the acting desk gets no hint for its own
 *                change (skip_desk)
 *   asgi.py      ws_endpoint (579-707): a refused add closes 4409 and returns
 *                before the try whose finally calls HUB.discard (633-643)
 *   client/ws.py card 834: connect refuses by default (__main__.py 1072-1101);
 *                a first 4409 is retried after 1 s and 2 s (BUSY_SETTLE_S,
 *                785-786, 1474-1480), then busy, exit 0, no wake
 *   client/tw/link.py  the hop is sent by the sit link inside a live connect
 *                (sender loop 480-492); a hop not sent stays in the outbox
 *                for the next connect
 *
 * Switches (0 = the code on main):
 *   N            items from other desks (item 0 a hint, items 1.. letters)
 *   WK           finite connects of the desk's own working session (not woken)
 *   TW           1 = connects run tw-wrapped commands; each exit hop rings
 *                post_desk as the code does
 *   HMAX         tw exit hops waiting in the outbox at once
 *   ZOMBIE       1 = a connect's exit and the office's Hub.discard are two
 *                steps: between them the seat is held by a socket whose
 *                process is gone (the seat-free window)
 *   ZOMBIE_SEND_OK 1 = a live frame sent into that window may return without
 *                error, so the row is marked sent though no desk got it
 *                (unclear in the code: depends on when starlette sees the
 *                close)
 *   SETTLE_OWN   proposed: a refused connect retries while the holder is this
 *                desk's own exited connect (the window), so it is never busy
 *                on itself
 *   TW_GUARD     #416 (card 1141, main ec280da): a tw exit or crash goes through
 *                post_desk's empty skip (wake.py 520-521, 1407); stall and match
 *                stay exempt (not modelled: they are mid-run alerts)
 *   PENDING_OWED proposed: the empty skip and the trailing POST count only
 *                rows not handed over live (not state 'sent')
 *   WASTE_FIX    proposed: a lapsed lease is stamped too, and only the run
 *                that holds the lease's token marks it acted
 *   SKIP_TAKE_ATOMIC proposed: _hold_or_take re-reads the empty check under the
 *                gate lock, so work another run handled between the check
 *                (1407-1425) and the take is not woken for again
 *   MUT_NO_EMPTY_SKIP  mutation: no empty skip in post_desk and no waiting
 *                check in ring_waiting (keeps F1 from being vacuous)
 *   MUT_SIT_NOGUARD    mutation of #889: wake-done sends its trailing POST
 *                while another connect sits
 *   MUT_NO_LEAVE_RING  mutation of #832: Hub.discard does not ring
 *   MUT_TRAIL_ANY      mutation: wake-done sends its trailing POST with nothing
 *                waiting (with MUT_NO_EMPTY_SKIP: keeps no_busy_ring from being vacuous)
 */
#ifndef N
#define N 2
#endif
#ifndef WK
#define WK 2
#endif
#ifndef TW
#define TW 0
#endif
#ifndef HMAX
#define HMAX 1
#endif
#ifndef ZOMBIE
#define ZOMBIE 0
#endif
#ifndef ZOMBIE_SEND_OK
#define ZOMBIE_SEND_OK 0
#endif
#ifndef SETTLE_OWN
#define SETTLE_OWN 0
#endif
#ifndef TW_GUARD
#define TW_GUARD 0
#endif
#ifndef PENDING_OWED
#define PENDING_OWED 0
#endif
#ifndef WASTE_FIX
#define WASTE_FIX 0
#endif
#ifndef SKIP_TAKE_ATOMIC
#define SKIP_TAKE_ATOMIC 0
#endif
#ifndef MAXSKIP
#define MAXSKIP 1
#endif
#ifndef TRACK
#define TRACK 0       /* 1: keep the wasted_wake tracker (wake_counted) */
#endif
#ifndef SELFG
#define SELFG 0       /* 1: keep the self-wake ghosts (no_self_wake, no_self_loop) */
#endif

#define ALL ((1 << N) - 1)
#define BIT(i) (1 << (i))
#define MAILMASK (ALL & ~1)

byte queued = 0;   /* wake rows with state <> 'taken' (records/push.py pending) */
byte missed = 0;   /* of those, rows marked missed (owed): waiting() */
byte sentm = 0;    /* of those, rows marked sent: a live frame went out */
byte dlv = 0;      /* items the desk got, live or by a sync */
byte mbox = 0;     /* letters in the mailbox (unread until opened) */
byte opened = 0;
byte skips = 0;

#define UNREAD_LEFT (mbox & ~opened)
/* counts_as_waiting (mail_push.py 135-143) and _send_trailing: pending() > 0 or unread */
#if PENDING_OWED
#define WAITING (((queued & ~sentm) != 0) || UNREAD_LEFT != 0)
#else
#define WAITING (queued != 0 || UNREAD_LEFT != 0)
#endif
/* ring_waiting: a waiting() row or unread mail */
#define OWED (((queued & missed) != 0) || UNREAD_LEFT != 0)
/* ghost: work from other desks the desk has not got or not opened */
#define OUTSIDE (((queued & ~dlv) != 0) || UNREAD_LEFT != 0)

/* wake.py _GATE / _EPOCH / _TRAIL (one desk); tokens cycle 1..3 (the code's are uuids) */
byte gate_ep = 0;
byte ep_ctr = 0;
bool held = false;       /* _TRAIL for the live lease */
bool held_self = false;  /* ghost: every item it held back was the desk's own */
byte firing = 0;
chan pend = [2] of { byte };
byte selfmask = 0;       /* ghost: leases a self trigger started, by token */

/* wasted_wake._leases[D] */
bool tr_live = false;
bool tr_acted = false;
bool tr_run = false;     /* ghost: the run that holds the lease acted */
byte tr_tok = 0;

/* Hub.rooms[D]: slots 0 and 1 are the working session's connects (it
   alternates, so a new connect can start while the last one's socket is
   still in the room), slot 2 the woken run */
bool seat[3];
bool gone[3];            /* the client process exited; the office has not seen it */
byte hops = 0;           /* tw exit hops in the outbox */
bool hop_sl = false;     /* ghost: the hop came from a run a self wake started */

#define SITTING (seat[0] || seat[1] || seat[2])
#define LIVE_ANY ((seat[0] && !gone[0]) || (seat[1] && !gone[1]) || (seat[2] && !gone[2]))
#define OTHER_SEAT(i) ((i != 0 && seat[0]) || (i != 1 && seat[1]) || (i != 2 && seat[2]))
#define OTHER_LIVE(i) ((i != 0 && seat[0] && !gone[0]) || (i != 1 && seat[1] && !gone[1]) || (i != 2 && seat[2] && !gone[2]))

/* ghosts for the properties */
bool empty_wake = false;  /* F1: a wake went out whose trigger found nothing waiting */
bool self_wake = false;   /* F7: a wake started by the desk's own step, no outside work */
bool self_loop = false;   /* F7: a run that a self wake started starts another */
bool miscount = false;    /* F1: a wake the wasted counter misses or credits to another connect */
bool self_busy = false;   /* F2: a connect refused busy by the desk's own exited connect */
bool busy_ring = false;   /* F2: a refused (busy) run rings a wake with nothing waiting */

#ifdef MUT_NO_EMPTY_SKIP
#define SKIP_PASS(tw) true
#else
#define SKIP_PASS(tw) ((tw && !TW_GUARD) || WAITING)
#endif

/* _hold_locked: record an item under the live lease */
#define HOLD_ITEM held_self = (held -> held_self : true) && sf; held = true

/* post_desk from the empty skip on. The caller sets its locals e (the trigger
   found nothing waiting), sf (a self trigger, no outside work), sl (the caller
   is a run a self wake started), br (the caller is a refused run). */
inline post_desk(tw, tk) {
  if
  :: atomic { SKIP_PASS(tw) -> e = !WAITING };                 /* 1403-1421; e: it found nothing waiting */
     if
     :: atomic { gate_ep != 0 -> HOLD_ITEM }                   /* _coalesced */
     :: atomic { gate_ep == 0 -> skip };
        atomic {                                               /* _hold_or_take(take=True) */
          if
          :: gate_ep != 0 -> HOLD_ITEM; tk = 0
          :: gate_ep == 0 && SKIP_TAKE_ATOMIC && !SKIP_PASS(tw) -> tk = 0   /* proposed: re-check under the lock */
          :: gate_ep == 0 && !(SKIP_TAKE_ATOMIC && !SKIP_PASS(tw)) -> ep_ctr = ep_ctr % 3 + 1; gate_ep = ep_ctr; tk = gate_ep;
                     held = false; held_self = false; firing++;
                     if :: e -> empty_wake = true :: else -> skip fi;
#if SELFG
                     if :: sf && !OUTSIDE -> self_wake = true;   /* still no outside work at the take */ selfmask = selfmask | BIT(tk);
                               if :: sl -> self_loop = true :: else -> skip fi
                        :: else -> selfmask = selfmask & ~BIT(tk) fi;
#endif
                     if :: br && e -> busy_ring = true :: else -> skip fi
          fi
        };
        if
        :: tk != 0 ->
           atomic {                                            /* 2xx: a run starts; mark_lease */
             if :: nfull(pend) -> pend!tk :: full(pend) -> skip fi;
#if TRACK
             if :: tr_live -> miscount = true :: else -> skip fi;   /* overwritten, never stamped */
             tr_live = true; tr_acted = false; tr_run = false; tr_tok = tk;
#endif
             firing--
           }
        :: else -> skip
        fi
     fi
  :: atomic { !SKIP_PASS(tw) -> skip }                         /* skipped reason=empty */
  fi
}

/* push.py ring_waiting, for the desk's own leave (or a frame no socket took) */
inline ring_waiting(own, tk) {
  if
#ifdef MUT_NO_EMPTY_SKIP
  :: atomic { !SITTING -> e = !WAITING; sf = own && !OUTSIDE };
#else
  :: atomic { !SITTING && OWED -> e = !WAITING; sf = own && !OUTSIDE };
#endif
     post_desk(false, tk)
  :: else -> skip
  fi
}

/* Hub.add with refuse (the default since card 834). A refusal closes 4409 and
   returns: no discard, no ring (asgi.py 637-643). */
inline sit(i, refused) {
  atomic {
    !seat[i] && !(SETTLE_OWN && OTHER_SEAT(i) && !OTHER_LIVE(i)) ->
    if
    :: OTHER_SEAT(i) -> refused = true;
       if :: !OTHER_LIVE(i) -> self_busy = true :: else -> skip fi
    :: else -> refused = false; seat[i] = true; gone[i] = false
    fi
  }
}

/* connect_sync_frame(hold=True), send, ack: every row not taken, plus unread mail */
inline sync_open() {
  atomic { dlv = dlv | queued | UNREAD_LEFT; queued = 0; missed = 0; sentm = 0 };
  atomic { if :: skips < MAXSKIP -> skips++ :: true -> opened = opened | (dlv & mbox) fi }
}

/* the connect exits; the office discards its socket (at once, or later: ZOMBIE) */
inline leave(i, tk) {
#if ZOMBIE
  atomic { gone[i] = true }                                    /* Reaper discards it */
#else
  atomic { seat[i] = false; gone[i] = false };
#ifndef MUT_NO_LEAVE_RING
  ring_waiting(true, tk)
#endif
#endif
}

/* an action command (send, note, hold, drop, ...): note_rpc. The acting desk
   gets no hint of its own change (_poke skip_desk), so no item. */
inline act(mine) {
  atomic {
#if !TRACK
    skip
#elif WASTE_FIX
    if :: tr_live && mine -> tr_acted = true; tr_run = true :: else -> skip fi
#else
    if :: tr_live -> tr_acted = true; if :: mine -> tr_run = true :: else -> skip fi :: else -> skip fi
#endif
  }
}

/* a tw-wrapped command ends inside the connect: its exit hop goes in the outbox */
inline tw_cmd() {
  atomic { TW && hops < HMAX -> hops++;
#if SELFG
    hop_sl = sl
#endif
  }
}

/* One item from another desk (emit / fanout). */
proctype Emitter(byte i) {
  bool s, got, e, sf, sl, br;
  byte tk;
  atomic { queued = queued | BIT(i); if :: i > 0 -> mbox = mbox | BIT(i) :: else -> skip fi };
  s = SITTING;                                                 /* HUB.rooms read */
  if
  :: s ->
     atomic {                                                  /* _broadcast, _settle_row */
       if
       :: LIVE_ANY -> dlv = dlv | BIT(i); sentm = sentm | (queued & BIT(i)); got = true
       :: !LIVE_ANY && SITTING && ZOMBIE_SEND_OK -> sentm = sentm | (queued & BIT(i)); got = true
       :: !LIVE_ANY -> got = false;
          /* send_text raised: the dead sockets are discarded, the row marked missed */
          seat[0] = seat[0] && !gone[0]; seat[1] = seat[1] && !gone[1]; seat[2] = seat[2] && !gone[2];
          gone[0] = gone[0] && seat[0]; gone[1] = gone[1] && seat[1]; gone[2] = gone[2] && seat[2];
          missed = missed | (queued & BIT(i))
       fi
     };
     if :: !got -> ring_waiting(false, tk) :: else -> skip fi
  :: !s ->
     atomic { missed = missed | (queued & BIT(i)); e = false; sf = false };   /* its own row is the work */
     post_desk(false, tk)
  fi
}

/* The office notices a closed socket: Hub.discard, then ring on the last leave. */
#if ZOMBIE
proctype Reaper() {
  bool e, sf, sl, br, lv;
  byte tk, j;
end_reap:
  do
  :: atomic {
       if
       :: seat[0] && gone[0] -> j = 0
       :: seat[1] && gone[1] -> j = 1
       :: seat[2] && gone[2] -> j = 2
       fi;
       seat[j] = false; gone[j] = false; sl = false; br = false
     };
#ifndef MUT_NO_LEAVE_RING
     ring_waiting(true, tk)
#else
     skip
#endif
  od
}
#endif

/* The sit link sends a tw exit hop while a connect is live; the office runs
   _h_tw_event, then post_desk after the commit. */
#if TW
proctype Hop() {
  bool e, sf, sl, br;
  byte tk;
end_hop:
  do
  :: atomic { hops > 0 && LIVE_ANY -> hops--; sl = hop_sl; br = false };
     atomic { e = !WAITING; sf = !OUTSIDE };
     post_desk(true, tk)
  od
}
#endif

/* The lease runs out (wake.py lease_s): trail() when it held items back. */
proctype Clock() {
  bool e, sf, sl, br, h, hs;
  byte tk;
end_clock:
  do
  :: atomic { gate_ep != 0 && firing == 0 -> h = held; hs = held_self; gate_ep = 0; held = false;
              sl = false; br = false;
#if WASTE_FIX && TRACK
              tr_live = false
#else
              skip
#endif
            };
     if
     :: h ->
        if
        :: atomic { WAITING -> e = !WAITING; sf = hs && !OUTSIDE }; post_desk(false, tk)
        :: atomic { !WAITING -> skip }
        fi
     :: else -> skip
     fi
  od
}

/* mill wake-done --lease TOKEN (lease_done) */
inline wake_done(mytk, tk) {
  atomic {
    if
    :: gate_ep != mytk -> t = false                            /* stale: nothing ends, no stamp */
    :: else -> t = held; gate_ep = 0; held = false;
#if TRACK
       if :: tr_live -> if :: tr_acted && !tr_run -> miscount = true :: else -> skip fi; tr_live = false
          :: else -> skip fi                                   /* finish_lease */
#else
       skip
#endif
    fi
  };
  if
#ifdef MUT_SIT_NOGUARD
  :: atomic { t && WAITING -> e = !WAITING; sf = !OUTSIDE }; post_desk(false, tk)
#else
  :: atomic { t && SITTING -> skip }                           /* #889: sitting, no POST */
#ifdef MUT_TRAIL_ANY
  :: atomic { t && !SITTING -> e = !WAITING; sf = !OUTSIDE }; post_desk(false, tk)
#else
  :: atomic { t && !SITTING && WAITING -> e = !WAITING; sf = !OUTSIDE }; post_desk(false, tk)
#endif
#endif
  :: else -> skip
  fi
}

/* The desk's working session: WK finite connects, each in its own shell call. */
proctype Worker() {
  bool e, sf, sl, br, refused;
  byte k, i, tk;
  sl = false; br = false;
  do
  :: k < WK ->
     i = k % 2; k++;
     sit(i, refused);
     if
     :: refused -> skip                                        /* busy, exit 0 */
     :: else ->
        sync_open();
        if :: tw_cmd() :: skip fi;
#if TRACK
        if :: act(false) :: skip fi;                           /* send, note, drop ... */
#endif
        leave(i, tk)
     fi
  :: k >= WK -> break
  od
}

/* A woken run (the routine behind the webhook): one connect, then done or not. */
proctype Run() {
  bool e, sf, sl, br, refused, t, dn;
  byte mytk, tk;
end_run:
  do
  :: atomic { pend?mytk ->
#if SELFG
       sl = ((selfmask & BIT(mytk)) != 0);
#endif
       br = false; dn = false };
     sit(2, refused);
     if
     :: refused -> br = true;                                  /* busy, exit 0 */
        if :: wake_done(mytk, tk) :: skip fi
     :: else ->
        sync_open();
        if :: tw_cmd() :: skip fi;
#if TRACK
        if :: act(true) :: skip fi;
#endif
        if :: wake_done(mytk, tk); dn = true :: skip fi;       /* done inside the connect */
        leave(2, tk);
        if :: !dn -> wake_done(mytk, tk) :: !dn -> skip :: dn -> skip fi
     fi
  od
}

init {
  byte k;
  atomic {
    k = 0;
    do :: k < N -> run Emitter(k); k++ :: k >= N -> break od;
    run Worker(); run Run(); run Clock();
#if ZOMBIE
    run Reaper();
#endif
#if TW
    run Hop();
#endif
  }
}

ltl no_empty_wake { [] !empty_wake }
ltl no_self_wake { [] !self_wake }
ltl no_self_loop { [] !self_loop }
ltl wake_counted { [] !miscount }
ltl no_self_busy { [] !self_busy }
ltl no_busy_ring { [] !busy_ring }
ltl all_handled { <> (dlv == ALL && (opened & MAILMASK) == MAILMASK) }

#else  /* !LIVE: the model pinned at SYNC */


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
#if SITTING_DONE && !defined(MUT_SIT_NOGUARD)
  :: atomic { t && SITTING -> skip }                            /* #322: wake=sitting, no POST */
  :: atomic { t && !SITTING && WAITING -> if :: seat[s] -> dup_done = true :: else -> skip fi };
     post_desk(ok, took, tk)                                    /* _send_trailing */
#elif SITTING_DONE
  /* MUT_SIT_NOGUARD: the #322 sitting guard removed, trailing POST whenever t && WAITING */
  :: atomic { t && WAITING -> if :: seat[s] -> dup_done = true :: else -> skip fi };
     post_desk(ok, took, tk)
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

#endif /* LIVE */
