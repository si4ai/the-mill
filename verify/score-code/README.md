# Score liveness-truth vs the 0.8.5 code (card 925)

The mill is middleware; the CLI is its API. This check prioritises whether score
tells the truth about liveness: missed wakes and blocked holds are counted (not
silently dropped); empty or missing input must not look like zero/green; a
truncated point window must be labelled.

- `Score.tla` / `Score.cfg`: TLA+ model of miss/hold/sample/publish/shape
- `view.mjs`: reader labels for `/statechart`
- `anchors.json` + `check_anchors.py`: ties the model to marker strings in the real files
- `mutants/*.cfg`: each flips one counting guard; the matching invariant must break
- `known/`: empty-as-zero and silent-truncation findings still violate; proposed fixes pass
- `run.sh`: one token-free command; out of CI
- `SKILL.md`: project skill for the next agent

Tool choice: TLA+ (read with `/statechart`) over a small model of the *code's*
tick/series/wall steps, plus anchor checks. SPIN (`verify/spin/score.pml`) keeps
S1-S6 lifecycle. Pytest/wall suites keep trend and paint rules. This package
keeps the Python/SQL *markers* those assume, plus caller-observed fields
(letter 4267 lesson).

## orthogonality

- `WsMissNotDropped` / `GuardCountWsMiss`: `score_tick._measure_host` increments
  `mill-wall.ws_miss` on fanout miss (`score_tick.py:464-465`). SPIN score.pml
  has no wake/miss KPI; wake-code covers lease races, not the score publish.
  Pytest score_tick covers parsing; this check keeps the count effect the
  Wall SCORE Last reads.
- `HoldBlockedNotDropped` / `GuardCountHoldBlocked`: `measure_hold_blocked`
  sums `hold.blocked` ms (`score_tick.py:293-304`). Hold-code covers mutex
  correctness; this check keeps the score-side sum so stuck-hold time is not
  dropped before publish.
- Stale doing / wake waste: not a separate score KPI today; wake wrong/retry
  p50 and doing cards 1017/1018 stay with those slices. This package does not
  invent a stale-doing counter.
- `EmptyShowsMissing` (known): `_p50` returns 0 on empty and publish uses
  `counts.get(kpi) or 0` (`score_tick.py:204-206`, book publish). Wall
  `missing Last` and `score_series.gap`/`number` correctly treat blank as
  missing/None; the tick path still writes a numeric 0. Filed as a finding.
- `TruncationLabelled` (known): `score_series.shape` slices `pts[:limit]` with
  no `truncated` flag (`score_series.py:159-160`). measure returns `window_s`
  (anchored); the series truncate is silent. Filed as a finding.
- Caller-observed wall: empty Last -> missing (`wall_logic/score.py:122-123`);
  empty target is not a miss (`:47-48`). Covered by pytest `test_score_rules`;
  this check keeps those markers.
- `value-must-number`: SQL refuses NULL point values (`sp_score.sql:194-195`).
  SPIN S1 assumes a numeric write; this check keeps the refuse.

Dropped as duplicates: S1-S6 concurrent lifecycle (SPIN), trend/gap unit tests
(`test_score_trend_076`, `test_score_series_288`), wall paint contract tests,
wake/mail/hold/doing 925 slices, score evidence spill byte cap (score_system).

## properties and results (model at sync ce115f8)

- ws_miss events are counted: proved; fails on `no_ws_miss`
- hold.blocked ms are counted: proved; fails on `no_hold_blocked`
- empty publish shows as missing: **known violated** (tick writes 0); proposed `empty_as_zero_fixed` passes
- truncated point window labelled: **known violated**; proposed `truncation_silent_fixed` passes

Run: `verify/score-code/run.sh`. Read results with `/statechart` on `Score.tla`.

## bounds and assumptions

- One office score stream, at most 6 steps; no concurrent tick writers (SPIN).
- Stale-doing score KPI absent in product; not modelled beyond the known note.
- Auth / roster gates out of scope.

## anchor rule (cards 1014, D4/D5)

each marker starts on the real guard (or definition) line, plus its first effect line. the first line must be code: a comment, import, log call, message or SIGNAL line, raise, bare `try:` or block keyword is refused, and a marker must hold at least one code line. matches are counted with comments blanked out, so a commented-out guard (line or block comment) no longer counts. `kind: absent` anchors name a region and patterns that must not appear in it (for paths that must write nothing). every anchor has self-mutants (remove, comment out per line, and for SQL a block comment; absent anchors inject a forbidden line) and `run.sh anchors` goes red for each. `check_anchors.py --selftest` proves the rules refuse the log-only, try+import, message-only and commented shapes. `STATECHART_CMD` overrides host path discovery.

## Tokens

Recorded at hand-off in the PR body and in `TOKENS.txt` (build only; runs are
token-free).

## findings

- empty tick sample published as 0: `known/empty_as_zero`. Filed as card 1019 (`score-empty-publish-as-zero`, loop:2).
- silent series point truncation: `known/truncation_silent`. Filed as card 1020 (`score-silent-point-truncation`, loop:2).
