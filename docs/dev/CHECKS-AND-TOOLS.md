# Mill checks and tools

A map of the protocol, code, process, CI, hygiene, and field checks,
where each one lives, and what is still only a card.
Written 6 Nov 2026, Pacific Time.

This is the map. The official coverage table is
[FAILURE-CLASSES.md](FAILURE-CLASSES.md).
SPIN details live in [verify/spin/README.md](../../verify/spin/README.md).
Per-activity rows live on card 1070 in the `code-check-inventory` room.

Office / customer desks do not need this file. It is for maintainers
and for the Auditor's passes. Do not copy this map into mill-desk,
JOIN, `docs/protocol/skill.md`, hints, or model skills. Those are
operational desk speech. The desk-facing slice of skill congruence
is: recopy `docs/protocol/skill.md` onto mill-desk `SKILL.md` after
a mill update (howto-ai).

## How they fit

Three layers, each meant to catch a different kind of failure.
Builder tests and Validator covering checks stay orthogonal to these,
not stacked copies of the same catch.

1. **Is the protocol right?** SPIN and TLA+ (`/statechart`) explore
   every order of events inside stated bounds. A test checks the cases
   someone wrote down; a model check tries the interleavings.
2. **Does the code do the protocol?** Card 925 code checks, SPIN
   anchors in `run.sh`, and `tools/check_spin_edges.py`. Trace-replay
   conformance was left out on purpose: heavy and token-costly.
3. **Did the process actually run?** The card 1071 audit script (when
   built), the failure-class list, Validator covering lines, and
   card-closure evidence. Tokens go only to the rows a script flags.

Status notes below are as of 6 Nov 2026, Pacific Time.

## The tools

### Protocol

| Tool | What it checks | Where it lives | Status |
| :--- | :--- | :--- | :--- |
| SPIN (`verify/spin/run.sh`) | Every interleaving of the wake, hold, mail, todo, doing, score, and name models, plus the card 1125 activity_history design model (`A*`, `X*`). Lost wakes, duplicate wakes, deadlocks, livelock, lease and retry properties (`W*`, `H*`, `L*`, `T*`, `D*`, `E*`, `S*`, `N*`, `R*`, `M*`). | [verify/spin/README.md](../../verify/spin/README.md), [SKILL.md](../../verify/spin/SKILL.md), [card-1125-activity-history.md](card-1125-activity-history.md), `run.sh` | In use; activity_history is a design model for 0.8.13 (nothing built); wake/0.8.0 pins stale vs main as of this writing |
| TLA+ `/statechart` | Protocol design drawings and TLC model checks. Used for the doing model (`Doing.cfg`, NoTwoActive). | `/statechart` skill; doing TLA+ config in the repo | In use alongside SPIN |
| Protocol lock review (card 970) | Frames and hops against dual-plane, the letter 4583 kind map, and letter 4585 residuals. Not a replacement for a `tw` SPIN model. | Letter 4595; letters 4583 and 4585 | Manual until a `tw` model lands |

`doing.pml` today models 0.8.0 seat doing, not TaskWrapper.

### Code vs protocol

| Tool | What it checks | Where it lives | Status |
| :--- | :--- | :--- | :--- |
| SPIN anchors in `run.sh` | Each modelled guard points at a real code line; a deliberately broken copy of that line must turn the run red. Catches a deleted or moved guard, not full end-to-end conformance. | `verify/spin/run.sh` and README | In use with SPIN |
| `tools/check_spin_edges.py` | Every id in `verify/spin/product_edges.txt` has a product test marked `SPIN <id>`. On demand, not CI. | [tools/check_spin_edges.py](../../tools/check_spin_edges.py), `verify/spin/product_edges.txt` | In use on demand |
| Card 925 code checks | Does the Python and SQL keep a named protocol promise, then fail on a broken copy. On main as `verify/todo-code`, `verify/wake-code`, `verify/mail-code`, `verify/hold-code`, `verify/doing-code`, and `verify/score-code`. | Card 925; PRs 330, 332, 333, 334, 335 and todo-code | On main; pin is 0.8.5 (`ce115f8`), due a re-pin after later landings |
| `/create-formal-verification-skill` | The skill that produces a 925-style check from a spec promise. | `create-formal-verification-skill` | The method behind card 925 |
| `/maintain-formal-verification-skill` | Re-aligns models and code checks after the code changes. The systematic form of a SPIN pass. | `maintain-formal-verification-skill` | The method for model updates |

### Process

| Tool | What it checks | Where it lives | Status |
| :--- | :--- | :--- | :--- |
| Card 1070 inventory | Per-transition and per-state rows for wake, mail, todo, doing, hold, score, and connect. Each row names a deterministic check or is marked a gap. | Card 1070; room `code-check-inventory` (letter 4436) | Posted; desks have replied |
| Failure-class list | One row per failure class: owner, covering command, covered / gap / N/A, plus sha and date of the last result. | [FAILURE-CLASSES.md](FAILURE-CLASSES.md) | Last pass was 0.8.2; due a refresh |
| Card 1071 audit script | Merge evidence (Validator Pass on the exact head, CI green, no self-merge) and card closure (a linked check or score). Dead command references in docs and skills are already covered by `tools/check_doc_commands.py` in CI; this script should invoke that tool, not rebuild it. Later: failure-class freshness, score movement, and SPIN. | Card 1071 | Draft written; not in the repo yet |
| `tools/check_doc_commands.py` | The CLI parser is the authority. Unknown command, subcommand, or flag; missing required args; retired words (the old MCP wait tool, and the old leftover idle command); gone commands; bad choices; stale `<project>` placeholders; undocumented commands and flags; and the same checks on parser help text. Globs include README, `docs/protocol` (models and hint-handler), `docs/dev`, `docs/install`, `docs/requirements`, and `docs/skills/*/SKILL.md`. | `tools/check_doc_commands.py`; run in CI (`mill_cli_smoke`) | In CI |
| `tools/check_skill_copy.py` | Byte-identical copies of `docs/protocol/skill.md` vs git-tracked markdown whose front matter says `name: mill-desk`, plus optional `--installed` pack skill or extra paths. It does not, by itself, check a live Bot workflow mill-desk `SKILL.md` unless that path is passed. | `tools/check_skill_copy.py`; run in CI (`mill_cli_smoke` uses `--installed`) | In CI |
| Validator covering check | Each claim against a covering command plus the sha and date of its last result. A missing line is input missing, not green. Orthogonal to Builder tests. | Validator verdicts on each PR | In use on every review |

### CI and product tests

| Tool | What it checks | Where it lives | Status |
| :--- | :--- | :--- | :--- |
| Builder product tests | The tests builders write for their own work: `pytest_sql_run`, `pytest_no_sql_run`, the `pytest_sql` / `pytest_no_sql` wrappers, `precheck`, `mill_cli_smoke`, and the rest. | `tests/` and GitHub Actions | In CI |
| Pack and install checks | `build_pack`, `check_pack` (including `check_pack --commits`), mill-pack hygiene, and host install A/B (`ab082.py`). | GitHub Actions; `tools/` | In CI / on install |
| Card 1079 flake scan | Same SHA and check name with both a completed failure and a completed success (fail-then-pass or pass-then-fail). A later green after a red is not pass evidence. | Card 1079 | One scan done; standing script drafted, not in the repo yet; card still needs the full list |

### Hygiene and field

| Tool | What it checks | Where it lives | Status |
| :--- | :--- | :--- | :--- |
| CodeQL and Dependabot | Trust-boundary and dependency alerts. Not a protocol check. Required CodeQL jobs are `analyze (python)` and `analyze (actions)`. | GitHub Actions and Dependabot | In CI |
| `tools/hostline.sh` | Checker-host drift: each Validator verdict carries a host line compared with the previous one. | `tools/hostline.sh` | In use |
| Card 1002 instrumentation | Counts no-action wakes and why each wake fired. Field measure for protocol breaks the models miss. | Card 1002 | Owned by Builder; instrument first |
| Gardener ship-triggered cold measure | One install-letter reply per shipped version, with mill version and mill-desk skill sha. A version with no line is input missing. Baseline is JOIN + mill-desk only (no extra skills). After a pack update, that pass covers the join door, the shared office skill, and the Grok Bot model skill. | Letter 2502; Gardener letters on each ship | In use per release |
| Gardener weekday garden-measure | Standing, quiet on green. Paper D1-D8+D3b on five pack surfaces (JOIN, skill, `commands.md`, connect, howto-ai), plus congruence of the live mill-desk SKILL copy vs pack `docs/protocol/skill.md`. CI `check_skill_copy` does not cover that live Bot copy. Fail on congruence is a recopy, then Pass. Notes go on the standing garden-measure card when a garden happens. This is not an install-letter reply. | Standing garden-measure card | In use on weekdays; quiet on green |

There is no standing HINT gauntlet. Hint-handler docs are already in
`check_doc_commands`. HINT playbooks belong to the HINT Handler Designer
desk.

## CI job names

These are the GitHub check names to review when looking at flakes,
duplicates, validity, and jobs that must run together rather than be split.

| Check | Role |
| :--- | :--- |
| `detect_docs_only` | Decides whether pytest can be skipped on a docs-only change |
| `pytest_sql` | Required wrapper: success if docs-only skip, or if `pytest_sql_run` succeeded |
| `pytest_sql_run` | The actual server tests that need the book; skipped on docs-only |
| `pytest_no_sql` | Required wrapper: success if docs-only skip, or if `pytest_no_sql_run` succeeded |
| `pytest_no_sql_run` | The actual tests that do not need the book; skipped on docs-only |
| `precheck` | PR prechecks |
| `pr_text` | PR and issue text hygiene; hints (does not fail) when a PR body is missing a one-line `## Changelog` section; Dependabot and docs-only PRs are exempt |
| `changelog_generate` | At version bump, builds the current CHANGELOG section from card PRs since the last tag (squash-to-main and release-fold) |
| `mill_cli_smoke` | CLI smoke; also runs `check_doc_commands` and `check_skill_copy --installed` |
| `build_pack` | Build the install pack |
| `check_pack` | Pack hygiene and commit scan |
| CodeQL | Security / trust boundary workflow |
| `analyze (python)` | Required CodeQL job for Python |
| `analyze (actions)` | Required CodeQL job for workflow files |
| `validator` | Validator GitHub app. This is the merge gate. |
| `validator_pass` | Report-only on `pull_request` (it can stay green while `validator` is still missing). On `merge_group` it passes only when every PR in the entry has a `validator` success on its head sha. |
| Dependabot | Dependency alerts |

## Landed, still due a follow-up

Recorded status as of 6 Nov 2026, Pacific Time.

- Card 925 slices are on main: wake ([PR 330](https://github.com/si4ai/the-mill/pull/330)), mail ([PR 332](https://github.com/si4ai/the-mill/pull/332)), hold ([PR 333](https://github.com/si4ai/the-mill/pull/333)), doing ([PR 334](https://github.com/si4ai/the-mill/pull/334)), score ([PR 335](https://github.com/si4ai/the-mill/pull/335)), plus `verify/todo-code`. Pin is still 0.8.5 (`ce115f8`); due a re-pin after later landings.

## Not built yet

Recorded status as of 6 Nov 2026, Pacific Time.

- Card 1071 audit script: draft written (merge evidence, card closure; invokes `check_doc_commands.py` rather than rebuilding it). Not in the repo yet. Add failure-class freshness, scores, and SPIN later.
- A TaskWrapper / doing SPIN model (`tw` lifecycle, kind map, cap 8, no return from a terminal state). `doing.pml` today models 0.8.0 seat doing, not `tw`.
- Refresh SPIN pins (`SYNC` and `SYNC_080`) against current main after card 970 landed. README last full run was 1 Nov 2026, 102 checks, pins `c1c1d87` and `8a80dc1`.
- A standing flake detector that reports fail-then-pass and pass-then-fail on the same SHA. Script drafted with the 1071 tooling; card 1079 still needs the full list. Not in the repo yet.
- Refresh [FAILURE-CLASSES.md](FAILURE-CLASSES.md) after 0.8.2.

## How a protocol audit uses them

On a release, incident, recurring-correction, or SPIN pass, these are
the checks, not a grade of each PR.

1. **Process.** Each step or card has a written done-when. Validator
   checks claims against a covering command plus the sha and date of
   its last result. A missing line is input missing, not green.
2. **Protocol.** Frames and hops against dual-plane, the letter 4583
   kind map, and letter 4585 residuals. Product-code drift is a card
   to the owner, not an Auditor edit.
3. **SPIN.** If wake, hold, or doing/`tw` design changed, update
   `verify/spin` models and README to match the code, run
   `verify/spin/run.sh`, and open a PR. SPIN stays outside CI. A
   middle version bump also starts a pass.
4. **Stale pointers.** A covering command is not re-run by the
   Auditor. A pointer that resolves to nothing, or a result older
   than the span, is reported as stale.
