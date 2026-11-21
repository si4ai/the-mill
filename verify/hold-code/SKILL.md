---
name: verify-hold-code-recovery
description: Check that the mill's hold take, keyed drop, hand-off and release_other guards still enforce at most one holder, no second take, only the live release key frees or hands off (and is then spent), refusal rows in the refusing transaction, expect-holder and already-free honesty on release-other, and drop idempotence, and that the known no-TTL stuck-hold finding still reproduces. Use when a change touches sp_hold.sql MILL_HOLD_KH/mill_hold_upsert/mill_hold_drop/release_desk/release_other, records/hold.py may_drop_other/delete_other/drop, helpers/hold_key.py, or when someone asks whether two desks can both hold, a stale renew can extend another's hold, force-take can orphan a row, or a crashed holder blocks forever.
---

# verify hold mutex and release-other against the code

## Why TLA+ here

`verify/spin/holds.pml` models concurrent policies and the H01-H13 matrix.
Pytest covers F223 Admin/stale drop. This check asks whether the *real* SQL
and Python markers still enforce the mutex and release-other race guards
those assume. Package:

1. Models each indivisible take/drop/release-other step in TLA+, citing `path:lines`.
2. Ties the model to the code with `anchors.json`.
3. Shows each property failing on a deliberately broken copy.
4. Re-anchors the known no-TTL finding and a proposed auto-expire fix cfg.
5. Is read with the pstack `/statechart` skill.

## does my change touch the covered code?

Sync commit (in `run.sh` as `SYNC`, currently 047b9f50feff2928b96b04aa755d099c30ac350f,
PR #490 head, card 1267; not merged: run with `HOLD_CODE_ROOT` set to a
checkout of it until it lands):

- take, hand-off and refusal row: `sp_hold.sql` `mill_hold_upsert`
- live key: `sp_hold.sql` `MILL_HOLD_KH`; key hash: `helpers/hold_key.py`
- keyed drop and its refusal row: `sp_hold.sql` `mill_hold_drop`
- release-other expect / already free / no own-desk kept: `sp_hold.sql` `mill_hold_release_other`
- keyed or keyless drop routing and the stale age gate: `records/hold.py` `drop`, `may_drop_other`

## properties (plain)

- `AtMostOneHolder` / `TakeFromFree`: two holders, or a take that overwrote another desk
- `NoSecondTake`: a take of a held row succeeded without the live key (the old same-desk refresh)
- `OnlyLiveKeyReleases` / `DropFreesRow` / `DropIdempotent`: a drop without the live key frees, or a drop leaves the row held / invents a holder on free
- `HandoffSpendsKey`: after a hand-off the presented key still works
- `RefusalRecorded`: a refused take, hand-off or keyed drop has no refusal row
- `ExpectGuardHolds`: release-other frees a row whose holder was not the expected desk
- `AlreadyFreeHonest`: release-other on a free row does not report already_free
- `NoStuckHoldPastBound` (known): a hold stays held past the age bound with no actor

## Run

    verify/hold-code/run.sh
    verify/hold-code/run.sh anchors
    verify/hold-code/run.sh model
    verify/hold-code/run.sh mutant no_take_free
    HOLD_CODE_ROOT=DIR verify/hold-code/run.sh   # another checkout
    verify/hold-code/run.sh known

## Read a result

Use `/statechart` on `verify/hold-code/Hold.tla` (config `Hold.cfg`, or
`Hold-chart.cfg` for a small chart; view `view.mjs`).

## Change the model when the code changes on purpose

1. Edit the TLA+ action for the changed step.
2. Update `anchors.json`.
3. Run `verify/hold-code/run.sh`. Keep every mutant failing; keep known no_ttl
   violated until product adds expiry.
4. Move `SYNC` forward only after the model and anchors match that commit.

## findings stay findings

Report counterexamples as cards. Do not weaken invariants. Do not change
product code unless asked.

## Out of scope

- Concurrent policy search (SPIN H04-H08). Waiter starvation (SPIN H09).
- F223 Admin/stale authorization scenarios (pytest).
- SPIN doc lag on release_other (card 941).
- CI: on demand only.
