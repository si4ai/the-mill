---
name: office-sales
description: >
  Use when this desk is moving pipeline to close-won or a clean stage handoff
  on a mill office. Pull mill-desk first. Thin adapter - not a second mill.
  Product = Close-won / handoff - not a CRM clone.
metadata:
  short-description: "Sales: Close-won / handoff via mill"
---

# Office - Sales -> Close-won / handoff

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for deal/enablement cards; optional inbound role if the host has it; SDR/AE/CS = `send`+`assign` named desk - do not invent role `SDR`; no fan-out `*`.

## Product
**Close-won / handoff** - opportunity advanced to close-won (deal closed; CS/delivery
mailed) **or** a clean stage handoff (SDR->AE->CS/delivery) with owner + next step.
CRM stays system of record for amounts, accounts, and stage history.

Lead/MQL/SQL, proposal, renewal, and forecast are **stages, steps, or score** on
this spine - not second day-one products. Close-lost = same card `pass` + `replace-body` why.

## Inputs
On the desk **before** you can advance or close (else `replace-body` gap + `send` asker / `waiting_on`):
- **CRM identity** - opportunity/account id or URL in detail (do not clone amounts)
- **Stage / outcome ask** - advance, close-won, close-lost, or handoff destination
- **Owner path** - SDR / AE / CS / delivery (for claim/assign)
- **Next step** - call, demo, proposal, legal, pricing (progress via `note` as you go)
- When blocked: legal/pricing/security context for waiting_on mail
- On close-won: CS onboarding ask (who/what to mail or todo)

Not inputs: "grow the pipeline," CRM data entry as mill's job, fan-out assign.

## Lingo -> mill
| Their word | Mill |
|---|---|
| lead / opportunity | `create todo` (CRM id in detail) |
| MQL / SQL / stage | `replace-body` on opp card (CRM stage outside mill) |
| own / work deal | `claim` / `assign` |
| drop the claim | `unclaim` |
| next step / progress | `note` |
| find work / mail landed | `inbox` |
| handoff SDR->AE->CS | `send` + `assign` |
| blocked (legal/pricing) | waiting_on + `send` / `note` |
| proposal path | `replace-body` (+ `send` legal/finance if gate) |
| forecast / KPI | `score` - a row in the score table (`kpi`, `value`, `target`) |
| close-won | `pass` + `send` CS/delivery (+ optional onboarding `create todo` / `assign`) |
| close-lost | `pass` + `replace-body` why |
| park / later | `create todo` `<roster> <need> --status parked` |
| renewal | same spine: `create todo` renew opp **or** `send` CS |

Do **not** teach `hold`/`drop` day-one unless the office leases a shared proposal doc.
Never teach `open` / `yield` / bare `create` / `done`.

## Handoffs
| To | When |
|---|---|
| CS / delivery | Close-won - mail + optional onboarding todo |
| Legal | Contract / redline / clear gate |
| Finance | Pricing / discount / approve gate |
| Marketing | Launch asset or inbound MQL context |
| Support | Post-sale user issue (ticket product owns resolve) |
| Engineering / QA | POC, security review, or Claims remasure |

## Must-not
- Bypass mill-desk HINT routing.
- Replace CRM as SoR for amounts/accounts/stage/forecast-of-record.
- Fan-out the same assign to `*` + role + desk.
- Invent mill commands for CRM slang (`qualify`, `pipeline`, `close`, `stage` as CLI).
- Fake `pass` while blocked - use waiting_on + mail.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Close-won: card `pass`ed; CS/delivery mailed (and/or onboarding todo assigned); CRM closed outside mill.
- Close-lost: card `pass`ed with `replace-body` why.
- Handoff: next owner assigned and/or mailed; waiting_on cleared or explicit.
- Else clean waiting_on or parked - never silent open.
