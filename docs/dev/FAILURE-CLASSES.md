# Failure classes: who checks what

The Auditor's coverage list (auditor-focus decision, letter 2668). One row per
failure class. Status is **covered** (an owner and a check that has run and
catches the class), **gap** (no owner, no check, or the check has never run),
**split** (covered for one part, gap for another; both named), or **N/A** (the
reason, and what would change it). Evidence is the covering command plus the sha
and date of its last result. A result older than the pass it is listed in is
**stale**. Times are PT.

Last pass: the 0.8.17 release pass (live letter 6892, start letter 6894), tag
v0.8.17 at 8c8e9925, 2026-11-23. Previous pass in this file: 0.8.13 (letter
5377, 625746e4). 0.8.14, 0.8.15, 0.8.16 and 0.8.16.1 shipped with no auditor
release pass (see row "Release with no audit input"). Cards are mill cards on
roster the-mill. "Release run" = release run 45334305656 at 8c8e9925 (ci jobs,
verify, publish_pypi success, letter 6892).

`tools/check_failure_classes.py --repo . --as-of 2026-11-23 --strict` on the
0.8.13 rows at v0.8.17: 30 classes, 15 findings (missing path 1:
`tools/hostline.sh`; stale 14). Not a CI gate and no release step runs it
(card 1151 done-when unmet).

| Class | Status | Owner | Covering check | Last result (sha, date) | Note |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Lock order and deadlock between procedures | covered | builder (code), auditor (model) | `verify/spin/run.sh` holds model (card 1267, #490); `tests/server/records/test_lane_b_moves_080.py` in CI `pytest_sql` | SPIN holds at release/0.8.16 77ed251 / 3528b8d, 2026-11-21 (letters 6649, 6708); CI release run 8c8e9925 2026-11-23 | wake model not re-run since #419 (0.8.14) |
| Deadlock and lock-wait retry (an untested retry path) | covered | builder | `tests/server/test_book_health.py::test_deadlock_and_lock_wait_retry_by_code_whatever_the_class` in CI `pytest_no_sql` | release run 8c8e9925 2026-11-23 | one immediate retry; no fault-injection per retry path (card 1146) |
| Isolation level the procedures assume | covered | builder | two-connection join-vs-retire test in CI `pytest_sql` | release run 8c8e9925 2026-11-23; SPIN N03 stale (2026-10-30) | |
| Optimistic/pessimistic locking (row locks as guards) | covered | builder, auditor | SPIN holds (run-owned design, card 1267); F186/F223/F226 tests | SPIN 2026-11-21 (6708); CI 8c8e9925 2026-11-23 | card 1271 (hold refusal row can go unrecorded) open |
| Retry jitter | split: covered (client reconnect) / gap (wake) | builder, grok-tui (827) | `tests/client/test_ws_reconnect.py` (+/-20%); wake retry: none | CI 8c8e9925 2026-11-23; wake: never | card 827 claimed since 2026-10-23, no change in span |
| One DB connection per command | gap | builder | none | not measured in span | cards 907, 1146 |
| Connection pool exhaustion | gap | builder | none at the beta target | not measured in span | card 907 |
| Migrations, idempotent ensure | covered | builder | `mill install sql --apply` twice, same stamp; `sql check` ok, both hosts | 8c8e9925 2026-11-23, pack = book 35e26e4d68cc (letter 6892) | manual, not CI |
| Done-check on the wrong artifact | split: covered (migrations) / gap (card done_when) | builder | migrations: as above. Cards: none; 0.8.17 shipped lines written on each listed card (6892) | 2026-11-23 (6892) | card 946 open |
| Zero-downtime upgrade | N/A | builder | one office, planned stop: about 53 s at 0.8.17 | 2026-11-23 (6892) | expires when an office cannot take a stop |
| Stored-procedure and install drift between hosts | split: covered (detect) / gap (duration, object diff) | builder | `/health` refuses (503) when the running pack stamp differs from the book: LAN host 46b378419e6b vs book 35e26e4d68cc | 8c8e9925 2026-11-23 (6892), loud and correct | hosts differ until a human service restart (also 0.8.16, 6730/6732); nothing records how long; `tools/check_install_drift.py` never run between hosts (card 1145); card 908 |
| Two copies of mill on one host | gap | builder | none: LAN wall still runs from a git checkout beside the package | 6892 (checkout at v0.8.17, untracked files kept) | card 908 claimed, last progress 0.8.5 |
| Client/server version skew | covered (warn) | builder | client `warn_wall_version` on X-Mill-Version (agent_coord/client/http.py) | code at 8c8e9925; desks asked to `mill update` (6892) | warn only |
| Lost wakes | gap (0.8.17 wake change unmodelled) | builder (code), auditor (model) | SPIN live wake modes F1 F2 F3 F7 (#419); `tests/server/test_wake_lease_races_887_888.py` in CI | SPIN 2026-11-12 (stale vs 0.8.17 `mill-build-wake`, card 1285); CI 2026-11-23 | card 1284 (failed poke stays seated) open; 827 open; new card for the SPIN letter |
| Duplicate or overlapping wakes | covered (stale model) | builder, auditor | SPIN W01-W03, L01-L03, L05, M07, M21 | 2026-11-12 (#419) stale | card 1136 |
| Webhook receiver down or slow | gap (known) | builder, grok-tui | SPIN W08, W17 violated by design | stale | card 827 |
| Queue rows and dead letters | covered (stale model) | builder, auditor | SPIN `no_loss` | 2026-11-12 stale | 30-day sweep not modelled |
| notification after commit (outbox) | gap (known) | builder | none | n/a | |
| graceful shutdown / restart | gap (known) | builder | SPIN W11 violated | stale | LAN restart pending at 0.8.17 |
| Docs, hints and skills naming dead commands | split: covered (CI docs, host skills) / gap (wider scan) | builder (check), gardener (skill) | `check_doc_commands.py`, `check_skill_copy.py --installed` in CI; host skill sha 5981ce81 = pack (6892) | CI 8c8e9925 2026-11-23 | `check_dead_commands.py` (#411) not a gate and never run at a release |
| Silent truncation at size limits | covered (refusals) / stale | builder | 4096 refusals on body, detail; evidence uncapped | 2026-10-30 stale | cards 1149, 999 open |
| Health checks | covered | builder, validator | `/health` + X-Mill-Version after install | cloud 200 0.8.17; LAN 503 (stamp) 2026-11-23 (6892) | the 503 caught the LAN drift |
| tracing and per-command cost | covered (stale) | builder | F171 per-command lines | 2026-10-30 stale | |
| Checker-host drift | covered (stale pointer) | validator | host line in each VERDICT | letter 6719, 2026-11-21: host-drift none | pointer `tools/hostline.sh` does not exist in the repo (missing_path) |
| Trust boundary | covered | builder, validator | CodeQL (redactor sanitizer, card 1273), `check_silencers.py`, `check_hidden_code.py`, `check_pack --commits/--pr-message` in CI | release run 8c8e9925 2026-11-23; 6719 hidden_code_report success | card 1292 (LogRotateCopy over-broad) deferred |
| Cold-agent outcome | split: covered (0.8.14) / INPUT MISSING (0.8.15, 0.8.16, 0.8.16.1, 0.8.17) | gardener | cold measure per shipped version, mill version + skill sha | 0.8.14 letter 6142 (mill 0.8.14, skill 9fbdffe854df) PASS; 6728 and 6895 skipped (barker-wake paused) | |
| Card state after ship | gap (recurs) | builder | none | 2026-11-23 | still claimed after merge: 1140, 1141, 1153, 1160, 1163, 1207, 1223, 1239, 1228, 1138, 1155; card 942 |
| Release with no audit input | gap | builder (ship step), auditor | none: auditor letter is a hand-written line | 0.8.14-0.8.16.1 no pass | card 996 |
| Wake or hold design change without a SPIN letter | split: covered (hold, 6649) / gap (wake, 1285) | builder | letter by hand | 6649 (2026-11-20); none for 1285 | cards 1144, new 1285 card |
| Known false positive accepted each release | gap | builder | `check_sql` MILL_DESK_ID case-fold flagged and waved through (5376, 6108, 6730) | 0.8.16 (6730) | new card |
| replicas, sharding, partitioning | N/A | - | one office is one MySQL | 2026-11-23 re-checked | expires with a second book |
| CQRS, event sourcing, distributed transactions | N/A | - | one book | 2026-11-23 re-checked | same |
| circuit breakers, rate limiting | N/A | - | one dependency; wake lease limits POSTs | 2026-11-23 re-checked | beta load target |
| Cache invalidation and stampedes | N/A | - | glance cached read only | 2026-11-23 re-checked | second cache |

A row changes only through a normal PR. The Validator checks that each
pointer resolves and that the rows parse; it does not re-run the checks.
