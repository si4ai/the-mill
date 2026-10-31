# Release flow

How finished card PRs reach `main`. Pair with the mill-desk Habits line in
`docs/protocol/skill.md`.

## One Validator Pass per release

The Validator passes the **release branch** once. Card PRs do not each ask
for a Pass. When a card PR is finished (CI green, partner review done), mail
your loop lead to fold it onto the next `release/*` branch. It rides that
release's single Pass.

## Card PR

1. Open a normal PR against `main` (or the current release branch when the
   lead says so). Keep it one card.
2. CI green. Partner review as usual.
3. Do **not** ask Validator for a Pass on the card PR.
4. Mail the loop lead: fold this PR/sha onto `release/X.Y.Z`.

## Fold onto the release branch

The lead (or Builder on the lead's ask) merges each finished card tip into
`release/X.Y.Z` with a **merge commit** (not squash, not rebase), so card
commits keep their shas. Colliding numbered F-rows (`F229` and up on this
line) are slug-renamed to `F-<slug>.md` on the release only. CHANGELOG lines
cite the **card**, not the PR number, and land under the release that ships
them.

## Release PR to main

1. Open (or update) the `release/X.Y.Z` PR against `main`.
2. Ask Validator for one Pass on that release head.
3. Merge with `--merge` (merge commit), never squash/rebase, so the next
   release can stack on the frozen head (card 935 / F225). Subject and body
   go through `python tools/precommit_hygiene.py msg ...` before merge.
4. Normal card PRs that already rode the release are closed or left; they do
   not need a second merge.

## What stays on CONTRIBUTING-PR

PR shape, CI checks, the Validator gate details, cold measure, and merge
hygiene stay in `docs/dev/CONTRIBUTING-PR.md`. This file is only the fold
habit and the release Pass rule.
