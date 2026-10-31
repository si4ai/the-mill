# Failure classes: who checks what

The Auditor's coverage list (auditor-focus decision, letter 2668). One row per
failure class. Each pass compares with the last one. Status is **covered** (an
owner and a check that has run and catches the class), **gap** (no owner, no
check, or the check has never run), or **N/A** (the reason, and what would
change it). Evidence is the covering command plus the sha and date of its last
result. A result older than the pass it is listed in is **stale**.

Last pass: the 0.8.0 release pass (release letter 3386), main 8a80dc1, tag
v0.8.0, 2026-10-30 (PDT). Cards named here are mill cards on roster the-mill.


> Hygiene note (card 913 land): five class labels were lowercased at the first word so the repo name-token rule accepts the file (`notification`, `graceful`, `tracing`, `replicas`, `circuit`). Status cells are unchanged. Auditor may restore Title case via the ordinary-words list.

| Class | Status | Owner | Covering check | Last result (sha, date) | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Lock order and deadlock between procedures | covered | builder (code), auditor (model) | `verify/spin/run.sh` D03/D04; `tests/server/records/test_lane_b_moves_080.py` (F183) in CI `pytest_sql` | SPIN 8a80dc1 2026-10-30; CI ci run at 8a80dc1 2026-10-30 | seat first, then the item |
| Deadlock and lock-wait retry (an untested retry path) | covered | builder | `tests/server/test_book_health.py::test_deadlock_and_lock_wait_retry_by_code_whatever_the_class` in CI `pytest_no_sql` | 8a80dc1 2026-10-30 | one immediate retry, no delay |
| Isolation level the procedures assume | gap | builder | none: `tables.sql` says READ COMMITTED; no code sets it; SPIN N03/N04 show the join re-check depends on it | SPIN 8a80dc1 2026-10-30 | card join-name-recheck-isolation |
| Optimistic/pessimistic locking (row locks as guards) | covered | builder, auditor | SPIN T01-T04, E01-E03, N01-N02, H01-H02/M03; F186 tests | 8a80dc1 2026-10-30 | |
| Retry jitter | covered (client reconnect) / gap (wake) | builder | `reconnect_delay_s` +/-20% jitter, `tests/client/test_ws_reconnect.py`; wake retry: none (card 827, SPIN W08 violated) | 8a80dc1 2026-10-30 | card 827 open |
| One DB connection per command | gap | builder | none: a /ws command checks out a pool connection for the command and another for the sync reply (asgi.py `_run`, `_sync`); F171 lines are per connection, nothing counts checkouts per command | not measured | card ws-command-pool-checkouts |
| Connection pool exhaustion | gap | builder | pool size 8, about 2 s wait (records/db.py); no load result at the beta target | not measured | same card |
| Migrations, idempotent ensure | covered | builder | throwaway A/B on a fresh office dump, ensure twice, shape vs fresh (ab080.py) before each live apply | 8a80dc1 2026-10-30 (letter 3385) | manual, not CI |
| Done-check on the wrong artifact (migration "already done") | covered | builder | same A/B: re-apply identical, routines and triggers counted | 8a80dc1 2026-10-30 | |
| Zero-downtime upgrade | N/A | builder | one office, a planned stop: the wall was down about 19 s at 0.8.0 | 2026-10-30 | expires when an office cannot take a stop |
| Stored-procedure and install drift between hosts | covered | builder | `sql check` pack = book digest at install on each host | cloud and workstation f1e5022c7da4, 2026-10-30 (letters 3385, 3391) | at install only; no periodic check |
| Two copies of mill on one host | gap | builder | none: the workstation wall runs a git checkout moved by hand beside the pip pack (letters 3194, 3391) | equal by hand at 8a80dc1, 2026-10-30 | card wall-checkout-vs-pack |
| Lost wakes | covered / open finding | builder (code), auditor (model) | SPIN W04-W07, W18, W21, L04, L06; `tests/server/test_wake_lease_races_887_888.py` | 8a80dc1 2026-10-30 | W08 (both POSTs fail) open, card 827; card 889 open |
| Duplicate or overlapping wakes | covered | builder, auditor | SPIN W01-W03, L01-L03, L05, M07, M21 | 8a80dc1 2026-10-30 | |
| Webhook receiver down or slow | gap (known) | builder | SPIN W08, W17 violated by design today | 8a80dc1 2026-10-30 | card 827 |
| Queue rows and dead letters | covered | builder, auditor | SPIN `no_loss` (W04-W06, W18, W19, W21) | 8a80dc1 2026-10-30 | 30-day sweep not modelled |
| notification after commit (outbox) | gap (known) | builder | none: a crash between commit and its pokes leaves the row unqueued (SPIN README, not modelled) | n/a | |
| graceful shutdown / restart | gap (known) | builder | SPIN W11 violated: a wall restart forgets the lease window and a pending trailing POST | 8a80dc1 2026-10-30 | rows survive in push_queue |
| Docs, hints and skills naming dead commands | covered | builder (check), gardener (cold) | `tools/check_doc_commands.py` and `tools/check_skill_copy.py` in CI; Gardener cold measures | CI 8a80dc1 2026-10-30; cold measure 0.8.0 letter 3390 | |
| Silent truncation at size limits | covered (notes, evidence, letters) | builder | refusals with counts: note budget 4096, evidence 2000 (F143, `mill_doing_move`), letter body 4096 | 8a80dc1 2026-10-30 | previews are cut by design |
| Health checks | covered | builder, validator | `/health` with X-Mill-Version after install; Validator post-ship check | 8a80dc1 2026-10-30 (letters 3385, 3387) | |
| tracing and per-command cost | covered | builder | F171 per-command lines with a request id, `perf.ON` on by default (`tests/server/test_perf_ps_080.py`) | 8a80dc1 2026-10-30 | numbers are baselines, not gates |
| Checker-host drift | gap | validator | none: nothing records what a checker host has (mysqld, spin, node, cron) next to its verdict | not recorded | card checker-host-inventory |
| Trust boundary | covered | builder, validator | CodeQL in CI, Dependabot, Validator gate | codeql run at 8a80dc1 2026-10-30 | not reviewed by the Auditor; Dependabot #228/#230/#231 held "until after 0.8.0": card dependabot-hold-expired |
| Cold-agent outcome | covered | gardener | cold measure per shipped version, with mill version and mill-desk skill sha | 0.7.19 letter 3198 (2026-10-26), 0.8.0 letter 3390 (2026-10-30), both green | recurring friction: card cold-friction-recurs |
| Card state after ship | gap | builder | none: cards 830, 886, 887, 888 are still claimed after their PRs merged | board, 2026-10-30 | card claimed-after-merge |
| replicas, sharding, partitioning | N/A | - | one office is one MySQL | 2026-10-30 | expires with a second book per office |
| CQRS, event sourcing, distributed transactions | N/A | - | one book; activity is the one shared timeline | 2026-10-30 | same |
| circuit breakers, rate limiting | N/A | - | one dependency (the book); the wake lease limits POSTs to one per lease | 2026-10-30 | expires at the beta load target |
| Cache invalidation and stampedes | N/A | - | the only cache is glance's cached read, rebuilt by the server | 2026-10-30 | revisit if a second cache appears |

A row changes only through a normal PR. The Validator checks that each
pointer resolves and that the rows parse; it does not re-run the checks.
