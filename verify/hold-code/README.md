# Hold mutex, one-use release key and release-other vs the code (cards 925, 1267)

The mill is middleware; the CLI is its API. This check prioritises deadlock and
liveness over feature behaviour: at most one holder, no second take, only the
live release key frees or hands off a hold, every refusal has its row in the
refusing transaction, the release-other race guards, drop idempotence, and the
known no-TTL stuck-hold finding (no expiry is by design since card 1267).

**Code of record: PR #490 (card 1267), landed on release/0.8.16 as a9d5f2e.**
`SYNC` in `run.sh` is 047b9f5, the head the anchors were written against;
later #490 commits changed refusal text and docs only. Run
`verify/hold-code/run.sh` from this checkout.

- `Hold.tla` / `Hold.cfg`: TLA+ model of take, hand-off take, keyed drop,
  release-other, tick; guards as CONSTANTS
- `view.mjs`: reader labels for `/statechart`
- `anchors.json` + `check_anchors.py`: ties the model to marker strings in the real files
- `mutants/*.cfg`: each flips one guard; the matching invariant must break
- `known/`: no-TTL finding still violates; the old auto-expire cfg passes
- `run.sh`: one token-free command; out of CI; `HOLD_CODE_ROOT` picks the checkout
- `SKILL.md`: project skill for the next agent

Tool choice: TLA+ (read with `/statechart`) over a small model of the *code's*
steps, plus anchor checks. SPIN (`verify/spin/holds.pml`, `RUNS` block,
`OWNER=2`) keeps runs, one-shot borrows, slow runs and the hand-off by letter.
The pytest hold suite (`test_hold_key_1267.py`, F223) keeps the scenarios. This
package keeps the SQL/Python *markers* those assume.

## orthogonality

- `AtMostOneHolder` / `TakeFromFree`: SPIN K15/M32; this check keeps the
  seat, name, hold `FOR UPDATE` order (`upsert-for-update`, `name-row-lock`)
  and `desk_id IS NULL` on take (`take-when-null`).
- `NoSecondTake`: SPIN K15/M33; this check keeps no same-desk refresh in
  `mill_hold_upsert` (`upsert-no-same-desk-refresh`, absent anchor) and the
  key match on the hand-off (`handoff-key-match`).
- `OnlyLiveKeyReleases` / `DropFreesRow` / `DropIdempotent`: SPIN K16/M34;
  this check keeps the live-key match in `mill_hold_drop` (`drop-key-match`),
  the live key read (`kh-live`) and the `FOR UPDATE` holder read.
- `HandoffSpendsKey`: SPIN K27/M37; this check keeps the new kh on
  `hold_refresh` (`handoff-new-kh`).
- `RefusalRecorded`: SPIN K17/M36; this check keeps the `hold_refuse` rows
  before the commit in `mill_hold_upsert` and `mill_hold_drop`. The keyless
  refusal written by `_h_drop` after the decision is SPIN K30 (card 1271),
  not modelled here.
- `ExpectGuardHolds` / `AlreadyFreeHonest`: F223 pytest covers Admin/stale
  scenarios; this check keeps `desk_id = v_expect`, `holder changed`, and
  `already free`, and no own-desk `kept` branch (`release-other-no-own-kept`,
  SPIN K24).
- `NoStuckHoldPastBound` (known): SPIN H11 / K22. Starvation of waiters (SPIN
  H09) stays with SPIN (mill never queues; refuse at once).

Dropped as duplicates: concurrent policy search (SPIN H04-H08, K01-K31),
reset/retire release_desk scenarios (SPIN H12/H13, card 842), F223
Admin/stale pytest paths, doing-hold move rows (doing.pml H1-H5), CLI
refuse-exit (`test_hold_exit.py`).

## properties and results (model at sync 047b9f5)

- at most one holder / take only from free: proved; fails on `no_take_free`
- no second take of a held row without the live key: proved; fails on `same_desk_refresh`
- only the live key frees; drop frees the row: proved; fails on `no_key_drop` / `no_drop_clears`
- a hand-off spends the presented key: proved; fails on `handoff_keeps_key`
- every refused take, hand-off and keyed drop has its row: proved; fails on `no_refuse_row`
- drop on free is honest (`DropIdempotent`): by-construction sanity (no breakable guard; letter 4252)
- release-other frees only the expected holder: proved; fails on `no_expect`
- already-free is honest: proved; fails on `no_already_free`
- no stuck hold past bound: **known violated** (no TTL; by design since card 1267); `no_ttl_fixed` passes

Run: `verify/hold-code/run.sh`. Read results with `/statechart` on `Hold.tla`.

## bounds and assumptions

- One resource, two desks, at most 6 steps; keys 0..6 (0 = wrong or none); age bound 3.
- Concurrent interleaving of two upserts is out of scope (SPIN).
- The name-insert race path (1062, 1213, 1644 answered as a refusal) is anchored, not modelled.
- may-drop-other / stale-days anchors are presence-only; auth out of scope beyond them (B8 info-only).
- Admin/stale *authorization* (`may_drop_other`) is out of scope beyond anchors;
  the model assumes an authorized release-other call.
- Waiter starvation stays with SPIN H09 (no queue in product).


## anchor rule (cards 1014, D4/D5)

each marker starts on the real guard (or definition) line, plus its first effect line. the first line must be code: a comment, import, log call, message or SIGNAL line, raise, bare `try:` or block keyword is refused, and a marker must hold at least one code line. matches are counted with comments blanked out, so a commented-out guard (line or block comment) no longer counts. `kind: absent` anchors name a region and patterns that must not appear in it (for paths that must write nothing). every anchor has self-mutants (remove, comment out per line, and for SQL a block comment; absent anchors inject a forbidden line) and `run.sh anchors` goes red for each. `check_anchors.py --selftest` proves the rules refuse the log-only, try+import, message-only and commented shapes. `STATECHART_CMD` overrides host path discovery.

## Tokens

Recorded at hand-off in the PR body and in `TOKENS.txt` (build only; runs are
token-free).

## findings

- no auto-expire / no TTL: re-anchored here as `known/no_ttl` (same class as
  SPIN H11). Card 1013 (`hold-no-auto-expire`, loop:2); card 1267 keeps no
  expiry by design (SPIN K22). The known check is model-side (letter 4252).
- card 941: the override's `hold_force` row is still written after the commit.
- card 1271: a refused keyless drop's row is soft-fail (SPIN K30).
