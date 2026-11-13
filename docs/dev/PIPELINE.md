# Build and CI pipeline

Every job GitHub Actions runs for the-mill, what triggers it, what it
really checks, and why it exists. The last part explains the
personal-name check in `check_pack`, and why it sometimes fails on
ordinary words.

This is for a dev or agent new to the mill. Pack contents, the release
order and the ship path are in [BUILD.md](BUILD.md). How cards reach
`main` is in [RELEASE-FLOW.md](RELEASE-FLOW.md). The wider map of checks
is [CHECKS-AND-TOOLS.md](CHECKS-AND-TOOLS.md).

Read from the code on `main` at `080a871` (12 Nov 2026, Pacific Time).
`.github/`, `ci/` and `tools/` were the same on `release/0.8.15` at
`5bb96ef`. Where this page and a workflow file disagree, the workflow
file wins: fix this page.

## Workflows

Six files live under `.github/workflows/`:

| File | Starts on | Jobs |
| :--- | :--- | :--- |
| `ci.yml` | pull request, merge queue (`merge_group`), push to `main`, manual run, and called by `release.yml` | `select`, `build_pack`, `check_pack`, `hidden_code_report`, `mill_cli_smoke`, `pytest_no_sql_run`, `pytest_sql_run`, `pytest_no_sql`, `pytest_sql`, `precheck` |
| `codeql.yml` | pull request, merge queue, push to `main`, weekly (Monday 06:17 UTC), manual run | `analyze (python)`, `analyze (actions)` |
| `validator.yml` | pull request (opened, synchronize, reopened), merge queue | `validator_pass` |
| `pr_text.yml` | pull request (opened, edited, synchronize, reopened), issue opened or edited, issue comment, daily (06:17 UTC), manual run | `event`, `sweep` |
| `release.yml` | push of a `v*` tag, manual run (dry run) | `ci` (calls `ci.yml`), `verify`, `publish_pypi` |
| `copilot-setup-steps.yml` | push or pull request that changes this file, manual run | `copilot-setup-steps` |

Rules every workflow keeps, and why:

- Every action is pinned to a full commit sha. A tag such as `v4` can be
  moved to new code; a sha cannot.
- No `pull_request_target` and no self-hosted runner. A fork PR on a
  public repo must never run with secrets or on our machines.
- The default token is read-only (`permissions: contents: read`, or
  none in `release.yml`). A job gets more only where it needs it.
- Every PyPI install is hash-checked: a pinned pip wheel, then
  `pip install --require-hashes -r tools/ci-lock/<lock>.txt`. The built
  pack installs with `--no-deps --no-build-isolation`, so it fetches
  nothing (#634).
- On a pull request, a new push cancels the run still going for the old
  head (`cancel-in-progress`). That is why older runs show `cancelled`.

## What runs when

The required checks come from the `main` ruleset, a repo setting, not a
file. As of this writing they are `build_pack`, `check_pack`,
`mill_cli_smoke`, `pytest_no_sql`, `pytest_sql`, `analyze (python)`,
`analyze (actions)` and the `validator` commit status. The ruleset also
requires a PR to be up to date with `main` before it merges. The merge
queue lands entries as squash commits.

| Job | Pull request | Merge queue | Push to `main` | `v*` tag | Required |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `select` | yes | yes (ancestry check, see below) | yes (picks no suite) | yes (picks no suite) | no, but the wrappers need it |
| `build_pack` | yes | yes | yes | yes | yes |
| `check_pack` | yes, plus `--commits` and `--pr-message` | yes, plus `--head-message` | yes, pack and tip only | yes, pack and tip only | yes |
| `hidden_code_report` | yes | yes | yes | yes | no (report only) |
| `mill_cli_smoke` | yes | yes | yes | yes | yes |
| `pytest_no_sql_run`, `pytest_sql_run` | yes, unless no changed file selects them | never | never | never | no |
| `pytest_no_sql`, `pytest_sql` (wrappers) | yes | yes | yes | yes | yes |
| `precheck` | yes | yes | yes | yes | no |
| `analyze (python)`, `analyze (actions)` | yes | yes | yes | no | yes |
| `validator_pass` | yes (reports only) | yes (the gate) | no | no | no |
| `pr_text` `event` | yes | no | no | no | no |

The split, as the code does it today:

- A pull request runs the full pytest suites once, on its own head,
  unless the change selects no suite (docs only, or a version-only
  bump). That run is the one Validator's Pass measures.
- The merge queue does not run the suites. It checks that nothing
  merged ahead of the tested code, and it re-runs the pack, smoke and
  message checks on the squash commit it is about to land.
- A push to `main` and a `v*` tag run no suite: that code already ran
  them on its PR. They still build, scan and smoke the pack.

That split landed in #437 (12 Nov 2026). Before it, the merge queue
diffed its base against the queued commit and ran the suites that diff
selected.

## `ci.yml` jobs

### `select`

Runs `python3 ci/test_select.py --github`. It decides whether
`pytest_no_sql_run` and `pytest_sql_run` run, from the map in
`ci/test-select.toml` (card 1127).

- **Pull request.** Diffs `base...head`. If any changed file matches a
  rule in the map, both suites run on the whole tree; if none does, no
  suite runs. A file no rule lists selects nothing (docs, `README.md`,
  `CHANGELOG.md`, `LICENSE`). A `pyproject.toml` whose only changed
  lines are `version = "..."` counts as unchanged, so a version bump runs
  no suite. A malformed sha, an all-zero base, an empty diff or a failed
  diff runs both, so an error never skips the tests.
- **Merge queue.** Runs no suite. It fetches `refs/pull/N/head` (N from
  the queue branch name) and passes only when `merge_group.base_sha` is
  an ancestor of that head. Otherwise it fails with "main moved after
  this PR was tested: rebase, re-test on the PR, re-pass", and the
  required `pytest_sql` and `pytest_no_sql` wrappers turn red.
- **Push** (to `main`, or a tag through `release.yml`): no suite.
- **Manual run:** both suites.

Why: the suites are the slow part of CI. Running them once per change,
on the head Validator measures, saves runner time. The ancestry check
stops the queue from landing code that was tested against an older
`main`.

### `build_pack`

Builds the wheel and sdist with
`SOURCE_DATE_EPOCH=<commit time> python -m build --no-isolation`, from
the hash-locked `tools/ci-lock/build.txt` tools. The in-tree backend
`build_backend/mill_build.py` fixes member times, owners and modes.
Then `python tools/check_repro.py dist` clones the commit twice, under
umask 022 and 002, builds each, and fails unless both builds match
`dist/` byte for byte (F78). The result is uploaded as the `dist`
artifact, which every later job installs or scans.

Why: anyone must be able to rebuild a release and get the same sha256
as PyPI. One artifact, built once, is what is scanned, smoked, tested
and published, so the bytes users get are the bytes CI checked.

### `check_pack`

Needs `build_pack`. Checks out full history (`fetch-depth: 0`): the
message scans fail closed on a shallow clone. Steps, in order:

1. `python tools/check_pack.py dist`, on every event. It unpacks the
   wheel and sdist and fails on junk (backups, bytecode,
   `wall_ui_save/`, binaries under `agent_coord/`), home paths with a
   login name, emails outside placeholder domains, IPs outside the
   documentation ranges, credential shapes, byte-order marks and
   typographic punctuation, and the private names. It runs the same
   scans on every tracked file at the tip, fails on a tracked symlink
   under a packaged path, and requires every pack member to be a tracked
   regular file. It scans commit messages (see
   [The name-token check](#the-name-token-check)), and requires every
   author and committer email in history to be a GitHub noreply address
   (S-10).
2. Merge queue only: `python tools/check_pack.py --head-message`. Scans
   the message of the queued squash commit, which is the exact text that
   lands on `main` (#810, F109).
3. Pull request only: `python tools/check_pack.py --commits
   origin/main..HEAD`. Every commit the PR would bring to `main`: its
   message, its author and committer identity (noreply email, and a role
   name such as `builder` or a `[bot]` name), and its added diff lines
   (card 935, F225). The range is always from `main`, also for a PR into
   `release/X.Y.Z`, because release branches land with a merge commit
   and keep every commit.
4. Pull request only: `python tools/check_pack.py --pr-message`. Builds
   the squash message the queue will land (`TITLE (#N)`, a blank line,
   the PR body) from the event file and runs every message rule on it,
   so a hit shows on the PR instead of in the queue.
5. `python tools/precommit_hygiene.py tree`. The name-token rule over
   comments, docstrings and Markdown prose in every tracked file, plus
   credential shapes. The same scan as the `pre-commit` hook.
6. `python tools/write_pack_deps.py`, then `pip-audit` on
   `pack-floors.txt` (the oldest dependency versions a user may keep)
   and on `tools/ci-lock/ci.txt`. Nothing is installed for the audit.

The private names come from the `MILL_PRIVATE_NAMES` secret, in env
only. An empty list fails closed, except on a fork PR, which GitHub
gives no secrets: there it prints that it skipped.

Why: the pack, the git history and the PR text all ship publicly. Once
a personal name, a home path, a private address or a key is in a pushed
commit or on PyPI, it cannot be taken back. This job is the last place
to stop it.

### `hidden_code_report`

Runs `tools/check_hidden_code.py --base B --head H`, with the range
picked per event: the PR diff from its merge base, the queued squash
against its base, or the push range. It lists code a mapped test job
may never see: executable files no `ci/test-select.toml` rule matches,
import-time or build-time hooks, obfuscation patterns, `.github/**` and
test-map edits, and lock-file changes (card 1155).

It is a report, not a gate. It runs without `--strict`, exits 0
whatever it finds, and is not a required check. Only a crash of the
scanner turns it red (#420).

Why: path-based test selection runs nothing for an unlisted file. This
job makes that blind spot visible to the reviewer.

### `mill_cli_smoke`

Needs `build_pack`. Installs the sdist into a clean environment, runs
`pip check`, then:

- `python tools/mill_cli_smoke.py`: the required commands appear in
  `--help`, retired ones do not, and the real-path rows run a command's
  body, not only its argument parser.
- Checks the runner is x86_64 and runs
  `python -m agent_coord.server.records.driver --require-c`: the book
  must run on the MySQL connector's C extension (F34).
- `python tools/check_skill_copy.py --installed`: the installed
  `skill.md` matches the source (F33).
- `python tools/check_doc_commands.py`: every command, flag and
  positional the docs teach is one the parser accepts (F90).

Why: a `--help` that parses can still hide a broken command body; a
stale name in connect shipped green that way (0.6.40). Users install the
sdist, so the smoke runs on the sdist, not on the checkout.

### `pytest_no_sql_run` and `pytest_sql_run`

Run only when `select` picks them (on a pull request).

- `pytest_no_sql_run` installs Node 24.21.0 from the official tarball,
  checks its sha256, runs `npm ci --prefix tools/wall-validators`
  (stylelint, eslint, html-validate for the Wall files), installs the
  sdist, and runs `python -m pytest tests -m "not sql"`.
- `pytest_sql_run` starts a throwaway MySQL 8.4 service (pinned by
  digest), waits for it, installs the sdist, and runs
  `python -m pytest tests -m sql -n 2 --dist loadgroup`. It uploads a
  JUnit file.

Both check out full history: some pack-check tests scan commit
messages.

Why: these are the product tests. They are split so the tests that
need a database get one, and the rest run without the wait.

### `pytest_no_sql` and `pytest_sql`

Thin wrappers, and the names the ruleset requires. Each passes only when
`select` succeeded and its run job either was not picked or succeeded.
A failed selector, or a picked run job that failed or was skipped,
fails the wrapper.

Why: a required check that never reports blocks a merge forever. The
wrappers keep the required names present on every event, including the
ones where the suites skip on purpose.

### `precheck`

Needs `build_pack`. Installs the sdist and runs
`./tools/precheck.sh HEAD --skip-pack --base origin/<PR base>` (or
`origin/main` when there is no PR base). `tools/precheck.py` runs:

- the `CHANGELOG.md` rules: unreleased bullets cite a card, shipped
  headings carry a date;
- the regression-row rules: a new row file must be named
  `F-<slug>.md`, not a number such as `F229.md`, and no id appears in
  two row files;
- `tools/check_code_commands.py` (or the lighter verb check) on command
  names in hints and docs;
- DDL id columns are `BIGINT UNSIGNED`;
- non-SQL pytest on the test files the diff touches (Wall tests are
  dropped when Node modules are absent);
- `tools/check_doc_commands.py` and `tools/check_skill_copy.py`.

`--skip-pack` skips its own pack rebuild, since `check_pack` already
covers it. In the merge queue there is no PR base, so the diff is the
queued commit against `main`, and the targeted tests run there too.

`precheck` is not a required check. A red `precheck` does not block
the ruleset, but Validator reads it as red CI.

Why: cheap, deterministic findings before anyone spends a Validator
pass on the PR (card 959, F-precheck).

## The other workflows

### `codeql.yml`

CodeQL for Python and for the workflow files themselves, with
`build-mode: none` and `.github/codeql/codeql-config.yml`. The config
drops one query (`py/clear-text-storage-sensitive-data`) on
`agent_coord/server/log_rotate.py`, which copies a log that was
redacted when written. It runs in the merge queue because its jobs are
required checks on `main` (#810).

Why: trust-boundary bugs (injection, unsafe paths, ReDoS, workflow
injection) that tests rarely aim at.

### `validator.yml`

Runs `python3 tools/check_validator_pass.py`.

- In the merge queue it finds every PR in the entry and requires the
  latest `validator` commit status on each PR's head sha to be success.
  Only statuses posted by the Validator GitHub App count (#811, F111):
  anyone with write access can post a status named `validator`.
- On a pull request it reports the state and passes, printing
  `WAITING` or `REPORT`, never `OK`, so a green job is not read as a
  Pass.

Why: no code lands without a Validator Pass on the exact head that was
tested (#810, F110).

### `pr_text.yml`

`event` runs `python3 tools/check_pr_text.py event` on the text of the
triggering PR, issue or comment. `sweep` runs daily and on a manual run
over every PR and issue title, body, comment and review. Both use the
`check_pack` text rules: addresses, home paths, emails, credential
shapes. PR and issue titles and bodies also get the name-token rule,
except when the author is a bot account. On a PR, a missing
`## Changelog` section prints a hint and does not fail.

Why: GitHub keeps every revision of a PR body in its edit history, so a
slip stays public after an edit. Text has to be scanned when it is
posted.

### `release.yml`

The ship path; details in [BUILD.md](BUILD.md#ci-ship-path).

- `ci` calls `ci.yml` with the private-name secret. Inside a called
  workflow the event is the caller's (a tag push), so `select` picks no
  suite and the PR-only and queue-only `check_pack` steps are skipped.
- `verify` requires the tagged sha to be on `main` (F207), requires
  `dist/` to hold exactly the wheel and sdist for the tag's version, and
  re-runs `check_pack.py dist`, `precommit_hygiene.py tree`,
  `twine check --strict` and `check_repro.py dist`. When the
  `MILL_PASSED_SHA` variable is set, `tools/release_gate.py` also
  confirms the tag's tree equals the passed tree (card 960).
- `publish_pypi` runs only on a pushed `v*` tag, in the `pypi`
  environment with a required reviewer. It checks the publish action's
  image digest against a pin (F208), then uploads with trusted
  publishing (OIDC). No PyPI token is stored.

Why: PyPI never takes the same version twice, so a bad upload costs a
new version. Every gate runs again on the exact tagged commit first.

### `copilot-setup-steps.yml`

The environment the Copilot coding agent starts in when a card is
assigned to it as an issue. It installs Node, the wall validators, the
locked test tools and a pinned released mill, then joins the office as
`github-pilot` when the seat secret is set. It keeps the repo hooks off,
because the agent's first commit is generated text the name-token rule
refuses. CI `check_pack` stays the gate.

## The name-token check

`check_pack` refuses text that may hold a real person's name. Names
must never reach a public commit, PR or pack. There is no list of names
to match against (that list would itself leak the names), so the rule
works on the shape of words.

### How it decides

The core is `text_has_personal_name_token` in `tools/check_pack.py`:

1. Every word matching `\b[A-Z][a-z]{2,20}\b` is a candidate: one
   capital, then 2 to 20 lower-case letters. `Revert` and `System` match.
   `API`, `PyPI` and `mill` do not.
2. A candidate passes when its lower-case form is on
   `DESK_WORD_ALLOWLIST`, a fixed list of neutral words (`add`, `card`,
   `fix`, `release`, `the`, ...). That holds at any position.
3. A candidate at the start of a line, or the first word of a sentence
   inside a line (after `. `, `! ` or `? `), also passes when its
   lower-case form is an ordinary word: a word that appears in lower
   case somewhere in the tree, or is listed in `tools/hygiene_words.txt`.
   A line start can follow a bullet, a list number, `#338` or Markdown
   heading marks. Sentence case puts capitals there.
4. Any other candidate fails the whole text. In practice that means a
   capitalised word in the middle of a sentence that is not on the
   allow-list.

The idea behind step 3: a word the repo uses in lower case is an
ordinary word, and a name never is. Step 3 only applies at sentence
starts; mid-sentence, only the allow-list counts.

`tools/precommit_hygiene.py` uses a looser form for comments,
docstrings and Markdown prose: it skips code spans and path-like words,
and accepts an ordinary word at any position.

### The lists

| List | Where | What it does |
| :--- | :--- | :--- |
| `DESK_WORD_ALLOWLIST` | `tools/check_pack.py` | Neutral words that pass at any position. Never a list of names. |
| ordinary words | `ordinary_words()`: lower-case words in the tree, plus `tools/hygiene_words.txt` | Words that pass at a line or sentence start (and anywhere in comment prose). |
| `NAME_TOKEN_SCAN_SINCE` (`f3aeff8`) | `tools/check_pack.py` | The history-scrub cut (12 Oct 2026). The history scan reads only commits after it. |
| `NAME_TOKEN_REVIEWED` | `tools/check_pack.py` | 22 commits after the cut that were read by hand on 18 Oct 2026 and kept. The code comment says a new commit is never added; reword it before it is pushed. |
| Dependabot and Copilot exceptions | `tools/check_pack.py` | A commit by Dependabot's exact identity with its sign-off skips the rule. For the Copilot agent's exact identity, a first line of `Initial plan` is not read. |

### What it scans

| Scan | Text | Honours `NAME_TOKEN_REVIEWED` |
| :--- | :--- | :--- |
| `check_pack.py dist` (every event) | Every commit message on `HEAD` after the cut | yes |
| `check_pack.py --commits origin/main..HEAD` (PR) | Every commit message the PR brings to `main` | **no** |
| `check_pack.py --pr-message` (PR) | `TITLE (#N)` plus the PR body | not a commit |
| `check_pack.py --head-message` (merge queue) | The queued squash message | not a commit |
| `check_pr_text.py event` and `sweep` | PR and issue titles and bodies; skipped for bot authors | not a commit |
| `precommit_hygiene.py msg` (`commit-msg` hook) | The message being written, line by line | not a commit |
| `precommit_hygiene.py staged` and `tree` | Comments, docstrings, Markdown prose (looser rule) | not a commit |

File contents outside comments and prose, and the added lines of a
commit's diff, are not name-token scanned; they get the address, path,
email and credential rules only.

### Why it produces false positives

The rule cannot tell a name from an ordinary word. It sees only a
capital letter in a place where English does not need one. Anything
that puts a capital mid-sentence trips it: a product or component
written with a capital, a word quoted from code or a UI label, or text
that git writes for you.

**Example: `System` in the #441 PR body.** An earlier revision of
the body wrote `System` with a capital, mid-sentence. `system` is an ordinary word in the tree,
but it is not on `DESK_WORD_ALLOWLIST`, and mid-sentence only the
allow-list counts. `check_pack --pr-message` failed. The fix was to
write it in lower case; the body now reads "the system desk". The same word at the start of a sentence would
have passed.

`pr_text` `event` stayed green on that PR: its author is the
`si4ai-builder[bot]` account, and `check_pr_text.py` skips the
name-token rule for bot authors. `check_pack --pr-message` has no such
skip. So the same body can pass one check and fail the other.

**Example: commit `07f8876` on `release/0.8.15`.** This was a revert of
a revert. `git revert` writes the subject itself:

    Revert "Revert "wall: every station with its last connection on pov desks (card 1191) (#441)""

The first `Revert` starts the line, and `revert` is an ordinary word,
so it passes. The second `Revert` comes after a quote mark, in the
middle of the line. That is not a sentence start, and `revert` is not
on `DESK_WORD_ALLOWLIST`, so it fails. A single revert, `Revert "x"`,
passes; any revert of a revert fails. Every PR whose range from `main`
includes that commit fails `check_pack --commits` and the `dist` history
scan, so PRs cut from the branch (#442, #443) inherited the failure.

Two details make this case worse:

- The `commit-msg` hook refuses this subject when run on it, but
  `git revert` does not run the `commit-msg` hook (checked with git
  2.47.3, with and without `--no-edit`). The hook cannot catch a
  generated revert message.
- Adding the sha to `NAME_TOKEN_REVIEWED` clears only the `dist`
  history scan. `--commits`, the PR step, does not read that list, so
  the PR stays red. Rewording the commit is the only fix that clears
  both, which means rewriting the branch.

### What to do when it fires

The report names the commit or field and the kind, never the word.
Find it locally:

    python tools/precommit_hygiene.py msg FILE

with the message, title or body saved in `FILE`. It prints the line
number. Then:

1. **A real name.** Replace it with the desk role (`builder`,
   `validator`) or `<user>`. If it was pushed, tell the office owner: a
   pushed name needs a history rewrite.
2. **An ordinary word mid-sentence** (`System`, a UI label): write it in
   lower case, put it in backticks in a PR body or Markdown, or reword so
   it starts the sentence.
3. **A PR title or body.** Edit the PR. The next run reads the new
   text.
4. **A commit not yet pushed.** `git commit --amend` or an interactive
   rebase to reword it.
5. **A commit already pushed.** Reword and force-push the branch, with
   the office owner's go for a release branch. Do not add new commits to
   `NAME_TOKEN_REVIEWED`.
6. **A revert of a revert.** Do not keep git's default subject. Write
   your own, for example
   `wall: restore card 1191 station clock (re-applies #441)`, or drop
   the revert pair instead of stacking a third commit.

Turn the hooks on once per checkout so most hits never get committed:

    git config core.hooksPath .githooks

### Possible improvements

Not built; for discussion.

- **Accept git's own revert wording.** Treat a subject of the form
  `Revert "Revert "...""` as generated text, the way the Copilot
  `Initial plan` subject is: let a `Revert` that directly follows
  `Revert "` pass.
- **Catch generated messages at commit time.** A `commit-msg` hook
  already exists (`.githooks/commit-msg`), but it is opt-in per checkout,
  the Copilot setup keeps it off, `--no-verify` skips it, and
  `git revert` never calls it. A check that also covers reverts, for
  example a `pre-push` hook that runs `check_pack.py --commits` on the
  commits being pushed, would close that gap.
- **One rule for bots.** Decide whether bot-authored PR bodies get the
  name-token rule, and make `pr_text` and `check_pack --pr-message`
  agree.
- **Make `NAME_TOKEN_REVIEWED` consistent.** Either both history scans
  read it, or neither does.
