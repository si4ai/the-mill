# Doing focus, waiting, and end vs the 0.8.5 code (card 925)

**0.8.6 target, per builder:** doing comes only from tw (970); a desk may run several tw tasks at once (`MaxTasks=2`, `Doing-target.cfg`); `GuardSupersede=FALSE` drops D6. Current ce115f8 stays `MaxTasks=1` + `GuardSupersede=TRUE` (`Doing.cfg`). 1017/1018 are per task. `verify/spin/doing.pml` on main still models the 0.8.0 single `seat.doing_id` lock-order story; this package carries the concurrent-tw target.

The mill is middleware; the CLI is its API. This check prioritises liveness and
recovery: a doing entry always ends on ship/done/drop, a stale doing from a
crashed desk clears only via reset/retire (known), `--waiting-on` cannot form a
self-wait, and a retry does not duplicate focus rows. Wait-cycle detection
across two desks is a known gap (product refuses self-wait only).

- `Doing.tla` / `Doing.cfg`: TLA+ model of focus/wait/end/crash/clear/tick
- `view.mjs`: reader labels for `/statechart`
- `anchors.json` + `check_anchors.py`: ties the model to marker strings in the real files
- `mutants/*.cfg`: each flips one guard; the matching invariant must break
- `known/`: wait-cycle and stale-doing findings still violate; proposed fixes pass
- `run.sh`: one token-free command; out of CI
- `SKILL.md`: project skill for the next agent

Tool choice: TLA+ (read with `/statechart`) over a small model of the *code's*
steps, plus anchor checks. SPIN (`verify/spin/doing.pml`) keeps D01-D08. The
pytest waiting_818 suite keeps CLI/SQL scenarios. This package keeps the
SQL *markers* those assume.

## orthogonality

- `NoSelfWait` / `GuardNoSelfWait`: product refuses
  `v_wid = v_desk` (`sp_doing.sql:116-117`). SPIN D0x and pytest cover
  self-wait refuse; this check keeps that SQL marker. Cross-desk A<->B cycles
  are **not** refused in product; see known `NoInvisibleWaitCycle`.
- `LiveTokenRequired` / `GuardLiveToken`: F186 live-token gate
  (`sp_doing.sql:132-133`). SPIN does not model token_hash; pytest covers
  refuse paths; this check keeps the UPDATE+ROW_COUNT marker.
- `OneFocusInsertPerPut` / `GuardOneInsertPerPut`: single
  `mill_doing_insert` per put (`sp_doing.sql:164`) under seat `FOR UPDATE`
  (`sp_join.sql:45`). SPIN D01 serializes seat; this check keeps the insert
  call and the FOR UPDATE line so a retry cannot double-insert under the lock.
- `DoingEndsOnShip`: finish writes no row; end is derived from ship/done/drop
  (`sp_doing.sql` finish SELECT + `mill_doing_end` act filter). SPIN and
  pytest cover end semantics; this check keeps those markers.
- `NoInvisibleWaitCycle` (known): product has no A<->B cycle detect; only
  self-wait. SPIN does not currently state a cycle refuse. Filed as card 1017 with proposed `GuardDetectWaitCycle`.
- `StaleDoingClearsWithinBound` (known): crashed desk focus clears only via
  reset/retire (`ClearReset`), not a TTL. Same class as hold no-TTL. Filed as card 1018 with proposed `GuardAutoClearStale`.

Dropped as duplicates: full D01-D08 concurrent matrix (SPIN), waiting_818 CLI
paths (pytest), hold-mutex take/drop (hold-code), mail receipt (mail-code),
wake token (wake-code).

## properties and results (model at sync ce115f8)

- no self-wait: proved; fails on `no_self_wait`
- live token required for focus: proved; fails on `no_live_token`
- one insert per put: proved; fails on `no_one_insert`
- doing ends on ship/done/drop: by-construction of EndFocus; anchored on finish + mill_doing_end
- wait cycle invisible: **known violated**; proposed `wait_cycle_fixed` passes
- stale doing clears within bound: **known violated**; proposed `stale_doing_fixed` passes

Run: `verify/doing-code/run.sh`. Read results with `/statechart` on `Doing.tla`.

## bounds and assumptions

- Two desks, at most 6 steps; age bound 3 for the stale-doing check.
- Concurrent double-insert under lost lock is out of scope beyond the FOR UPDATE
  anchor (SPIN D01).
- Auth / roster gates out of scope beyond live-token.
- Cycle detect and stale auto-clear are model-only proposed fixes (known/).
- Model bounds: `OneFocusInsertPerPut` and `DoingEndsOnShip` hold by construction of the model (no step can break them), so they record intent, not a check; `DoingEndsOnShip` has no mutant. The code side is carried by the `one-insert`, `put-no-raw-insert`, `derived-end` and `finish-writes-nothing` anchors.
- Crash sets live=FALSE in the model, but in code the seat token survives a crash, so a restarted desk can focus again on the same token. The stale-doing finding (card 1018) still stands.
- Not anchored, named bounds: seat lock order across procedures, cleared act='clear' on empty text, insert id monotone, and mill_doing_move's lock and evidence cap. SPIN D01-D08 and pytest cover them.

## anchor rule (cards 1014, D4/D5)

each marker starts on the real guard (or definition) line, plus its first effect line. the first line must be code: a comment, import, log call, message or SIGNAL line, raise, bare `try:` or block keyword is refused, and a marker must hold at least one code line. matches are counted with comments blanked out, so a commented-out guard (line or block comment) no longer counts. `kind: absent` anchors name a region and patterns that must not appear in it (for paths that must write nothing). every anchor has self-mutants (remove, comment out per line, and for SQL a block comment; absent anchors inject a forbidden line) and `run.sh anchors` goes red for each. `check_anchors.py --selftest` proves the rules refuse the log-only, try+import, message-only and commented shapes. `STATECHART_CMD` overrides host path discovery.

## Tokens

Recorded at hand-off in the PR body and in `TOKENS.txt` (build only; runs are
token-free).

## findings

- no wait-cycle detect across desks: `known/wait_cycle` (product self-wait only). Filed as card 1017 (`doing-invisible-wait-cycle`, loop:2).
- no auto-clear of stale doing after crash: `known/stale_doing` (reset/retire only). Filed as card 1018 (`doing-stale-after-crash`, loop:2).
