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
  `mill-wall.ws_miss` on fanout miss. The chain from counter to Wall is anchored end to end: `score_tick.py:36-46` ws_miss in HOST_KPIS, `:53` regex, `:458-466` in-window filter and count, `:465-472` no reset, rebind, pop, update or compound assign before return, `:501` measure() calls `_measure_host`, `:520-524` measure() returns `**host`, `:668-671` host publish with target 0, and `wall_logic/score.py:52-54` a target-0 KPI is red on any nonzero Last. SPIN score.pml
  has no wake/miss KPI; wake-code covers lease races, not the score publish.
  Pytest score_tick covers parsing; this check keeps the count effect the
  Wall SCORE Last reads.
- `HoldBlockedNotDropped` / `GuardCountHoldBlocked`: `measure_hold_blocked`
  sums `hold.blocked` ms (`score_tick.py:293-308`, window filter through return; `measure` calls it at `:517`, nothing reassigns it before `:530` (absent anchor), and returns it at `:530`). Hold-code covers mutex
  correctness; this check keeps the score-side sum so stuck-hold time is not
  dropped before publish.
- Stale doing / wake waste: not a separate score KPI today; wake wrong/retry
  p50 and doing cards 1017/1018 stay with those slices. This package does not
  invent a stale-doing counter.
- `EmptyShowsMissing` (known): `_p50` returns 0 on empty and publish uses
  `counts.get(kpi) or 0` (`score_tick.py:204-206`, host publish `:670-671`, BOOK_PERF opt-in publish `:719-720`). Wall
  `missing Last` and `score_series.gap`/`number` correctly treat blank as
  missing/None; the tick path still writes a numeric 0. Filed as a finding.
- `TruncationLabelled` (known): `score_series.shape` slices `pts[:limit]` with
  no `truncated` flag (`score_series.py:159-161`); the SQL points limit is anchored at `sp_score.sql:398`. measure returns `window_s`
  (anchored); the series truncate is silent. Filed as a finding.
- Caller-observed wall: empty Last -> missing (`wall_logic/score.py:122-123`);
  empty target is not a miss (`:46-48`); a target-0 KPI is red on any nonzero Last (`:52-54`); a missing Last or stale publish makes the desk hot (`:135`) and is named in its reasons (`:139-140`, display only); `shape` passes `gap` through unchanged (`score_series.py:153`); `number` refuses blank, words, nan and inf (`score_series.py:52-58`). Covered by pytest `test_score_rules`;
  this check keeps those markers.
- `value-must-number`: SQL refuses NULL point values (`sp_score.sql:194-196`), and nothing coerces or rewrites `p_value` before that guard (`:169-194`, absent anchor: `SET =`, `SET :=`, `SELECT ... INTO`, `IFNULL`/`COALESCE`).
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
- Hold is modelled as blocked events, not an ms sum. The model proves a
  blocked event is not dropped; the ms arithmetic (sum, window, rounding) is
  held by the `hold-blocked-sum` anchor only, not by TLC.
- The model's invariants are close to true by construction (one writer, the
  guard is the step's precondition); the two model mutants show the guard is
  what holds them, and the anchors tie the guard to the code.
- Not claimed: `shape` reads a NULL point value as 0 (`score_series.py:128`).
  `mill_score_point_add` refuses NULL, so this is reachable only through rows
  written another way; noted next to card 1019, not a separate known model.
- Stale-doing score KPI absent in product; not modelled beyond the known note.
- Auth / roster gates out of scope.

## anchor rule (cards 1014, D4/D5)

each marker starts on the real guard (or definition) line and runs through the effects its property names (window filter, count or sum, return, caller-observed field). the first line must be a guard or effect statement (branch, loop, return, def, assignment, SQL statement, or a dict entry whose value is not a bare string): a comment, import, log call, message or SIGNAL line, raise, docstring, note string, bare `try:` or block keyword is refused, and a def marker also needs a guard or effect line after it. matches are counted with comments, Python triple-quoted strings and SQL string literals blanked out, so a guard that is commented out (line or block), wrapped in a triple-quoted Python string or wrapped in a SQL string no longer counts. Bound: a Python one-line string is not blanked (real code lines hold them), so a single-line marker wrapped in a one-line Python string still counts, and a first-line constant string assignment passes the first-line rule; both are shared-checker limits, not claimed here. `kind: absent` anchors name a region and patterns that must not appear in it (for paths that must write nothing). every anchor has self-mutants (remove, comment out per line, a triple-quoted wrap for Python and a block comment for SQL; absent anchors inject a forbidden line) and `run.sh anchors` goes red for each. `check_anchors.py --selftest` proves the rules refuse the log-only, try+import, import+name, message-only, note-string, def+docstring and commented or stringed-out shapes. `STATECHART_CMD` overrides host path discovery.

## Tokens

Recorded at hand-off in the PR body and in `TOKENS.txt` (build only; runs are
token-free).

## findings

- empty tick sample published as 0: `known/empty_as_zero`. Filed as card 1019 (`score-empty-publish-as-zero`, loop:2).
- silent series point truncation: `known/truncation_silent`. Filed as card 1020 (`score-silent-point-truncation`, loop:2).
