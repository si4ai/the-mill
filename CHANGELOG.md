# Changelog

## TBD (upcoming)
Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 1053 / transition-retention: archive + rollup for transition (and optional wake); deferred past 0.8.10; DDL needs office human review before code
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 950 desk-start launcher: moved to 0.8.5 (live: no visible grok screen)
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

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

## Last changes

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
