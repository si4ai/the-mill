---
name: verify-hold-code-recovery
description: Check that the mill's hold upsert/delete/release_other guards still enforce at most one holder, owner-only drop, expect-holder and already-free honesty on release-other, and drop idempotence, and that the known no-TTL stuck-hold finding still reproduces. Use when a change touches sp_hold.sql mill_hold_upsert/delete/release_desk/release_other, records/hold.py may_drop_other/delete_other/drop, or when someone asks whether two desks can both hold, a stale renew can extend another's hold, force-take can orphan a row, or a crashed holder blocks forever.
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

Sync commit (in `run.sh` as `SYNC`, currently ce115f8eb70e7e360b80974ec62e177e7771199f):

- take when free: `sp_hold.sql` `mill_hold_upsert` (74)
- own drop: `sp_hold.sql` `mill_hold_delete` (137)
- release-other expect / already free: `sp_hold.sql` `mill_hold_release_other` (221, 228, 232)
- stale age gate: `hold.py` `may_drop_other` (199, 217)

## properties (plain)

- `AtMostOneHolder` / `TakeFromFreeOrRefresh`: two holders, or a take that overwrote another desk
- `OnlyOwnerDropReleases` / `DropFreesRow` / `DropIdempotent`: a non-owner drop frees, or a drop leaves the row held / invents a holder on free
- `ExpectGuardHolds`: release-other frees a row whose holder was not the expected desk
- `AlreadyFreeHonest`: release-other on a free row does not report already_free
- `NoStuckHoldPastBound` (known): a hold stays held past the age bound with no actor

## Run

    verify/hold-code/run.sh
    verify/hold-code/run.sh anchors
    verify/hold-code/run.sh model
    verify/hold-code/run.sh mutant no_take_free
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
