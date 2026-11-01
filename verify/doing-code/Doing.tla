---- MODULE Doing ----
\* Card 925 (doing slice): code-against-spec for doing focus/waiting/end guards
\* at SYNC (see run.sh). Card 1014 anchors.
\*
\* Current (ce115f8): one focus per desk (seat.doing_id); MaxTasks=1;
\* GuardSupersede=TRUE models D6 (newer --doing ends the prior entry).
\*
\* 0.8.6 target, per builder: doing only from tw (970); a desk may run several
\* tw tasks at once (MaxTasks>=2); GuardSupersede=FALSE (no D6). Wait-cycles
\* (1017) and stale clear (1018) are per task. See Doing-target.cfg.
\*
\* Not verify/spin/doing.pml (0.8.0 lock-order, still single pointer on main).
\* Code anchors: sp_doing.sql / sp_join.sql at current.

EXTENDS Naturals

CONSTANTS
  MaxSteps,
  MaxTasks,              \* 1 = current single pointer; 2 = 0.8.6 concurrent tw
  GuardNoSelfWait,
  GuardLiveToken,
  GuardOneInsertPerPut,
  GuardDetectWaitCycle,
  GuardAutoClearStale,
  GuardSupersede         \* TRUE = current D6; FALSE = 0.8.6 target (keep peers)

ASSUME MaxSteps \in Nat /\ MaxSteps >= 1
ASSUME MaxTasks \in {1, 2}
ASSUME GuardNoSelfWait \in BOOLEAN
ASSUME GuardLiveToken \in BOOLEAN
ASSUME GuardOneInsertPerPut \in BOOLEAN
ASSUME GuardDetectWaitCycle \in BOOLEAN
ASSUME GuardAutoClearStale \in BOOLEAN
ASSUME GuardSupersede \in BOOLEAN

\* Two desks; up to MaxTasks task slots each (slot 2 unused when MaxTasks=1).
VARIABLES
  st11, st12,            \* desk1 task slots: 0 idle, 1 active, 2 waiting
  st21, st22,
  w11, w12,              \* wait target desk id (0 none, 1/2 desk); per task
  w21, w22,
  ended11, ended12,
  ended21, ended22,
  live1, live2,          \* desk process alive (tw/connect)
  inserts,
  lastOut, lastStep, lastActor, lastTask,
  age11, age12, age21, age22,
  steps

vars == <<st11, st12, st21, st22, w11, w12, w21, w22,
          ended11, ended12, ended21, ended22, live1, live2,
          inserts, lastOut, lastStep, lastActor, lastTask,
          age11, age12, age21, age22, steps>>

TypeOK ==
  /\ st11 \in 0..2 /\ st12 \in 0..2 /\ st21 \in 0..2 /\ st22 \in 0..2
  /\ w11 \in 0..2 /\ w12 \in 0..2 /\ w21 \in 0..2 /\ w22 \in 0..2
  /\ ended11 \in BOOLEAN /\ ended12 \in BOOLEAN
  /\ ended21 \in BOOLEAN /\ ended22 \in BOOLEAN
  /\ live1 \in BOOLEAN /\ live2 \in BOOLEAN
  /\ inserts \in Nat
  /\ lastOut \in {"none", "focused", "waiting", "refused", "ended", "cleared"}
  /\ lastStep \in {"init", "focus", "wait", "end", "clear", "term"}
  /\ lastActor \in 0..2 /\ lastTask \in 0..2
  /\ age11 \in Nat /\ age12 \in Nat /\ age21 \in Nat /\ age22 \in Nat
  /\ steps \in Nat
  /\ (MaxTasks = 1) => (st12 = 0 /\ st22 = 0 /\ w12 = 0 /\ w22 = 0)

Room == steps < MaxSteps

Init ==
  /\ st11 = 0 /\ st12 = 0 /\ st21 = 0 /\ st22 = 0
  /\ w11 = 0 /\ w12 = 0 /\ w21 = 0 /\ w22 = 0
  /\ ended11 = FALSE /\ ended12 = FALSE /\ ended21 = FALSE /\ ended22 = FALSE
  /\ live1 = TRUE /\ live2 = TRUE /\ inserts = 0
  /\ lastOut = "none" /\ lastStep = "init" /\ lastActor = 0 /\ lastTask = 0
  /\ age11 = 0 /\ age12 = 0 /\ age21 = 0 /\ age22 = 0 /\ steps = 0

\* Pick a free slot on desk d, or supersede slot 1 when MaxTasks=1 and GuardSupersede.
FreeSlot(d) ==
  IF d = 1
  THEN IF st11 = 0 THEN 1
       ELSE IF MaxTasks = 2 /\ st12 = 0 THEN 2
       ELSE IF GuardSupersede /\ st11 # 0 THEN 1   \* D6 current: reuse slot 1
       ELSE 0
  ELSE IF st21 = 0 THEN 1
       ELSE IF MaxTasks = 2 /\ st22 = 0 THEN 2
       ELSE IF GuardSupersede /\ st21 # 0 THEN 1
       ELSE 0

Focus(d) ==
  /\ Room /\ d \in {1, 2}
  /\ LET okLive == IF d = 1 THEN live1 ELSE live2
         slot == FreeSlot(d)
     IN
       /\ slot # 0
       /\ lastActor' = d /\ lastTask' = slot /\ lastStep' = "focus" /\ steps' = steps + 1
       /\ IF GuardLiveToken /\ ~okLive
          THEN /\ lastOut' = "refused" /\ inserts' = 0
               /\ UNCHANGED <<st11, st12, st21, st22, w11, w12, w21, w22,
                              ended11, ended12, ended21, ended22,
                              live1, live2, age11, age12, age21, age22>>
          ELSE /\ lastOut' = "focused"
               /\ inserts' = IF GuardOneInsertPerPut THEN 1 ELSE 2
               /\ IF d = 1 /\ slot = 1
                  THEN /\ st11' = 1 /\ w11' = 0 /\ ended11' = FALSE /\ age11' = 0
                       /\ UNCHANGED <<st12, st21, st22, w12, w21, w22,
                                      ended12, ended21, ended22, live1, live2,
                                      age12, age21, age22>>
                  ELSE IF d = 1 /\ slot = 2
                  THEN /\ st12' = 1 /\ w12' = 0 /\ ended12' = FALSE /\ age12' = 0
                       /\ UNCHANGED <<st11, st21, st22, w11, w21, w22,
                                      ended11, ended21, ended22, live1, live2,
                                      age11, age21, age22>>
                  ELSE IF d = 2 /\ slot = 1
                  THEN /\ st21' = 1 /\ w21' = 0 /\ ended21' = FALSE /\ age21' = 0
                       /\ UNCHANGED <<st11, st12, st22, w11, w12, w22,
                                      ended11, ended12, ended22, live1, live2,
                                      age11, age12, age22>>
                  ELSE /\ st22' = 1 /\ w22' = 0 /\ ended22' = FALSE /\ age22' = 0
                       /\ UNCHANGED <<st11, st12, st21, w11, w12, w21,
                                      ended11, ended12, ended21, live1, live2,
                                      age11, age12, age21>>

TaskActive(d, t) ==
  IF d = 1 THEN IF t = 1 THEN st11 = 1 ELSE st12 = 1
           ELSE IF t = 1 THEN st21 = 1 ELSE st22 = 1

TaskWaiting(d, t) ==
  IF d = 1 THEN IF t = 1 THEN st11 = 2 ELSE st12 = 2
           ELSE IF t = 1 THEN st21 = 2 ELSE st22 = 2

\* Any task on desk `other` is waiting on desk `d`?
DeskWaitsOn(other, d) ==
  IF other = 1 THEN (w11 = d \/ w12 = d) ELSE (w21 = d \/ w22 = d)

WaitOn(d, t, other) ==
  /\ Room /\ d \in {1, 2} /\ other \in {1, 2} /\ d # other
  /\ t \in 1..MaxTasks
  /\ TaskActive(d, t) \/ TaskWaiting(d, t)
  /\ lastActor' = d /\ lastTask' = t /\ lastStep' = "wait" /\ steps' = steps + 1 /\ inserts' = 0
  /\ LET cycle == DeskWaitsOn(other, d)
     IN
       /\ IF GuardDetectWaitCycle /\ cycle
          THEN /\ lastOut' = "refused"
               /\ UNCHANGED <<st11, st12, st21, st22, w11, w12, w21, w22,
                              ended11, ended12, ended21, ended22,
                              live1, live2, age11, age12, age21, age22>>
          ELSE /\ lastOut' = "waiting"
               /\ IF d = 1 /\ t = 1
                  THEN /\ st11' = 2 /\ w11' = other
                       /\ UNCHANGED <<st12, st21, st22, w12, w21, w22,
                                      ended11, ended12, ended21, ended22,
                                      live1, live2, age11, age12, age21, age22>>
                  ELSE IF d = 1 /\ t = 2
                  THEN /\ st12' = 2 /\ w12' = other
                       /\ UNCHANGED <<st11, st21, st22, w11, w21, w22,
                                      ended11, ended12, ended21, ended22,
                                      live1, live2, age11, age12, age21, age22>>
                  ELSE IF d = 2 /\ t = 1
                  THEN /\ st21' = 2 /\ w21' = other
                       /\ UNCHANGED <<st11, st12, st22, w11, w12, w22,
                                      ended11, ended12, ended21, ended22,
                                      live1, live2, age11, age12, age21, age22>>
                  ELSE /\ st22' = 2 /\ w22' = other
                       /\ UNCHANGED <<st11, st12, st21, w11, w12, w21,
                                      ended11, ended12, ended21, ended22,
                                      live1, live2, age11, age12, age21, age22>>

WaitSelf(d, t) ==
  /\ Room /\ d \in {1, 2} /\ t \in 1..MaxTasks
  /\ TaskActive(d, t) \/ TaskWaiting(d, t)
  /\ lastActor' = d /\ lastTask' = t /\ lastStep' = "wait" /\ steps' = steps + 1 /\ inserts' = 0
  /\ IF GuardNoSelfWait
     THEN /\ lastOut' = "refused"
          /\ UNCHANGED <<st11, st12, st21, st22, w11, w12, w21, w22,
                         ended11, ended12, ended21, ended22,
                         live1, live2, age11, age12, age21, age22>>
     ELSE /\ lastOut' = "waiting"
          /\ IF d = 1 /\ t = 1
             THEN /\ st11' = 2 /\ w11' = 1
                  /\ UNCHANGED <<st12, st21, st22, w12, w21, w22,
                                 ended11, ended12, ended21, ended22,
                                 live1, live2, age11, age12, age21, age22>>
             ELSE IF d = 1 /\ t = 2
             THEN /\ st12' = 2 /\ w12' = 1
                  /\ UNCHANGED <<st11, st21, st22, w11, w21, w22,
                                 ended11, ended12, ended21, ended22,
                                 live1, live2, age11, age12, age21, age22>>
             ELSE IF d = 2 /\ t = 1
             THEN /\ st21' = 2 /\ w21' = 2
                  /\ UNCHANGED <<st11, st12, st22, w11, w12, w22,
                                 ended11, ended12, ended21, ended22,
                                 live1, live2, age11, age12, age21, age22>>
             ELSE /\ st22' = 2 /\ w22' = 2
                  /\ UNCHANGED <<st11, st12, st21, w11, w12, w21,
                                 ended11, ended12, ended21, ended22,
                                 live1, live2, age11, age12, age21, age22>>

EndTask(d, t) ==
  /\ Room /\ d \in {1, 2} /\ t \in 1..MaxTasks
  /\ TaskActive(d, t) \/ TaskWaiting(d, t)
  /\ lastActor' = d /\ lastTask' = t /\ lastStep' = "end" /\ lastOut' = "ended"
  /\ steps' = steps + 1 /\ inserts' = 0
  /\ IF d = 1 /\ t = 1
     THEN /\ st11' = 0 /\ w11' = 0 /\ ended11' = TRUE /\ age11' = 0
          /\ UNCHANGED <<st12, st21, st22, w12, w21, w22,
                         ended12, ended21, ended22, live1, live2,
                         age12, age21, age22>>
     ELSE IF d = 1 /\ t = 2
     THEN /\ st12' = 0 /\ w12' = 0 /\ ended12' = TRUE /\ age12' = 0
          /\ UNCHANGED <<st11, st21, st22, w11, w21, w22,
                         ended11, ended21, ended22, live1, live2,
                         age11, age21, age22>>
     ELSE IF d = 2 /\ t = 1
     THEN /\ st21' = 0 /\ w21' = 0 /\ ended21' = TRUE /\ age21' = 0
          /\ UNCHANGED <<st11, st12, st22, w11, w12, w22,
                         ended11, ended12, ended22, live1, live2,
                         age11, age12, age22>>
     ELSE /\ st22' = 0 /\ w22' = 0 /\ ended22' = TRUE /\ age22' = 0
          /\ UNCHANGED <<st11, st12, st21, w11, w12, w21,
                         ended11, ended12, ended21, live1, live2,
                         age11, age12, age21>>

Crash(d) ==
  /\ Room /\ d \in {1, 2}
  /\ (IF d = 1 THEN live1 ELSE live2)
  /\ lastActor' = d /\ lastTask' = 0 /\ lastStep' = "clear" /\ lastOut' = "cleared"
  /\ steps' = steps + 1 /\ inserts' = 0
  /\ IF d = 1 THEN /\ live1' = FALSE
                   /\ UNCHANGED <<st11, st12, st21, st22, w11, w12, w21, w22,
                                  ended11, ended12, ended21, ended22, live2,
                                  age11, age12, age21, age22>>
              ELSE /\ live2' = FALSE
                   /\ UNCHANGED <<st11, st12, st21, st22, w11, w12, w21, w22,
                                  ended11, ended12, ended21, ended22, live1,
                                  age11, age12, age21, age22>>

ClearReset(d) ==
  /\ Room /\ d \in {1, 2}
  /\ lastActor' = d /\ lastTask' = 0 /\ lastStep' = "clear" /\ lastOut' = "cleared"
  /\ steps' = steps + 1 /\ inserts' = 0
  /\ IF d = 1 THEN /\ st11' = 0 /\ st12' = 0 /\ w11' = 0 /\ w12' = 0
                   /\ live1' = FALSE /\ age11' = 0 /\ age12' = 0
                   /\ UNCHANGED <<st21, st22, w21, w22, ended11, ended12,
                                  ended21, ended22, live2, age21, age22>>
              ELSE /\ st21' = 0 /\ st22' = 0 /\ w21' = 0 /\ w22' = 0
                   /\ live2' = FALSE /\ age21' = 0 /\ age22' = 0
                   /\ UNCHANGED <<st11, st12, w11, w12, ended11, ended12,
                                  ended21, ended22, live1, age11, age12>>

Tick ==
  /\ Room
  /\ LET stale1 == (~live1 /\ (st11 # 0 \/ st12 # 0))
         stale2 == (~live2 /\ (st21 # 0 \/ st22 # 0))
     IN stale1 \/ stale2
  /\ steps' = steps + 1
  /\ lastStep' = "init" /\ lastOut' = "none" /\ lastActor' = 0 /\ lastTask' = 0 /\ inserts' = 0
  /\ LET a11 == IF ~live1 /\ st11 # 0 THEN age11 + 1 ELSE age11
         a12 == IF ~live1 /\ st12 # 0 THEN age12 + 1 ELSE age12
         a21 == IF ~live2 /\ st21 # 0 THEN age21 + 1 ELSE age21
         a22 == IF ~live2 /\ st22 # 0 THEN age22 + 1 ELSE age22
     IN
       /\ IF GuardAutoClearStale /\ a11 >= 3 /\ st11 # 0 /\ ~live1
          THEN /\ st11' = 0 /\ w11' = 0 /\ age11' = 0
          ELSE /\ age11' = a11 /\ UNCHANGED <<st11, w11>>
       /\ IF GuardAutoClearStale /\ a12 >= 3 /\ st12 # 0 /\ ~live1
          THEN /\ st12' = 0 /\ w12' = 0 /\ age12' = 0
          ELSE /\ age12' = a12 /\ UNCHANGED <<st12, w12>>
       /\ IF GuardAutoClearStale /\ a21 >= 3 /\ st21 # 0 /\ ~live2
          THEN /\ st21' = 0 /\ w21' = 0 /\ age21' = 0
          ELSE /\ age21' = a21 /\ UNCHANGED <<st21, w21>>
       /\ IF GuardAutoClearStale /\ a22 >= 3 /\ st22 # 0 /\ ~live2
          THEN /\ st22' = 0 /\ w22' = 0 /\ age22' = 0
          ELSE /\ age22' = a22 /\ UNCHANGED <<st22, w22>>
       /\ UNCHANGED <<ended11, ended12, ended21, ended22, live1, live2>>

Term == /\ steps >= MaxSteps /\ UNCHANGED vars

Next ==
  \/ \E d \in {1, 2}: Focus(d)
  \/ \E d \in {1, 2}: \E t \in 1..MaxTasks: \E o \in {1, 2}: WaitOn(d, t, o)
  \/ \E d \in {1, 2}: \E t \in 1..MaxTasks: WaitSelf(d, t)
  \/ \E d \in {1, 2}: \E t \in 1..MaxTasks: EndTask(d, t)
  \/ \E d \in {1, 2}: Crash(d)
  \/ \E d \in {1, 2}: ClearReset(d)
  \/ Tick
  \/ Term

Spec == Init /\ [][Next]_vars

NoSelfWait == ~(w11 = 1 \/ w12 = 1 \/ w21 = 2 \/ w22 = 2)

LiveTokenRequired ==
  (lastStep = "focus" /\ lastOut = "focused") =>
    (IF lastActor = 1 THEN live1 ELSE live2)

OneFocusInsertPerPut ==
  (lastStep = "focus" /\ lastOut = "focused") => (inserts = 1)

DoingEndsOnShip ==
  (lastStep = "end" /\ lastOut = "ended") =>
    (IF lastActor = 1 /\ lastTask = 1 THEN st11 = 0
     ELSE IF lastActor = 1 /\ lastTask = 2 THEN st12 = 0
     ELSE IF lastActor = 2 /\ lastTask = 1 THEN st21 = 0
     ELSE st22 = 0)

\* 1017: any task on desk1 waiting on desk2 while any task on desk2 waits on desk1
NoInvisibleWaitCycle == ~ (DeskWaitsOn(1, 2) /\ DeskWaitsOn(2, 1))

\* 1018: per-task stale age bound
StaleDoingClearsWithinBound ==
  ~ ((age11 >= 3 /\ st11 # 0 /\ ~live1) \/ (age12 >= 3 /\ st12 # 0 /\ ~live1)
     \/ (age21 >= 3 /\ st21 # 0 /\ ~live2) \/ (age22 >= 3 /\ st22 # 0 /\ ~live2))

\* 0.8.6 target: two concurrent actives on one desk are allowed
ConcurrentTasksAllowed ==
  (MaxTasks = 2 /\ ~GuardSupersede) => TRUE

====
