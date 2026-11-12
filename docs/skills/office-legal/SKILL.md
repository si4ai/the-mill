---
name: office-legal
description: >
  Use when this desk clears contracts or compliance holds on a mill office.
  Pull mill-desk first. Thin adapter - not a second mill. Product = Cleared /
  hold - not a CLM suite.
metadata:
  short-description: "Legal: cleared / hold via mill"
---

# Office - Legal -> Cleared / hold

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for clearance cards; optional counsel intake role if host has it; named counsel = `send` desk.

## Product
**Cleared / hold** - durable clearance decision: **cleared** (ship/sign/close
allowed) or **hold/withheld** (blocked with reason), mailed so eng/sales
dependents unlock or stay waiting_on.

Redline, opinion memo, and audit crumbs are **modes/crumbs** of this product
(same spine), not second day-one products. Contract file stays **SoR outside**
mill (CLM / e-sign / Drive) - link, don't clone.

## Inputs
On the desk **before** clear/withhold (else `replace-body` gap + `send` / `waiting_on`):
- **Review ask** - contract/compliance/ship gate (`inbox` / mail / `create todo`)
- **Artifact pointer** - contract id, doc path, PR/ship or deal card (link SoR)
- **Gated action** - ship / sign / close / publish; name dependent cards if known
- **Owner** - `claim` / `assign`
- When redlining shared doc: ready to `hold` / `drop` the doc station
- When **clearing**: `send` / `reply` `--receipt` to the signatory/authority before Pass-equivalent mail
- When escalate: counsel/specialist dest for `send`

Not inputs: "just approve" with no pointer; silent chat greenlight; full contract
body dumped into mill as SoR.

## Lingo -> mill
| Their word | Mill |
|---|---|
| review request | `inbox` / `create todo` -> `claim` / `assign` |
| contract (pointer) | todo `detail` / `replace-body` link; **CLM SoR outside** |
| redline / exclusive edit | `hold` / `drop` on doc station (+ `note`) |
| approval / clear authority | `send` / `reply` `--receipt` (+ `assign` as needed) |
| escalate to counsel | `send` (optional `assign`) |
| hold / block ship / withhold | waiting_on on eng/sales card + `send`/`replace-body` reason (**!=** mill `hold`) |
| clear / approve | `--receipt` -> `send` Pass-equivalent -> unlock dependents -> legal `pass` |
| opinion | `replace-body` and/or `send` memo/link |
| audit trail | `send` + `replace-body` crumbs (SoR stays outside) |
| drop the claim | `unclaim` |
| progress | `note` |
| diary | `replace-body` (not mail) |
| blocked on others | waiting_on + `send` / `note` |
| park / defer | `create todo` `<roster> <need> --status parked` |
| cycle-time KPI (optional) | `score` - a row in the score table (`kpi`, `value`, `target`) |

## Handoffs
| To | When |
|---|---|
| Engineering | Ship/release blocked or cleared |
| Sales | Deal/sign blocked on legal or cleared to close |
| Finance | Commercial/PO terms need finance gate |
| Research | Diligence facts before clear |
| Marketing | Publish/embargo legal review |
| Counsel desk | Escalate to counsel |
| Asker / human signatory | `--receipt` clear; redline questions |

## Must-not
- Bypass mill-desk HINT routing.
- Silent clear without mail; unlock ship while waiting_on legal remains.
- Replace Contract/CLM/e-sign/Drive SoR - link paths only.
- Invent mill commands for legal slang (`clear`, `withhold`, `redline`, `escalate` as CLI).
- Teach `open` / `yield` / bare `create` / `done`.
- Confuse `drop` (hold) with `unclaim`; confuse legal "hold" (block ship) with mill `hold`.
- Skip `--receipt` on clear when office requires it.
- Own eng ship, CRM stages, or finance ledger.

## Done looks like
- Clear or withhold mailed; `--receipt` opened on clear; dependents
  unlocked or still waiting_on with owner; legal card `pass`ed or clean
  waiting_on - never silent open forever.
