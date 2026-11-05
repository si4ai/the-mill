---- MODULE Wake ----
\* Card 925 (wake slice): code-against-spec for the wake.py / push.py steps
\* the 0.8.0 wake path and verify/spin/wake.pml assume. Sync commit SYNC in
\* run.sh (ce115f8, shipped 0.8.5). Every action cites path:lines a reviewer
\* can open. Guards are CONSTANTS so a mutant cfg can turn one off.
\*
\* This is not a concurrency model (that is verify/spin/wake.pml) and not a
\* scenario suite (that is tests/server/test_wake_*.py). It asks: do the real
\* control-flow guards still implement the transitions those assume?
\*
\* Code at SYNC:
\*   agent_coord/server/wake.py
\*     _send_trailing (695-723), lease_done (770-823),
\*     _queue_drained (971-986), _arm_retry (989-1069),
\*     post_desk retry arm (1170-1174)
\*   agent_coord/server/push.py
\*     ring_waiting unread branch (251-273), desk_sitting (354),
\*     unread_mail_frames (751)

EXTENDS Naturals

CONSTANTS
  MaxSteps,
  GuardRetryPushOnly,     \* post_desk: pending > 0 before _arm_retry (wake.py:1170)
  GuardDrainStopsRetry,   \* _arm_retry pump: _queue_drained stops chain (wake.py:1018)
  GuardTrailingUnread,    \* _send_trailing falls back to unread_mail_frames (wake.py:710-715)
  GuardRingUnread,        \* ring_waiting falls back to unread when push empty (push.py:267-273)
  GuardSittingNoTrail,    \* lease_done: desk_sitting => return "sitting" (wake.py:812-818)
  GuardStaleToken,        \* lease_done: token != _EPOCH => stale (wake.py:788-801)
  GuardRetryOnUnread      \* proposed fix for card 1005: also arm/keep retry while unread
                          \* (FALSE = current code; TRUE = W31 / RETRY_UNREAD=1)

ASSUME MaxSteps \in Nat /\ MaxSteps >= 1
ASSUME GuardRetryPushOnly \in BOOLEAN
ASSUME GuardDrainStopsRetry \in BOOLEAN
ASSUME GuardTrailingUnread \in BOOLEAN
ASSUME GuardRingUnread \in BOOLEAN
ASSUME GuardSittingNoTrail \in BOOLEAN
ASSUME GuardStaleToken \in BOOLEAN
ASSUME GuardRetryOnUnread \in BOOLEAN

\* Outcomes of the last code step (names match wake.py return strings).
Outcomes == {"none", "sent", "error", "stale", "sitting", "coalesced", "armed", "stopped"}

VARIABLES
  pushPending,     \* rec_push.pending(cn, desk) > 0
  unreadLeft,      \* unread_mail_frames nonempty
  leaseLive,       \* _GATE has an entry for the desk
  leaseToken,      \* current _EPOCH token (0 = none, 1 = live token)
  sitting,         \* desk_sitting(desk)
  retryArmed,      \* an _arm_retry chain is alive
  lastOut,         \* last step's outcome string
  lastStep,        \* which action committed
  armedWithoutPush, \* TRUE if a retry armed with pushPending=FALSE (mutant / finding)
  lostUnread,      \* TRUE when unread-only wake failed and nothing retried (card 1005)
  steps

vars == <<pushPending, unreadLeft, leaseLive, leaseToken, sitting,
          retryArmed, lastOut, lastStep, armedWithoutPush, lostUnread, steps>>

TypeOK ==
  /\ pushPending \in BOOLEAN
  /\ unreadLeft \in BOOLEAN
  /\ leaseLive \in BOOLEAN
  /\ leaseToken \in 0..1
  /\ sitting \in BOOLEAN
  /\ retryArmed \in BOOLEAN
  /\ lastOut \in Outcomes
  /\ lastStep \in {"init", "post_ok", "post_fail", "arm", "drain_stop",
                   "trail", "ring", "done", "done_stale", "done_sit", "term"}
  /\ armedWithoutPush \in BOOLEAN
  /\ lostUnread \in BOOLEAN
  /\ steps \in Nat

Room == steps < MaxSteps

Init ==
  /\ pushPending = FALSE
  /\ unreadLeft = FALSE
  /\ leaseLive = FALSE
  /\ leaseToken = 0
  /\ sitting = FALSE
  /\ retryArmed = FALSE
  /\ lastOut = "none"
  /\ lastStep = "init"
  /\ armedWithoutPush = FALSE
  /\ lostUnread = FALSE
  /\ steps = 0

\* ---- environment: letters arrive / are opened / desk sits ----

ArrivePush ==
  /\ Room
  /\ pushPending' = TRUE
  /\ lastStep' = "init"
  /\ lastOut' = "none"
  /\ steps' = steps + 1
  /\ UNCHANGED <<unreadLeft, leaseLive, leaseToken, sitting, retryArmed,
                 armedWithoutPush, lostUnread>>

ArriveUnread ==
  /\ Room
  /\ unreadLeft' = TRUE
  /\ lastStep' = "init"
  /\ lastOut' = "none"
  /\ steps' = steps + 1
  /\ UNCHANGED <<pushPending, leaseLive, leaseToken, sitting, retryArmed,
                 armedWithoutPush, lostUnread>>

OpenMail ==
  /\ Room /\ unreadLeft
  /\ unreadLeft' = FALSE
  /\ lastStep' = "init"
  /\ lastOut' = "none"
  /\ steps' = steps + 1
  /\ UNCHANGED <<pushPending, leaseLive, leaseToken, sitting, retryArmed,
                 armedWithoutPush, lostUnread>>

Sit ==
  /\ Room
  /\ sitting' = TRUE
  /\ lastStep' = "init"
  /\ lastOut' = "none"
  /\ steps' = steps + 1
  /\ UNCHANGED <<pushPending, unreadLeft, leaseLive, leaseToken, retryArmed,
                 armedWithoutPush, lostUnread>>

Leave ==
  /\ Room /\ sitting
  /\ sitting' = FALSE
  /\ lastStep' = "init"
  /\ lastOut' = "none"
  /\ steps' = steps + 1
  /\ UNCHANGED <<pushPending, unreadLeft, leaseLive, leaseToken, retryArmed,
                 armedWithoutPush, lostUnread>>

DrainPush ==
  /\ Room /\ pushPending
  /\ pushPending' = FALSE
  /\ lastStep' = "init"
  /\ lastOut' = "none"
  /\ steps' = steps + 1
  /\ UNCHANGED <<unreadLeft, leaseLive, leaseToken, sitting, retryArmed,
                 armedWithoutPush, lostUnread>>

\* ---- post_desk take + POST (wake.py:1132-1174) ----

\* Successful wake: takes lease, clears retry need.
PostOk ==
  /\ Room /\ ~sitting
  /\ \/ pushPending \/ unreadLeft
  /\ leaseLive' = TRUE
  /\ leaseToken' = 1
  /\ retryArmed' = FALSE
  /\ lastOut' = "sent"
  /\ lastStep' = "post_ok"
  /\ armedWithoutPush' = FALSE
  /\ lostUnread' = FALSE
  /\ steps' = steps + 1
  /\ UNCHANGED <<pushPending, unreadLeft, sitting>>

\* Failed wake. Arms retry only when the code's guard allows.
\* code: wake.py:1170 `if pending > 0 and _retryable(status) ...`
\* proposed: also when unreadLeft (GuardRetryOnUnread, card 1005 / W31).
PostFail ==
  /\ Room /\ ~sitting
  /\ \/ pushPending \/ unreadLeft
  /\ leaseLive' = TRUE
  /\ leaseToken' = 1
  /\ LET mayArm ==
         IF GuardRetryOnUnread
         THEN (pushPending \/ unreadLeft)
         ELSE IF GuardRetryPushOnly THEN pushPending ELSE TRUE
     IN
       /\ retryArmed' = mayArm
       /\ armedWithoutPush' = (mayArm /\ ~pushPending)
       /\ lostUnread' = (~mayArm /\ unreadLeft /\ ~pushPending)
       /\ lastOut' = IF mayArm THEN "armed" ELSE "error"
       /\ lastStep' = "post_fail"
       /\ steps' = steps + 1
       /\ UNCHANGED <<pushPending, unreadLeft, sitting>>

\* ---- _arm_retry stop on drain (wake.py:1018) ----

DrainStopsRetry ==
  /\ Room /\ retryArmed
  /\ ~pushPending
  /\ IF GuardDrainStopsRetry
     THEN IF GuardRetryOnUnread /\ unreadLeft
          THEN /\ retryArmed' = TRUE
               /\ lastOut' = "armed"
               /\ lastStep' = "drain_stop"
               /\ steps' = steps + 1
               /\ UNCHANGED <<pushPending, unreadLeft, leaseLive, leaseToken,
                              sitting, armedWithoutPush, lostUnread>>
          ELSE /\ retryArmed' = FALSE
               /\ lastOut' = "stopped"
               /\ lastStep' = "drain_stop"
               /\ steps' = steps + 1
               /\ UNCHANGED <<pushPending, unreadLeft, leaseLive, leaseToken,
                              sitting, armedWithoutPush, lostUnread>>
     ELSE /\ UNCHANGED <<retryArmed, pushPending, unreadLeft, leaseLive,
                         leaseToken, sitting, armedWithoutPush, lostUnread>>
          /\ lastOut' = "armed"
          /\ lastStep' = "drain_stop"
          /\ steps' = steps + 1

\* ---- _send_trailing (wake.py:695-723) ----

Trail ==
  /\ Room /\ leaseLive
  /\ ~sitting   \* sitting path is DoneSitting
  /\ LET hasWork ==
         IF pushPending THEN TRUE
         ELSE IF GuardTrailingUnread THEN unreadLeft ELSE FALSE
     IN
       /\ IF hasWork
          THEN /\ lastOut' = "sent"
               /\ lastStep' = "trail"
               /\ leaseLive' = FALSE
               /\ leaseToken' = 0
               /\ retryArmed' = FALSE
               /\ lostUnread' = FALSE
               /\ steps' = steps + 1
               /\ UNCHANGED <<pushPending, unreadLeft, sitting, armedWithoutPush>>
          ELSE /\ lastOut' = "none"
               /\ lastStep' = "trail"
               /\ leaseLive' = FALSE
               /\ leaseToken' = 0
               /\ steps' = steps + 1
               /\ UNCHANGED <<pushPending, unreadLeft, sitting, retryArmed,
                              armedWithoutPush, lostUnread>>

\* ---- ring_waiting unread fallback (push.py:251-273) ----

Ring ==
  /\ Room /\ ~sitting /\ ~leaseLive
  /\ (pushPending \/ unreadLeft)
  /\ LET hasWork ==
         IF pushPending THEN TRUE
         ELSE IF GuardRingUnread THEN unreadLeft ELSE FALSE
     IN
       /\ IF hasWork
          THEN /\ leaseLive' = TRUE
               /\ leaseToken' = 1
               /\ lastOut' = "sent"
               /\ lastStep' = "ring"
               /\ lostUnread' = FALSE
               /\ steps' = steps + 1
               /\ UNCHANGED <<pushPending, unreadLeft, sitting, retryArmed, armedWithoutPush>>
          ELSE /\ lastOut' = "none"
               /\ lastStep' = "ring"
               /\ steps' = steps + 1
               /\ UNCHANGED <<pushPending, unreadLeft, leaseLive, leaseToken,
                              sitting, retryArmed, armedWithoutPush, lostUnread>>

\* ---- lease_done (wake.py:770-823) ----

DoneOk ==
  /\ Room /\ leaseLive
  /\ ~sitting
  /\ leaseLive' = FALSE
  /\ leaseToken' = 0
  /\ lastStep' = "done"
  /\ LET hasWork ==
         IF pushPending THEN TRUE
         ELSE IF GuardTrailingUnread THEN unreadLeft ELSE FALSE
     IN
       /\ lastOut' = IF hasWork THEN "sent" ELSE "none"
       /\ lostUnread' = IF hasWork THEN FALSE ELSE lostUnread
       /\ retryArmed' = FALSE
       /\ steps' = steps + 1
       /\ UNCHANGED <<pushPending, unreadLeft, sitting, armedWithoutPush>>

DoneSitting ==
  /\ Room /\ leaseLive /\ sitting
  /\ IF GuardSittingNoTrail
     THEN /\ lastOut' = "sitting"
          /\ lastStep' = "done_sit"
          /\ leaseLive' = FALSE
          /\ leaseToken' = 0
          /\ retryArmed' = FALSE
          /\ steps' = steps + 1
          /\ UNCHANGED <<pushPending, unreadLeft, sitting, armedWithoutPush, lostUnread>>
     ELSE \* mutant: trailing POST goes out to a sitting desk
          /\ lastOut' = "sent"
          /\ lastStep' = "done_sit"
          /\ leaseLive' = FALSE
          /\ leaseToken' = 0
          /\ retryArmed' = FALSE
          /\ steps' = steps + 1
          /\ UNCHANGED <<pushPending, unreadLeft, sitting, armedWithoutPush, lostUnread>>

\* Stale done: caller passes a token that is not the current lease's.
\* code: wake.py:788-801. Modelled as an action that fires only when
\* GuardStaleToken is off (mutant), or as a no-op end when on.
DoneStale ==
  /\ Room /\ leaseLive /\ leaseToken = 1
  /\ IF GuardStaleToken
     THEN /\ lastOut' = "stale"
          /\ lastStep' = "done_stale"
          /\ steps' = steps + 1
          /\ UNCHANGED <<pushPending, unreadLeft, leaseLive, leaseToken,
                         sitting, retryArmed, armedWithoutPush, lostUnread>>
     ELSE \* mutant: stale token ends the current lease
          /\ lastOut' = "none"
          /\ lastStep' = "done_stale"
          /\ leaseLive' = FALSE
          /\ leaseToken' = 0
          /\ retryArmed' = FALSE
          /\ steps' = steps + 1
          /\ UNCHANGED <<pushPending, unreadLeft, sitting, armedWithoutPush, lostUnread>>

Term ==
  /\ steps >= MaxSteps
  /\ UNCHANGED vars

Next ==
  \/ ArrivePush \/ ArriveUnread \/ OpenMail \/ Sit \/ Leave \/ DrainPush
  \/ PostOk \/ PostFail
  \/ DrainStopsRetry
  \/ Trail \/ Ring
  \/ DoneOk \/ DoneSitting \/ DoneStale
  \/ Term

Spec == Init /\ [][Next]_vars

\* ---- properties (plain sentences in README / SKILL) ----

\* A retry is armed only when push rows wait (wake.py:1170), unless the
\* proposed unread fix is on. Mutant: GuardRetryPushOnly=FALSE.
RetryArmRequiresPushPending ==
  (lastStep = "post_fail" /\ lastOut = "armed" /\ ~GuardRetryOnUnread)
    => pushPending

\* No retry is armed with an empty push queue under current code.
NeverArmedWithoutPush ==
  GuardRetryOnUnread \/ ~armedWithoutPush

\* _queue_drained stops a retry when push is empty and (under current code)
\* unread is ignored. Mutant: GuardDrainStopsRetry=FALSE leaves it armed.
DrainStopsWhenPushEmpty ==
  (lastStep = "drain_stop" /\ ~GuardRetryOnUnread /\ ~pushPending)
    => (lastOut = "stopped" /\ ~retryArmed)

\* Trailing wake still fires when push is empty but unread remains.
\* Mutant: GuardTrailingUnread=FALSE.
TrailingFallsBackToUnread ==
  (lastStep = "trail" /\ ~pushPending /\ unreadLeft)
    => (lastOut = "sent")

\* Ring-on-leave still fires on unread alone.
\* Mutant: GuardRingUnread=FALSE (action disabled when push empty).
RingFallsBackToUnread ==
  (lastStep = "ring" /\ ~pushPending /\ unreadLeft)
    => (lastOut = "sent")

\* wake-done inside a sitting connect sends no trailing POST (#322).
\* Mutant: GuardSittingNoTrail=FALSE.
SittingDoneSendsNoTrailing ==
  (lastStep = "done_sit") => (lastOut = "sitting")

\* A wake-done with a stale token ends nothing (F144b).
\* Mutant: GuardStaleToken=FALSE.
StaleTokenEndsNothing ==
  (lastStep = "done_stale") => (lastOut = "stale" /\ leaseLive)

\* Desired delivery (card 1005 / W31): a failed unread-only wake is retried.
\* Current code (GuardRetryOnUnread=FALSE) violates this; kept as a known
\* finding, not weakened. Run under known/card_1005.cfg expecting a break.
UnreadAloneFailedWakeIsRetried ==
  ~lostUnread

====
