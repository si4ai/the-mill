# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.16.1 (2026-11-21)

- card 1223: a mill command from a tw run's descendant is forwarded with its arguments; 0.8.16 sent the bare verb and still printed ok
- card 1239: a mill write two or more tw levels down reaches the office; 0.8.16 refused it with "command refused"
- card 1239: a nested tw run's start and exit events name the run above it as parent, never the run itself, and the desk link passes that parent to the office (card 1279)
- tools: changelog_generate and precheck read a four-part version such as 0.8.16.1

## Last changes

0.8.16 (2026-11-21)

- card 1234: name gets a plain (type, name) index again (idx_type_name) on fresh and upgraded hosts; idx_name stays the only unique key
- dependency bumps: fastapi 0.162.7 (CI lock), html-validate 11.21.1 (wall validators), desk client pin the-mill 0.8.15
- card 1236: replacing a letter tells the desks that already read it.
- card 1233: desk writes and reads of the six activities take repeatable --label.
- card 1223: a tw run forwards allowlisted mill commands from its descendants (in 0.8.16 the arguments were lost and the bare verb went through; fixed in 0.8.16.1)
- card 1223: the office records each mill call a tw run's descendants make, and `mill connected --run WATCH_ID` lists the run and those calls
- card 1232: the sitting desk pipe is owner-only and checks the server process.
- card 1239: a nested tw run keeps its parent, and connected --run lists that tree (in 0.8.16 a write two tw levels down was refused and nested events named the run as its own parent; fixed in 0.8.16.1)
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
