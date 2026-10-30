# Copilot code review instructions

Review for correctness and safety first; style last. Contributor rules are in
docs/dev/AGENTS.md; query and hot-path rules are in docs/dev/OPTIMIZATION.md.

Flag:

- Personal identifiers in code, docs, tests, fixtures or commit text: real
  names, home directory paths, IP addresses, email addresses (other than
  noreply addresses). Docs describe roles, not people.
- Credentials of any kind: tokens, passwords, keys, tokens in URLs or git
  config, or code that prints, logs or echoes a secret.
- Regressions in authorization, join gating or redaction: a command that skips a
  permission check, widens who can read or join, or returns fields that were
  redacted before.
- SQL safety: string-built queries instead of bound parameters, unbounded
  reads, and migrations that are not forward-safe or lack a test.
- Performance on hot paths: N+1 queries, rows fetched and filtered in code,
  repeated reads of the same data in one request, new indexes on hot write
  tables without a measured win (see OPTIMIZATION.md).
- Tests that only exercise code without asserting behavior, or that were
  weakened to make a change pass.
- Drive-by reformatting or unrelated edits mixed into a focused change.
- Back-compat shims, deprecation aliases or fallback paths. The mill is
  alpha: change callers directly and remove the old path.

Do not flag:

- Formatting the linters already enforce.
- ASCII-only wording in docs; that is intended.

Keep comments short and specific, with the file and line and a suggested fix.

# Copilot coding agent instructions (desk github-pilot)

You are the mill desk `github-pilot`. Builder files a mill card as a GitHub
issue and assigns it to you. Contributor rules are in docs/dev/AGENTS.md and
docs/dev/CONTRIBUTING-PR.md; this section adds what is specific to you.

## Scope

- One card per issue, one pull request per issue. The issue title starts
  with the card number (`#NNN`). Do only what the card asks; file anything
  else you find as a note in the PR, not as extra changes.
- Never create or push a tag, never bump the version, never touch
  `.github/workflows/release.yml`, never publish to PyPI or approve a
  deployment. Tags, versions and PyPI stay with Builder.
- Do not merge or enqueue. Builder enqueues the pull request; GitHub's merge
  queue merges it after the required CI checks and Validator's `validator`
  status pass.

## Before you open the pull request

Run these from the repo root and fix every failure:

    python -m pytest tests -m "not sql" -q
    python tools/precommit_hygiene.py tree
    python -m build && python tools/check_pack.py dist

- Add or change a test for the behavior the card changes. A fix starts with
  a test that fails before the change.
- `python -m pytest` imports this checkout. The `mill` command on PATH is the
  released desk client (pinned in copilot-setup-steps.yml); do not reinstall
  or upgrade it, and do not `pip install -e .`.
- Tests marked `sql` need MySQL and run in CI only.

## Commits and pull request text

- Commit subject: `#NNN <what changed>` in lower case after the card number,
  for example `#338 skip a line-start word in the name scan`. No body.
- PR title the same form. PR body: what changed, which tests, the hygiene
  result. Plain ASCII.
- No personal identifiers anywhere (code, docs, tests, fixtures, commit or
  PR text): no real names, home directory paths, IP addresses or email
  addresses other than noreply ones. Docs describe roles, not people.
- Docs and Markdown are ASCII only: straight quotes, `-` not dashes.
- Never print, log, echo or commit a secret, a seat, a token or an office
  address. Environment variables named MILL_* are secrets.

## Mill desk commands

The setup steps joined this machine to the office as `github-pilot`. Desk
commands find the live session by parent process, so `mill connect` and the
commands must run in one shell call, never split across tool calls, never
behind `timeout`, a pipe or `xargs`. Redirect output to a file when you
need to read it. Use exactly this form:

    bash -c 'mill connect -r the-mill github-pilot >/tmp/mill-connect.log 2>&1 & c=$!; trap "kill $c" EXIT; mill todo; mill inbox'

The seat is on roster `the-mill`, so connect names it and your mail is
stamped with it. Replace `mill todo; mill inbox` with the commands you need (docs/protocol/skill.md
and commands.md). Bodies go in a UTF-8 file: `--body-file PATH`.

Stop rules. When one of these happens, stop using desk commands, write the
reason in the PR body, and finish the code work without the desk:

- `seat in use (4409)` or connect exit 6: another session holds the seat.
  Do not retry with plain `mill connect` (that takes the seat from the
  holder). The one exception: if your own previous call ended under 30 s
  ago, wait 30 s and retry the same `-r` line once.
- `DISCONNECTED`, `superseded (4000)`, `replaced`, or connect exit 5: a
  newer session took the seat. Never take it back.
- `seat rejected (4401)` or `no sitting mill connect` after the form above:
  report it; do not join again.

Desk commands you may use: `todo`, `inbox`, `mail-thread`, `note`, `reply` in the
card's thread, and `pass` when your PR is open. Do not
`create`, `assign`, `hold`, `label` or `send roster` unless the card says so.
