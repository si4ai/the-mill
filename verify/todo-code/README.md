# Todo who-may vs the 0.8.0 code (card 925)

A test checks the cases someone wrote. This check asks whether the Python CLI
and stored procedures allow only the todo transitions T1-T14 from
`docs/protocol/activity-states.md`: who may claim, assign, take over, unclaim,
pass, pass --done, pass --back, retire and reclaim.

| Piece | Role |
| :--- | :--- |
| `Todo.tla` / `Todo.cfg` | TLA+ model of each SP/CLI step, with who-may guards as CONSTANTS |
| `view.mjs` | Reader labels for `/statechart` |
| `anchors.json` + `check_anchors.py` | ties the model to marker strings in the real files |
| `mutants/*.cfg` | Each flips one guard; the matching invariant must break |
| `run.sh` | One token-free command; out of CI |
| `SKILL.md` | Project skill for the next agent |

Tool choice: TLA+ (read with `/statechart`) over a small model of the *code's*
steps, plus anchor checks on the real files. A model checker fits "can the wrong
desk ever take this step?". There is no SQL/Python verifier in-tree; generated
inputs against a live DB are left to the existing `pytest.mark.sql` suite.
SPIN (`verify/spin/todo.pml`) keeps concurrency and lock-order.

## Properties and results (model at SYNC 4ee4a34)

| Property | Result |
| :--- | :--- |
| Only the volunteer (or asker when none) may ship | proved; fails on `no_who_may_ship` |
| Only the asker or Admin may `pass --done` | proved; fails on `no_who_may_done` |
| Only the asker or volunteer may `pass --back` | proved; fails on `no_who_may_back` |
| Only the volunteer may unclaim | proved; fails on `no_who_may_unclaim` |
| Only the asker or Admin may retire/reclaim | proved; fails on `no_who_may_retire` |
| Claim without `--take-over` never lands | proved; fails on `no_claimed_by` |
| Assign only when no volunteer | proved; fails on `no_assign_empty` |
| No ordinary move on a retired card | proved; fails on `no_deleted` |
| Unpark only from parked | proved; fails on `no_unpark_status` |

Run: `verify/todo-code/run.sh`. Read results with `/statechart` on
`Todo.tla` (full check: `Todo.cfg`; chart under 500 states: `Todo-chart.cfg`,
view `view.mjs`). Finding card from this build: #927
(`create-refuses-retired-need`).

## Bounds and assumptions

- One card, four desks (`asker`, `worker`, `other`, `admin`), at most 7 steps.
- Asker always resolves (the volunteer-closes-when-asker-gone path is not modelled).
- Limited-trust Admin-only assign is not modelled as a separate guard; the empty-volunteer check is.
- Concurrent lock interleaving is out of scope (SPIN).

## Tokens

Recorded at hand-off in the PR body and in `TOKENS.txt` (build only; runs are
token-free).

## Findings

Filed as their own cards when the check surfaces a real code gap. This PR does
not fix product code.
