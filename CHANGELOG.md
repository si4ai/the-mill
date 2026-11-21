# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.16 (2026-11-21)

- card 1234: name gets a plain (type, name) index again (idx_type_name) on fresh and upgraded hosts; idx_name stays the only unique key
- dependency bumps: fastapi 0.162.7 (CI lock), html-validate 11.21.1 (wall validators), desk client pin the-mill 0.8.15
- card 1236: replacing a letter tells the desks that already read it.
- card 1233: desk writes and reads of the six activities take repeatable --label.
- card 1223: a tw run forwards allowlisted mill commands from its descendants
- card 1223: the office records each mill call a tw run's descendants make, and `mill connected --run WATCH_ID` lists the run and those calls
- card 1232: the sitting desk pipe is owner-only and checks the server process.
- card 1237: `mill label TYPE ID DESK` adds to or re-ranks that desk's focus list instead of failing with "name in use"
- card 1239: a nested tw run keeps its parent, and connected --run lists that tree
- card 1240: the Wall nests live tw runs under their parent and opens a run tree with each run's forwarded mill calls
- docs: webhook desks sit a connect for the whole wake run (card 1242)
- #1242 Webhook desk presence: borrow hint and reach by wake
- Name collisions say which type already holds the name, and a desk name is not minted as a label.
- card 1207: a live run's state_at is UTC, the same as its created time.
- wall: a desk reachable by wake reads "reachable by wake" with its last wake time, not disconnected (card 1242)
- #1255 Lists hide trashed names; activities keep them marked deleted
- #1258 #1259 #1260 Wall and list join fixes from the joins audit
- #1266 Dev host book import script for the card 1200 steps
- #1255 Wall paint: strikethrough plus deleted tag for retired and trashed names
- #1266 Revert the import script print sink to the text layer
- #1267 hold: one-use release key, refuse second take, keyed drop
- A refused command names the office sentence on stdout.
- card 1241: mill delete NAME empties a name and mill purge is removed
- Verify: SPIN `holds.pml` models card 1267 hold-session-safe (today's desk-owned hold as the counterexample, the release-key design as PR #490 builds it, with mutants); `verify/hold-code` re-anchored to the release-key code.

## Last changes

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
