# Failure classes: who checks what

The Auditor's coverage list (auditor-focus decision, letter 2668). One row per
failure class. Each pass compares with the last one. Status is **covered** (an
owner and a check that has run and catches the class), **gap** (no owner, no
check, or the check has never run), or **N/A** (the reason, and what would
change it). Evidence is the covering command plus the sha and date of its last
result. A result older than the pass it is listed in is **stale**.

Last pass: the 0.8.13 release pass (live letter 5376, start letter 5377), main
625746e4, tag v0.8.13, 2026-11-11 (PST). Previous pass: 0.8.2 (letter 3974,
bed8d4c). Cards named here are mill cards on roster the-mill.

0.8.13 was not a 0.X bump, so no SPIN pass was asked (letter 5377). No SQL,
server or wall change. Scope named in letter 5377: card 1130 desk-flag fixes
(#397, docs #401), grok-bot guide --desk examples (#396), check_pack
--pr-message (#402), card 1127 CI test map (#398). Row text starts from
what letters 5376 and 5377 name, and adds letter 5337 (0.8.12 cold
measure), still-open card 908, card 1136, and the known check_pack
misfires on #396 and #403.

> Hygiene note (card 913 land): five class labels were lowercased at the first word so the repo name-token rule accepts the file (`notification`, `graceful`, `tracing`, `replicas`, `circuit`). Status cells are unchanged. Auditor may restore Title case via the ordinary-words list.

| Class | Status | Owner | Covering check | Last result (sha, date) | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Lock order and deadlock between procedures | covered (model stale for holds) | builder (code), auditor (model) | `verify/spin/run.sh` D03/D04; `tests/server/records/test_lane_b_moves_080.py` (F183) in CI `pytest_sql` | SPIN 8a80dc1 2026-10-30 (stale: no SPIN pass asked, letter 5377); CI at bed8d4c 2026-10-31 (stale) | seat first, then the item; card 941 |
| Deadlock and lock-wait retry (an untested retry path) | covered | builder | `tests/server/test_book_health.py::test_deadlock_and_lock_wait_retry_by_code_whatever_the_class` in CI `pytest_no_sql` | 8a80dc1 2026-10-30 (stale) | one immediate retry, no delay |
| Isolation level the procedures assume | covered | builder | `mill_join_upsert` reads id, deleted under FOR UPDATE (#239, F195); two-connection join-vs-retire test in CI `pytest_sql` | CI at bed8d4c 2026-10-31 (stale); SPIN N03 not re-run (letter 5377: no SPIN pass asked) | |
| Optimistic/pessimistic locking (row locks as guards) | covered (model stale for holds) | builder, auditor | SPIN T01-T04, E01-E03, N01-N02, H01-H02/M03; F186 tests; F223 and F226 tests for `mill_hold_release_other` | SPIN 8a80dc1 2026-10-30 (stale: no SPIN pass asked, letter 5377); CI at bed8d4c 2026-10-31 (stale) | admin and stale release-other unmodelled; card 941 |
| Retry jitter | covered (client reconnect) / gap (wake) | builder | `reconnect_delay_s` +/-20% jitter, `tests/client/test_ws_reconnect.py`; wake retry: none (card 827, SPIN W08 violated) | 8a80dc1 2026-10-30 (stale: no SPIN pass asked, letter 5377) | card 827 open |
| One DB connection per command | gap | builder | none: a /ws command checks out a pool connection for the command and another for the sync reply; nothing counts checkouts per command | not measured (not in letters 5376 or 5377) | card 907 |
| Connection pool exhaustion | gap | builder | pool size 8, about 2 s wait (records/db.py); no load result at the beta target | not measured (not in letters 5376 or 5377) | card 907 |
| Migrations, idempotent ensure | covered | builder | live install: ensure twice, routines, triggers, columns and row counts identical before and after each; pack digest equals the book (letter 5376) | 625746e4 2026-11-11 (letter 5376); book f3b0f9fdd1f7; no SQL change in v0.8.12..v0.8.13; check_sql: only the known MILL_DESK_ID case-fold false positive | manual, not CI; 28 steps each ensure |
| Done-check on the wrong artifact | covered (migrations) / gap (card done_when) | builder | migrations: live ensure re-apply identical, routines, triggers, columns and row counts (letter 5376). Cards: no general check named; cards 1127 and 1130 were noted and passed to shipped, accepted with pass --done (letter 5376) | migrations 625746e4 2026-11-11 (letter 5376) | |
| Zero-downtime upgrade | N/A | builder | one office, a planned stop: the wall was down about 13 s at 0.8.13 | 2026-11-11 (letter 5376) | expires when an office cannot take a stop |
| Stored-procedure and install drift between hosts | gap | builder | `sql check` pack = book digest at install on the live office | live office f3b0f9fdd1f7 at 625746e4 2026-11-11 (letter 5376); second host not in this pass (letter 5376: not touched) | nothing tracks how long hosts differ; card 908 |
| Two copies of mill on one host | gap (caught once) | builder | install refuses a non-fast-forward wall checkout (prior letter 3934) | not in letters 5376 or 5377 | card 908 still claimed |
| Lost wakes | covered / open finding | builder (code), auditor (model) | SPIN W04-W07, W18, W21, L04, L06; `tests/server/test_wake_lease_races_887_888.py` | 8a80dc1 2026-10-30 (stale: no SPIN pass asked, letter 5377) | W08 (both POSTs fail) open, card 827; card 889 open; card 1136 (0.8.13 wake-done came back stale after real work; not caught by SPIN) |
| Duplicate or overlapping wakes | covered | builder, auditor | SPIN W01-W03, L01-L03, L05, M07, M21 | 8a80dc1 2026-10-30 (stale: no SPIN pass asked, letter 5377) | card 1136 (0.8.13 wake dogfood; SPIN did not catch the stale wake-done) |
| Webhook receiver down or slow | gap (known) | builder | SPIN W08, W17 violated by design today | 8a80dc1 2026-10-30 (stale: no SPIN pass asked, letter 5377) | card 827 |
| Queue rows and dead letters | covered | builder, auditor | SPIN `no_loss` (W04-W06, W18, W19, W21) | 8a80dc1 2026-10-30 (stale: no SPIN pass asked, letter 5377) | 30-day sweep not modelled |
| notification after commit (outbox) | gap (known) | builder | none: a crash between commit and its pokes leaves the row unqueued (SPIN README, not modelled) | n/a | |
| graceful shutdown / restart | gap (known) | builder | SPIN W11 violated: a wall restart forgets the lease window and a pending trailing POST | 8a80dc1 2026-10-30 (stale: no SPIN pass asked, letter 5377) | rows survive in push_queue |
| Docs, hints and skills naming dead commands | covered (repo docs) / gap (cold-measure kit) | builder (check), gardener (cold, kit) | `tools/check_doc_commands.py` and `tools/check_skill_copy.py` in CI; host skills byte-equal to the pack (letter 5376); grok-bot guide --desk examples (#396, letter 5377); docs #401 (letter 5377) | host skills 625746e4 2026-11-11 (letter 5376); CI last result not in this pass; cold 0.8.1 letter 3946: soft fail, kit snapshot.sh calls a command that does not exist, no card | kit gap still open; no owner card |
| Silent truncation at size limits | covered (notes, evidence, letters) | builder | refusals with counts: note budget 4096, evidence 2000 (F143, `mill_doing_move`), letter body 4096 | 8a80dc1 2026-10-30 (stale) | previews are cut by design |
| Health checks | covered | builder, validator | `/health` with X-Mill-Version after install | 625746e4 2026-11-11 (letter 5376): /health 200, X-Mill-Version 0.8.13 | |
| tracing and per-command cost | covered | builder | F171 per-command lines with a request id, `perf.ON` on by default (`tests/server/test_perf_ps_080.py`) | 8a80dc1 2026-10-30 (stale) | numbers are baselines, not gates |
| Checker-host drift | covered | validator | `tools/hostline.sh` host line in each VERDICT, flagged against the previous one | bed8d4c 2026-10-31 (letter 3964: host-drift none) (stale; not in letters 5376 or 5377) | card 940 |
| Trust boundary | covered | builder, validator | CodeQL in CI, Dependabot, Validator gate; `check_pack --commits` on PRs (F225); `check_pack --pr-message` on the pull_request run (#402, letter 5377) | codeql at bed8d4c 2026-10-31 (letter 3951) (stale; not in letters 5376 or 5377); #402 landed in 0.8.13 (letter 5377) | not reviewed by the Auditor; release merge commits land outside the queue with admin bypass (card 943); push CI does not scan the merge commit (Validator N1, noted on 935); known risks: a name-token substring match inside a desk-command example ejected #396 from the merge queue; on #403, --pr-message read the old PR text after a body-only edit (stale input); owner decides the fix |
| Cold-agent outcome | covered (0.8.1, 0.8.12) / input missing (0.8.2, 0.8.13) | gardener | cold measure per shipped version, with mill version and mill-desk skill sha | 0.8.1 letter 3946 (mill 0.8.1, skill 071cfe2a8512): soft fail, caught a guide gap; 0.8.12 letter 5337: fail, caught the 1112 refusal (fixed by #396 and #397); 0.8.2 none; 0.8.13 input missing (none in letters 5376 or 5377) | |
| Card state after ship | gap (recurs) | builder | none as a general check; 0.8.13 cards 1127 and 1130 were passed to shipped and accepted with pass --done (letter 5376) | letter 5376, 2026-11-11 | prior-pass claimed-after-merge cards were not listed in this letter; card 942 |
| replicas, sharding, partitioning | N/A | - | one office is one MySQL | 2026-11-11 (reason re-checked at 0.8.13) | expires with a second book per office |
| CQRS, event sourcing, distributed transactions | N/A | - | one book; activity is the one shared timeline | 2026-11-11 (reason re-checked at 0.8.13) | same |
| circuit breakers, rate limiting | N/A | - | one dependency (the book); the wake lease limits POSTs to one per lease | 2026-11-11 (reason re-checked at 0.8.13) | expires at the beta load target |
| Cache invalidation and stampedes | N/A | - | the only cache is glance's cached read, rebuilt by the server | 2026-11-11 (reason re-checked at 0.8.13) | revisit if a second cache appears |

A row changes only through a normal PR. The Validator checks that each
pointer resolves and that the rows parse; it does not re-run the checks.
