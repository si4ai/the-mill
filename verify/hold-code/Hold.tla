---- MODULE Hold ----
\* Card 925 (hold slice): code-against-spec for hold mutex, drop idempotence,
\* and release-other race guards at SYNC (see run.sh). Deadlock/liveness first.
\*
\* Not verify/spin/holds.pml (policy/concurrency) and not F223 pytest.
\* Code: sp_hold.sql mill_hold_upsert/delete/release_desk/release_other;
\* records/hold.py may_drop_other, delete_other, drop.

EXTENDS Naturals

CONSTANTS
  MaxSteps,
  GuardTakeWhenFree,
  GuardOwnDropOnly,
  GuardExpectHolder,
  GuardAlreadyFree,
  GuardAutoExpire

ASSUME MaxSteps \in Nat /\ MaxSteps >= 1
ASSUME GuardTakeWhenFree \in BOOLEAN
ASSUME GuardOwnDropOnly \in BOOLEAN
ASSUME GuardExpectHolder \in BOOLEAN
ASSUME GuardAlreadyFree \in BOOLEAN
ASSUME GuardAutoExpire \in BOOLEAN

VARIABLES
  holder,       \* 0 free, 1 desk A, 2 desk B
  priorHolder,  \* holder before last mutating step
  lastExpect,   \* expect desk last passed to ReleaseOther (0 if N/A)
  lastOut,
  lastStep,
  lastActor,
  twoHolders,
  steps,
  age

vars == <<holder, priorHolder, lastExpect, lastOut, lastStep, lastActor, twoHolders, steps, age>>

TypeOK ==
  /\ holder \in 0..2
  /\ priorHolder \in 0..2
  /\ lastExpect \in 0..2
  /\ lastOut \in {"none", "taken", "refused", "refreshed", "released",
                  "kept", "already_free", "holder_changed", "expired"}
  /\ lastStep \in {"init", "take", "refresh", "drop", "release_other", "expire", "term"}
  /\ lastActor \in 0..2
  /\ twoHolders \in BOOLEAN
  /\ steps \in Nat
  /\ age \in Nat

Room == steps < MaxSteps

Init ==
  /\ holder = 0
  /\ priorHolder = 0
  /\ lastExpect = 0
  /\ lastOut = "none"
  /\ lastStep = "init"
  /\ lastActor = 0
  /\ twoHolders = FALSE
  /\ steps = 0
  /\ age = 0

\* mill_hold_upsert: take when free (desk_id IS NULL), refresh when same desk,
\* refuse when another holds. GuardTakeWhenFree off = blind overwrite.
Take(d) ==
  /\ Room /\ d \in {1, 2}
  /\ IF holder = 0 \/ (~GuardTakeWhenFree /\ holder # d)
     THEN /\ priorHolder' = holder
          /\ holder' = d
          /\ lastExpect' = 0
          /\ lastOut' = "taken"
          /\ lastStep' = "take"
          /\ lastActor' = d
          /\ twoHolders' = (holder # 0 /\ holder # d)
          /\ age' = 0
          /\ steps' = steps + 1
     ELSE IF holder = d
          THEN /\ priorHolder' = holder
               /\ lastExpect' = 0
               /\ lastOut' = "refreshed"
               /\ lastStep' = "refresh"
               /\ lastActor' = d
               /\ steps' = steps + 1
               /\ UNCHANGED <<holder, twoHolders, age>>
          ELSE /\ priorHolder' = holder
               /\ lastExpect' = 0
               /\ lastOut' = "refused"
               /\ lastStep' = "take"
               /\ lastActor' = d
               /\ steps' = steps + 1
               /\ UNCHANGED <<holder, twoHolders, age>>

\* mill_hold_delete: owner-only drop. GuardOwnDropOnly off = any desk can free.
DropOwn(d) ==
  /\ Room /\ d \in {1, 2}
  /\ LET isOwner == (holder = d)
         mayForce == (~GuardOwnDropOnly /\ holder # 0 /\ ~isOwner)
         doRelease == isOwner \/ mayForce
     IN
       /\ priorHolder' = holder
       /\ lastExpect' = 0
       /\ lastStep' = "drop"
       /\ lastActor' = d
       /\ steps' = steps + 1
       /\ IF doRelease
          THEN /\ holder' = 0
               /\ lastOut' = "released"
               /\ twoHolders' = FALSE
               /\ age' = 0
          ELSE /\ lastOut' = "kept"
               /\ UNCHANGED <<holder, twoHolders, age>>

\* mill_hold_release_other: free only when desk_id = expect; already free / holder
\* changed are honest outs. Guards off = lie or blind free.
ReleaseOther(expect) ==
  /\ Room /\ expect \in {1, 2}
  /\ priorHolder' = holder
  /\ lastExpect' = expect
  /\ lastStep' = "release_other"
  /\ lastActor' = 2
  /\ steps' = steps + 1
  /\ IF holder = 0
     THEN /\ lastOut' = IF GuardAlreadyFree THEN "already_free" ELSE "kept"
          /\ UNCHANGED <<holder, twoHolders, age>>
     ELSE IF holder # expect
          THEN IF GuardExpectHolder
               THEN /\ lastOut' = "holder_changed"
                    /\ UNCHANGED <<holder, twoHolders, age>>
               ELSE /\ holder' = 0
                    /\ lastOut' = "released"
                    /\ twoHolders' = FALSE
                    /\ age' = 0
          ELSE /\ holder' = 0
               /\ lastOut' = "released"
               /\ twoHolders' = FALSE
               /\ age' = 0

\* Time passes. With GuardAutoExpire, the step that would cross the bound
\* frees the hold instead (proposed fix for the no-TTL finding).
Tick ==
  /\ Room /\ holder # 0
  /\ priorHolder' = holder
  /\ lastExpect' = 0
  /\ steps' = steps + 1
  /\ IF GuardAutoExpire /\ (age + 1 >= 3)
     THEN /\ holder' = 0
          /\ lastOut' = "expired"
          /\ lastStep' = "expire"
          /\ lastActor' = 0
          /\ twoHolders' = FALSE
          /\ age' = 0
     ELSE /\ age' = age + 1
          /\ lastStep' = "init"
          /\ lastOut' = "none"
          /\ UNCHANGED <<holder, lastActor, twoHolders>>

\* Kept for clarity; unreachable when GuardAutoExpire folds into Tick.
Expire ==
  /\ FALSE
  /\ UNCHANGED vars

Term ==
  /\ steps >= MaxSteps
  /\ UNCHANGED vars

Next ==
  \/ \E d \in {1, 2}: Take(d)
  \/ \E d \in {1, 2}: DropOwn(d)
  \/ \E e \in {1, 2}: ReleaseOther(e)
  \/ Tick
  \/ Expire
  \/ Term

Spec == Init /\ [][Next]_vars

AtMostOneHolder == ~twoHolders

\* take only from free (or mutant blind overwrite). No guard in consequent.
TakeFromFreeOrRefresh ==
  (lastStep = "take" /\ lastOut = "taken") => (priorHolder = 0)

\* own drop releases only when actor held. No guard in consequent.
OnlyOwnerDropReleases ==
  (lastStep = "drop" /\ lastOut = "released") => (priorHolder = lastActor)

DropFreesRow ==
  (lastStep = "drop" /\ lastOut = "released") => (holder = 0)

\* release-other frees only the expected holder. No guard in consequent.
ExpectGuardHolds ==
  (lastStep = "release_other" /\ lastOut = "released" /\ priorHolder # 0)
    => (priorHolder = lastExpect)

AlreadyFreeHonest ==
  (lastStep = "release_other" /\ priorHolder = 0) => (lastOut = "already_free")

DropIdempotent ==
  (lastStep = "drop" /\ priorHolder = 0) => (lastOut = "kept" /\ holder = 0)

\* Known finding (SPIN H11): without an actor, a hold stays held past any bound.
NoStuckHoldPastBound ==
  ~(age >= 3 /\ holder # 0)

====
