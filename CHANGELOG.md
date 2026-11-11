# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.11 (2026-11-10)

- card 1103: skip the name-token rule on bot-authored PR bodies
- card 1090: keep a finished tw run and log stderr
- bump html-validate from 11.17.0 to 11.18.0 in tools/wall-validators
- ci-lock: bump the-mill pin in desk.txt to 0.8.10
- bump github/codeql-action from 4.39.1 to 4.39.3
- bump stylelint from 17.16.0 to 18.0.0 in tools/wall-validators
- card 1090: count a reply that auto-ends the wake lease as acted
- card 1090 step 4 (server): sweep stale task rows at the cap; cap reply names oldest watches
- card 1111: write webhook failures and fill wake desk and cause
- card 1113: todo insert takes the desk seat before its FK check (fix concurrent-insert deadlock)
- card 1113: todo card writes take the desk seat before the card; source lock-order check
- card 1090: tw hops through the sitting connect
- card 1113: wake, mail, join, plan, score and status procedures lock before they read
- card 1113: score step re-raises deadlocks; wake ids from AUTO_INCREMENT; visible push errors
- card 1090: tw docs for 0.8.11 (doing under tw, updates habit, cards as bodies of work)
- card 1120: generate CHANGELOG.md at bump from each PR's one-line Changelog section
- card 1120: docs-only Changelog exemption diffs base...head in CI
- docs: hold habit in mill-desk skill (0.8.11)

## Last changes

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
