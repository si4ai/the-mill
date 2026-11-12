# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.14 (2026-11-12)

- card 1125: SPIN model and design doc for the agreed replace-body MVP
- card 1138: failure-class list for the 0.8.13 release pass
- card 1133: card and letter text keep their history: `activity_history`, body edit stamps, `todo.body` is the text and `todo.meta` the rest, `mill_body_replace` with a stale check and a plain same-text refusal, `mill_body_history` newest first with an order option; existing books migrate in place.
- grok-bot guide: end a wake with wake-done, not a trailing connect argument
- A tw exit or crash no longer rings an empty webhook wake. It rings only when mail, a hint or an unopened receipt waits for the desk. Stall and match still ring.
- card 1155: add a hidden-code scan of the PR diff
- docs: card 1132, correct the 0.8.12 1112 refusal wording and point pr authors at ci/test-select.toml
- Score tab redesign: scores by impact, tw-time spend
- card 1147: add a dead-command scan for mill examples outside check_doc_commands
- card 1151: add a failure-class coverage check for FAILURE-CLASSES.md
- card 1152: add a test-overlap check for duplicate tests and uncovered F-rows
- card 1148: add a CI flake-rerun check for fail-then-success runs
- card 1145: add an install-drift check for routines, tables, and columns
- verify/spin: V01-V24 model the live wake modes F1, F2, F3 and F7 before and after #416.
- card 1153: PRIORITIES tab, each desk's ranked list (first slice)
- card 1160: Score tab routes /api/v1/activity-buckets and /api/v1/score-runs, score.updated
- card 1140: record the wake lease on the wake that rang it
- card 1154: tw keeps the sitting connect's link when a second connect for the desk starts, waits for a starting connect, and shows the tw form in its refusal
- card 1153: GET /api/v1/labels for the Wall PRIORITIES tab, label.updated (schema change)
- card 1141 step 2: pending() no longer counts rows already sent live, so a tw exit or trailing wake does not ring for work the desk already has; the empty skip is re-checked under the gate lock.
- hygiene: check_pack's home-path rule now catches WSL UNC shares (wsl$ and wsl.localhost) and /mnt/<drive>/Users/<login> paths.
- free the seat after this desk's own connect exits
- ci: let a hidden-code scanner crash show red (card 1155)
- card 1171: mill_mail_delete finds wakes by cause/cause_id and locks each row by primary key only
- card 1125: delete the note command; `mill todo ROSTER NEED --eta/--started/--done-when/--progress` sets card fields and `mill replace-body` changes card and letter text; replace-body rights follow office trust (matrix in docs/requirements/admin.md)

## Last changes

0.8.13 (2026-11-11)

- card 1130: `mill connected` filters one desk with `--who DESK`; `--desk` is the seat borrow there too. A command with no connect and no `--desk` says why and prints the exact next command. `todo --mine --desk DESK` matches the borrowed desk.
- docs: grok-bot guide examples pass --desk (0.8.12 cold measure)
- check_pack `--pr-message`: the pull_request run scans the squash message (title and body) with the private names, so a hit shows before the merge queue.
- card 1127: select CI test jobs from ci/test-select.toml
- docs: card 1130 wording for 0.8.13 (connected --who, refusal next command)
