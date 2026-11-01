# F-desk-start-sh

card 934. `tools/desk/desk-start.sh` is a POSIX sh launcher for Linux/WSL/macOS.
It reads plan JSON from `desk_start_plan.py` and execs `grok` from `argv`.
Credential check covers Windows Credential Manager (`cmdkey`), macOS keychain
(`security find-generic-password`), or a mode-600 file named by
`credential_target`. Dry-run prints the plan JSON. Live launch refuses
`launch_mode=dashboard` (UNVERIFIED attach) and missing credentials. Never
passes `-r`/`-c`/`--fork-session`/`-p`. No GNU-only shell flags. macOS live
coverage noted on card 933.
