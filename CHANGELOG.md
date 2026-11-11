# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.13 (2026-11-11)

- card 1130: `mill connected` filters one desk with `--who DESK`; `--desk` is the seat borrow there too. A command with no connect and no `--desk` says why and prints the exact next command. `todo --mine --desk DESK` matches the borrowed desk.
- docs: grok-bot guide examples pass --desk (0.8.12 cold measure)
- check_pack `--pr-message`: the pull_request run scans the squash message (title and body) with the private names, so a hit shows before the merge queue.
- card 1127: select CI test jobs from ci/test-select.toml
- docs: card 1130 wording for 0.8.13 (connected --who, refusal next command)

## Last changes

0.8.12 (2026-11-10)

- card 1112: a desk command with no sitting connect takes `--desk DESK` and borrows that desk's seat. It does not read the active-desk file. With no `--desk` and no connect, the refusal says why and names the exact next command. When this shell already has a connect, `--desk` is refused. When that desk has a seat on more than one office and `--office` was omitted, the command names those aliases and asks for `--office ALIAS`
