# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.15 (2026-11-13)

- ci: run the pytest suites once on the PR; the merge queue checks ancestry
- schema: one unique name string, with type triggers (card 1163)
- card 1191: GET /api/pov?part=desks returns every station with last_connected (ISO UTC) and recent_activity.at
- add oldest waiting letter time and the over-a-day count (card 1192)
- wall: 7-day station rail with last connection, full list in Admin (card 1191)
- Drop the 800px pane cap so the Wall is fluid at any width
- wall: working desks lead the desk list, idle sits last
- Wall: tabs are DESKS-first (DESKS, TODO, MAIL, PRIORITIES, SCORE, COLLAB).
- fix: close the four codeql findings (cards 1064-1067)
- wall: DESKS urgency keeps working desks before idle ones
- add cascade on foreign keys and the bearer salt copy (card 1200)
- card 1193: Wall scope filters. desks= and window=1d|7d|30d on every Wall list route, comma roster lists on doing, labels, activity-buckets and score-runs, and roster members on GET /api/pov?part=rosters
- docs: document every CI job and why the name-token check misfires
- list every roster with its member count (card 1204)
- doing is only tw runs: `--doing` / `--waiting-on` and the focus row are gone, `mill connected` lists each desk's live doings and `n`, and the migration drops `seat.doing_id` and doing's focus columns (card 1207).
- fix: apply_1207 zone check, connect-anchor desk, compressed hold test (card 1207)
- add the collab replay keyset with edges (cards 1205 1206)
- card 1207: copy `doing.peer_id` onto assign transition `meta.to` before the 1207 migration drops those rows, so assigns made before 0.8.15 keep their assignee.
- add the part 1 attention scores read (card 1212)
- wake by the delivery chosen at join (card 1211)
- card 1214: a score is one desk and one kpi, and a view points at that score
- docs: webhook desks are rung while connected (fix-forward #458)
- wall: full redesign - scope rail and six roster-wide tabs

## Last changes

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
- check_pack: markdown heading marks are a line-start prefix for the name-token rule
