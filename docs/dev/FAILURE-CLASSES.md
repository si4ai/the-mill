# Failure classes: who checks what

The Auditor's coverage list (auditor-focus decision, letter 2668). One row per
failure class. Each pass compares with the last one. Status is **covered** (an
owner and a check that has run and catches the class), **gap** (no owner, no
check, or the check has never run), or **N/A** (the reason, and what would
change it). Evidence is the covering command plus the sha and date of its last
result. A result older than the pass it is listed in is **stale**.

Last pass: the 0.8.2 release pass (release letter 3974), main bed8d4c, tag
v0.8.2, 2026-10-31 (PDT). Previous pass: 0.8.1 (letter 3935, 4644131). Cards named here are mill cards on roster the-mill.


> Hygiene note (card 913 land): five class labels were lowercased at the first word so the repo name-token rule accepts the file (`notification`, `graceful`, `tracing`, `replicas`, `circuit`). Status cells are unchanged. Auditor may restore Title case via the ordinary-words list.

| Class | Status | Owner | Covering check | Last result (sha, date) | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Lock order and deadlock between procedures | covered (model stale for holds) | builder (code), auditor (model) | `verify/spin/run.sh` D03/D04; `tests/server/records/test_lane_b_moves_080.py` (F183) in CI `pytest_sql` | SPIN 8a80dc1 2026-10-30 (stale: sp_hold.sql changed in #277 and again in #281); CI at bed8d4c 2026-10-31 | seat first, then the item; card 941 |
| Deadlock and lock-wait retry (an untested retry path) | covered | builder | `tests/server/test_book_health.py::test_deadlock_and_lock_wait_retry_by_code_whatever_the_class` in CI `pytest_no_sql` | 8a80dc1 2026-10-30 | one immediate retry, no delay |
| Isolation level the procedures assume | covered | builder | `mill_join_upsert` reads id, deleted under FOR UPDATE (#239, F195); two-connection join-vs-retire test in CI `pytest_sql` | CI at bed8d4c 2026-10-31 | SPIN N03 not re-run since the fix |
| Optimistic/pessimistic locking (row locks as guards) | covered (model stale for holds) | builder, auditor | SPIN T01-T04, E01-E03, N01-N02, H01-H02/M03; F186 tests; F223 and F226 tests for `mill_hold_release_other` | SPIN 8a80dc1 2026-10-30 (stale for holds, two releases); CI at bed8d4c 2026-10-31 | admin and stale release-other unmodelled; card 941 |
| Retry jitter | covered (client reconnect) / gap (wake) | builder | `reconnect_delay_s` +/-20% jitter, `tests/client/test_ws_reconnect.py`; wake retry: none (card 827, SPIN W08 violated) | 8a80dc1 2026-10-30 | card 827 open |
| One DB connection per command | gap | builder | none: a /ws command checks out a pool connection for the command and another for the sync reply; nothing counts checkouts per command | not measured (open two releases) | card 907 claimed, no measurement yet |
| Connection pool exhaustion | gap | builder | pool size 8, about 2 s wait (records/db.py); no load result at the beta target | not measured (open two releases) | card 907 |
| Migrations, idempotent ensure | covered | builder | throwaway A/B on a fresh office dump, ensure twice, shape vs fresh (ab082.py) before the live apply | bed8d4c 2026-10-31 (letters 3951, 3973) | manual, not CI |
| Done-check on the wrong artifact | covered (migrations) / gap (card done_when) | builder | migrations: A/B re-apply identical, routines 151, triggers counted (letter 3951). Cards: none; card 936 moved to shipped with two of its done_when checks absent at v0.8.2 | migrations bed8d4c 2026-10-31; cards: board 2026-10-31 | new card this pass |
| Zero-downtime upgrade | N/A | builder | one office, a planned stop: the wall was down about 11 s at 0.8.2 | 2026-10-31 (letter 3973) | expires when an office cannot take a stop |
| Stored-procedure and install drift between hosts | gap (live drift, two releases) | builder | `sql check` pack = book digest at install on each host | cloud ae28f291f17a at bed8d4c 2026-10-31 (letter 3973); workstation still f1e5022c7da4 (0.8.0 book), install pending since letter 3934 | nothing tracks how long hosts differ; card 908 |
| Two copies of mill on one host | gap (caught once) | builder | the workstation install refuses a non-fast-forward wall checkout (letter 3934) | 2026-10-31: still not fast-forward at 0.8.2 (letter 3973) | card 908 still claimed |
| Lost wakes | covered / open finding | builder (code), auditor (model) | SPIN W04-W07, W18, W21, L04, L06; `tests/server/test_wake_lease_races_887_888.py` | 8a80dc1 2026-10-30 | W08 (both POSTs fail) open, card 827; card 889 open |
| Duplicate or overlapping wakes | covered | builder, auditor | SPIN W01-W03, L01-L03, L05, M07, M21 | 8a80dc1 2026-10-30 | |
| Webhook receiver down or slow | gap (known) | builder | SPIN W08, W17 violated by design today | 8a80dc1 2026-10-30 | card 827 |
| Queue rows and dead letters | covered | builder, auditor | SPIN `no_loss` (W04-W06, W18, W19, W21) | 8a80dc1 2026-10-30 | 30-day sweep not modelled |
| notification after commit (outbox) | gap (known) | builder | none: a crash between commit and its pokes leaves the row unqueued (SPIN README, not modelled) | n/a | |
| graceful shutdown / restart | gap (known) | builder | SPIN W11 violated: a wall restart forgets the lease window and a pending trailing POST | 8a80dc1 2026-10-30 | rows survive in push_queue |
| Docs, hints and skills naming dead commands | covered (repo docs) / gap (cold-measure kit) | builder (check), gardener (cold, kit) | `tools/check_doc_commands.py` and `tools/check_skill_copy.py` in CI; Gardener cold measures | CI at bed8d4c 2026-10-31; cold 0.8.1 letter 3946: soft fail, kit snapshot.sh calls a command that does not exist, no card | guide fix #285 passed (3947), not merged, not in 0.8.2; new card this pass |
| Silent truncation at size limits | covered (notes, evidence, letters) | builder | refusals with counts: note budget 4096, evidence 2000 (F143, `mill_doing_move`), letter body 4096 | 8a80dc1 2026-10-30 | previews are cut by design |
| Health checks | covered | builder, validator | `/health` with X-Mill-Version after install | bed8d4c 2026-10-31 (letter 3973, 0.8.2) | |
| tracing and per-command cost | covered | builder | F171 per-command lines with a request id, `perf.ON` on by default (`tests/server/test_perf_ps_080.py`) | 8a80dc1 2026-10-30 | numbers are baselines, not gates |
| Checker-host drift | covered | validator | `tools/hostline.sh` host line in each VERDICT, flagged against the previous one | bed8d4c 2026-10-31 (letter 3964: host-drift none) | test that skips without pwsh is card 940 (PR open) |
| Trust boundary | covered | builder, validator | CodeQL in CI, Dependabot, Validator gate; `check_pack --commits` on PRs (F225) | codeql at bed8d4c 2026-10-31 (letter 3951) | not reviewed by the Auditor; release merge commits land outside the queue with admin bypass (card 943); push CI does not scan the merge commit (Validator N1, noted on 935) |
| Cold-agent outcome | covered (0.8.1) / input missing (0.8.2) | gardener | cold measure per shipped version, with mill version and mill-desk skill sha | 0.8.1 letter 3946 (mill 0.8.1, skill 071cfe2a8512): soft fail, caught a guide gap; 0.8.2 none yet | |
| Card state after ship | gap (recurs, fourth pass) | builder | none: cards 913, 924, 929 and 881 still claimed at 0.8.2 after their work merged | board, 2026-10-31 | card 942 open, unclaimed |
| replicas, sharding, partitioning | N/A | - | one office is one MySQL | 2026-10-30 | expires with a second book per office |
| CQRS, event sourcing, distributed transactions | N/A | - | one book; activity is the one shared timeline | 2026-10-30 | same |
| circuit breakers, rate limiting | N/A | - | one dependency (the book); the wake lease limits POSTs to one per lease | 2026-10-30 | expires at the beta load target |
| Cache invalidation and stampedes | N/A | - | the only cache is glance's cached read, rebuilt by the server | 2026-10-30 | revisit if a second cache appears |

A row changes only through a normal PR. The Validator checks that each
pointer resolves and that the rows parse; it does not re-run the checks.
