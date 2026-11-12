---
name: office-support
description: >
  Use when this desk resolves user/reporter tickets on a mill office (incl.
  GitLab/GitHub bug reports). Pull mill-desk first. Thin adapter - not a
  second mill. Product = resolved ticket - forge Issues stay SoR; mill
  coordinates.
metadata:
  short-description: "Support: resolved ticket via mill"
---

# Office - Support -> resolved ticket

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for ticket/SR cards; optional L2/on-call role if the host has it; `label ... bug` when ticket->bug; escalate = `send` desk/role (host).

## Product
**Resolved ticket** - user/reporter unblocked (answer or workaround) **or**
remaining fix visibly owned elsewhere (eng/ops todo id) with forge Issue
updated when the report came from GitLab/GitHub.

Incident vs service request are **modes** of this product (detail/label), not
second day-one products. Major SEV / runtime outage -> hand off office-ops.

## Inputs
On the desk **before** triage resolve (else `replace-body` gap + `send` / `waiting_on`):
- **Ticket identity** - what broke or what was asked (`create todo` need + detail)
- **Reporter path** - who to unblock; reply desk or `--receipt` channel
- **Forge URL** - required in detail when report came from GitLab/GitHub Issue
- Strong: priority (impactxurgency) text; incident vs request vs bug classification
  (bug -> `label ... bug`)

Not inputs: vague "improve CSAT," silent close with no ball location, cloning the
ITSM/forge database into mill.

## Lingo -> mill
| Their word | Mill |
|---|---|
| ticket / new bug report | `create todo` (+ forge URL in detail; bug -> bug label) |
| queue / find work | `todo` list / `inbox` |
| triage / own / assign | `claim` / `assign` |
| drop the claim | `unclaim` |
| priority (impactxurgency) | todo `detail` (text) |
| progress | `note` |
| workaround / diary | `replace-body` |
| need more info | `send` reporter / `--receipt` + `waiting_on` |
| escalate (L1->L2/L3, eng/ops) | `send` + eng/ops todo/`assign`; support `waiting_on` |
| duplicate | `replace-body` canonical + `pass` |
| resolve / close | `pass` when user unblocked **or** fix owned elsewhere |
| blocked (reporter/eng/vendor) | `waiting_on` + `send` / `note` |
| park / defer | `create todo` `<roster> <need> --status parked` |
| SLA (and optional CSAT) | `score` - a row in the score table (`kpi`, `value`, `target`) |
| exclusive file lock | omit day-one (`hold`/`drop` only if office leases) |

## Handoffs
| To | When |
|---|---|
| Engineering | Code fix / bug ownership |
| Ops | Runtime SEV / incident ownership; customer-impact ops owns |
| QA | Remasure before telling user "fixed" |
| Reporter / human | More info; workaround; confirm unblock |
| Auditor | Policy/spec gap blocked triage |

## Must-not
- Bypass mill-desk HINT routing.
- Replace forge/ITSM SoR - link Issues; do not clone the bug database.
- `pass` without saying where the ball is (answer/workaround **or** eng/ops todo id).
- Skip forge link in detail when the report came from GitLab/GitHub.
- Invent mill commands (`escalate`, `resolve`, `triage`, `priority` as CLI).
- Teach `open` / `yield` / bare `create` / teaching `done`.
- Confuse `drop` (hold) with `unclaim`; confuse `note` with `send`.
- Teach `hold` day-one unless the office leases shared resources.

## Done looks like
- User unblocked **or** visible eng/ops todo owns the fix; forge Issue updated when applicable.
- Support card `pass`ed or clean waiting_on or parked.
