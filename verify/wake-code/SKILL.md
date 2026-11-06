---
name: verify-wake-code-guards
description: Check that the mill's wake.py and push.py control-flow guards still implement the transitions verify/spin/wake.pml and the 0.8.5 wake path assume (retry arm on push pending, drain stops retry, trailing and ring fall back to unread, sitting wake-done skips trailing, stale lease token ends nothing). Use when a change touches wake.py (post_desk, _arm_retry, _queue_drained, _send_trailing, lease_done) or push.py (ring_waiting, unread_mail_frames, desk_sitting), or when someone asks whether the real wake code still matches the model. Also reproduces card 1005 (failed unread-only wake never retried) as a known finding.
---

# Verify wake code guards against the code

## Why TLA+ here

`verify/spin/wake.pml` models the *design* of the wake path under interleaving.
The pytest wake suite covers the scenario cases. This check asks a different
question: do the *real* control-flow guards in `wake.py` and `push.py` still
implement the transitions those assume? There is no verifier that runs on the
Python itself, so this package:

1. Models each indivisible wake.py / push.py step in TLA+, with every action citing `path:lines`.
2. Ties the model to the code with `anchors.json` (marker strings that must still appear).
3. Shows each property failing on a deliberately broken copy (mutant cfg, or `--mutant` on an anchor).
4. Reproduces card 1005 as a known finding (`known/card_1005`) without weakening it.
5. Is read with the pstack `/statechart` skill (do not copy its CLI into scripts; it changes).

SPIN stays for concurrency and delivery under loss. Pytest stays for scenarios.
This check stays for code-against-spec of the cited guards.

## Does my change touch the covered code?

Sync commit (in `run.sh` as `SYNC`, currently ce115f8eb70e7e360b80974ec62e177e7771199f):

| Step | Code |
| :--- | :--- |
| Retry arm | `wake.py` `post_desk` `pending > 0` (1170); `_arm_retry` (989) |
| Drain stops retry | `wake.py` `_queue_drained` (971), pump check (1018) |
| Trailing unread | `wake.py` `_send_trailing` (695-723) |
| Ring unread | `push.py` `ring_waiting` (251-273); `unread_mail_frames` (751) |
| Sitting no trail | `wake.py` `lease_done` (812-818); `push.py` `desk_sitting` (354) |
| Stale token | `wake.py` `lease_done` (788-801) |

`run.sh` prints `note: covered code changed since SYNC` when any of those files differ.

## Properties (plain)

| Invariant | harm if broken |
| :--- | :--- |
| `RetryArmRequiresPushPending` / `NeverArmedWithoutPush` | A failed wake arms a retry with an empty push queue under current rules (or the `pending > 0` gate left the file) |
| `DrainStopsWhenPushEmpty` | A retry keeps firing after the desk drained its push queue |
| `TrailingFallsBackToUnread` | A lease end with unread mail and an empty push queue sends no wake |
| `RingFallsBackToUnread` | Leave with unread mail alone sends no wake |
| `SittingDoneSendsNoTrailing` | `mill wake-done` inside an open connect POSTs a trailing wake to the sitting desk |
| `StaleTokenEndsNothing` | A stale `mill wake-done --lease` ends a newer run's lease |
| `UnreadAloneFailedWakeIsRetried` | Desired (card 1005); **violated** by current code; not weakened |

## Run

    verify/wake-code/run.sh              # anchors + model + mutants + known
    verify/wake-code/run.sh anchors
    verify/wake-code/run.sh model
    verify/wake-code/run.sh mutant no_stale_token
    verify/wake-code/run.sh known

Needs Python 3, java 17+, `tla2tools.jar`, and the pstack `/statechart` skill (or `STATECHART_CMD`). Exit 0 means every check matched. Known findings are filed as cards, not weakened here.

## Read a result

Use `/statechart` on `verify/wake-code/Wake.tla` (config `Wake.cfg` for the
full check, or `Wake-chart.cfg` when you want `chart.mmd` under the 500-state
budget; view `view.mjs`). A state marked `breaks` names the invariant. An
anchor `FAIL` means the cited guard string left the file - treat that as a
real code change until proven otherwise.

## Change the model when the code changes on purpose

1. Edit the TLA+ action that stands for the changed step; keep one atomic step per indivisible code step.
2. Update the matching row in `anchors.json` (marker string and line hint).
3. Run `verify/wake-code/run.sh`. Keep every mutant failing. Update an expectation only when the code change explains it, and say so in the commit.
4. When card 1005 is fixed, set `GuardRetryOnUnread = TRUE` in `Wake.cfg`, move `UnreadAloneFailedWakeIsRetried` into the main invariant list, and retire `known/card_1005` as a must-break.
5. Move `SYNC` in `run.sh` and the sync commit named in this skill forward only after the model and anchors describe the code at that commit.

## Findings stay findings

When the current code breaks a desired property, report the counterexample in the code's words and file a card. Do not weaken the invariant or the model to make it pass, and do not change product code unless asked.

## Out of scope

- Concurrent lease interleaving, Hub races, PUTFIRST / ACK_AFTER_SEND (see `verify/spin/wake.pml`).
- Retry backoff timing and allowlist / public-host checks (pytest).
- Mail, todo, doing, hold, score (split cards per activity).
- CI: this check is on demand only, like `verify/spin/run.sh`.
