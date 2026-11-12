---
name: office-marketing
description: >
  Use when this desk is producing a campaign launch or published asset on a
  mill office. Pull mill-desk first. Thin adapter - not a second mill.
  Product = Launch / campaign - not a CMS or analytics clone.
metadata:
  short-description: "Marketing: Launch / campaign via mill"
---

# Office - Marketing -> Launch / campaign

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for campaign/asset cards; optional marketing intake role if host has it; named reviewer = `send`; embargo = waiting_on speech.

## Product
**Launch / campaign** - campaign live **or** asset published under the office
review/approve gate, with the KPI owner pointed at the score row.
README catalog noun: Launch / publish. CMS/DAM and analytics stay systems of
record; mill coordinates collab only.

Brief, creative work, channel, embargo, and KPI are **inputs, steps, gates, or
score** on this spine - not second day-one products.

## Inputs
On the desk **before** you can launch or publish (else `replace-body` gap + `send` asker / `waiting_on`):
- **Brief / ask** - what ships (in todo detail)
- **Campaign or asset identity** - name + CMS/DAM id or URL (do not clone CMS)
- **Channel / date** - and embargo if any
- **Review / approve path** - who must greenlight (brand -> `--receipt` if policy)
- **KPI** - a row in the score table (`kpi`, `value`, `target`)
- When handoff: sales enablement / support FAQ / eng landing ask

Not inputs: "grow reach," CMS upload as mill's job, analytics warehouse as mill's job.

## Lingo -> mill
| Their word | Mill |
|---|---|
| brief | `create todo` + detail |
| campaign | `create todo` (CMS/campaign id in detail) |
| creative / asset work | `claim` + `replace-body` (+ `hold`/`drop` if exclusive asset station) |
| own / take it | `claim` / `assign` |
| drop the claim | `unclaim` |
| progress | `todo <roster> <need> --eta E` / `--started` / `--progress 9/12` |
| diary | `replace-body` |
| find work / mail landed | `inbox` |
| review cycle | `send` (+ second desk claim if needed) |
| approval / brand approve | `send` / `reply` `--receipt` if policy |
| embargo / wait | waiting_on + `send` |
| channel | detail / `replace-body` |
| handoff to sales/support | `send` + `assign` |
| KPI (reach/conversion) | `score` - a row in the score table (`kpi`, `value`, `target`) |
| publish / launch | `pass` (+ optional Wall glance) |
| park / later | `create todo` `<roster> <need> --status parked` |

Teach `hold`/`drop` only when the office leases a shared creative station.
Never teach `open` / `yield` / bare `create` / `done`.

## Handoffs
| To | When |
|---|---|
| Sales | Enablement / launch asset / inbound MQL context |
| Support | FAQ or customer-facing copy after publish |
| Legal | Claims, trademark, disclosure, legal embargo |
| Finance | Media spend / budget approve gate |
| Engineering | Landing, tracking, release-tied launch |
| QA | Claims remasure / evidence |
| Research | Insights brief feeding the ask |
| Brand human | Approve gate / embargo lift (`--receipt`) |

## Must-not
- Bypass mill-desk HINT routing.
- Treat mill as DAM/CMS or as analytics SoR.
- Invent mill commands for marketing slang (`publish`, `launch`, `approve`, `embargo` as CLI).
- Launch without the review gate the office requires.
- Fake `pass` while embargoed or waiting brand/legal/finance - use waiting_on + mail.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Launch/publish: card `pass`ed; CMS/channel live outside mill; optional Wall glance; KPI owner knows the row in the score table (`kpi`, `value`, `target`).
- Handoff: sales/support (etc.) mailed and/or assigned when brief requires.
- Else clean waiting_on or parked - never silent open.
