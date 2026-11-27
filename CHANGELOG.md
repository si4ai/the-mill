# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.19 (2026-11-27)

- card 1293: record the 0.8.18 failure-class list
- card 1310: CI checks that skill examples with --desk are the no-connect form
- reword the 0.8.18 failure-class note so it is not a mill --desk example
- card 1324: exact-edge tests for the 7d and 30d doing-error windows
- card 1311: replay wake events against the model (slice 1)
- card 1312: scan for wake writes that skip the wake queue code (slice 1)
- card 1329: wake bypass scan warnings from #526
- card 1328: wake trace replay and collect warnings from #525
- card 1312: bypass scan reads card status writes
- card 1311: trace_conform replays todo (card status) events
- card 1312: bypass scan skips quoted strings in a SET list
- card 1334: pr_text name-token skip applies to dependabot only, not every bot account
- card 1335: pr_text name-token skip needs the exact dependabot login
- card 1336: call the shared si4ai/.github pr_text, validator and codeql workflows; drop the local copies
- card 1321: a tw start records the wake that started the run
- the rco report job pins repo-context-optimizer 0.1.7 (hash-locked)

## Last changes

0.8.18 (2026-11-24)

- card 1293: record the 0.8.17 failure-class list
- 1302: rco token metrics step accepts rco pack findings exit
- 1289: tw run bytes per card and per PR (server half)
- A tw run records byte counts, and can name its card and pull.
- 1303: tw command word and doing-error counts (server half)
- 1304: warn when an rco pack is over its token budget
- A tw run records its command word and prints a repeated error count.
- #1303 Wall desks: paint doing errors in the desk score row
- 1303 add the repeat-errors habit and name both doing-error score keys
