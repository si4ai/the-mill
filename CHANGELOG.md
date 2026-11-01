# Changelog

## TBD (upcoming)

Upcoming changes are our current plan, not a promise; they can change or move at release time.

- card 979 / F-rooms-live-ws: mill rooms works on live /ws (drop _require_live_ws from _h_rooms)
- after card 935 lands: repo admin applies the merge-commit ruleset draft for `release/*`
- card 943: per-desk GitHub apps (needs human app create/install)

## New changes

0.8.3 (2026-10-31)

- #286 F-pytest-sql-xdist-2 ci-speed xdist -n2; #287 F-pwsh-f221-guard pwsh F221 guard; #288 F-name-trash-roster-gate name-trash roster gate; #290 F-pr-title-body-name-token pr_text name-token; #297 card 949 / F-replay-unread; #298 card 952 skill/cli-desk flag coverage; F-connect-explicit-db connect(database=) bypasses stale pool; F-perf-lock-ms-structural perf lock_ms structural waits; #292 card 923 / F-client-older-than-office client-older warn; #293 card 815 / F-strict-csp-wall strict wall CSP; #262 desk.txt the-mill 0.7.19; #291 card 817 browser write origin; #300 card 827 wake retry; #280/#285/#289 skill prune + connect wording + barker-kit; card 734 / F-code-hint-commands; card 649 / F-find-hint-given-flags; card 948 failure-class list; card 927 / F-create-todo-retired; card 933 macOS test-day checklist; card 797 / F-log-rotation; #302 finished-card-PR habit -> docs/dev/RELEASE-FLOW.md; card 958 / F-mill-rooms; card 955 / F-delivery-kpi-score; card 735 / F-notfound-names-next-command; card 962 / F-post-ship-check; card 736 / F-argparse-errors-subcommand-usage; F-pool-follows-database pool follows AGENT_COORD_DATABASE; #309 card 969 ETA tool-call rounds; #307 card 963 / F-roster-send-skips-retired

## Last changes

0.8.2 (2026-10-31)

- card 734 / F-code-hint-commands: code-hint parity for mill commands in agent_coord strings
- #279 card 935 / F225: `check_pack --commits` scans every commit a pull request would bring to main
- #281 card 931 / F226: drop-call holder race refuses; already-free wording; `hold_stale_days` docs
- #282 card 814 / F227: harden wall session-cookie tests
- #283 card 936 / F228: changelog with three sections (TBD, New, Last)
