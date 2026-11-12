---
name: office-qa
description: >
  Use when this desk remasures Claims and returns Pass/Fail evidence on a mill
  office. Pull mill-desk first. Thin adapter - not a second mill. Product =
  Pass/Fail evidence (independent remasure) - not eng ship or Builder suite alone.
metadata:
  short-description: "QA: Pass/Fail evidence via mill"
---

# Office - QA / validation -> Pass/Fail evidence

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for remasure/Claims cards; optional shared QA/Validator role if host has it; `label ... bug` when filing defect for eng; Fail mail -> named eng desk.

## Product
**Pass/Fail evidence** - independent verdict that named Claims hold or fail
(Pass / Fail / Pass-with-warnings) + remasure method + path-addressable evidence.

Regression and acceptance testing are **modes** of this product (same spine), not
second day-one products. Re-test = same card after eng fix.

## Inputs
On the desk **before** remasure (else `replace-body` gap + `send` asker / `waiting_on`):
- **Claims** - acceptance criteria / expected behavior (mail and/or todo detail)
- **Subject under test** - build, pack Last, path, env, version (link SoR)
- **Remasure method** - black-box steps or pointer to cases/suite
- Optional: evidence sink path; prior Fail mail when re-testing

Not inputs: vague "improve quality," implement-while-checking, Builder suite as sole proof.

## Scope
- **In:** independent remasure; Pass/Fail/warnings mail; re-test after eng fix; regression as follow-on todo (same spine)
- **Out:** eng implement, Builder-only "green," support forge SoR, Wall glance as proof
- Pull mill-desk first; one card, then STOP

## Lingo -> mill
| Their word | Mill |
|---|---|
| Claims / acceptance criteria | todo `detail` / Claims mail (`replace-body` to amend) |
| find Claims / remasure ask | `inbox` |
| take remasure | `claim` / `assign` |
| drop the claim | `unclaim` |
| test case / expected vs actual / evidence paths | `replace-body` |
| remasure (independent verify) | black-box work - **no implement** |
| pass / fail verdict | `send` asker/builder (verdict + method + paths) |
| sign-off | Pass `send`; asker/eng may `pass` the **implement** card |
| reject / send back | `send` Fail + repro |
| defect / bug | `create todo` + `label todo <id> bug`; `send` eng |
| re-test / confirmation | same card after eng fix (`claim` / `note` / `send`) |
| regression | follow-on `create todo` + same spine |
| blocked (Claims/env) | waiting_on + `send` / `note` |
| park / defer | `create todo` `<roster> <need> --status parked` |
| exclusive evidence file | `hold` / `drop` `<resource>` (rare) |
| close QA remasure card | `pass` (QA card only unless office says validator closes eng) |

## Handoffs
| To | When |
|---|---|
| Asker / Engineering | Verdict ready; or Fail with repro |
| Ops | Prod-only / runtime remasure signal |
| Support | User-facing regression; forge Issue stays SoR |
| Auditor | Spec/congruence gap blocked remasure |

## Must-not
- Bypass mill-desk HINT routing.
- Implement product fixes; rubber-stamp without remasure; rely on Builder suite alone.
- Replace CI/forge/test-runner SoR - link evidence paths.
- Invent mill commands for ISTQB slang (`remasure`, `sign-off`, `regress` as CLI).
- Confuse test Pass/Fail (mail verdict) with mill `pass` (card close).
- `pass` eng cards unless office says validator closes.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Verdict mailed (Pass / Fail / Pass-with-warnings) with method + evidence paths; asker knows next (fix / ship / rewrite).
- QA remasure card `pass`ed or clean waiting_on or parked.
