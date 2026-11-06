# Changelog

## TBD (upcoming)

Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); target 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

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

## Last changes

0.8.8 (2026-11-05)

- card 1072 / readme-honest-caveats: README honest caveats refreshed against 0.8.7; mail-thread wording per docs owner GO (#210)
- card 1009: grok-bot guide inlines cold barker join flags (no installed link to docs/dev/barker-kit.md) (#331)
- card 1063 / antigravity-model-docs: howto-ai Google section + models/antigravity skill (#344)
- card 925 auditor verify pack: verify/{doing,score,mail,wake,hold}-code anchors and mutants (#329, #330, #332-#335)
- card 1073 / dep-bumps-088: dependency bumps: pytest 9.2.0 (#261), starlette 1.10.0 (#263), eslint 10.14.0 (#345), ci-lock the-mill 0.8.0 (#346); desk.txt the-mill pin to 0.8.7
- card 949: stop picked-up letter re-rings and bound pending retries
- card 1068: schema parity prev-release, setuptools ci pin, wake sql fixture clear (#348)

0.8.7 (2026-11-01)

- card 1059 / migrate-1022-watcher-keep-name: migrate_1022 deletes illegal watcher type=name rows before the tip ENUM (name is not an activity); repairs hand-widened books that kept name

0.8.6 (2026-11-01)

- card 1030 / F-connect-wait-startup-sync: connect-wait first sync ends on push_queue work only (not mailbox resurfacing); one final JSON line; HINT exits 0
- card 1052: stamp span day fixture from mill_now so day-grain score tests stay inside the 30-day window
- card 1051: open-PR score (983), release score (1029), and escapes guard (955) move to tools/dev_scores (not shipped); mill score / cards guards stay product-only; no activity.type=release
- card 1028 / F-connect-activity-score: connect D2/D3 transitions + mill score startup/session median+worst, drop/reconnect counts (empty omitted; no DDL)
- card 982 / F-open-cards-queue-score: todo FEATURE transitions (T1-T12) + mill score open/claimed ages and open->claimed->shipped->done median+worst (fixtures excluded; empty omitted; no DDL)
- card 981 / F-hold-activity-score: hold FEATURE transitions (H1-H9) + mill score wait/held median+worst, contention, force-taken, expired (empty omitted; no DDL)
- card 980 / F-mail-activity-score: mail feature transitions + score views (send-to-wake / wake-to-answer / re-rings / never-answered; empty omitted)
- card 1002 / F-wasted-wake-score: no-action wakes counted and tagged by trigger; share is wasted/all wakes (empty omitted); durable W9 wake_done transition meta `{wasted, trigger}` on existing transition table (no DDL)
- card 1021 / F-score-read-only: desk score VALUE/define/retire refused (message names mill score read verb); server tick writes; note limit on point_add
- card 1020 / F-score-truncation-labelled: shaped score series labels capped point windows (truncated=true / truncated_n)
- card 1019 / F-score-empty-as-missing: empty score_tick samples omit from publish (never numeric 0); measured 0 still publishes
- card 1045: release-branch batch is the default path (RELEASE-FLOW / CONTRIBUTING-PR); skill.md keeps no release-path line (desk skill stays generic)
- card 1022 / F-transition-table: fold `push_queue` into `wake` activity + `transition`/`transition_edge`; System desk id 0; name ids 0-99 reserved; enums in code (`transition_enums.py`) / VARCHAR text in rows; hand-back marks taken (no delete) and writes a transition on take and ack; `pending` ignores taken; expire only untaken markers; `mill_transition_put`
