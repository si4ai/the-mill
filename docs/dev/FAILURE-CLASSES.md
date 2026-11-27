# Failure classes: who checks what

The Auditor's coverage list (auditor-focus decision, letter 2668). One row per
failure class. Status is **covered** (an owner and a check that has run and
catches the class), **gap** (no owner, no check, or the check has never run),
**split** (covered for one part, gap for another; both named), or **N/A** (the
reason, and what would change it). Evidence is the covering command plus the sha
and date of its last result. A result older than the pass it is listed in is
**stale**. Times are PT.

Last pass: the 0.8.18 release pass (live letter 6989, start letter 6990), tag
v0.8.18 at 2c8e08e7, 2026-11-24. Previous pass in this file: 0.8.17 (letter
6894, 8c8e9925); that list landed as docs/dev/FAILURE-CLASSES.md in #512 (card
1293) and is byte-equal to the 0.8.17 draft at v0.8.18. Cards are mill cards on
roster the-mill. "Release run" = release run 45450537727 at 2c8e08e7 (ci,
verify, publish_pypi success, letter 6989). 0.8.18 has no SQL or schema change
and touches no wake or hold code (diff v0.8.17..v0.8.18: tw client, doing
records, score view, Wall rd pane, rco workflow, docs).

`tools/check_failure_classes.py` is still not a CI gate and no release step runs
it (card 1151 open, no volunteer).

| Class | Status | Owner | Covering check | Last result (sha, date) | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Lock order and deadlock between procedures | covered | builder (code), auditor (model) | `verify/spin/run.sh` holds model (card 1267, #490); `tests/server/records/test_lane_b_moves_080.py` in CI `pytest_sql` | SPIN holds 3528b8d, 2026-11-21 (6708); CI release run 2c8e08e7 2026-11-24 | wake model not re-run since #419 (0.8.14); no SQL change in 0.8.18 |
| Deadlock and lock-wait retry (an untested retry path) | covered | builder | `tests/server/test_book_health.py::test_deadlock_and_lock_wait_retry_by_code_whatever_the_class` in CI `pytest_no_sql` | release run 2c8e08e7 2026-11-24 | one immediate retry; no fault-injection per retry path (card 1146) |
| Isolation level the procedures assume | covered | builder | two-connection join-vs-retire test in CI `pytest_sql` | release run 2c8e08e7 2026-11-24; SPIN N03 stale (2026-10-30) | |
| Optimistic/pessimistic locking (row locks as guards) | covered | builder, auditor | SPIN holds (run-owned design, card 1267); F186/F223/F226 tests | SPIN 2026-11-21 (6708); CI 2c8e08e7 2026-11-24 | card 1271 (hold refusal row can go unrecorded) open |
| Retry jitter | split: covered (client reconnect) / gap (wake) | builder, grok-tui (827) | `tests/client/test_ws_reconnect.py` (+/-20%); wake retry: none | CI 2c8e08e7 2026-11-24; wake: never | card 827 claimed since 2026-10-23, no change in span |
| One DB connection per command | gap | builder | none | not measured in span | cards 907, 1146; 0.8.18 adds a server read on each nonzero tw exit (`_tw_exit_errors`, card 1303) on the same connection |
| Connection pool exhaustion | gap | builder | none at the beta target | not measured in span | card 907 |
| Migrations, idempotent ensure | covered | builder | `sql check` on both hosts (no apply: no schema change) | 2c8e08e7 2026-11-24, pack = book 35e26e4d68cc, applied false (6989) | manual, not CI; ensure-twice last run 0.8.17 (6892) |
| Done-check on the wrong artifact | split: covered (migrations) / gap (card done_when) | builder | migrations: as above. Cards: none; shipped lines written on 1289, 1303, 1304 (6989) | 2026-11-24 (6989) | card 946 open |
| Zero-downtime upgrade | N/A | builder | one office, planned stop | 2026-11-24 (6989: mill-wall restart, /health 200) | expires when an office cannot take a stop |
| Stored-procedure and install drift between hosts | split: covered (detect) / gap (duration, object diff) | builder | `/health` stamp check: both hosts 200, X-Mill-Version 0.8.18, same stamp | 2c8e08e7 2026-11-24 (6989) | LAN process recycled by itself after checkout; nothing records how long hosts differ; `tools/check_install_drift.py` never run between hosts (card 1145); card 908 |
| Two copies of mill on one host | gap | builder | none | 6989 (2026-11-24): LAN service runs the v0.8.18 checkout while the host pip package is still 0.8.17 | card 908 (note this pass) |
| Client/server version skew | covered (warn) | builder | client `warn_wall_version` on X-Mill-Version (agent_coord/client/http.py) | code at 2c8e08e7; desks asked to `mill update` (6989) | warn only |
| Lost wakes | gap (0.8.17 wake change unmodelled) | builder (code), auditor (model) | SPIN live wake modes F1 F2 F3 F7 (#419); `tests/server/test_wake_lease_races_887_888.py` in CI | SPIN 2026-11-12 (stale vs 0.8.17 `mill-build-wake`, card 1285); CI 2026-11-24 | cards 1296 (deferred to 0.8.19), 1284, 827 open; 0.8.18 touched no wake code |
| Duplicate or overlapping wakes | covered (stale model) | builder, auditor | SPIN W01-W03, L01-L03, L05, M07, M21 | 2026-11-12 (#419) stale | card 1136 |
| Webhook receiver down or slow | gap (known) | builder, grok-tui | SPIN W08, W17 violated by design | stale | card 827 |
| Queue rows and dead letters | split: covered (stale model) / gap (tw hop failure branches) | builder, auditor, grok-tui | SPIN `no_loss`; tw hop queue: `tests/client/test_tw_cmd_1303.py` ok path only | SPIN 2026-11-12 stale; CI 2c8e08e7 2026-11-24 | `outbox.post_through` down / not-ok / cap branches (card 1303) have no test; card 1307 (note this pass) |
| Run end lost when the session closes first | gap | grok-tui (tw client), builder | none: reconcile closes the run later | builder's 7-day count: 19 of 21 reconcile-closed runs had finished (card 1307, 2026-11-24) | card 1307 open; builder works around it with a local poll |
| notification after commit (outbox) | gap (known) | builder | none | n/a | |
| graceful shutdown / restart | gap (known) | builder | SPIN W11 violated | stale | LAN restart may still be a human step (6989) |
| Docs, hints and skills naming dead commands | split: covered (command names) / gap (flags refused in a session, wider scan) | builder (check), gardener (skill) | `check_doc_commands.py`, `check_skill_copy.py --installed` in CI; host skill sha 3fd69ad6 = pack on both hosts (6989, 6991) | CI 2c8e08e7 2026-11-24 | new 0.8.18 skill line (`mill score ...` with `--desk DESK`) is refused in a sitting connect: caught by hand (6986), not by CI; new card this pass; `check_dead_commands.py` (#411) never run at a release |
| Silent truncation at size limits | split: covered (tw meta drops named) / stale (4096 caps) | builder | 0.8.18: bad `pr`, `bytes_*`, `cmd` are dropped and named in meta `dropped` (`tests/server/test_tw_run_bytes_1289.py`, CI); 4096 refusals on body, detail | CI 2c8e08e7 2026-11-24; caps 2026-10-30 stale | cards 1149, 999 open; client drops a bad `cmd` without a record |
| Health checks | covered | builder, validator | `/health` + X-Mill-Version after install | cloud 200 0.8.18; LAN 200 0.8.18, 2026-11-24 (6989) | |
| tracing and per-command cost | split: covered (tw runs) / stale (mill commands) | builder | tw runs: cmd word, bytes in/out, per-card and per-PR rollup (cards 1289, 1303); mill commands: F171 lines | CI 2c8e08e7 2026-11-24; F171 2026-10-30 stale | rollup has no live data until desks run 0.8.18 tw |
| Checker-host drift | covered (stale pointer) | validator | host line in each VERDICT | letter 6719, 2026-11-21: host-drift none | pointer `tools/hostline.sh` still missing at v0.8.18 (missing_path, card 1298) |
| Trust boundary | covered | builder, validator | CodeQL, `check_silencers.py`, `check_hidden_code.py`, `check_pack --commits/--pr-message` in CI | codeql 45447110979 and ci 45447110912 at 2c8e08e7, 2026-11-24 | cards 1292, 1300 open |
| Cold-agent outcome | split: covered (0.8.14) / INPUT MISSING (0.8.15, 0.8.16, 0.8.16.1, 0.8.17, 0.8.18) | gardener | cold measure per shipped version, mill version + skill sha | 0.8.14 letter 6142 (mill 0.8.14, skill 9fbdffe854df) PASS; 6895 and 6991 skipped (barker-wake paused) | card 1294; resuming barker-wake waits on the office human (6898) |
| Card state after ship | gap (recurs) | builder | none | 2026-11-24 | 0.8.18 cards moved to shipped at ship (good); still claimed after merge, unchanged since 0.8.17: 1140, 1141, 1153, 1160, 1163, 1207, 1223, 1239, 1228, 1155; card 942 |
| Release with no audit input | gap | builder (ship step), auditor | none: auditor letter is a hand-written reply | 0.8.18 got one (6990) | card 996 |
| Release gate names desks that are not on the office | gap | gardener (build skill), builder | none: the ship-desk mapping is hand-written in the build skill | 0.8.18 tagged with 3 mapped desks absent and no owner waiver (6982, 6989); asked list included an unmapped desk (6985) | new card this pass |
| Wake or hold design change without a SPIN letter | split: covered (hold, 6649) / gap (wake, 1285) | builder | letter by hand | 6649 (2026-11-20); none for 1285 | cards 1144, 1296; 0.8.18 had no wake or hold change |
| Known false positive accepted each release | gap | builder | `check_sql` MILL_DESK_ID case-fold flagged and waved through (5376, 6108, 6730) | 0.8.16 (6730); not named at 0.8.18 (no SQL change) | card 1297 |
| replicas, sharding, partitioning | N/A | - | one office is one MySQL | 2026-11-24 re-checked | expires with a second book |
| CQRS, event sourcing, distributed transactions | N/A | - | one book | 2026-11-24 re-checked | same |
| circuit breakers, rate limiting | N/A | - | one dependency; wake lease limits POSTs | 2026-11-24 re-checked | beta load target |
| Cache invalidation and stampedes | N/A | - | glance cached read only | 2026-11-24 re-checked | second cache |

A row changes only through a normal PR. The Validator checks that each
pointer resolves and that the rows parse; it does not re-run the checks.
