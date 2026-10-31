---
name: verify-todo-code-who-may
description: Check that the mill's Python CLI and stored procedures allow only the 0.8.0 todo transitions T1-T14 (who may claim, assign, take over, unclaim, pass, pass --done, pass --back, retire, reclaim). Use when a change touches sp_cmd.sql (cmd_claim, cmd_unclaim, cmd_pass, MILL_CARD_MOVES), sp_todo.sql (mill_todo_write, mill_todo_retire, mill_todo_reclaim), or api/mill/rpc.py (_h_claim, _h_assign, _h_yield, _h_pass, _h_unpark, _todo_retire_one, _h_note), or when someone asks whether the wrong desk can move a card.
---

# Verify todo who-may (T1-T14) against the code

## Why TLA+ here

The existing `verify/spin/todo.pml` models the *design* of card moves under the card lock. This check asks a different question: do the *real* CLI handlers and stored procedures enforce the who-may and status guards of T1-T14? There is no verifier that runs on the SQL/Python themselves, so this package:

1. Models each indivisible SP/CLI step in TLA+, with every action citing `path:lines`.
2. ties the model to the code with `anchors.json` (marker strings that must still appear).
3. Shows each property failing on a deliberately broken copy (mutant cfg, or `--mutant` on an anchor).
4. Is read with the pstack `/statechart` skill (do not copy its CLI into scripts; it changes).

SPIN stays for concurrency and lock-order. This check stays for who-may and the T1-T14 edge set.

## Does my change touch the covered code?

Sync commit (in `run.sh` as `SYNC`, currently 4ee4a347ebc141fe27648cf4e72e56c7a9d8160b):

| Step | Code |
| :--- | :--- |
| T1, T2 create | `rpc.py` `_h_open`; `sp_todo.sql` `mill_todo_insert` |
| T3 unpark | `rpc.py` `_h_unpark`; `sp_todo.sql` `card:unpark_status` in `mill_todo_write` |
| T4 claim | `rpc.py` `_h_claim`; `sp_cmd.sql` `cmd_claim`, `MILL_CARD_MOVES`, `card:claimed_by`, `card:deleted` |
| T5 assign | `rpc.py` `_h_assign`; `sp_todo.sql` `card:assign_guard` |
| T6 take-over | `sp_cmd.sql` `cmd_claim` take-over / `card:stale_prior` |
| T7 unclaim | `rpc.py` `_h_yield`; `sp_cmd.sql` `cmd_unclaim`, `card:who_may_unclaim` |
| T8 ship | `rpc.py` `_h_pass`; `sp_cmd.sql` `cmd_pass` ship, `card:who_may_ship` |
| T9 done | `sp_cmd.sql` `cmd_pass` done, `card:who_may_done` |
| T10, T11 back | `sp_cmd.sql` `cmd_pass` back, `card:who_may_back` |
| T12 retire | `rpc.py` `_todo_retire_one`; `sp_todo.sql` `mill_todo_retire` |
| T13 reclaim | `rpc.py` `_todo_retire_one`; `sp_todo.sql` `mill_todo_reclaim` |
| T14 note | `rpc.py` `_h_note`; `sp_todo.sql` `mill_todo_write` body only |

`run.sh` prints `note: covered code changed since SYNC` when any of those files differ.

## Properties (plain)

| Invariant | harm if broken |
| :--- | :--- |
| `OnlyVolunteerShips` | A non-volunteer ships someone else's card |
| `OnlyAskerOrAdminDones` | A random desk closes a card with `pass --done` |
| `OnlyAskerOrVolBacks` | A stranger steps a card back |
| `OnlyVolunteerUnclaims` | A stranger empties the volunteer |
| `OnlyAskerOrAdminRetires` | A stranger retires or reclaims a card |
| `NeverTookWithoutFlag` | A desk takes a claimed card without `--take-over` |
| `AssignOnlyWhenEmpty` | Assign overwrites a volunteer |
| `NoOrdinaryMoveWhileRetired` | A retired card still moves |
| `UnparkFromParked` | Unpark rewrites a non-parked card to open |
| `ClaimedHasVolunteer` / `OpenHasNoVolunteer` | Status and volunteer disagree |

## Run

    verify/todo-code/run.sh              # anchors + model + mutants
    verify/todo-code/run.sh anchors
    verify/todo-code/run.sh model
    verify/todo-code/run.sh mutant no_who_may_done

Needs Python 3, java 17+, `tla2tools.jar`, and the pstack `/statechart` skill (or `STATECHART_CMD`). Exit 0 means every check matched. Known findings are filed as cards, not weakened here.

## Read a result

Use `/statechart` on `verify/todo-code/Todo.tla` (config `Todo.cfg` for the
full check, or `Todo-chart.cfg` when you want `chart.mmd` under the 500-state
budget; view `view.mjs`). A state marked `breaks` names the invariant. Replay the path as mill commands: create, claim, pass, pass --done, and so on. An anchor `FAIL` means the cited guard string left the file - treat that as a real code change until proven otherwise.

## Change the model when the code changes on purpose

1. Edit the TLA+ action that stands for the changed SP/CLI step; keep one atomic step per indivisible code step (one stored procedure under the card lock, or one rpc handler guard).
2. Update the matching row in `anchors.json` (marker string and line hint).
3. Run `verify/todo-code/run.sh`. Keep every mutant failing. Update an expectation only when the code change explains it, and say so in the commit.
4. Move `SYNC` in `run.sh` and the sync commit named in this skill forward only after the model and anchors describe the code at that commit.

## Findings stay findings

When the current code breaks a property, report the counterexample in the code's words and file a card. Do not weaken the invariant or the model to make it pass, and do not change product code unless asked.

## Out of scope

- Concurrent card-lock interleaving (see `verify/spin/todo.pml`).
- Mail, doing, hold, score, name (split cards per activity; start was todo).
- CI: this check is on demand only, like `verify/spin/run.sh`.
