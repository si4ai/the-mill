# Changelog

## TBD (upcoming)

Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

- card 1113: renaming cards from several sessions at once, or renaming a card while noting it, no longer deadlocks; rename takes the desk's seat lock before the card, as every card write does. New `tools/sql_lock_order.py` lists each procedure's row locks from the schema's foreign keys and fails on a shared-to-exclusive lock upgrade; a no-database test runs it and lists the known lock-order cycles

- card 1113: one desk filing cards from several sessions at once no longer deadlocks; the todo insert takes the desk's seat lock before its insert, and the concurrent-insert test no longer retries

- card 1111: webhook failures write wake_fail (and wake_retry when a retry is armed); wake edges use the woken desk; new wake rows fill cause_type and cause_id

- card 1111: retry_armed stays visible to ring_waiting; a POST with no wake row writes no row state; expire-marker error tallies include retry_armed

- card 1111: precheck does not fail when a changed test file holds only SQL tests

- card 1090: a reply that auto-ends the wake lease is not scored wasted
- card 1090 step 4 (server): a live tw task row is stale only once its desk has been offline (no connected seat) for 24h, counted from `seat.time_disconnect`; a connected desk's rows are never stale. The score tick sweeps desks offline 24h+ (one `tw_stale` edge each, cause `sweep`), and a tw start at the cap sweeps the same way; a cap reply still at the cap names the oldest live watch ids and says to end one with `kill PID`. New session hop `tw.reconcile`: on start, a desk's connect reports the watch ids it believes live; the host closes that desk's other live task rows through the crash path (`tw_failed`, cause `reconcile`), ignores unknown ids, and a repeat closes nothing. Glance alerts gain `tw_offline`: each offline desk with live tw rows, how long offline, and the count (a fact, not a gate). `tw.event` takes an optional `ts_ms` (tw's clock, epoch ms) and dwell uses it when both hops carry one

- card 1103: skip the title-case name-token rule on a bot-authored PR or issue title and body; other hygiene rules still run, and the skip is reported in the check output

0.8.10 (2026-11-09)

- card 1098 items 1-2: compress two-state transition cycles into one row with count `n`; admin transitions pane; idempotent migrate adds `transition.n` (#371)
- card 1098 item 3: tw writes score transitions on start, finish and fail (#373)
- card 1098 / 1093: `--receipt` on send and reply; unopened receipt dests always wake; Wall Needs human clears once opened (#373)
- card 1098 item 5: wake owed only on a real miss, automatic wake-done, skip empty wakes (#373)
- card 1098 / admin book pane: admin window selector, by-pair table, wake health; book tab type table, transitions block, wake-health alerts (#373)
- card 1098 / docs: `--receipt` and the tw score note, plus the single-host config.toml limit (#373)
- card 1098 / sql: `sp_cmd.sql` and `sp_push.sql` reload via migrate (#371, #373)
- card 1095 / card 1097: tw status without a sit; join and connect write the desk pointer (#370)
- card 970 / pack skill.md: tw habit with `--log FILE` (#368, #369)

## Last changes

0.8.9 (2026-11-06)

- card 970 / task wrapper: `tw` run, list and stop, local link, local watch and status, notices and one recipe, spool and sit-end survival (#350, #353, #355, #357, #359)
- card 970 / tw.event: server accepts the tw.event hop, drops stream and sample bodies, births one task doing row with transitions and wake, and caps live tasks with replay-safe ingest (#351, #356, #358, #360)
- card 970 / task act schema: `task` added to the activity and doing act enums; existing books take `migrate_970_task.sql` (idempotent) (#358)
- card 1005 / F-unread-wake-retry: failed wake for unread-only mail arms retry (push drained) (#338)
- card 1011 / F-insert-deadlock-retry: concurrent insert deadlock retries twice (#337)
- card 1069: light and heavy partner review and ship GO documented in docs/dev (#349)
- card 1080 / commands-without-sitting-connect: a desk command that cannot see a sitting connect opens one socket, sends that command, and releases the bearer; a bearer another connect already holds stays with that connect (#361)

- card 970 / doing tasks feed: doing view lists live task rows as `tasks[]` (#365)
- card 970 / wall display: tasked rows, doing.task rollups and a last-done tail when no live task remains; only available score fields, no invented command text or relative timestamp (#363)
- card 1080 / command docs: document desk commands without a leftover sitting connect; align the foreground forms assertion (#364, #367)
- card 1089 / docs: map protocol, code, process and CI checks in CHECKS-AND-TOOLS (#366)
- card 970 / docs: activity-state diagrams for the current schema, including task (#226)
- card 1080 / docs: README caveats reflect the unused-connect same-shell change (#210)
