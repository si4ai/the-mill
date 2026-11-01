---- MODULE Doing ----
\* Card 925 (doing slice): code-against-spec for doing focus/waiting/end guards
\* at SYNC (see run.sh). Liveness and recovery first. Card 1014 anchors.
\*
\* Not verify/spin/doing.pml (D01-D08) and not pytest waiting_818.
\* Code: sp_doing.sql mill_doing_put/finish; sp_join.sql mill_doing_insert.

EXTENDS Naturals

CONSTANTS
  MaxSteps,
  GuardNoSelfWait,
  GuardLiveToken,
  GuardOneInsertPerPut,
  GuardDetectWaitCycle,
  GuardAutoClearStale

ASSUME MaxSteps \in Nat /\ MaxSteps >= 1
ASSUME GuardNoSelfWait \in BOOLEAN
ASSUME GuardLiveToken \in BOOLEAN
ASSUME GuardOneInsertPerPut \in BOOLEAN
ASSUME GuardDetectWaitCycle \in BOOLEAN
ASSUME GuardAutoClearStale \in BOOLEAN

VARIABLES
  focus1, focus2,
  wait1, wait2,
  ended1, ended2,
  live1, live2,
  inserts,
  lastOut, lastStep, lastActor,
  age1, age2, steps

vars == <<focus1, focus2, wait1, wait2, ended1, ended2, live1, live2,
          inserts, lastOut, lastStep, lastActor, age1, age2, steps>>

TypeOK ==
  /\ focus1 \in 0..1 /\ focus2 \in 0..1
  /\ wait1 \in {0, 1, 2} /\ wait2 \in {0, 1, 2}
  /\ ended1 \in BOOLEAN /\ ended2 \in BOOLEAN
  /\ live1 \in BOOLEAN /\ live2 \in BOOLEAN
  /\ inserts \in Nat
  /\ lastOut \in {"none", "focused", "waiting", "refused", "ended", "cleared"}
  /\ lastStep \in {"init", "focus", "wait", "end", "clear", "term"}
  /\ lastActor \in 0..2
  /\ age1 \in Nat /\ age2 \in Nat /\ steps \in Nat

Room == steps < MaxSteps

Init ==
  /\ focus1 = 0 /\ focus2 = 0 /\ wait1 = 0 /\ wait2 = 0
  /\ ended1 = FALSE /\ ended2 = FALSE
  /\ live1 = TRUE /\ live2 = TRUE /\ inserts = 0
  /\ lastOut = "none" /\ lastStep = "init" /\ lastActor = 0
  /\ age1 = 0 /\ age2 = 0 /\ steps = 0

Focus(d) ==
  /\ Room /\ d \in {1, 2}
  /\ LET okLive == IF d = 1 THEN live1 ELSE live2 IN
       /\ lastActor' = d /\ lastStep' = "focus" /\ steps' = steps + 1
       /\ IF GuardLiveToken /\ ~okLive
          THEN /\ lastOut' = "refused" /\ inserts' = 0
               /\ UNCHANGED <<focus1, focus2, wait1, wait2, ended1, ended2,
                              live1, live2, age1, age2>>
          ELSE /\ lastOut' = "focused"
               /\ inserts' = IF GuardOneInsertPerPut THEN 1 ELSE 2
               /\ IF d = 1
                  THEN /\ focus1' = 1 /\ ended1' = FALSE /\ wait1' = 0 /\ age1' = 0
                       /\ UNCHANGED <<focus2, wait2, ended2, live1, live2, age2>>
                  ELSE /\ focus2' = 1 /\ ended2' = FALSE /\ wait2' = 0 /\ age2' = 0
                       /\ UNCHANGED <<focus1, wait1, ended1, live1, live2, age1>>

WaitOn(d, other) ==
  /\ Room /\ d \in {1, 2} /\ other \in {1, 2} /\ d # other
  /\ (IF d = 1 THEN focus1 = 1 ELSE focus2 = 1)
  /\ lastActor' = d /\ lastStep' = "wait" /\ steps' = steps + 1 /\ inserts' = 0
  /\ LET cycle == IF d = 1 THEN (wait2 = 1) ELSE (wait1 = 2) IN
       /\ IF GuardDetectWaitCycle /\ cycle
          THEN /\ lastOut' = "refused"
               /\ UNCHANGED <<focus1, focus2, wait1, wait2, ended1, ended2,
                              live1, live2, age1, age2>>
          ELSE /\ lastOut' = "waiting"
               /\ IF d = 1 THEN wait1' = other ELSE wait2' = other
               /\ IF d = 1 THEN UNCHANGED <<focus1, focus2, wait2, ended1, ended2, live1, live2, age1, age2>>
                            ELSE UNCHANGED <<focus1, focus2, wait1, ended1, ended2, live1, live2, age1, age2>>

WaitSelf(d) ==
  /\ Room /\ d \in {1, 2}
  /\ (IF d = 1 THEN focus1 = 1 ELSE focus2 = 1)
  /\ lastActor' = d /\ lastStep' = "wait" /\ steps' = steps + 1 /\ inserts' = 0
  /\ IF GuardNoSelfWait
     THEN /\ lastOut' = "refused"
          /\ UNCHANGED <<focus1, focus2, wait1, wait2, ended1, ended2, live1, live2, age1, age2>>
     ELSE /\ lastOut' = "waiting"
          /\ IF d = 1 THEN /\ wait1' = 1 /\ UNCHANGED <<focus1, focus2, wait2, ended1, ended2, live1, live2, age1, age2>>
                          ELSE /\ wait2' = 2 /\ UNCHANGED <<focus1, focus2, wait1, ended1, ended2, live1, live2, age1, age2>>

EndFocus(d) ==
  /\ Room /\ d \in {1, 2}
  /\ (IF d = 1 THEN focus1 = 1 ELSE focus2 = 1)
  /\ lastActor' = d /\ lastStep' = "end" /\ lastOut' = "ended"
  /\ steps' = steps + 1 /\ inserts' = 0
  /\ IF d = 1 THEN /\ focus1' = 0 /\ wait1' = 0 /\ ended1' = TRUE /\ age1' = 0
                   /\ UNCHANGED <<focus2, wait2, ended2, live1, live2, age2>>
              ELSE /\ focus2' = 0 /\ wait2' = 0 /\ ended2' = TRUE /\ age2' = 0
                   /\ UNCHANGED <<focus1, wait1, ended1, live1, live2, age1>>

Crash(d) ==
  /\ Room /\ d \in {1, 2}
  /\ (IF d = 1 THEN live1 ELSE live2)
  /\ lastActor' = d /\ lastStep' = "clear" /\ lastOut' = "cleared"
  /\ steps' = steps + 1 /\ inserts' = 0
  /\ IF d = 1 THEN /\ live1' = FALSE
                   /\ UNCHANGED <<focus1, focus2, wait1, wait2, ended1, ended2, live2, age1, age2>>
              ELSE /\ live2' = FALSE
                   /\ UNCHANGED <<focus1, focus2, wait1, wait2, ended1, ended2, live1, age1, age2>>

ClearReset(d) ==
  /\ Room /\ d \in {1, 2}
  /\ lastActor' = d /\ lastStep' = "clear" /\ lastOut' = "cleared"
  /\ steps' = steps + 1 /\ inserts' = 0
  /\ IF d = 1 THEN /\ focus1' = 0 /\ wait1' = 0 /\ live1' = FALSE /\ age1' = 0
                   /\ UNCHANGED <<focus2, wait2, ended1, ended2, live2, age2>>
              ELSE /\ focus2' = 0 /\ wait2' = 0 /\ live2' = FALSE /\ age2' = 0
                   /\ UNCHANGED <<focus1, wait1, ended1, ended2, live1, age1>>

Tick ==
  /\ Room /\ ((focus1 = 1 /\ ~live1) \/ (focus2 = 1 /\ ~live2))
  /\ steps' = steps + 1
  /\ lastStep' = "init" /\ lastOut' = "none" /\ lastActor' = 0 /\ inserts' = 0
  /\ LET a1 == IF focus1 = 1 /\ ~live1 THEN age1 + 1 ELSE age1
         a2 == IF focus2 = 1 /\ ~live2 THEN age2 + 1 ELSE age2
     IN
       /\ IF GuardAutoClearStale /\ a1 >= 3 /\ focus1 = 1 /\ ~live1
          THEN /\ focus1' = 0 /\ wait1' = 0 /\ age1' = 0
          ELSE /\ age1' = a1 /\ UNCHANGED <<focus1, wait1>>
       /\ IF GuardAutoClearStale /\ a2 >= 3 /\ focus2 = 1 /\ ~live2
          THEN /\ focus2' = 0 /\ wait2' = 0 /\ age2' = 0
          ELSE /\ age2' = a2 /\ UNCHANGED <<focus2, wait2>>
       /\ UNCHANGED <<ended1, ended2, live1, live2>>

Term == /\ steps >= MaxSteps /\ UNCHANGED vars

Next ==
  \/ \E d \in {1, 2}: Focus(d)
  \/ \E d \in {1, 2}: \E o \in {1, 2}: WaitOn(d, o)
  \/ \E d \in {1, 2}: WaitSelf(d)
  \/ \E d \in {1, 2}: EndFocus(d)
  \/ \E d \in {1, 2}: Crash(d)
  \/ \E d \in {1, 2}: ClearReset(d)
  \/ Tick
  \/ Term

Spec == Init /\ [][Next]_vars

NoSelfWait == ~ (wait1 = 1 \/ wait2 = 2)

LiveTokenRequired ==
  (lastStep = "focus" /\ lastOut = "focused") =>
    (IF lastActor = 1 THEN live1 ELSE live2)

OneFocusInsertPerPut ==
  (lastStep = "focus" /\ lastOut = "focused") => (inserts = 1)

DoingEndsOnShip ==
  (lastStep = "end" /\ lastOut = "ended") =>
    (IF lastActor = 1 THEN focus1 = 0 ELSE focus2 = 0)

\* Known: product refuses only self-wait, not A<->B cycles (letter 4252 class).
NoInvisibleWaitCycle == ~ (wait1 = 2 /\ wait2 = 1)

\* Known: crashed desk focus has no auto-clear (reset/retire only).
StaleDoingClearsWithinBound ==
  ~ ((age1 >= 3 /\ focus1 = 1 /\ ~live1) \/ (age2 >= 3 /\ focus2 = 1 /\ ~live2))

====
