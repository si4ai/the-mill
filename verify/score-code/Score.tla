---- MODULE Score ----
\* Card 925 (score slice): liveness-truth of score KPIs vs the 0.8.5 code.
\* Missed wakes / blocked holds counted; empty vs zero; truncated windows labelled.
\* Card 1014 anchors + caller-observed fields (letter 4267 lesson).
\*
\* Not verify/spin/score.pml (S1-S6 lifecycle) and not wall/pytest score suites alone.

EXTENDS Naturals

CONSTANTS
  MaxSteps,
  GuardCountWsMiss,
  GuardCountHoldBlocked,
  GuardEmptyAsMissing,
  GuardTruncationLabelled

ASSUME MaxSteps \in Nat /\ MaxSteps >= 1
ASSUME GuardCountWsMiss \in BOOLEAN
ASSUME GuardCountHoldBlocked \in BOOLEAN
ASSUME GuardEmptyAsMissing \in BOOLEAN
ASSUME GuardTruncationLabelled \in BOOLEAN

VARIABLES
  wsMissEvents, wsMissCount,
  holdEvents, holdCount,
  samples,
  published,
  truncated, labelled,
  lastOut, lastStep, steps

vars == <<wsMissEvents, wsMissCount, holdEvents, holdCount, samples,
          published, truncated, labelled, lastOut, lastStep, steps>>

TypeOK ==
  /\ wsMissEvents \in Nat /\ wsMissCount \in Nat
  /\ holdEvents \in Nat /\ holdCount \in Nat
  /\ samples \in 0..1
  /\ published \in {"none", "missing", "zero", "value"}
  /\ truncated \in BOOLEAN /\ labelled \in BOOLEAN
  /\ lastOut \in {"none", "counted", "published", "shaped"}
  /\ lastStep \in {"init", "miss", "hold", "sample", "publish", "shape"}
  /\ steps \in Nat

Room == steps < MaxSteps

Init ==
  /\ wsMissEvents = 0 /\ wsMissCount = 0
  /\ holdEvents = 0 /\ holdCount = 0
  /\ samples = 0 /\ published = "none"
  /\ truncated = FALSE /\ labelled = FALSE
  /\ lastOut = "none" /\ lastStep = "init" /\ steps = 0

WsMiss ==
  /\ Room
  /\ lastStep' = "miss" /\ lastOut' = "counted" /\ steps' = steps + 1
  /\ wsMissEvents' = wsMissEvents + 1
  /\ wsMissCount' = IF GuardCountWsMiss THEN wsMissCount + 1 ELSE wsMissCount
  /\ UNCHANGED <<holdEvents, holdCount, samples, published, truncated, labelled>>

HoldBlocked ==
  /\ Room
  /\ lastStep' = "hold" /\ lastOut' = "counted" /\ steps' = steps + 1
  /\ holdEvents' = holdEvents + 1
  /\ holdCount' = IF GuardCountHoldBlocked THEN holdCount + 1 ELSE holdCount
  /\ UNCHANGED <<wsMissEvents, wsMissCount, samples, published, truncated, labelled>>

Sample ==
  /\ Room /\ samples = 0
  /\ lastStep' = "sample" /\ lastOut' = "counted" /\ steps' = steps + 1
  /\ samples' = 1
  /\ UNCHANGED <<wsMissEvents, wsMissCount, holdEvents, holdCount,
                 published, truncated, labelled>>

Publish ==
  /\ Room
  /\ lastStep' = "publish" /\ lastOut' = "published" /\ steps' = steps + 1
  /\ IF samples = 0
     THEN published' = IF GuardEmptyAsMissing THEN "missing" ELSE "zero"
     ELSE published' = "value"
  /\ UNCHANGED <<wsMissEvents, wsMissCount, holdEvents, holdCount,
                 samples, truncated, labelled>>

ShapeTrunc ==
  /\ Room /\ ~truncated
  /\ lastStep' = "shape" /\ lastOut' = "shaped" /\ steps' = steps + 1
  /\ truncated' = TRUE
  /\ labelled' = IF GuardTruncationLabelled THEN TRUE ELSE FALSE
  /\ UNCHANGED <<wsMissEvents, wsMissCount, holdEvents, holdCount,
                 samples, published>>

Term == /\ steps >= MaxSteps /\ UNCHANGED vars

Next ==
  \/ WsMiss
  \/ HoldBlocked
  \/ Sample
  \/ Publish
  \/ ShapeTrunc
  \/ Term

Spec == Init /\ [][Next]_vars

WsMissNotDropped == wsMissCount = wsMissEvents
HoldBlockedNotDropped == holdCount = holdEvents

\* Caller / tick truth: empty input must not look like a green zero.
EmptyShowsMissing ==
  (lastStep = "publish" /\ samples = 0) => (published = "missing")

\* A truncated point window must be labelled for the caller.
TruncationLabelled == truncated => labelled

====
