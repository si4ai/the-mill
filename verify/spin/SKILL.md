---
name: verify-spin-wake-holds
description: Model-check the mill wake path, holds, and 0.8.0 activities (mail, todo, doing, score, name) with SPIN. Use when a change touches agent_coord/server/wake.py, push.py, the /ws handler in asgi.py, records/push.py, sp_push.sql, sp_hold.sql, records/hold.py, the hold/drop handlers, client/ws.py, the reset and retire routines, or the 0.8.0 activity writers (sp_todo.sql, sp_cmd.sql, sp_doing.sql, sp_opened.sql, sp_score.sql, sp_beta_name.sql, fn_name.sql, mill/rpc.py), or when someone asks whether the mill can deadlock, livelock, lose a wake, or break an activity invariant.
---

# Verify the mill with SPIN

## Does my change touch the modelled code?

Covered code (the sync commits are in `run.sh`: `SYNC` for wake and holds, `SYNC_080` for the 0.8.0 activities):

| Model | Code |
| :--- | :--- |
| `wake.pml` | `agent_coord/server/wake.py` (`_fire`, `_gate_open`, `_gate_take`, `gate_clear`, `_coalesced`, `trail`, `post_desk`); `agent_coord/server/push.py` (`emit`, `fanout`, `Hub.add`, `take_sync`, `connect_sync_frame`); `agent_coord/server/asgi.py` (`ws_endpoint`: add, sync, send; `_ws_handle_client_text` reply); `agent_coord/server/records/push.py`; `agent_coord/server/sql/sp_push.sql`; `agent_coord/client/ws.py` (busy seat, card 834) |
| `holds.pml` | `agent_coord/server/sql/sp_hold.sql`; `agent_coord/server/records/hold.py`; `agent_coord/server/api/mill/rpc.py` (`_h_hold`, `_h_drop`); `agent_coord/client/http.py` (`_refused_hold`); `agent_coord/server/sql/sp_join.sql` (`mill_join_reset`) and `sp_name.sql` / `sp_beta_name.sql` (`mill_name_delete` / `sp_name_retire`), which free a desk's holds (card 842) |
| `todo.pml` | `sp_todo.sql` (`mill_todo_write`, retire, reclaim); `sp_cmd.sql` (`cmd_claim`, `cmd_unclaim`, `cmd_pass`); `api/mill/rpc.py` (`_h_assign`, `_h_unpark`) |
| `doing.pml` | `sp_doing.sql` (`mill_doing_put`, `mill_doing_finish`, `mill_doing_end`); `sp_join.sql` (join, reset, heartbeats); `sp_hold.sql` (take, drop, release desk); `sp_todo.sql` / `sp_cmd.sql` (card moves that write doing); `sp_beta_name.sql` (retire); `api/mill/rpc.py` (`_doing_finish`, `_doing_after`) |
| `mail.pml` | `sp_opened.sql` (`mill_mail_open`); `sp_mail.sql` (send, reply, add, remove) |
| `score.pml` | `sp_score.sql` (score, target, retire, revive, Wall writers) |
| `name.pml` | `sp_beta_name.sql` (`sp_name_retire`, `sp_name_reclaim`); `fn_name.sql` (`MILL_NAME_PUT`); `sp_join.sql` (`mill_join_upsert`, `mill_join_reset`) |

`run.sh` prints `note: covered code changed since SYNC` (or `SYNC_080`) when any covered file differs from the pin.

## Run

    verify/spin/run.sh            # every check, about seven minutes
    verify/spin/run.sh W07        # one check, with its trail
    verify/spin/run.sh --strict   # any violation fails

Needs `spin` 6.5.x (`apt-get install spin`) and gcc. Exit 0 means every
check matched its expectation in the table inside `run.sh`. Known findings
and deliberate mutations are listed there as `violated`; they are findings
or mutants, not passes.

## Read a result

- `pass`: no counterexample in the whole state space of that configuration.
- `violated`: `run.sh ID` prints the trail. Read it as steps of the code:
  each line names a model line, and each model step carries a comment with
  the code line it stands for.
- A check that differs from its expectation: first decide whether the code
  changed (a real bug or a fixed finding) or the model is wrong. A model bug
  usually shows as a trail with a step the code cannot take. Fix the model, not
  the expectation, unless the code really changed.

## Pins

| Pin | In `run.sh` | What it is |
| :--- | :--- | :--- |
| `SYNC` | wake and holds | the commit the wake and hold models last matched |
| `DOC_080` | 0.8.0 design | `docs/requirements/beta/activity-states-080.md` (PR #226) |
| `SYNC_080` | 0.8.0 code | release/0.8.0 lane B head the activity models last matched |

When the models describe the code at a new commit, move the pin in `run.sh`
and the commit named in `README.md` forward. Only then.

## Change the models when the code changes on purpose

1. Edit the model step that stands for the changed code; keep one atomic
   block per indivisible code step (one lock hold, one stored procedure).
2. Run `run.sh`. Update an expectation only when the code change explains it
   (for example a fix that turns a FINDING into `pass`), and say so in the
   commit. Keep the old-shape mutant (`-DSwitch=0` or a `MUT_*` define)
   failing so the property still guards something.
3. Keep the mutations (M01-M20) failing; a mutation that passes means the
   property no longer guards anything.
4. Key the 0.8.0 models on transition ids (T4, D8, H5, ...), not on the
   spelling of the act. Acts and CLI verbs can rename; the ids stay.
5. When the models describe the code at a new commit, move `SYNC` or
   `SYNC_080` and the commit named in `README.md` forward. Only then.

## Expected results (summary)

Wake and holds: see the results table in `README.md` (W01-W24, H01-H13,
M01-M05). Findings 1-3 are fixed on main; W23 and W24 keep the old orders
failing.

0.8.0 activities at `SYNC_080` (lane B): every check in the `T*`, `D*`,
`E*`, `S*`, `N*`, `R*` and `M08`-`M20` rows of `run.sh` matches its
expectation. Switches default to the fixed code; a `-DSwitch=0` or `MUT_*`
row is the pre-fix shape and must stay `violated`. One finding stays open
at the current pin: N03 (join of a retired name is still a plain read in
`MILL_NAME_PUT`).
