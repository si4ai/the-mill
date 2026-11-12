---
name: office-engineering
description: >
  Use when this desk is shipping working software (code, package, API, service
  behavior) on a mill office. Pull mill-desk first. Thin adapter - not a second
  mill. Product = working software/package - not forge PR theater or other eng
  disciplines. Forge PRs stay SoR.
metadata:
  short-description: "Software eng: working software/package via mill"
---

# Office - Engineering (software) -> Working software / package

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer an office project for implement/feature cards; optional eng pickup role if the host has it; `label ... bug` on defects; named assignee = `assign`/`claim` desk; PR stays forge SoR.

**Scope:** software that runs (merged change, wheel/image, service behavior).
Other engineering disciplines = different product + inputs -> separate skills later.
Forge PRs/CI stay systems of record; mill coordinates the card.

## Product
**Working software / package** - change users/agents can run (merged code,
published package, live service behavior).

Review, RC/release, and hotfix are **modes or collab** on this spine (same
commands), not second day-one products. The PR object lives in forge SoR - link it.

## Inputs
On the desk **before** implement (else `replace-body` gap + `send` asker / `waiting_on`
or `create todo` `<roster> <need> --status parked`):
- **Card** - claimed or assigned; need + detail locked enough to build (or explicit spike)
- **Scope crumbs** - repo/path, pack, or service named; acceptance in detail or linked Claims
- **If remasure Fail** - Validator Fail mail + evidence paths (`inbox`)
- **If touching shared files** - ready to `hold` those paths before write

Not inputs: vague "make it better," no card, or implementing while QA owns Pass/Fail.

## Lingo -> mill
| Their word | Mill |
|---|---|
| change / bug / feature | `create todo` (+ `label ... bug` when bug) |
| take / give work | `claim` / `assign` |
| drop the claim | `unclaim` |
| PR / branch | todo card + link in `detail`/`replace-body`; forge SoR (not a mill PR command) |
| exclusive tree/file | `hold` / `drop` |
| progress | `note` |
| CI links / artifact path / diary | `replace-body` (not mail) |
| review / approve / request changes | `send` reviewer (+ optional second `claim`); forge review SoR |
| ask remasure / Claims ready | `send` -> validator/QA with Claims |
| Validator Fail / re-fix | `inbox` -> fix on card -> `note` -> re-`send` Claims |
| merge / ship | `replace-body` forge merge/link; `pass` after Pass/pack gate |
| RC / release / pack Last | pack cut + `send` validator; `pass` after gate |
| hotfix | urgent `create todo`/`claim` + `send` ops when runtime |
| blocked (review/QA/CI/ops) | waiting_on + `send` / `note` |
| park / spike later | `create todo` `<roster> <need> --status parked` |
| find Fail / eng mail | `inbox` |
| close after Pass | `pass` (shipped->done per mill-desk; no teaching `done`) |
| eng KPI | `score` - a row in the score table (`kpi`, `value`, `target`), only if the office sets it |

## Handoffs
| To | When |
|---|---|
| Validator / QA | Claims ready; remasure ask |
| Ops | Deploy/incident needs runtime; hotfix prod impact |
| Support | User-facing regression context |
| Auditor | Spec unclear / congruence |
| Reviewer (peer) | Review/approve ask |

## Must-not
- Bypass mill-desk HINT routing.
- Final Pass/Fail (QA hat); own ops uptime/deploy product.
- Ship without a visible card; leave claimed+100% without `pass`.
- Replace forge/CI/registry SoR - link paths; invent git/CI mill commands (`pr`, `merge`, `release` as CLI).
- Teach `open` / `yield` / bare `create` / `done`.
- Confuse `drop` (hold) with `unclaim`; confuse forge approve/merge with mill `pass`.

## Done looks like
- Behavior/package exists; Claims mail has evidence paths; implement card `pass`ed
  after Pass/pack gate (or clean waiting_on / parked).
