# Wake code guards vs the 0.8.5 code (card 925)

A test checks the cases someone wrote. SPIN checks the design under
interleaving. This check asks whether the *real* `wake.py` / `push.py`
control-flow guards still implement the transitions those assume: when a
failed wake arms a retry, when trailing and ring fall back to unread mail,
when `mill wake-done` skips a trailing POST to a sitting desk, and when a
stale lease token ends nothing.

| Piece | Role |
| :--- | :--- |
| `Wake.tla` / `Wake.cfg` | TLA+ model of each wake.py / push.py step, with guards as CONSTANTS |
| `view.mjs` | Reader labels for `/statechart` |
| `anchors.json` + `check_anchors.py` | ties the model to marker strings in the real files |
| `mutants/*.cfg` | Each flips one guard; the matching invariant must break |
| `known/card_1005*` | Card 1005 finding still reproduces; proposed fix holds |
| `run.sh` | One token-free command; out of CI |
| `SKILL.md` | Project skill for the next agent |

Tool choice: TLA+ (read with `/statechart`) over a small model of the *code's*
steps, plus anchor checks on the real files. There is no Python verifier
in-tree. SPIN (`verify/spin/wake.pml`) keeps concurrency, lease races and
delivery under loss. The pytest wake suite keeps the scenario cases.

## Orthogonality

| Property | Already covered by | This check catches that those do not |
| :--- | :--- | :--- |
| `RetryArmRequiresPushPending` / `NeverArmedWithoutPush` | SPIN models `RETRY_UNREAD=0`; `test_wake_retry_827` covers drain-stop *after* arm | The marker `pending > 0` still gates `_arm_retry` in `wake.py:1170`. A rename or drop of that gate leaves SPIN and the scenario tests green. |
| `DrainStopsWhenPushEmpty` | `test_wake_retry_827` (drained queue stops retry) | The marker `if _queue_drained(desk):` still sits in the retry pump (`wake.py:1018`). |
| `TrailingFallsBackToUnread` | `test_replay_unread_on_connect_949` (wake-done / lease-end with unread) | The `unread_mail_frames` import and fallback in `_send_trailing` (`wake.py:710-715`) still exist as the code SPIN cites. |
| `RingFallsBackToUnread` | `test_replay_unread_on_connect_949` (leave rings on unread) | The `#949` unread branch in `ring_waiting` (`push.py:267-273`) still exists. |
| `SittingDoneSendsNoTrailing` | SPIN W27; shipped with #322 | The `desk_sitting` check and `return "sitting"` in `lease_done` (`wake.py:812-818`) still exist. |
| `StaleTokenEndsNothing` | `test_wake_lease_races_887_888` | The `token != _EPOCH` stale path in `lease_done` (`wake.py:788-801`) still exists. |
| `UnreadAloneFailedWakeIsRetried` (known) | SPIN W30 (finding 11); **no** server test yet | Same finding from the code-step model; `known/card_1005` expects the break. Points at card 1005. Not weakened. |

Dropped as duplicates of SPIN or pytest: lease exclusivity, coalesce races,
retry backoff timing, ring-on-leave with push rows, unread merge on connect,
PUTFIRST / ACK_AFTER_SEND delivery races.

## Properties and results (model at SYNC ce115f8)

| Property | Result |
| :--- | :--- |
| Retry arms only when push rows wait | proved; fails on `no_retry_push_only` |
| Drain stops a retry when push is empty | proved; fails on `no_drain_stops` |
| Trailing falls back to unread mail | proved; fails on `no_trailing_unread` |
| Ring-on-leave falls back to unread mail | proved; fails on `no_ring_unread` |
| Sitting wake-done sends no trailing POST | proved; fails on `no_sitting_trail` |
| Stale lease token ends nothing | proved; fails on `no_stale_token` |
| Failed unread-only wake is retried | **violated** on current code (`known/card_1005`); holds with proposed `GuardRetryOnUnread` (`known/card_1005_fixed`). Finding card 1005. |

Run: `verify/wake-code/run.sh`. Read results with `/statechart` on
`Wake.tla` (full check: `Wake.cfg`; chart under 500 states: `Wake-chart.cfg`,
view `view.mjs`).

## Bounds and assumptions

- One desk, boolean push-pending / unread / sitting / lease flags, at most 6 steps.
- POST success and failure are environment choices; backoff timing is out of scope.
- Concurrent lease interleaving and Hub races are out of scope (SPIN).
- `GuardRetryOnUnread` is the proposed card 1005 fix (SPIN `RETRY_UNREAD=1`); current code keeps it FALSE.

- Text anchors cannot catch a guard that keeps its text but changes a value or adds a path after it. Named bounds: C1 drain returning False instead of True, C4/C5 an unconditional `return "none"` after the unread guards, C6 `_arm_retry(url, None, ...)`. pytest covers the return values; SPIN covers retry arming.

## anchor rule (cards 1014, D4/D5)

each marker starts on the real guard (or definition) line, plus its first effect line. the first line must be code: a comment, import, log call, message or SIGNAL line, raise, bare `try:` or block keyword is refused, and a marker must hold at least one code line. matches are counted with comments blanked out, so a commented-out guard (line or block comment) no longer counts. `kind: absent` anchors name a region and patterns that must not appear in it (for paths that must write nothing). every anchor has self-mutants (remove, comment out per line, and for SQL a block comment; absent anchors inject a forbidden line) and `run.sh anchors` goes red for each. `check_anchors.py --selftest` proves the rules refuse the log-only, try+import, message-only and commented shapes. `STATECHART_CMD` overrides host path discovery.

## Tokens

Recorded at hand-off in the PR body and in `TOKENS.txt` (build only; runs are
token-free).

## Findings

Card 1005 (`unread-wake-no-retry`) is reproduced here as a known finding and
is not fixed in this PR. This PR does not change product code.
