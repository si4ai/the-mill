# Release flow

How finished card PRs and release PRs reach `main`. Pair with the mill-desk
Habits line in `docs/protocol/skill.md` and the Validator gate in
`docs/dev/CONTRIBUTING-PR.md`.

## Path (current practice)

- **Card PR:** one card, one branch, one PR against `main`. CI green, then a
  **Validator Pass on the exact head**. A partner desk (never the author)
  enqueues it; the merge queue lands it as a **squash**.
- **Release PR** (`release/*` against `main`): one Validator Pass on the
  release head; a partner desk merges with a **merge commit** (not squash,
  not rebase) so the next release can stack on the frozen head (card 935 /
  F225).
- Nobody merges their own work. The gh merge wrapper should refuse a
  self-merge (card 1035).

A card PR that must ride a release branch instead of landing alone is the
exception: the loop lead says so on the card, and the release Pass covers it.

## Card PR

1. Open a normal PR against `main`. Keep it one card.
2. CI green. Partner review as usual.
3. Ask Validator for a Pass on the named head.
4. Post the PR link for the partner merge desk (card PR, squash). Do not
   merge it yourself.

## Release PR to main

1. Open (or update) the `release/X.Y.Z` PR against `main`.
2. Ask Validator for one Pass on that release head.
3. Partner merges with `--merge` (merge commit), never squash/rebase.
   Subject and body go through `python tools/precommit_hygiene.py msg ...`
   before merge.
4. Say "release" when handing the link to the merge desk so it keeps the
   merge commit.

## What stays on CONTRIBUTING-PR

PR shape, CI checks, the Validator gate details, cold measure, and merge
hygiene stay in `docs/dev/CONTRIBUTING-PR.md`. This file is the path: who
Passes, who merges, squash vs merge commit.
