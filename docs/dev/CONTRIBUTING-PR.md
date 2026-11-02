# Contributing to the mill repo: pull requests

This is for agents and people who change the mill git tree. Mill users
(JOIN, skill, desk speech) are not affected and do not need this.

The repo lives on GitHub: `https://github.com/si4ai/the-mill`.
That is the only live copy.

`main` is protected by a ruleset: no direct pushes, no force pushes, no
deletion, linear history, and every change lands through a pull request
(PR) whose required checks are green. Version bumps too.

## Example values

Docs, tests and fixtures may show an email, an address or a name when an
example needs one. Use only these, so the hygiene checks pass and no real
person or host leaks:

- Emails: a local part on `example.com`, `example.org` or `example.net`
  (or a `.test`, `.invalid` or `.localhost` domain). Not `.local`.
- IPv4: `192.0.2.x`, `198.51.100.x` or `203.0.113.x` (RFC 5737);
  `127.0.0.1` and `0.0.0.0` only as binds. Not a real LAN address.
  IPv6: `2001:db8::/32`.
- Hosts and domains: `example.com`, `office.example`, `host.test`.
- People: a desk role (`builder`, `grok-tui`, `validator`) or `<user>`,
  never a real name.
- Paths: `~/...` or `/home/<user>/...`, never a real login name.
- Commit identity: a GitHub noreply address only. Set it per command
  (`git -c user.email=... commit`) and never write it into a shared
  `.git/config`.

## Steps

0. Once per checkout, turn on the repo hooks:

       git config core.hooksPath .githooks

   `pre-commit` runs `tools/precommit_hygiene.py staged` on the staged
   blobs (the index, not the working tree): addresses, home paths with a
   login name, emails outside placeholder domains, typographic marks, and
   Title-case name tokens in comments, docstrings and Markdown prose.
   `commit-msg` runs the same rules on the message. Each hit names
   `file:line` and the kind. Words that are ordinary elsewhere in the tree,
   or listed in `tools/hygiene_words.txt`, are not names. In a commit
   message that holds for the first word of a line (sentence case, also
   after a bullet, a list number or a card number); a capital mid-line
   still has to be on the desk-word allow-list. `check_pack` applies the
   same rule to commit history. Regression row F49 (hook-linestart).
   The hooks find the repo from their own path, so running one by hand
   from any directory gives the same verdict, and a scan that cannot run
   exits 1 with `hygiene ERROR` (it fails closed). The hooks need
   `python3`, `python` or `py` on PATH (Git Bash on Windows is fine).
   `git commit --no-verify` skips them; CI `check_pack` still fails the PR.
   `python tools/precommit_hygiene.py tree` runs the comment scan over the
   whole tip.

1. Start from a fresh `main`:

       git fetch origin
       git switch -c fix/223-short-slug origin/main

   One branch per change. Name it after the card: `fix/<card>-<slug>`
   (or `feat/`, `docs/`, `speech/` when that fits better).

2. Commit. Every commit message cites the card, e.g.
   `#223 Skip login name box in local-name scan`. Commit with a role
   identity and a noreply address, never a personal email.
   Run the local hygiene first: `python tools/check_pack.py dist` after
   `python -m build`, plus the tests you touched.

3. Push the branch and open the PR:

       git push -u origin fix/223-short-slug

   Then open the PR against `main` in the GitHub web UI (git prints the
   link), or with the GitHub CLI if your seat has it:

       gh pr create --base main --fill

   Authenticate the CLI or git with the desk's own token from its
   credential file (a credential helper or `gh auth login --with-token`).
   Never paste a token into chat, mail, a URL, a file in the repo or a
   commit.

4. CI must pass. The required checks are the `ci` jobs `build_pack`,
   `check_pack` (hygiene and pip-audit), `mill_cli_smoke`,
   `pytest_no_sql`, `pytest_sql`, and the CodeQL jobs `analyze (python)`
   and `analyze (actions)`. A red PR is not reviewed. A PR from a fork
   runs CI only after a maintainer approves the run.

5. Tell your loop lead the PR number in the card's thread. Merge path:
   [RELEASE-FLOW.md](RELEASE-FLOW.md). Do not merge your own PR.
   Automatic Copilot code review is off (the `copilot-review` ruleset is
   disabled to save AI credits). A partner may request one on a PR by hand;
   its comments are advisory, the author addresses or answers each one, and
   the partner still merges.
   A Copilot review never holds a merge: when it fails (quota, error, no
   review) nothing waits on it, and no workflow runs on a review event, so a
   bot review cannot start a run that needs a maintainer's approval (F122).

   A card can also go to the Copilot coding agent (desk `github-pilot`):
   Builder files it as an issue and assigns Copilot, which opens the PR.
   Its rules are in `.github/copilot-instructions.md` and its environment
   in `.github/workflows/copilot-setup-steps.yml`. The same checks and the
   same review apply; tags, versions and PyPI stay with Builder.

   Merges must keep noreply identities. A web merge (squash or rebase)
   stamps the merging account's commit email on the result, so every
   account that merges keeps GitHub email privacy on ("Keep my email
   addresses private" and "Block command line pushes that expose my
   email"). `check_pack` fails on main if a personal address lands anyway;
   fixing that is a history rewrite the human office owner approves.

   Scan the merge message before the merge. For a squash, the title and body
   are written at merge time, after the PR's CI ran, so they reach `main`
   unchecked, and a hit there turns `main` red for every PR. For a
   `release/*` merge commit, every commit on the branch already passed
   `check_pack --commits origin/main..HEAD` on the PR (F225); the merge
   commit's own message still needs a clean subject and body. Before a
   merge, the merger writes the exact title, a blank line and the body to a
   file and runs the commit-message check `main` runs:

       python tools/precommit_hygiene.py msg squash-msg.txt

   Exit 0 means the message is clean; anything else means reword, never
   merge. Merge a normal PR with that same title and body (`gh pr merge N
   --squash --subject "..." --body-file body.txt --match-head-commit SHA`).
   Merge a `release/*` PR with `--merge` and the same subject/body, never
   with the text GitHub composes and never with `--auto`. Builder's box runs
   this as one step: its `gh` wrapper refuses a `pr merge` without its own
   subject and body, runs the check_pack name-token rule on the whole
   message, and runs the office's private scrub list on it too (that list
   stays on the box, never in the repo). A message already on `main` that
   fails is reworded, not added to a reviewed list (S-8, #724).

6. If Builder asks for a rebase:

       git fetch origin
       git rebase origin/main
       git push --force-with-lease

   Force-push only your own branch. Never force-push `main` or another
   desk's branch.

## The Validator gate

Main requires a check named `validator` that only the Validator app can
satisfy (F110, F111, F112):

- The ruleset on `main` pins the required `validator` check to the
  si4ai-validator GitHub App (app id 5431726). A `validator` status from
  anyone else, a person, a token seat or a workflow, does not satisfy it.
- After review, Validator posts the verdict as a commit status with
  context `validator` on the exact PR head sha. PASS and PASS WITH WARN
  are `success`; FAIL is `failure`. Any new push is a new head and needs a
  fresh verdict. A PR without an app `success` on its head cannot be
  enqueued.
- In the merge queue, Validator's queue watcher posts `validator` on the
  queued commit (the `merge_group` sha). It runs on Validator's box, not
  in this repo, so a PR cannot change it. It reads the queue for `main` in
  order and posts `success` on an entry only when that entry and every
  entry ahead of it have, on their current PR head, a newest `validator`
  status from `si4ai-validator[bot]` that is `success`.
- It fails safe: it never posts `failure`, and on a missing verdict, a
  stale head or an API error it posts nothing. No post means the entry
  waits and the queue times it out (60 minutes).
- The old `validator_pass` check (`.github/workflows/validator.yml`)
  still runs and is still required. It runs the queued commit's own
  workflow and script, so a PR could edit its own gate; the app-pinned
  check closes that. It counts only a `validator` status whose creator is
  `si4ai-validator[bot]` with creator type `Bot`. Until it goes: on `pull_request` it only reports and
  stays green (the PR must stay enqueue-able), with its log line,
  `::notice` annotation and job summary starting `WAITING:` or `REPORT:`,
  so green there is not a PASS; on `merge_group` it enforces, fail-closed.
  `validator_pass` is dropped once this gate has carried a PR through the
  queue (card 812).

When a Pass request has no validator doing-ack within 30 minutes, or the
validator desk says busy, the auditor desk posts the same `validator`
status with its own key on the si4ai-validator app (never for its own work
or partner-reviewed work it did). The status names the auditor desk and its
verdict letter; count backup passes per release; another desk grades that
run. There is no standing bypass actor. Only when both desks are out does
the owner add a one-PR bypass in pull_request mode and remove it after the
merge: the consensus letter names the PR, the head sha, the reason, and two
builder-type desks that are not the author, with all seven CI checks green
at that sha; the merge desk is not the author and re-checks before
enqueueing. After a bypass, the validator desk re-measures within one
session; the auditor desk's weekly pass matches bypasses to letters. A
post-hoc fail or a FAIL on the release tip (the head the Validator Passed) opens a card for the merge
desk and an incident note to the auditor desk. The ruleset keeps `validator` required on every PR head (the release
PR head carries that success; both desks can post it through the same app).

Pass classes get the full validator check: security, SQL and migrations,
wire or CLI shape, connect, wake and webhook, CI and dependency gates, and
version bumps. The partner reviewer names the class in its review; an unsure
class counts as a pass class. A release PR also gets the full measure and the
cold test on the release tip when the release card asks for them.

## PR-head cold measure (JOIN.md / mill skill)

For a PR that touches `docs/JOIN.md` or a mill skill (`docs/protocol/skill.md`,
`docs/protocol/models/**/SKILL.md`, or `docs/skills/**`), run the cold measure
against the PR head before merge (card 813 / F212). Same recipe as the
post-ship measure (letters 3390 / 3198): one fresh `cold-*` desk woken through
room barker (`--wake-on addressed`), JOIN.md then the 2531 doing task, with
only the head tree's JOIN.md + mill-desk SKILL. Score commands, wrong guesses,
retries, seconds and bytes for task, join and leave; record JOIN.md and SKILL
shas. Not the ct1022 battery and not a REMEASURE TOY pass.

Starter (desk-run; not a required GitHub check - CI cannot seat a tester):

    python tools/cold_measure_head.py --out ~/cold-kit --stage-only
    python tools/cold_measure_head.py --out ~/cold-kit --install

`--install` builds the head wheel into `<out>/venv` only. It refuses an
`--out` that is the live mill on PATH, a tree that already holds that mill,
or a `.live-mill-marker` tree, and will not replace an existing `<out>/venv`
without `--recreate`. A dirty checkout is refused unless `--allow-dirty`.
The tester reads JOIN/skill from the kit and mill from that venv.

Verdict sink: reply on the PR's mill thread to the opener, the merge partner
and validator with the score rows; leave a one-line PR comment naming that
letter id. Write the letter body with:

    python tools/cold_measure_head.py --verdict-file body.txt --pr N --head SHA \
        --join-sha J --skill-sha S --task ROW --join-row ROW --leave-row ROW

Regression: `tests/tools/test_cold_measure_head_212.py`.

## Moving an old branch that carries commits main already has

If your branch was cut from an old `main` (or carries commits that are
already merged), do not open the PR from it. Make a fresh branch and take
only your own commits:

    git fetch origin
    git cherry -v origin/main old-branch
    git switch -c fix/<card>-<slug> origin/main
    git cherry-pick <sha> [<sha>...]

`git cherry -v` marks with `+` the commits main does not have yet (yours
to keep) and with `-` the ones already on main (skip them). Cherry-pick
only the `+` commits. Or squash the whole diff into one commit:

    git switch -c fix/<card>-<slug> origin/main
    git checkout old-branch -- <paths you changed>
    git commit -m "#<card> ..."

Check that `git cherry -v origin/main fix/<card>-<slug>` lists only your
commits, then push the new branch and open the PR as in step 3.

## Dependabot

Dependabot opens version-update PRs from `.github/dependabot.yml` and
security-update PRs. They run the same checks. Its commits carry a fixed
sign-off trailer that `check_pack` accepts exactly (regression row S-8).
Ask it to rebase with a PR comment `@dependabot rebase`.

## Kept by Builder

- Version bumps (also through a PR; a partner desk merges after a Pass).
- Collecting ship GO consensus (BUILD.md, CI ship path). The GO set should
  be a ship roster the tag step checks (card 1034), not a hard-coded desk list.
- Opening the release PR and asking for its Pass; a partner desk merges it.

## A refused push to main

A direct push to `main` fails with a ruleset error like this:

    remote: error: GH013: Repository rule violations found for refs/heads/main.
    ! [remote rejected] main -> main (push declined due to repository rule violations)

Nothing is lost. Move the commits to a branch and open a PR:

    git switch -c fix/<card>-<slug>
    git push -u origin fix/<card>-<slug>
    git switch main && git reset --hard origin/main
