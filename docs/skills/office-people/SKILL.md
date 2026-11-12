---
name: office-people
description: >
  Use when this desk is hiring or onboarding humans on a mill office. Pull
  mill-desk first. Thin adapter - not a second mill. Product = Hired /
  onboarded - not an ATS.
metadata:
  short-description: "People: hired / onboarded via mill"
---

# Office - People / recruiting -> Hired / onboarded

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for req/offer/onboard cards; optional recruiting intake role only if the host created it; HM/buddy/interviewer = `assign`/`send` named desk - do not invent role `people`.

## Product
**Hired / onboarded** - two day-one artifacts, one spine:

1. **Hired** - requisition filled: interview loop complete, offer cleared via
   `--receipt`, outcome recorded (ATS updated outside mill).
2. **Onboarded** - onboarding checklist complete: each owner slice claimed and
   `pass`ed (access, equipment, training, paperwork pointers).

Req / interview loop / debrief are **structure and collab** under Hired, not
extra products. Interview notes are `replace-body`/`send`. A KPI is a row in the score table (`kpi`, `value`, `target`).

## Inputs
On the desk **before** advance/offer/onboard (else `replace-body` gap + `send` / `waiting_on`):

**Hired**
- **Req identity** - role, ATS/req id, hiring manager (`create todo` parent + `detail` link)
- **Candidate pointer** - ATS id / policy-safe label (minimize PII)
- **Loop plan** - interviewers as child `create todo`s; `assign` / `claim`
- Before offer: debrief decision + offer approver path (`send` / `reply` **`--receipt`**)

**Onboarded**
- **Hire confirmed** - start date / filled-req link (else waiting_on)
- **Checklist + owners** - child `create todo` per item; `assign` / `claim` per owner

Not inputs: paste full resumes/SSN into mill, skip `--receipt` when required,
replace ATS/HRIS, invent recruiting CLI commands.

## Lingo -> mill
| Their word | Mill |
|---|---|
| req / requisition | parent `create todo` + `detail` (ATS link) |
| candidate | `detail` / `replace-body` pointer (minimize PII; ATS SoR) |
| interview loop | child `create todo` per interviewer + `assign` / `claim` |
| panel | `assign` panelists + `send` |
| debrief | `send` + `replace-body` (replace-body != mail) |
| interview notes | `replace-body` (+ `send` HM) - not a score row |
| hiring manager / recruiter | `assign` / `claim` / `send` |
| advance / reject | `replace-body` decision + next `assign` (or park) |
| drop the claim | `unclaim` |
| offer | **`--receipt`** + `send` approver + `replace-body` outcome |
| onboarding | checklist `create todo`s + `claim` / `assign` per owner |
| blocked (approver / candidate / IT / legal) | waiting_on + `send` |
| escalate | `send` legal/finance/IT (optional their `create todo`) |
| exclusive offer-doc file | `hold` / `drop` (rare; if the office leases a res name) |
| hiring KPI (optional) | a row in the score table (`kpi`, `value`, `target`) |
| filled req / hired | `replace-body` outcome + parent `pass`; `send` onboarding kickoff |
| checklist complete / onboarded | children + parent `pass` |
| park / defer | `create todo` `<roster> <need> --status parked` |
| find people mail | `inbox` |

## Handoffs
| To | When |
|---|---|
| Hiring manager | Debrief, advance/reject, offer approve, start-date |
| Recruiter / people | Loop ownership, offer packet, onboarding kickoff |
| Legal | Employment / compliance review - waiting_on their clear |
| Finance | Comp / offer cost approve when office requires |
| IT / ops / facilities | Access, equipment, badge checklist children |
| Eng / function desk | Role interviewers; buddy assignment |
| Sales / CS | Customer onboarding from close-won - **not** this skill unless office routes it |

## Must-not
- Bypass mill-desk HINT routing.
- Replace ATS/HRIS/e-sign/background-check SoR - link paths; minimize PII.
- Skip `--receipt` on offer if office requires it.
- Invent mill commands for recruiting slang (`offer`, `advance`, `loop`, `debrief` as CLI).
- Teach `open` / `yield` / bare `create` / `done`.
- Confuse `drop` (hold) with `unclaim`. A hiring KPI is a score row. Interview notes are `replace-body`.
- Own legal clearance or finance approval.

## Done looks like
- **Hired:** loop noted; offer `--receipt` opened; outcome recorded; ATS
  updated outside mill; req card `pass`ed or clean waiting_on/parked; onboarding
  kickoff mailed/todos assigned on accept.
- **Onboarded:** checklist children `pass`ed (or explicit parked leftovers);
  parent `pass`ed; manager/IT mailed as needed.
