---- MODULE Todo ----
\* Card 925: todo transitions T1-T14 as the Python CLI and stored procedures
\* enforce them at sync commit SYNC (see run.sh). Every action cites the code
\* a reviewer can open. Who-may and status guards are CONSTANTS so a mutant
\* cfg can turn one off; the matching invariant then fails.
\*
\* Spec table: docs/protocol/activity-states.md (todo, T1-T14).
\* Code at SYNC:
\*   agent_coord/server/sql/sp_cmd.sql
\*     MILL_CARD_MOVES (58-70), cmd_claim (115-154), cmd_unclaim (157-183),
\*     cmd_pass (191-254)
\*   agent_coord/server/sql/sp_todo.sql
\*     mill_todo_insert (14-51), mill_todo_write (149-273),
\*     mill_todo_retire (350-383), mill_todo_reclaim (385-415)
\*   agent_coord/server/api/mill/rpc.py
\*     _todo_retire_one (1289-1330), _h_assign (2225-2248),
\*     _h_claim (2344+), _h_open (2453+), _h_unpark (2519+),
\*     _h_yield (2592+), _h_pass (2626+), _h_note (2686+)

EXTENDS Naturals

CONSTANTS
  MaxSteps,
  GuardWhoMayShip,     \* cmd_pass ship: volunteer (sp_cmd.sql:220-221)
  GuardWhoMayDone,     \* cmd_pass done: asker or Admin (sp_cmd.sql:225-229)
  GuardWhoMayBack,     \* cmd_pass back: asker or volunteer (sp_cmd.sql:233-235)
  GuardWhoMayUnclaim,  \* cmd_unclaim: volunteer (sp_cmd.sql:174-176)
  GuardWhoMayRetire,   \* rpc._todo_retire_one: asker or Admin (rpc.py:1304-1309)
  GuardClaimedBy,      \* cmd_claim without --take-over (sp_cmd.sql:143-144)
  GuardAssignEmpty,    \* mill_todo_write assign_guard + rpc assign (sp_todo.sql:202-206, rpc.py:2235-2236)
  GuardMovesStatus,    \* MILL_CARD_MOVES open|claimed only (sp_cmd.sql:62-65)
  GuardDeleted,        \* card:deleted under the card lock (sp_cmd.sql:137-138, sp_todo.sql:192-193)
  GuardUnparkStatus    \* card:unpark_status (sp_todo.sql:197-199)

ASSUME MaxSteps \in Nat /\ MaxSteps >= 1
ASSUME GuardWhoMayShip \in BOOLEAN
ASSUME GuardWhoMayDone \in BOOLEAN
ASSUME GuardWhoMayBack \in BOOLEAN
ASSUME GuardWhoMayUnclaim \in BOOLEAN
ASSUME GuardWhoMayRetire \in BOOLEAN
ASSUME GuardClaimedBy \in BOOLEAN
ASSUME GuardAssignEmpty \in BOOLEAN
ASSUME GuardMovesStatus \in BOOLEAN
ASSUME GuardDeleted \in BOOLEAN
ASSUME GuardUnparkStatus \in BOOLEAN

Statuses == {"none", "parked", "open", "claimed", "shipped", "done"}
\* Desks that act on the card. asker created it; worker is the usual volunteer;
\* other is a third desk; admin is Admin (is_role_admin).
Desks == {"asker", "worker", "other", "admin"}
Volunteers == {"none", "asker", "worker", "other", "admin"}

T1 == 1
T2 == 2
T3 == 3
T4 == 4
T5 == 5
T6 == 6
T7 == 7
T8 == 8
T9 == 9
T10 == 10
T11 == 11
T12 == 12
T13 == 13
T14 == 14

VARIABLES
  status,     \* todo.status
  retired,    \* activity.deleted IS NOT NULL
  vol,        \* todo.assigned_id as desk name, or "none"
  priorVol,   \* volunteer before the last WriteMove (for who-may checks)
  priorStatus, \* status before the last WriteMove
  act,        \* activity.act as transition id
  laststep,   \* last committed transition id
  lastActor,  \* desk that committed the last step
  tookWithoutFlag, \* TRUE after a claim that skipped --take-over (mutant only)
  moves,      \* count of move rows (status or volunteer change)
  steps

vars == <<status, retired, vol, priorVol, priorStatus, act, laststep, lastActor, tookWithoutFlag, moves, steps>>

TypeOK ==
  /\ status \in Statuses
  /\ retired \in BOOLEAN
  /\ vol \in Volunteers
  /\ priorVol \in Volunteers
  /\ priorStatus \in Statuses
  /\ act \in 0..14
  /\ laststep \in 0..14
  /\ lastActor \in Desks \union {"none"}
  /\ tookWithoutFlag \in BOOLEAN
  /\ moves \in Nat
  /\ steps \in Nat

Live == ~retired
HasCard == status # "none"
Room == steps < MaxSteps
IsAdmin(d) == d = "admin"

\* ---- writers (one indivisible SP write under the card lock) ----

WriteMove(a, actor, nst, nvol) ==
  /\ status' = nst
  /\ priorVol' = vol
  /\ priorStatus' = status
  /\ vol' = nvol
  /\ moves' = moves + 1
  /\ act' = a
  /\ laststep' = a
  /\ lastActor' = actor
  /\ tookWithoutFlag' = FALSE
  /\ steps' = steps + 1
  /\ UNCHANGED retired

FlagStep(a, actor) ==
  /\ act' = a
  /\ laststep' = a
  /\ lastActor' = actor
  /\ tookWithoutFlag' = FALSE
  /\ steps' = steps + 1
  /\ UNCHANGED <<status, vol, priorVol, priorStatus, moves, retired>>

Init ==
  /\ status = "none"
  /\ retired = FALSE
  /\ vol = "none"
  /\ priorVol = "none"
  /\ priorStatus = "none"
  /\ act = 0
  /\ laststep = 0
  /\ lastActor = "none"
  /\ tookWithoutFlag = FALSE
  /\ moves = 0
  /\ steps = 0

\* T1 create todo -> open
\* code: rpc.py:_h_open -> sp_todo.sql:14 mill_todo_insert
T1_File(d) ==
  /\ Room /\ ~HasCard /\ d \in Desks
  /\ WriteMove(T1, d, "open", "none")

\* T2 create todo --status parked
\* code: rpc.py:_h_open (parked) -> sp_todo.sql:14
T2_Park(d) ==
  /\ Room /\ ~HasCard /\ d \in Desks
  /\ WriteMove(T2, d, "parked", "none")

\* T3 unpark: parked -> open
\* code: rpc.py:_h_unpark -> mill_todo_write; GuardUnparkStatus = sp_todo.sql:197-199
T3_Unpark(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ IF GuardUnparkStatus
     THEN status = "parked"
     ELSE status \in {"parked", "claimed", "shipped", "done"}
  /\ WriteMove(T3, d, "open", vol)

\* T4 claim: open -> claimed by caller
\* code: rpc.py:_h_claim -> sp_cmd.sql:115 cmd_claim; MILL_CARD_MOVES (58-70)
T4_Claim(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ IF GuardMovesStatus
     THEN status = "open"
     ELSE status \in {"open", "parked", "shipped", "done"}
  /\ vol = "none"
  /\ WriteMove(T4, d, "claimed", d)

\* T5 assign: open (or claimed with no volunteer) -> claimed by named desk
\* code: rpc.py:_h_assign (2225); mill_todo_write assign_guard (sp_todo.sql:202-206)
\* Model: the assigner is asker or admin (limited-trust Admin; high trust any desk
\* is out of scope of who-may on the card itself — GuardAssignEmpty is the empty-vol check).
T5_Assign(d, peer) ==
  /\ Room /\ Live /\ d \in Desks /\ peer \in Desks
  /\ IF GuardAssignEmpty
     THEN /\ status \in {"open", "claimed"}
          /\ vol = "none"
     ELSE TRUE
  /\ IF GuardMovesStatus
     THEN status \in {"open", "claimed"}
     ELSE TRUE
  /\ WriteMove(T5, d, "claimed", peer)

\* T6 claim --take-over: claimed by another -> claimed by caller
\* code: sp_cmd.sql:143-147 (claimed_by / stale_prior)
T6_TakeOver(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ status = "claimed"
  /\ vol # "none" /\ vol # d
  /\ WriteMove(T6, d, "claimed", d)

\* Illegal claim without --take-over while another holds it.
\* When GuardClaimedBy is TRUE this action is disabled; when FALSE it succeeds (mutant).
T6_StealNoFlag(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ status = "claimed"
  /\ vol # "none" /\ vol # d
  /\ ~GuardClaimedBy
  /\ status' = "claimed"
  /\ priorVol' = vol
  /\ priorStatus' = status
  /\ vol' = d
  /\ moves' = moves + 1
  /\ act' = T6
  /\ laststep' = T6
  /\ lastActor' = d
  /\ tookWithoutFlag' = TRUE
  /\ steps' = steps + 1
  /\ UNCHANGED retired

\* T7 unclaim: claimed -> open, volunteer only
\* code: sp_cmd.sql:157 cmd_unclaim; who_may_unclaim at 174-176
T7_Unclaim(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ status = "claimed"
  /\ IF GuardWhoMayUnclaim THEN vol = d ELSE TRUE
  /\ IF GuardMovesStatus THEN status = "claimed" ELSE TRUE
  /\ WriteMove(T7, d, "open", "none")

\* T8 pass (ship): claimed (or open with volunteer) -> shipped, volunteer
\* code: sp_cmd.sql:215-222
T8_Ship(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ \/ status = "claimed"
     \/ (status = "open" /\ vol # "none")
  /\ IF GuardWhoMayShip
     THEN \/ vol = d
          \/ (vol = "none" /\ d = "asker")
     ELSE TRUE
  /\ WriteMove(T8, d, "shipped", vol)

\* T9 pass --done: shipped -> done, asker or Admin
\* (volunteer only when asker does not resolve — modelled as asker always resolves)
\* code: sp_cmd.sql:224-230
T9_Done(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ status = "shipped"
  /\ IF GuardWhoMayDone
     THEN \/ d = "asker"
          \/ IsAdmin(d)
     ELSE TRUE
  /\ WriteMove(T9, d, "done", vol)

\* T10 pass --back from done -> shipped, asker or volunteer
\* code: sp_cmd.sql:232-236
T10_Back(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ status = "done"
  /\ IF GuardWhoMayBack
     THEN \/ d = "asker"
          \/ d = vol
     ELSE TRUE
  /\ WriteMove(T10, d, "shipped", vol)

\* T11 pass --back from shipped -> claimed (or open if no volunteer)
\* code: sp_cmd.sql:232-236
T11_Back(d) ==
  /\ Room /\ Live /\ d \in Desks
  /\ status = "shipped"
  /\ IF GuardWhoMayBack
     THEN \/ d = "asker"
          \/ d = vol
     ELSE TRUE
  /\ IF vol # "none"
     THEN WriteMove(T11, d, "claimed", vol)
     ELSE WriteMove(T11, d, "open", vol)

\* T12 retire todo: any status -> retired, asker or Admin
\* code: rpc.py:1289-1330; sp_todo.sql:350 mill_todo_retire
T12_Retire(d) ==
  /\ Room /\ HasCard /\ Live /\ d \in Desks
  /\ IF GuardWhoMayRetire
     THEN \/ d = "asker"
          \/ IsAdmin(d)
     ELSE TRUE
  /\ IF GuardDeleted THEN ~retired ELSE TRUE
  /\ retired' = TRUE
  /\ act' = T12
  /\ laststep' = T12
  /\ lastActor' = d
  /\ steps' = steps + 1
  /\ tookWithoutFlag' = FALSE
  /\ UNCHANGED <<status, vol, priorVol, priorStatus, moves>>

\* T13 reclaim todo: retired -> prior status, asker or Admin
\* code: rpc.py:1289-1330; sp_todo.sql:385 mill_todo_reclaim
T13_Reclaim(d) ==
  /\ Room /\ HasCard /\ retired /\ d \in Desks
  /\ IF GuardWhoMayRetire
     THEN \/ d = "asker"
          \/ IsAdmin(d)
     ELSE TRUE
  /\ retired' = FALSE
  /\ act' = T13
  /\ laststep' = T13
  /\ lastActor' = d
  /\ tookWithoutFlag' = FALSE
  /\ steps' = steps + 1
  /\ UNCHANGED <<status, vol, priorVol, priorStatus, moves>>

\* T14 note: status unchanged
\* code: rpc.py:_h_note -> mill_todo_write body only
T14_Note(d) ==
  /\ Room /\ HasCard /\ Live /\ d \in Desks
  /\ IF GuardDeleted THEN ~retired ELSE TRUE
  /\ FlagStep(T14, d)

\* A retired card's ordinary moves are refused under the card lock when GuardDeleted.
\* Mutant: allow a claim on a retired card.
T4_ClaimRetired(d) ==
  /\ Room /\ HasCard /\ retired /\ d \in Desks
  /\ ~GuardDeleted
  /\ status = "open"
  /\ WriteMove(T4, d, "claimed", d)

Term ==
  /\ steps >= MaxSteps
  /\ UNCHANGED vars

Next ==
  \/ \E d \in Desks: T1_File(d)
  \/ \E d \in Desks: T2_Park(d)
  \/ \E d \in Desks: T3_Unpark(d)
  \/ \E d \in Desks: T4_Claim(d)
  \/ \E d, peer \in Desks: T5_Assign(d, peer)
  \/ \E d \in Desks: T6_TakeOver(d)
  \/ \E d \in Desks: T6_StealNoFlag(d)
  \/ \E d \in Desks: T7_Unclaim(d)
  \/ \E d \in Desks: T8_Ship(d)
  \/ \E d \in Desks: T9_Done(d)
  \/ \E d \in Desks: T10_Back(d)
  \/ \E d \in Desks: T11_Back(d)
  \/ \E d \in Desks: T12_Retire(d)
  \/ \E d \in Desks: T13_Reclaim(d)
  \/ \E d \in Desks: T14_Note(d)
  \/ \E d \in Desks: T4_ClaimRetired(d)
  \/ Term

Spec == Init /\ [][Next]_vars

\* ---- properties (plain sentences in README / SKILL) ----

\* Only the volunteer (or asker when none) may ship.
OnlyVolunteerShips ==
  (laststep = T8) => (lastActor = priorVol \/ (priorVol = "none" /\ lastActor = "asker"))

\* Only the asker or Admin may pass --done.
OnlyAskerOrAdminDones ==
  (laststep = T9) => (lastActor = "asker" \/ lastActor = "admin")

\* Only the asker or the volunteer may pass --back.
OnlyAskerOrVolBacks ==
  (laststep \in {T10, T11}) => (lastActor = "asker" \/ lastActor = priorVol)

\* Only the volunteer may unclaim.
OnlyVolunteerUnclaims ==
  (laststep = T7) => (lastActor = priorVol)

\* Only the asker or Admin may retire or reclaim.
OnlyAskerOrAdminRetires ==
  (laststep \in {T12, T13}) => (lastActor = "asker" \/ lastActor = "admin")

\* A take-over without the flag never lands when GuardClaimedBy is on
\* (modelled by disabling T6_StealNoFlag). When a take-over lands, the actor
\* becomes the volunteer.
TakeOverSetsVolunteer ==
  (laststep = T6) => (lastActor = vol /\ priorVol # lastActor)

\* A claim that skipped --take-over never lands (sp_cmd.sql:143-144).
NeverTookWithoutFlag ==
  ~tookWithoutFlag

\* Assign only when there is no volunteer (rpc.py:2235; sp_todo.sql:202-206).
AssignOnlyWhenEmpty ==
  (laststep = T5) => (priorVol = "none")

\* Claimed cards have a volunteer.
ClaimedHasVolunteer ==
  (status = "claimed" /\ ~retired) => vol # "none"

\* Open cards have no volunteer (non-migrated).
OpenHasNoVolunteer ==
  (status = "open" /\ ~retired) => vol = "none"

\* A retired card keeps its status; ordinary moves do not run on it when GuardDeleted.
RetiredKeepsStatus ==
  retired => status \in {"parked", "open", "claimed", "shipped", "done"}

\* Ordinary card moves do not run on a retired card (card:deleted).
NoOrdinaryMoveWhileRetired ==
  retired => laststep \in {0, T12, T13}

\* Unpark only from parked when GuardUnparkStatus.
UnparkFromParked ==
  (laststep = T3) => (status = "open" /\ priorStatus = "parked")

====
