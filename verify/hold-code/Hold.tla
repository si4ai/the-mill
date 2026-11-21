---- MODULE Hold ----
\* Card 925 (hold slice), re-anchored for card 1267 (PR #490 head 047b9f5):
\* code-against-spec for the hold mutex with a one-use release key, keyed drop,
\* hand-off, refusal rows, and the release-other race guards. Deadlock and
\* liveness first.
\*
\* Not verify/spin/holds.pml (runs, policies, concurrency) and not F223 pytest.
\* Code: sp_hold.sql MILL_HOLD_KH, mill_hold_upsert, mill_hold_drop,
\* mill_hold_release_desk, mill_hold_release_other; records/hold.py drop,
\* may_drop_other, delete_other; helpers/hold_key.py key_hash.
\*
\* A key is a generation number: every grant and every hand-off mints the
\* next one (the kh on hold_grant / hold_refresh); live is the newest one
\* (MILL_HOLD_KH) while the row is held, 0 when it is free. Any desk may
\* present any key; 0 stands for a wrong or missing key.

EXTENDS Naturals

CONSTANTS
  MaxSteps,
  GuardTakeWhenFree,   \* take UPDATE only WHERE desk_id IS NULL
  GuardRefuseHeld,     \* a held row is refused for every caller (no same-desk refresh)
  GuardKeyDrop,        \* mill_hold_drop frees only when the key is the live one
  GuardSpendKey,       \* a hand-off writes a new kh, so the presented key is spent
  GuardRefuseRow,      \* the hold_refuse row is written in the refusing transaction
  GuardExpectHolder,
  GuardAlreadyFree,
  GuardAutoExpire,
  GuardDropClears

ASSUME MaxSteps \in Nat /\ MaxSteps >= 1
ASSUME \A g \in {GuardTakeWhenFree, GuardRefuseHeld, GuardKeyDrop, GuardSpendKey,
                 GuardRefuseRow, GuardExpectHolder, GuardAlreadyFree,
                 GuardAutoExpire, GuardDropClears} : g \in BOOLEAN

VARIABLES
  holder,       \* 0 free, 1 desk A, 2 desk B
  live,         \* live key generation (0 = none: free)
  gen,          \* keys minted so far
  priorHolder,  \* holder before the last step
  priorLive,    \* live key before the last step
  lastKey,      \* key presented by the last step (0 = none or wrong)
  lastExpect,   \* expect desk last passed to ReleaseOther (0 if N/A)
  lastOut,
  lastStep,
  lastActor,
  refuseRow,    \* the last refusal has its hold_refuse row
  twoHolders,
  steps,
  age

vars == <<holder, live, gen, priorHolder, priorLive, lastKey, lastExpect, lastOut,
          lastStep, lastActor, refuseRow, twoHolders, steps, age>>

TypeOK ==
  /\ holder \in 0..2
  /\ live \in Nat /\ gen \in Nat /\ live <= gen
  /\ priorHolder \in 0..2
  /\ priorLive \in Nat
  /\ lastKey \in Nat
  /\ lastExpect \in 0..2
  /\ lastOut \in {"none", "taken", "refused", "refreshed", "handoff", "released",
                  "kept", "already_free", "holder_changed", "expired"}
  /\ lastStep \in {"init", "take", "take_key", "drop", "release_other", "expire", "term"}
  /\ lastActor \in 0..2
  /\ refuseRow \in BOOLEAN
  /\ twoHolders \in BOOLEAN
  /\ steps \in Nat
  /\ age \in Nat

Room == steps < MaxSteps

Init ==
  /\ holder = 0 /\ live = 0 /\ gen = 0
  /\ priorHolder = 0 /\ priorLive = 0 /\ lastKey = 0 /\ lastExpect = 0
  /\ lastOut = "none" /\ lastStep = "init" /\ lastActor = 0
  /\ refuseRow = TRUE /\ twoHolders = FALSE /\ steps = 0 /\ age = 0

\* The refusal row: in the transaction (GuardRefuseRow), or after it and lost
\* sometimes (the soft-fail shape before card 1267).
RowWritten(b) == IF GuardRefuseRow THEN b = TRUE ELSE b \in BOOLEAN

Refuse(d, step, k) ==
  /\ lastOut' = "refused" /\ lastStep' = step /\ lastActor' = d /\ lastKey' = k
  /\ \E b \in BOOLEAN : RowWritten(b) /\ refuseRow' = b
  /\ UNCHANGED <<holder, live, gen, twoHolders, age>>

\* mill_hold_upsert without --key: a free (or missing) row is taken and gets a
\* new key on hold_grant; a held row is refused for every caller, its desk
\* included, with a hold_refuse row. GuardTakeWhenFree off = blind overwrite;
\* GuardRefuseHeld off = the same desk refreshes (0.8.15 and earlier).
Take(d) ==
  /\ Room /\ d \in {1, 2}
  /\ priorHolder' = holder /\ priorLive' = live /\ lastExpect' = 0
  /\ steps' = steps + 1
  /\ IF holder = 0 \/ (~GuardTakeWhenFree /\ holder # d)
     THEN /\ holder' = d /\ gen' = gen + 1 /\ live' = gen + 1
          /\ lastOut' = "taken" /\ lastStep' = "take" /\ lastActor' = d /\ lastKey' = 0
          /\ twoHolders' = (holder # 0 /\ holder # d)
          /\ refuseRow' = TRUE /\ age' = 0
     ELSE IF ~GuardRefuseHeld /\ holder = d
          THEN /\ lastOut' = "refreshed" /\ lastStep' = "take" /\ lastActor' = d /\ lastKey' = 0
               /\ refuseRow' = TRUE
               /\ UNCHANGED <<holder, live, gen, twoHolders, age>>
          ELSE Refuse(d, "take", 0)

\* mill_hold_upsert with --key K on a held row (old_kh): K = MILL_HOLD_KH moves
\* the hold to the caller's desk and writes a new kh on hold_refresh (K spent);
\* any other key is refused with its row. A free row ignores K (plain Take).
TakeKey(d, k) ==
  /\ Room /\ d \in {1, 2} /\ holder # 0
  /\ priorHolder' = holder /\ priorLive' = live /\ lastExpect' = 0
  /\ steps' = steps + 1
  /\ IF k # 0 /\ k = live
     THEN /\ holder' = d
          /\ IF GuardSpendKey THEN gen' = gen + 1 /\ live' = gen + 1
                              ELSE UNCHANGED <<gen, live>>
          /\ lastOut' = "handoff" /\ lastStep' = "take_key" /\ lastActor' = d /\ lastKey' = k
          /\ refuseRow' = TRUE
          /\ UNCHANGED <<twoHolders, age>>
     ELSE Refuse(d, "take_key", k)

\* mill_hold_drop(id, desk, kh): any desk; frees only when kh is the live key.
\* Wrong, spent, or free is refused ('kept') with a hold_refuse row.
\* GuardKeyDrop off = the drop checks the desk (mill_hold_delete before 1267).
DropKey(d, k) ==
  /\ Room /\ d \in {1, 2}
  /\ priorHolder' = holder /\ priorLive' = live /\ lastExpect' = 0
  /\ lastStep' = "drop" /\ lastActor' = d /\ lastKey' = k
  /\ steps' = steps + 1
  /\ LET doRelease == holder # 0 /\ IF GuardKeyDrop THEN (k # 0 /\ k = live) ELSE holder = d
     IN IF doRelease
        THEN /\ lastOut' = "released" /\ refuseRow' = TRUE
             /\ twoHolders' = FALSE /\ age' = 0 /\ live' = 0
             /\ IF GuardDropClears THEN holder' = 0 ELSE UNCHANGED holder
             /\ UNCHANGED gen
        ELSE /\ lastOut' = "kept"
             /\ \E b \in BOOLEAN : RowWritten(b) /\ refuseRow' = b
             /\ UNCHANGED <<holder, live, gen, twoHolders, age>>

\* mill_hold_release_other: the keyless override (Python authorized it: Admin,
\* or high-trust stale), for every desk including the holder's own (no own-desk
\* 'kept' branch since card 1267). Frees only when desk_id = expect.
ReleaseOther(a, expect) ==
  /\ Room /\ a \in {1, 2} /\ expect \in {1, 2}
  /\ priorHolder' = holder /\ priorLive' = live /\ lastExpect' = expect
  /\ lastStep' = "release_other" /\ lastActor' = a /\ lastKey' = 0
  /\ steps' = steps + 1 /\ refuseRow' = TRUE /\ UNCHANGED gen
  /\ IF holder = 0
     THEN /\ lastOut' = IF GuardAlreadyFree THEN "already_free" ELSE "kept"
          /\ UNCHANGED <<holder, live, twoHolders, age>>
     ELSE IF holder # expect /\ GuardExpectHolder
          THEN /\ lastOut' = "holder_changed"
               /\ UNCHANGED <<holder, live, twoHolders, age>>
          ELSE /\ lastOut' = "released"
               /\ twoHolders' = FALSE /\ age' = 0 /\ live' = 0
               /\ IF GuardDropClears THEN holder' = 0 ELSE UNCHANGED holder

\* Time passes. With GuardAutoExpire, the step that would cross the bound frees
\* the hold instead (the old proposed fix; card 1267 keeps no expiry by design).
Tick ==
  /\ Room /\ holder # 0
  /\ priorHolder' = holder /\ priorLive' = live /\ lastExpect' = 0 /\ lastKey' = 0
  /\ steps' = steps + 1 /\ refuseRow' = TRUE /\ UNCHANGED gen
  /\ IF GuardAutoExpire /\ (age + 1 >= 3)
     THEN /\ holder' = 0 /\ live' = 0
          /\ lastOut' = "expired" /\ lastStep' = "expire" /\ lastActor' = 0
          /\ twoHolders' = FALSE /\ age' = 0
     ELSE /\ age' = age + 1 /\ lastStep' = "init" /\ lastOut' = "none"
          /\ UNCHANGED <<holder, live, lastActor, twoHolders>>

Term ==
  /\ steps >= MaxSteps
  /\ UNCHANGED vars

Keys == 0..MaxSteps

Next ==
  \/ \E d \in {1, 2}: Take(d)
  \/ \E d \in {1, 2}, k \in Keys: TakeKey(d, k)
  \/ \E d \in {1, 2}, k \in Keys: DropKey(d, k)
  \/ \E a \in {1, 2}, e \in {1, 2}: ReleaseOther(a, e)
  \/ Tick
  \/ Term

Spec == Init /\ [][Next]_vars

AtMostOneHolder == ~twoHolders

\* A take without a key gets only a free row.
TakeFromFree ==
  (lastStep = "take" /\ lastOut = "taken") => (priorHolder = 0)

\* A take of a held row never succeeds without the live key (SPIN K01/K15 twin).
NoSecondTake ==
  (lastStep = "take" /\ priorHolder # 0) => (lastOut = "refused")

\* Only the live key frees a held row, whoever presents it (SPIN K16 twin).
OnlyLiveKeyReleases ==
  (lastStep = "drop" /\ lastOut = "released") => (priorLive # 0 /\ lastKey = priorLive)

\* Only the live key moves a held row; the presented key is then spent (SPIN K27, M37).
HandoffSpendsKey ==
  (lastOut = "handoff") => (lastKey = priorLive /\ live # lastKey)

DropFreesRow ==
  (lastStep = "drop" /\ lastOut = "released") => (holder = 0)

\* Every refused take, hand-off or keyed drop has its hold_refuse row (SPIN K17).
RefusalRecorded ==
  (lastOut = "refused" \/ (lastStep = "drop" /\ lastOut = "kept")) => refuseRow

\* release-other frees only the expected holder.
ExpectGuardHolds ==
  (lastStep = "release_other" /\ lastOut = "released" /\ priorHolder # 0)
    => (priorHolder = lastExpect)

AlreadyFreeHonest ==
  (lastStep = "release_other" /\ priorHolder = 0) => (lastOut = "already_free")

\* by-construction sanity (no breakable guard; letter 4252)
DropIdempotent ==
  (lastStep = "drop" /\ priorHolder = 0) => (lastOut = "kept" /\ holder = 0)

\* Known (SPIN H11, K22 by design since card 1267): with no actor a hold stays
\* held past any bound.
NoStuckHoldPastBound ==
  ~(age >= 3 /\ holder # 0)

====
