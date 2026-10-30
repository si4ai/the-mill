# Deterministic office steps - design (card #282)

**Card:** #282 `deterministic-office` (claimed by builder)
**Status:** design only. Nothing here is implemented yet. Each slice below
is its own card, branch and PR.
**Measure:** agent outcomes. A cold agent with only `mill help` and the
pack docs must finish the step first try, in the fewest steps, and get one
clear pass or fail. Lines of code do not count for or against a slice.

## Problem

Five recurring office steps are driven by an agent from memory today. Each
release the shipping agent writes the same three throwaway scripts again (a
host install script, a live smoke script and a GO poll script) and wraps
every desk command in a hand-written `mill connect` background dance. What goes
wrong:

1. **Release, install, SQL apply.** `mill update` (`run_update` in
   `agent_coord/install/host.py`) already stops the wall, pips, runs an
   import check, checks the SQL stamp and starts the wall. It does not:
   pin a version (`update_pip_cmd` is always `pip install -U the-mill`),
   back up the book, check `/health` 200 and `X-Mill-Version` after start,
   or roll back to the previous version when any of that fails. The agent
   adds those by hand on each host, and the book backup lives in a host
   script outside the pack.
2. **Background jobs fail silently.** `mill score-tick --once` prints the
   tick and returns 0 even when `publish` failed. `run_loop` catches every
   exception and writes it to `mill-score.log`, which nobody reads. A dead
   ticker is found only when a human notices a flat score.
3. **Hygiene, A/B, live smoke.** CI already gates hygiene (`check_pack`,
   `precommit_hygiene.py tree`), the SQL suites (`pytest_sql` on a
   throwaway MySQL) and the CLI smoke. Still manual: the A/B on a
   throwaway book before a live SQL apply (HOST.md "Stored procedures"),
   the upgrade path from the last release's book, and the live smoke after
   a host update.
4. **GO wait.** Ship GO is free text in the build room. The agent polls
   the room, reads letters and decides by eye whether every role sent GO
   naming the exact sha. A missed NOGO or a GO for the wrong sha is easy.
5. **PATH and env for routines.** A scheduled routine runs in a bare
   shell. It must find the right `mill`, drop a stray `PYTHONPATH` or
   `AGENT_COORD_MILL_HOME`, start `mill connect` in the background, wait
   for the sync frame, run one command and kill the connect. Every routine
   prompt carries that recipe, and a wrong PATH runs an old pack.

Agents should keep only the judgment calls: whether a NOGO is right,
whether a failed smoke is the release or the host, and when to wake the
office owner.

## Candidate approaches

### A. Product commands and flags in the pack

Put each step in the pip pack, mostly as flags on commands that exist:

- `mill update --to VERSION` pins, backs up, verifies and rolls back.
- `mill install sql --apply` runs the throwaway A/B itself and refuses
  without a fresh backup.
- `mill score-tick` exits nonzero on a failed tick and records a heartbeat
  score; a stale heartbeat alerts the Admin roster.
- `mill install check --smoke` runs the live smoke and cleans up.
- `mill go SHA` sends a structured GO; `mill go --wait SHA --from D1,D2`
  is the gate.
- `mill connect DESK --then COMMAND ...` connects, waits for sync, runs one
  command, prints its result and exits with its code.

Tradeoffs:

- Pro: a cold agent finds every step through `mill help COMMAND`, on any
  office (Linux or Windows), with no repo checkout. The code ships with
  the pack it updates, so it cannot drift from the SQL and the wall.
  CI tests it like any command.
- Pro: it removes the most agent steps. A host update becomes one
  command with one exit code, and a routine becomes one line.
- Con: more product surface. `mill go` is a new command against the
  lexicon's "tiny" rule; the rest are flags.
- Con: it is the largest change, so it needs to land in slices.

### B. Repo tools plus CI only

Keep the pack as it is except exit codes. Add `tools/host_release.py`,
`tools/go_gate.py` and `tools/live_smoke.py`, plus a CI upgrade-path job.

- Pro: smallest product change and the fastest first PR.
- Con: hosts run the pip pack, not the git tree. `tools/` is not in the
  wheel, so every host must fetch the scripts from git at the right sha.
  That is a new manual step and a new place to drift.
- Con: a cold agent on a host or in a routine cannot find them with
  `mill help`, so the success rate is no better than today's recipe in a
  prompt.

### C. GitHub Actions deploys the hosts

After `publish_pypi`, a deploy job reaches each host and runs the update.
GO becomes a GitHub environment approval at the tag.

- Pro: no agent steps after the tag.
- Con: the repo would hold host credentials, which the ship path rules
  out today (no stored secrets, no self-hosted runners, S-9). A host
  behind NAT or on a home network cannot be reached at all.
- Con: every desk commits and approves as the same GitHub identity, so
  an approval cannot tell builder, validator and shipper apart. The GO
  gate would get weaker, not stronger.
- Con: it needs repo and host settings that only the office owner can
  make.

## Recommendation

**Approach A, in six slices, with B's CI upgrade-path job folded in.** It
is the only option where a cold agent gets every step from `mill help`
and one exit code, and it keeps credentials off GitHub. Keep the command count
down: everything is a flag on an existing command except `mill go`.

Slices, ordered by agent steps saved per week:

| # | Slice | Card item | Steps today -> after |
|---|---|---|---|
| S1 | `mill connect DESK --then COMMAND ...` plus routine env | 5 | 5 shell lines per command -> 1 |
| S2 | `mill update --to V` verify and rollback; `install sql --apply` backup and A/B | 1, 3 | hand script per host per release -> 1 command |
| S3 | `score-tick` exit codes, heartbeat score, stale alert | 2 | none (silent) -> alert on first missed run |
| S4 | `mill go SHA` and `mill go --wait SHA --from ...` | 4 | room polling by eye -> exit 0/2 |
| S5 | `mill install check --smoke` live smoke | 3 | hand script per release -> 1 command |
| S6 | CI `upgrade_sql` job: last release's book, then this pack | 3 | manual A/B -> required check |

### S1 - connect --then and routine env

- `mill connect DESK --then COMMAND [ARGS...]`: start the socket, wait for
  the `sync` frame (with a timeout and a clear refusal on seat in use or
  superseded), run COMMAND in-process through the same dispatch the parent
  shell would use, print its output, close the socket, exit with COMMAND's
  code. Seat contention retries with backoff, then fails with one line.
- Before it runs, the routine env is fixed in code: drop `PYTHONPATH`,
  keep `AGENT_COORD_MILL_HOME` only when set on purpose, and refuse when
  the `mill` on PATH is not this interpreter's (print both paths).
- `mill briefing routine` prints the one-line routine command with the
  absolute path of this `mill`, so a scheduled prompt needs no PATH setup.
- Touches: `agent_coord/__main__.py` (connect parser and dispatch),
  `agent_coord/client/ws.py` (wait-for-sync helper), the briefing text,
  `docs/protocol/cli-desk.md`, `docs/protocol/skill.md`,
  `docs/protocol/models/grok-bot/SKILL.md` (routine steps).

### S2 - update and SQL apply that check themselves

- `mill update --to VERSION`: pip `the-mill==VERSION` (bare `-U` stays the
  default without `--to`). Record the running version first. After the
  wall starts, poll `/health` until 200 and check `X-Mill-Version` equals
  VERSION, with a bounded wait. On pip, import, start or verify failure,
  reinstall the recorded version, start the wall, verify again, and exit
  nonzero with `rolled_back: PREV`. A failed rollback exits with its own
  code and says the wall is down.
- `mill install sql --apply --backup PATH`: dump the book to PATH (owner
  only file mode) before ensure; refuse `--apply` without `--backup` or
  `--backup-ok FILE` naming a dump newer than a set age.
- `mill install sql --apply` runs the A/B itself first: create a throwaway
  database, load the live book's schema only (no rows), apply this pack
  by `split_script` and by whole file, compare routine names with
  `check_sql`, drop the throwaway database. Any mismatch refuses the live
  apply. `--ab-only` runs just that.
- Touches: `agent_coord/install/host.py` (`update_pip_cmd`,
  `update_plan`, `run_update`, new `_verify_live` and `_rollback`),
  `agent_coord/install/migrate.py` (`install_sql`, new `ab_check`),
  `tools/check_sql.py` (reuse as a function), `agent_coord/__main__.py`
  (flags), `docs/dev/BUILD.md` (Release order step 6), `docs/install/HOST.md`
  (Update a running host, Stored procedures), `docs/protocol/cli-install.md`.

### S3 - background jobs that report

- `mill score-tick --once` exits 1 when `publish` failed or measure raised.
- Every tick, ok or not, writes score `jobs.score_tick` on the Admin
  roster: 1 for ok, 0 for a failed run, with the error class in the note
  (redacted as every score note is).
- The wall `/health` body (not the status code) and `mill score Office/Admin`
  show the gap. After two missed or failed runs in a row, the next tick, or
  the wall's own check when the ticker is dead, mails the Admin roster once
  until it recovers.
- Same pattern for any later job: one helper, `job_heartbeat(name, ok, note)`.
- Touches: `agent_coord/server/score_tick.py` (`tick`, `run_loop`,
  `publish`, `_log`), `agent_coord/server/win_score_svc.py`,
  `agent_coord/__main__.py` (score-tick return code), `agent_coord/server/asgi.py`
  (health detail), `agent_coord/server/score_system.py`.

### S4 - GO gate at the exact sha

- `mill go SHA [--nogo REASON]` sends a letter to the build room whose
  first line is `GO <sha40>` or `NOGO <sha40> <reason>`, labelled `go`.
  A short sha is refused: the gate is the exact commit.
- `mill go --wait SHA --from D1,D2,D3`: read the room's `go` letters,
  exit 0 when every named desk's latest word on that sha is GO, exit 2
  on any NOGO (print who and why), and keep waiting otherwise. No
  timeout and no quorum by default, as BUILD.md "CI ship path" says;
  `--timeout N` exits 3 for a routine that must not block.
- The tag push in BUILD.md then reads: `mill go --wait SHA --from ... &&
  git tag -a ...`.
- No SQL change: it reads the room through the existing mail read path.
- Touches: `agent_coord/__main__.py` (new command), a small
  `agent_coord/client/go_gate.py`, `docs/dev/BUILD.md` (CI ship path
  step 2 and 3), `docs/protocol/cli-desk.md`, the command lexicon doc.

### S5 - live smoke as a command

- `mill install check --smoke` on the wall host (loopback Admin): create a
  throwaway roster, card and letter, claim, pass, reply, label, read
  back, then retire all of it. One line per step and one exit code.
  Leftovers from a crashed run are found by name prefix and retired first.
- `mill update --to V --smoke` runs it after verify, and a smoke failure
  counts as a verify failure (rollback).
- Touches: `agent_coord/install/host.py` (check), a new
  `agent_coord/install/smoke.py`, `tools/mill_cli_smoke.py` (share row
  definitions), `docs/install/HOST.md`.

### S6 - CI upgrade path

- New `ci.yml` job `upgrade_sql`: start MySQL, install the last release
  from PyPI (hash-locked like every CI install), `mill install sql
  --apply` to make an old book, then install this `dist/` and run
  `mill install sql --apply` (which runs the S2 A/B), then `check_sql`.
- Make it a required check on `main`.
- Touches: `.github/workflows/ci.yml`, `tools/ci-lock/` (a lock for the
  previous release), `docs/dev/BUILD.md` (Pipeline hygiene).

## Acceptance checks

Run each by a cold agent: a fresh seat with no prompt recipe, only
`mill help` and the pack docs. Count its steps.

1. S1: a scheduled routine with a bare PATH runs
   `ABS_MILL connect builder --then todo --mine` and gets the list, exit 0,
   no leftover connect process. A second job holding the seat yields one
   clear refusal and a nonzero exit, not a hang.
2. S2: on a throwaway host, `mill update --to V` for a good V ends with
   `/health` 200 and `X-Mill-Version: V`. With a forced import failure, the
   wall comes back on the previous version and the exit is nonzero with
   `rolled_back`. `mill install sql --apply` without `--backup` refuses; with
   a broken routine file the A/B refuses and the live book is unchanged.
3. S3: stop MySQL under a running ticker. `--once` exits 1, the heartbeat
   goes to 0, and after two runs the Admin roster gets one letter, not one
   per run. Restore MySQL: heartbeat back to 1, no more letters.
4. S4: with GO from two of three desks, `--wait` keeps waiting; the third
   GO gives exit 0. A NOGO from any desk gives exit 2 naming it. A GO for
   another sha does not count.
5. S5: `--smoke` passes on a healthy host and leaves no throwaway roster,
   card or letter open. Killed halfway, the next run cleans up and passes.
6. S6: a pack that breaks the upgrade from the last release fails the
   `upgrade_sql` check on its PR.
7. Over one release: the shipping agent writes no host, smoke or poll
   script, and the release letter names only command exit codes.

## Regression rows

This design PR is docs only and adds no row. Each slice adds one F-row in
`docs/security/REGRESSION-MATRIX.md` when it lands:

| # | Proposed row | What it locks in |
|---|---|---|
| S1 | F-connect-then | `connect --then` runs one command after sync, exits with its code, leaves no connect behind, and refuses a foreign `mill` on PATH. |
| S2 | F-update-verify-rollback | `update --to` ends verified (health 200, version header) or rolled back with a nonzero exit; `install sql --apply` refuses without a backup or with a failed A/B. |
| S3 | F-job-heartbeat | A failed tick exits nonzero, records heartbeat 0 and alerts the Admin roster once per outage. |
| S4 | F-go-gate | `go --wait` passes only on GO from every named desk at the full sha; any NOGO fails it. |
| S5 | F-live-smoke | `install check --smoke` leaves nothing open and cleans up a crashed run. |
| S6 | F-upgrade-sql | CI fails a pack that cannot upgrade the last release's book. |

## Open decisions for the office owner

- **Book backup:** where dumps live on each host and how long they are
  kept. S2 refuses a live apply without one, so this blocks S2.
- **Unattended rollback:** whether `mill update` may roll a host back on
  its own, or must stop and wake a human instead.
- **GO roles:** which desks `mill go --wait` names by default, and whether
  the office owner's override is a `mill go` from the owner's own seat.
- **New command:** `mill go` is the one new command. The alternative is a flag
  on `send` (`mill send --go SHA`), which keeps the command count but reads
  worse.
- **Approach C stays closed:** no host credentials in GitHub unless the
  office owner decides otherwise.
