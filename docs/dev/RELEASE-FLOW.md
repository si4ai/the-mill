# Release flow

How finished card branches and release PRs reach `main`. Pair with the mill-desk
Habits line in `docs/protocol/skill.md` and the Validator gate in
`docs/dev/CONTRIBUTING-PR.md`.

## Path (default)

- **Release batch** (`release/X.Y.Z` against `main`): finished card branches
  fold onto the release branch (merge commits, no squash). There is **no
  per-card Validator Pass**. The Validator does **one Pass on the release
  head**. A partner desk (never the author) merges the release PR to `main`
  as a **merge commit** (not squash, not rebase), with the PR labeled
  `release` so the merge desk keeps the merge commit (card 935 / F225).
- Nobody merges their own work. The gh merge wrapper should refuse a
  self-merge (card 1035).

## Exception: standalone card PR to main

A card PR against `main` with its own Validator Pass is the **exception**:
urgent desk-blocking fixes, and only when the loop lead says so on the card.
That PR still needs CI green and a Pass on the exact head; a partner desk
enqueues it and the merge queue lands it as a **squash**.

## Card branch (default path)

1. Finish the card on its branch. CI green on that branch.
2. Mail your loop lead to fold it onto the open `release/X.Y.Z` (or to open
   one). Do **not** ask Validator for a Pass on the card PR.
3. The loop lead merges the card branch into the release branch (merge
   commit). The card PR against `main`, if any, stays open only as a pointer
   and is not enqueued.

## Release PR to main

1. Open (or update) the `release/X.Y.Z` PR against `main`. Label it
   `release` when that label exists.
2. Ask Validator for one Pass on that release head. The required app
   `validator` success on the PR head is this Pass (the release head
   satisfies the ruleset; do not change the ruleset).
3. Partner merges with `--merge` (merge commit), never squash/rebase.
   Subject and body go through `python tools/precommit_hygiene.py msg ...`
   before merge.
4. Say "release" when handing the link to the merge desk so it keeps the
   merge commit.

## Standalone card PR (exception only)

1. Loop lead marks the card urgent / desk-blocking and says it lands alone.
2. Open a normal PR against `main`. Keep it one card.
3. CI green. Ask Validator for a Pass on the named head.
4. Post the PR link for the partner merge desk (squash via the queue). Do not
   merge it yourself.

## What stays on CONTRIBUTING-PR

PR shape, CI checks, the Validator gate details, cold measure, and merge
hygiene stay in `docs/dev/CONTRIBUTING-PR.md`. This file is the path: who
Passes, who merges, squash vs merge commit, and when a card rides a release
batch vs lands alone.
