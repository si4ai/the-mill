---
name: verify-spin-wake-holds
description: Model-check the mill wake path (push queue, webhook window, trailing POST, connect sync, seat rule) and mill hold/drop with SPIN. Use when a change touches agent_coord/server/wake.py, push.py, the /ws handler in asgi.py, records/push.py, sp_push.sql, sp_hold.sql, records/hold.py, the hold/drop handlers, client/ws.py, or the reset and retire routines in sp_join.sql and sp_name.sql, or when someone asks whether the mill can deadlock, livelock or lose a wake.
---

# Verify the wake path and holds with SPIN

## Does my change touch the modelled code?

Covered code (the sync commit is in `run.sh` as `SYNC`, currently 629c4f8):

| Model | Code |
| :--- | :--- |
| `wake.pml` | `agent_coord/server/wake.py` (`_fire`, `_gate_open`, `_gate_take`, `lease_synced`, `_coalesced`, `_send_trailing`, `trail`, `lease_done`, `post_desk`); `agent_coord/server/api/mill/rpc.py` (`_h_wake_done`); `agent_coord/server/push.py` (`emit`, `fanout`, `Hub.add`, `take_sync`, `connect_sync_frame`); `agent_coord/server/asgi.py` (`ws_endpoint`: add, sync, send; `_ws_handle_client_text` reply); `agent_coord/server/records/push.py`; `agent_coord/server/sql/sp_push.sql`; `agent_coord/client/ws.py` (busy seat, card 834) |
| `holds.pml` | `agent_coord/server/sql/sp_hold.sql`; `agent_coord/server/records/hold.py`; `agent_coord/server/api/mill/rpc.py` (`_h_hold`, `_h_drop`); `agent_coord/client/http.py` (`_refused_hold`); `agent_coord/server/sql/sp_join.sql` (`mill_join_reset`) and `sp_name.sql` (`mill_name_delete`), which free a desk's holds (card 842) |

`run.sh` prints `note: covered code changed since SYNC` when any covered file differs.

## Run

    verify/spin/run.sh            # every check, about two and a half minutes
    verify/spin/run.sh W07        # one check, with its trail
    verify/spin/run.sh --strict   # any violation fails

Needs `spin` 6.5.x (`apt-get install spin`) and gcc. Exit 0 means every
check matched its expectation in the table inside `run.sh`. Known findings
are listed there as `violated`; they are findings, not passes.

## Read a result

- `pass`: no counterexample in the whole state space of that configuration.
- `violated`: `run.sh ID` prints the trail. Read it as steps of the code:
  each line names a model line, and each model step carries a comment with
  the code line it stands for.
- A check that differs from its expectation: first decide whether the code
  changed (a real bug or a fixed finding) or the model is wrong. A model bug
  usually shows as a trail with a step the code cannot take (for example a
  window ending in the middle of the POST that opened it). Fix the model, not
  the expectation, unless the code really changed.

## Change the models when the code changes on purpose

1. Edit the model step that stands for the changed code; keep one atomic
   block per indivisible code step (one lock hold, one stored procedure).
2. Run `run.sh`. Update an expectation only when the code change explains it
   (for example a fix that turns W07 into `pass`), and say so in the commit.
3. Keep the mutations (M01-M06) failing; a mutation that passes means the
   property no longer guards anything.
4. When the models describe the code at a new commit, move `SYNC` in
   `run.sh` and the commit named in README.md forward. Only then.
