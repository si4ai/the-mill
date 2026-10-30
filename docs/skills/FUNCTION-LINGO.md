# Function lingo -> the Mill (draft - uncommitted)

Mill does not rename itself to Jira/GitHub/Zendesk. For each industry phrase ask:
1. **Product noun** - what artifact?
2. **Collab intent** - assign, review, escalate, approve, wait, finish?
3. **Mill fulfillment** - which shared record makes that intent durable (presence, todo, mail, hold, waiting_on, score row, wall)?

CLI commands are the write API for those records - secondary to the representation.
Industry verbiage for **what each office function ships** (product/artifact) and **how they collaborate**, then a sketch map onto mill primitives. Not a commitment that mill renames its commands - a translation layer for office-function skills.

Sources (public glossaries): GitHub/PR & release terms; ISTQB testing glossary; SRE/incident (Google/Atlassian/incident.io); ITIL 4 service desk. Sales/people/legal rows use common CRM/ATS practice language.

**Roster:** when mapping office lingo into mill todos/mail, pick one roster name (bare name; type `roster`); use `label` for classification (label `bug`, ...). See mill-desk Roster Guard + office-* Roster. If the ask omits one, ask the human which roster - do not invent.

## Legend - mill primitives (stable)

| Mill | Role |
|---|---|
| presence / HERE | who's on the floor |
| todo / claim / assign / pass | work cards |
| mail / send / inbox | handoff & wake |
| hold / drop | exclusive write |
| score | a scorecard: a row in the score table (`kpi`, `value`, `target`) |
| wall | human glance |
| waiting_on / leftover | blocked / unfinished |

---

## Engineering / build

**Product words:** change, branch, pull request (PR), review, approve, request changes, merge, build, artifact, release candidate (RC), release, deploy, hotfix, changelog, GA.

**Collab words:** contributor, reviewer, maintainer, code review, CI checks, merge queue, ship.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| PR / change | todo (implement) + hold on tree |
| review / approve | mail handoff; optional second desk claim |
| merge / ship | note progress; done after Pass/pack gate |
| RC / release | pack cut; Validator remasure Last |
| hotfix | urgent todo + ops handoff |

---

## QA / validation

**Product words:** acceptance criteria, test case, expected vs actual, pass / fail, defect, confirmation test (re-test), regression, acceptance testing, exit criteria, evidence.

**Collab words:** remasure / independent verify, pair testing, sign-off, reject / send back.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| acceptance criteria | todo `detail` / Claims |
| remasure | Validator desk; no implement |
| pass / fail | mail verdict + evidence paths |
| re-test | same card after eng fix |
| regression | leftover / follow-on todo |
| sign-off | Pass mail; asker may `pass` |

---

## Ops / SRE

**Product words:** service health, uptime, SLO/SLA, deploy, rollback, runbook, mitigation, resolution, incident, severity (SEV), postmortem (blameless).

**Collab words:** on-call, page, triage, escalate, incident commander (IC), stakeholder comms, follow-the-sun.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| on-call / HERE | presence |
| page / alert | wake / mail |
| incident | todo claim |
| SEV | detail + priority in doing |
| mitigate | note + done when impact stopped |
| escalate | mail eng/support |
| postmortem | follow-on todo or parked plan |
| drain / deploy window | drain + mail ETA |

---

## Support / service desk

**Product words:** ticket / service record, incident vs service request, resolution, workaround, backlog, CSAT (optional).

**Collab words:** queue, assign, priority (impactxurgency), functional vs hierarchical escalation, L1/L2/L3, SLA timer, close.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| ticket | todo |
| queue | open todos for support desk |
| assign / own | claim |
| escalate | mill send eng/ops |
| workaround | note on card |
| resolve / close | done when user unblocked **or** bug owned elsewhere |
| SLA | a row in the score table (`value` vs `target`) |

---

## Sales / pipeline (common CRM)

**Product words:** lead, MQL/SQL, opportunity, pipeline, proposal, close-won / close-lost, account, renewal.

**Collab words:** handoff (SDR->AE->CS), next step, blocked on legal/pricing, forecast.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| opportunity | todo (or plan row for big deals) |
| next step | progress / note |
| handoff | mail + assign |
| blocked | waiting_on |
| close-won | done; mail CS onboarding todo |

---

## Marketing / content

**Product words:** brief, creative asset, campaign, launch, publish, channel, KPI (reach/conversion).

**Collab words:** review cycle, approval, embargo, handoff to sales/support.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| brief | todo detail |
| review / approve | mail; human_required if needed |
| publish / launch | done + optional wall glance |
| KPI | a row in the score table (`kpi`, `value`, `target`) |

---

## People / recruiting

**Product words:** req / requisition, candidate, interview notes, offer, onboarding checklist.

**Collab words:** interview loop, panel, debrief, hiring manager, recruiter, reject/advance.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| req | plan or parent todo |
| interview loop | child todos per interviewer |
| debrief | mail thread / note |
| offer | human_required gate |
| onboarding | checklist todos; claim per owner |

---

## Legal / compliance

**Product words:** contract, redline, approval, hold, opinion, audit trail.

**Collab words:** review, escalate to counsel, block ship, clear / withhold.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| review | claim + hold on doc station |
| hold / block | waiting_on ship card |
| clear | mail Pass-equivalent; unlock eng/sales |
| audit trail | mail + notes (SoR) |

---

## Finance / admin

**Product words:** invoice, PO, budget, forecast, accrual, payment.

**Collab words:** approval chain, coding, exception, close the books.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| approval | human_required mail / todo |
| exception | escalate mail |
| paid / closed | done |
| forecast KPI | a row in the score table (`kpi`, `value`, `target`) |

---

## Research / knowledge

**Product words:** brief, findings, decision record, recommendation.

**Collab words:** review, challenge, synthesize, decide, park.

**-> mill sketch**

| Their word | Mill-ish |
|---|---|
| brief | todo deliverable path |
| challenge | mail / second desk |
| decision | note + optional plan park |
| park | plan upcoming / parked |

---

## Meta (not a product function)

**Project management / coordination** - words like roadmap, milestone, RACI, standup, blocker. These describe **motion**, not the artifact. In mill they collapse to mill-desk + Auditor coach, not a peer "PM product" skill.

---

## How office-function skills should talk

1. Lead with **their product noun** (release, Pass evidence, incident closed, ticket resolved).
2. Use **their collaboration words** in the When/Handoffs sections.
3. Map once to mill commands in a small table - don't rename mill CLI to "open PR."
4. Must-not: pretend mill *is* Jira/GitHub/Zendesk/PagerDuty.

## Next

- Fold these tables into each `docs/skills/office-*/SKILL.md` Lingo section.
- Pick one function to dogfood end-to-end on a mill office.

---

See also: [skills/README.md](README.md) for the general human->mill mapping pattern and full office-* skill set.
