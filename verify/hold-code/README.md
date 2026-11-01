# Hold mutex and release-other vs the 0.8.5 code (card 925)

The mill is middleware; the CLI is its API. This check prioritises deadlock and
liveness over feature behaviour: at most one holder, own-drop and release-other
race guards, drop idempotence, and the known no-TTL stuck-hold finding.

- `Hold.tla` / `Hold.cfg`: TLA+ model of take/drop/release-other/tick, guards as CONSTANTS
- `view.mjs`: reader labels for `/statechart`
- `anchors.json` + `check_anchors.py`: ties the model to marker strings in the real files
- `mutants/*.cfg`: each flips one guard; the matching invariant must break
- `known/`: no-TTL finding still violates; proposed auto-expire passes
- `run.sh`: one token-free command; out of CI
- `SKILL.md`: project skill for the next agent

Tool choice: TLA+ (read with `/statechart`) over a small model of the *code's*
steps, plus anchor checks. SPIN (`verify/spin/holds.pml`) keeps concurrent
hold policies and the H01-H13 matrix. The pytest hold suite keeps F223 admin /
stale drop scenarios. This package keeps the SQL/Python *markers* those assume.

## orthogonality

- `AtMostOneHolder` / `TakeFromFreeOrRefresh`: SPIN H01/H02 (design search) and
  M03 (no FOR UPDATE); this check keeps `desk_id IS NULL` on take
  (`sp_hold.sql:74`) and the seat-then-hold `FOR UPDATE` (`sp_hold.sql:56-59`).
- `OnlyOwnerDropReleases` / `DropFreesRow` / `DropIdempotent`: SPIN owner-drop
  policy; this check keeps `desk_id = v_desk` on delete (`sp_hold.sql:137`).
- `ExpectGuardHolds` / `AlreadyFreeHonest`: F223 pytest
  (`tests/server/records/test_admin_drop_hold_931.py`) covers Admin/stale
  scenarios; this check keeps `desk_id = v_expect` (`sp_hold.sql:232`),
  `holder changed` (`sp_hold.sql:228`), and `already free` (`sp_hold.sql:221`).
- `NoStuckHoldPastBound` (known): SPIN H11 (no TTL) already violated; this check
  reproduces the no-TTL stuck-hold finding in the model and shows a proposed
  `GuardAutoExpire` fix cfg. Starvation of waiters (SPIN H09) stays with SPIN
  (mill never queues; refuse at once).

Dropped as duplicates: concurrent policy search (SPIN H04-H08), reset/retire
release_desk scenarios (SPIN H12/H13, card 842), F223 Admin/stale pytest paths,
doing-hold move rows (doing.pml H1-H5), CLI refuse-exit (`test_hold_exit.py`).

Card 941 (`hold-admin-drop-unmodelled`) tracks SPIN still stating owner-only
drop while `mill_hold_release_other` exists; this PR does not rewrite
`holds.pml`.

## properties and results (model at sync ce115f8)

- at most one holder / take only from free: proved; fails on `no_take_free`
- only the owner drop releases; drop frees the row: proved; fails on `no_own_drop` / `no_drop_clears`
- drop on free is honest (`DropIdempotent`): by-construction sanity (no breakable guard; letter 4252)
- release-other frees only the expected holder: proved; fails on `no_expect`
- already-free is honest: proved; fails on `no_already_free`
- no stuck hold past bound: **known violated** (no TTL); proposed `no_ttl_fixed` passes

Run: `verify/hold-code/run.sh`. Read results with `/statechart` on `Hold.tla`.

## bounds and assumptions

- One resource, two desks, at most 6 steps; age bound 3 for the no-TTL check.
- Concurrent interleaving of two upserts is out of scope (SPIN).
- may-drop-other / stale-days anchors are presence-only; auth out of scope beyond them (B8 info-only).
- Admin/stale *authorization* (`may_drop_other`) is out of scope beyond anchors;
  the model assumes an authorized release-other call.
- Waiter starvation stays with SPIN H09 (no queue in product).


## anchor rule (card 1014)

each marker is the real guard line plus its first effect line. markers must not sit on a comment, import, or message line. every anchor has a self-mutant; `run.sh anchors` goes red for each. also anchor what the caller observes (result rows and fields the client reads: op/ok/reason), not just the guards (letter 4267). `STATECHART_CMD` overrides host path discovery.
## Tokens

Recorded at hand-off in the PR body and in `TOKENS.txt` (build only; runs are
token-free).

## findings

- no auto-expire / no TTL: re-anchored here as `known/no_ttl` (same class as
  SPIN H11). Filed as card 1013 (`hold-no-auto-expire`, loop:2). The known check is model-side (letter 4252); a product TTL would need a new code anchor.
- card 941 remains for SPIN/docs lag on release_other.
