# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.17 (2026-11-23)

- card 1281: a tw descendant cannot forge a start to take a run credit
- card 1228: report-only rco job (diff, affected, drift, notice, update) with an rco-report artifact and token metrics
- 1285: mill-build-wake prints one hint line and stays quiet when a child command exits 0.
- Ignore .rco/ and rco-report/ local RCO output
- card 1288: a body:stale refusal names the editor, the UTC time and the next step
- A reply keeps the body stamp of the letter it answered.
- A send names a webhook wake and keeps offline for a desk with no wake.
- #1286 Wall desks: nest live tw runs in the desk detail
- dependency bumps: eslint 10.15.0 (minimatch 11.0.9 for CVE-2026-118764), stylelint 18.1.0, fastapi 0.165.0 (CI lock), github/codeql-action 4.39.4
- A send or reply to the sender's own desk returns the letter id.
- A label skip names the type or the restore, and a trashed label-add drops the code prefix.
- card 1273: teach CodeQL the redactor and gate new silencers
- check_pack: a bare card number at the start of a line is a line-start prefix, the same as #338

## Last changes

0.8.16.1 (2026-11-21)

- card 1223: a mill command from a tw run's descendant is forwarded with its arguments; 0.8.16 sent the bare verb and still printed ok
- card 1239: a mill write two or more tw levels down reaches the office; 0.8.16 refused it with "command refused"
- card 1239: a nested tw run's start and exit events name the run above it as parent, never the run itself, and the desk link passes that parent to the office (card 1279)
- tools: changelog_generate and precheck read a four-part version such as 0.8.16.1
