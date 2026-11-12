---
name: office-finance
description: >
  Use when this desk moves spend approvals or paid/closed outcomes on a mill
  office. Pull mill-desk first. Thin adapter - not a second mill. Product =
  Approved / paid - not a ledger/ERP clone. `--receipt` for approve.
metadata:
  short-description: "Finance: Approved / paid via mill"
---

# Office - Finance -> Approved / paid

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for approval/remittance pointer cards; optional finance inbox role if host has it; named next approver = `send` desk.

## Product
**Approved / paid** - spend/invoice/PO request reached a durable approve
outcome (`--receipt` opened or withheld with reason) **or** a
paid/closed outcome with ledger id linked.

Invoice, PO, budget, forecast, accrual, coding, exception, and period-close
are **nouns, steps, score, or modes** on this spine - not second day-one
products. Ledger/ERP stays system of record for amounts, GL, and payments.

## Inputs
On the desk **before** you can approve or mark paid (else `note` gap + `send` asker / `waiting_on`):
- **Request identity** - invoice / PO / spend id or URL in detail (do not clone ledger amounts as SoR)
- **Outcome ask** - approve, withhold/reject, mark paid, or exception path
- **Approver / chain** - who must human-click (`assign` + `send` / `reply` `--receipt`)
- **Coding / cost center hint** - when office requires (note; coding runs in ledger)
- When exception: reason / policy cite for escalate mail
- On paid: payment / remittance pointer from ledger

Not inputs: "run the books," silent auto-approve when policy needs a human,
replacing ERP payment runs inside mill.

## Lingo -> mill
| Their word | Mill |
|---|---|
| invoice / PO / request | `create todo` (ledger id in detail) |
| own / work request | `claim` / `assign` |
| drop the claim | `unclaim` |
| approval / approve | `assign` + **`--receipt`** + `send` / `note` outcome |
| approval chain | `assign` next + `send`; waiting_on until human clicks |
| coding (GL / cost center) | `note` (ledger executes coding) |
| exception | `send` escalate (+ `note` reason) |
| progress | `note` |
| coded / approved diary | `replace-body` (not mail) |
| find work / mail landed | `inbox` |
| blocked (approver/bank/coding) | waiting_on + `send` / `note` |
| budget / forecast KPI | `score` - a row in the score table (`kpi`, `value`, `target`) |
| paid / closed | `note` payment pointer + `pass` |
| withhold / reject | `note` reason + `send` asker; `pass` or waiting_on revision |
| park / later | `create todo` `<roster> <need> --status parked` |
| accrual / period-close step | `note` / optional todo on same spine (ledger SoR) |

Do **not** teach `hold`/`drop` day-one unless the office leases a shared invoice/PO doc.
Never teach `open` / `yield` / bare `create` / `done`.
Never invent `approve` / `pay` / `code` as mill CLI.

## Handoffs
| To | When |
|---|---|
| Asker / requesting desk | Missing facts, withhold outcome, or revision ask |
| Next approver | Approval chain step (`--receipt`) |
| Sales | Pricing / discount / approve unblocks deal |
| Legal | Payment terms / compliance block on pay |
| People | Offer / comp spend needing finance approve |
| Ops / Engineering | Vendor spend tied to infra or incident cost |
| Support | Customer billing ticket (support owns resolve) |
| AP / controller desk | Exception escalate or period-close coordination |

## Must-not
- Bypass mill-desk HINT routing.
- Become the ledger of record (amounts, GL, AP/AR, bank, period close).
- Skip required human approval gates (`--receipt` on approve).
- Invent mill commands for finance slang (`approve`, `pay`, `code`, `close-books` as CLI).
- Fake `pass` while waiting on human approve or bank - use waiting_on + mail.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Approved: `--receipt` opened; outcome noted; dependents mailed; card `pass`ed or waiting_on next approver.
- Withheld/rejected: reason noted; asker mailed; card `pass`ed or waiting_on revision.
- Paid/closed: ledger payment pointer noted; card `pass`ed.
- Else clean waiting_on or parked - never silent open. Optional `score` if office sets forecast/budget KPI.
