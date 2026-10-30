# RESEARCH - office-ops

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward, dry, cite-first. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-ops \| Uptime / incident closed \| product** |
| Folder | `docs/skills/office-ops/` exists |
| Stub | Thin `SKILL.md` present (Product = Stable runtime; When + Verbs; no Inputs / Scope / full Lingo->mill; When!=TEMPLATE Inputs) |
| FUNCTION-LINGO.md | Present - S **Ops / SRE** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked; reject `open` / `yield` / bare `create` / teaching `done` |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-qa (`RESEARCH.md` + SKILL), office-support, office-engineering read |

**Function:** office-ops  
**README product noun:** Uptime / incident closed

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Uptime / incident closed** (stable runtime) | **KEEP** | Catalog product. Stub: deploy succeeded, incident closed, or intentional drain with ETA. FUNCTION-LINGO product words: uptime, incident, resolution, mitigation. |
| Deploy succeeded as separate product | **DROP** (day-one) | Deploy/rollback/deploy-window are **modes** of stable runtime (FUNCTION-LINGO drain/deploy window -> drain + mail ETA; stub When). Same spine; not a 2nd SKILL product. |
| Intentional drain with ETA as separate product | **DROP** (day-one) | Stub folds drain into Product; FL sketch: drain + mail ETA. Mode of uptime, not second artifact. |
| Postmortem (blameless) as product | **DROP** | FUNCTION-LINGO sketch: follow-on todo or parked plan. Collab/follow-on work, not the shippable ops artifact day-one. |
| SLO/SLA / service health KPI as product | **DROP** | README score row cluster: ops (SLO). Fulfillment = `score` / score rows - not a product noun. |
| Runbook as product | **DROP** | Method/input (how to mitigate). Lives in detail/note or external SoR; not the office artifact. |
| Status page essay / stakeholder blog | **DROP** | Stub description: "not a status page essay." Comms = `send` / note; SoR may be status tool. |
| SEV taxonomy / IC role as product | **DROP** | Collab structure (SEV -> detail priority; IC -> claim/assign). Not an artifact. |

**Kept products (day-one): 1 - Uptime / incident closed** (modes: incident mitigate/close, deploy/rollback window, intentional drain with ETA, health recovery).

---

## Product (kept) - Uptime / incident closed

**Artifact (one sentence):** Runtime is stable again - incident impact stopped and closed, deploy/rollback finished clean, or intentional drain has a clear ETA and stakeholders know - recorded on a mill card, not a status-page essay.

**Not the product:** eng merge/ship, QA Pass/Fail evidence, support ticket resolve, postmortem writeup as primary deliverable, inventing PagerDuty inside mill.

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Signal (page/alert/health fail / deploy ask / drain ask) | **Yes** | `inbox` / wake / mail; or human chat -> `create todo` |
| Scope of impact (service, SEV/priority, blast radius) | **Yes** | todo `detail` / `doing`; SEV in detail (FL: SEV -> detail + priority) |
| Owner / on-call coverage | **Yes** | presence HERE; `claim` / `assign` |
| Mitigation path (runbook pointer, rollback plan, drain steps) | Strong | `note` / detail; link SoR runbook - don't clone |
| Stakeholder / eng/support dests for comms | When impact visible | `send` dest=desk/role |
| Deploy artifact / change id (when deploy mode) | When deploy | detail link to forge/CI SoR |
| Drain ETA | When drain | `note` + `send` ETA (stub Drain; FL drain + mail ETA) |

Not inputs: vague "keep the lights on," silent prod change with no card when office requires one, infinite reconnect spam as a plan.

### Done looks like (this product)

- **Incident:** impact mitigated; card `note`d; stakeholders `send`ed; card `pass`ed **or** clean `waiting_on` (blocked on eng fix / human) **or** parked follow-on (postmortem).
- **Deploy/rollback:** change live or rolled back; card `pass`ed; optional QA remasure handoff if Claims say so.
- **Drain:** ETA clear on card + mailed; no reconnect spam; card `pass` when drain complete or waiting_on until window ends per office policy.
- Service healthy **or** intentional degraded state with ETA - never silent open forever.

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `note`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk). Wake exists on mill-desk for socket catch-up - cite as inbound, not invent ops CLI.

Sources for rows: **FUNCTION-LINGO.md S Ops / SRE** (required), mill-desk day-one, stub, README (score row: ops SLO; escalate = send; waiting_on; presence), siblings (eng->Ops deploy/incident; support escalate->ops; qa->Ops prod-only).

Shared spine (one table for the function):

| Their word | Source | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| on-call / HERE | FL Ops collab + sketch "presence"; stub Who's HERE | presence / agents | **presence / HERE** (glance; not a card command) | not invent `oncall` CLI |
| page / alert | FL sketch "wake / mail"; stub Page | wake, send, inbox | **`send` / wake** + **`inbox`** | wake = catch-up/inbound; page != new mill command |
| incident | FL sketch "todo claim"; stub Track | create todo, claim | **`create todo`** then **`claim`** / **`assign`** | reject bare `create` / `open` |
| SEV / severity | FL sketch "detail + priority in doing" | detail, note | **todo `detail` / `doing`** (`note` to amend) | no `sev` command |
| triage | FL collab | claim, note, assign | **`claim`/`assign`** + **`note`** priority/impact | - |
| mitigate | FL sketch "note + done when impact stopped"; stub Close | note, pass | **`note`** mitigation; **`pass`** when impact stopped | reject teaching `done` |
| resolution / incident closed | FL product; README product; stub Close | pass, note, send | **`note`** + stakeholder **`send`** + **`pass`** | - |
| escalate | FL sketch "mail eng/support"; README escalate = send | send | **`send`** eng/support (+ optional eng `create todo`) | never invent `escalate` command |
| incident commander (IC) | FL collab | claim, assign | **`claim`** / **`assign`** IC desk | role on card owner, not new command |
| stakeholder comms | FL collab; stub Done mailed | send, note | **`send`** + **`note`** on card | not status-page SoR clone |
| follow-the-sun | FL collab | unclaim, assign, send | **`unclaim`/`assign`** + **`send`** next shift | presence for who's HERE |
| postmortem | FL sketch "follow-on todo or parked plan" | create todo parked | **`create todo`** follow-on or `{status:"parked"}` | not day-one product; reject teaching `done` |
| deploy / rollback | FL product; stub Deploy | create todo, note, pass, send | **`create todo`/`claim`** -> **`note`** -> **`pass`**; **`send`** ops/eng as needed | forge/CI stay SoR |
| drain / deploy window | FL sketch "drain + mail ETA"; stub Drain | note, send, pass | office drain path + **`note`/`send` ETA**; **`pass`** when clear | reject inventing `drain` CLI |
| runbook | FL product | note, detail | **`note`/detail** pointer to SoR | method, not command |
| SLO / SLA / uptime KPI | FL product; README score row ops (SLO) | score | **`score`** (last vs target) | not a product |
| service health / health check failed | FL product; stub When | create todo, inbox, claim | **`inbox`/`create todo`** -> **`claim`** -> mitigate spine | - |
| drop the claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| exclusive runbook/config edit | eng hold pattern; TEMPLATE | hold / drop | **`hold` / `drop`** | rare; hold = lock resource, not unclaim |
| blocked (eng fix, access, change window) | README waiting_on | waiting_on + send | **`waiting_on` + `send`/`note`** | don't fake `pass` |
| park / defer (postmortem, non-urgent) | mill-desk | create todo parked | **`create todo` `{status:"parked"}`** | reject `open` / bare `create` |
| take / give incident | mill-desk; support assign | claim, assign | **`claim` / `assign`** | - |
| progress diary | mill-desk note; FL mitigate | note | **`note`** | note != mail |
| find ops mail / pages | mill-desk mail; stub | inbox | **`inbox`** | - |

**Stub lingo gaps this harvest fills:** Inputs, SEV->detail, escalate=`send`, postmortem=follow-on/parked, SLO=`score`, waiting_on, assign/unclaim, hold/drop nuance, follow-the-sun handoff, park, reject open/yield/bare create/teaching done.

---

## Handoffs

| To | When |
|---|---|
| **office-engineering** | Code fix / rollback change required (stub; eng Handoffs already list Ops for deploy/incident) |
| **office-qa** | Need remasure in prod-like / after deploy (stub; qa Handoffs list Ops for prod-only signal) |
| **office-support** | Customer / user-facing incident comms; ticket stays support SoR (stub; support escalate path can land on ops) |
| **Asker / stakeholder desks** | Status, ETA, resolved - `send` (not a status-page clone) |
| **Next on-call desk** | Follow-the-sun: `assign`/`unclaim` + `send` |

Pattern: README "Escalate always = mill send"; support "escalate = send + eng todo + waiting_on"; stub Eng/QA/Support. Ops does not steal eng claim - mail + optional eng todo.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- Silent prod change without a card when office requires it (stub).
- Infinite reconnect spam during drain (stub).
- Replace domain SoR: PagerDuty/Opsgenie, status page, CI/deploy logs, runbook wiki, forge - **link** in note/mail; don't clone.
- Invent mill commands for SRE slang (`page`, `escalate`, `drain`, `sev`, `mitigate`, `postmortem` as CLI).
- Teach `done` / `open` / `yield` / bare `create` (mill-desk alpha hard-cut).
- Confuse `drop` (hold release) with `unclaim`.
- Confuse mitigate-complete with mill `pass` without card close - `pass` closes the ops card after impact stopped + note/comms.
- Pretend mill *is* PagerDuty/Jira Ops/statuspage (FUNCTION-LINGO how-to-talk #4).
- Own eng ship or QA Pass/Fail - hand off.

---

## Done looks like - per product

**Uptime / incident closed**

1. Signal + impact scope were on the desk (or waiting_on mailed).
2. Owner claimed/assigned; mitigation/`note`d (runbook/rollback/drain steps).
3. Stakeholders/`send`ed as needed (ETA or resolved); eng/qa/support mailed when ball moves.
4. Ops card `pass`ed when stable **or** clean waiting_on (blocked on eng/human) **or** parked follow-on (postmortem) - never silent open forever.
5. Deploy mode: change live or rolled back; drain mode: ETA honored / window closed without reconnect spam.

---

## Scope note

- **In:** Incident track->mitigate->close; deploy/rollback coordination; intentional drain with ETA; health-fail recovery; SLO glance via `score`; on-call presence + mail wake.
- **Out:** Eng implement/merge, QA remasure verdict, support ticket DB, writing the blameless postmortem as primary product, owning PagerDuty/status page.
- **Day-one:** single product; deploy/drain/postmortem = **modes** or follow-ons, not second SKILL products.
- Adapter stays thin - pull mill-desk first; one card, then STOP.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog row Uptime / incident closed; score row ops (SLO); escalate = send; waiting_on; presence |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S Ops / SRE | **Required** product/collab words + mill sketch (on-call, page, incident, SEV, mitigate, escalate, postmortem, drain) |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-ops/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-engineering/SKILL.md` | Ops handoff for deploy/incident; hold pattern |
| `docs/skills/office-support/SKILL.md` | Escalate -> eng/ops; waiting_on; forge SoR |
| `docs/skills/office-qa/SKILL.md` + `RESEARCH.md` | Prod-only -> Ops; RESEARCH shape + TEMPLATE brief pattern |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; note!=mail; drop!=unclaim; create todo always includes todo; no open/yield/teaching done |
| `docs/protocol/commands.md` | Confirm wake/score/pass lifecycle; removed teaching CLI |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| Google SRE / incident response (IC, mitigate, severity) | IC = ownership (`claim`/`assign`); mitigate before perfect root-cause; severity in detail - aligns FL sketch |
| Atlassian / incident.io incident lifecycle | Declare -> triage -> mitigate -> resolve -> postmortem follow-on - card spine + parked postmortem todo |
| ITIL-ish service health / restore | Restore service (= uptime) is the product; process docs stay SoR |

### Guesses (flagged)

- Whether **deploy** should become a 2nd day-one Product subsection - **guess**; catalog names one compound product; stub folds three outcomes into Stable runtime.
- Office-specific **drain** command vs note+send only - **guess**; FL says drain + mail ETA, not a mill CLI `drain`.
- `hold` on runbook/config paths - **guess**; rare unless the office leases those res names.
- Teaching **wake** in Lingo table vs leave as mill-desk inbound only - prefer cite wake under page/alert; don't expand day-one teaching list.

---

## Open questions for human / gardener

1. Keep **one** compound product (Uptime / incident closed with deploy/drain modes), or split **Incident closed** vs **Deploy/drain window** into two Product subsections now?
2. Is office **drain** a named mill/office path agents must call, or day-one only `note`+`send` ETA + card `pass`?
3. May ops desk **`pass`** when mitigated but root-cause open (postmortem parked), or must waiting_on until eng closes fix?
4. Where does SEV live as SoR (detail text vs label vs external PD)? Affects whether gardener teaches `label-add`.
5. Should `score` (SLO/error budget) appear in day-one Lingo table as required, or optional "if office sets KPI"?
6. Follow-the-sun: prefer `assign` next desk vs `unclaim` + `send` - office policy?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Inputs section | Absent (has When triggers) | Add Inputs: signal, impact/SEV, owner, mitigation/runbook pointer, stakeholder dests, deploy id / drain ETA; When can stay thin or fold |
| Scope note | Absent | In/out; deploy/drain/postmortem = modes/follow-ons not 2nd product |
| Lingo -> mill table | "Verbs (mill)" need-oriented, incomplete | TEMPLATE-shaped Their word -> Mill; full FUNCTION-LINGO Ops/SRE harvest |
| SEV / escalate / postmortem / SLO / triage / IC | Missing or implicit | Map explicitly; escalate=`send`; postmortem=follow-on/parked; SLO=`score` |
| waiting_on / assign / unclaim / hold / park | Missing | Add; drop!=unclaim |
| score | Absent (presence mentioned) | Add optional/required per office SLO |
| Multi-product clarity | Single Stable runtime OK-ish | Align README noun **Uptime / incident closed**; list dropped in RESEARCH only |
| Done | healthy or drain ETA; pass; mailed | Add waiting_on/parked paths; mitigate-then-pass; no silent open |
| Must-not | Silent prod change; reconnect spam | Add: no invent commands; SoR outside mill; HINT bypass; drop!=unclaim; no teaching done/open/yield |
| Product noun | "Stable runtime..." | Align title/README: **Uptime / incident closed**; keep stable-runtime / three modes in body |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-ops/SKILL.md`. Pull mill-desk first. Do not invent commands.

```markdown
---
name: office-ops
description: >
  Use when this desk owns uptime, deploys, drains, or incidents on a mill
  office. Pull mill-desk first. Thin adapter - not a second mill. Product =
  Uptime / incident closed (stable runtime) - not a status-page essay.
metadata:
  short-description: "Ops: uptime / incident closed via mill"
---

# Office - Ops / SRE -> Uptime / incident closed

Pull **mill-desk** first. One card, then **STOP**.

## Product
**Uptime / incident closed** - runtime stable again: incident impact stopped and
closed, deploy/rollback finished clean, or intentional drain with clear ETA and
stakeholders informed.

Deploy, drain, and health recovery are **modes** of this product (same spine),
not second day-one products. Postmortem = follow-on or parked todo, not the
primary artifact.

## Inputs
On the desk **before** mitigate/deploy/drain (else `note` gap + `send` / `waiting_on`):
- **Signal** - page/alert/health fail / deploy or drain ask (`inbox` / wake / mail)
- **Impact scope** - service, SEV/priority, blast radius (todo `detail` / `doing`)
- **Owner** - on-call HERE; `claim` / `assign`
- **Mitigation path** - runbook/rollback/drain steps (pointer in detail/`note`; SoR stays outside)
- When deploy: change/artifact id (link forge/CI). When drain: ETA for `note`/`send`.

Not inputs: vague "keep the lights on," silent prod change with no card when
office requires one, reconnect spam as a plan.

## Lingo -> mill
| Their word | Mill |
|---|---|
| on-call / HERE | presence (who's on the floor) |
| page / alert | wake / `send` + `inbox` |
| incident / health fail | `create todo` then `claim` / `assign` |
| SEV / severity / triage | todo `detail` / `doing` + `note` |
| IC / take ownership | `claim` / `assign` |
| drop the claim | `unclaim` |
| mitigate / progress | `note` (diary; not mail) |
| stakeholder comms | `send` (+ `note` on card) |
| escalate | `send` eng/support (optional eng `create todo`) |
| follow-the-sun | `assign` / `unclaim` + `send` next desk |
| deploy / rollback | same spine: `claim` -> `note` -> `pass`; forge/CI SoR |
| drain / deploy window | `note`/`send` ETA + office drain path; `pass` when clear |
| blocked (eng/human/window) | waiting_on + `send` / `note` |
| postmortem | follow-on `create todo` or `{status:"parked"}` |
| SLO / uptime KPI | `score` (last vs target) |
| exclusive config/runbook file | `hold` / `drop` (rare) |
| close incident / stable | `pass` after mitigate + note/comms |
| park / defer | `create todo` `{status:"parked"}` |

## Handoffs
| To | When |
|---|---|
| Engineering | Code fix / rollback change required |
| QA | Remasure in prod-like / after deploy |
| Support | Customer-facing incident comms; ticket SoR stays support |
| Next on-call | Follow-the-sun coverage handoff |

## Must-not
- Bypass mill-desk HINT routing.
- Silent prod change without a card when office requires it; reconnect spam during drain.
- Replace PagerDuty/status page/CI/runbook SoR - link paths.
- Invent mill commands for SRE slang (`page`, `escalate`, `drain`, `sev` as CLI).
- Teach `open` / `yield` / bare `create` / `done`.
- Confuse `drop` (hold) with `unclaim`.
- Own eng ship or QA Pass/Fail.

## Done looks like
- Service healthy or intentional drain ETA clear; stakeholders mailed; ops card
  `pass`ed or clean waiting_on or parked follow-on (postmortem).
```

---

## 2026-09-21 - Tier B/C hypo ladder (Scout)

Asker/Gardener GO: append cold-run ladder only (no SKILL.md patch this wake).

| Tier | Ids | Prove |
|---|---|---|
| A (existing) | H01-H10 | Single-desk ops spine; Inputs-gap mix |
| B Handoff | H11-H15 | Asker+Producer+Handoff; `assign`/`send` peer; src!=dst; ~half gap; no invent desks |
| C Watcher | H16-H20 | `mill add <type>:<id> [--hint]`; Watcher actor on >=2; >=1 gap (dest/card id); waiting_on speech-only |

Day-one add: `watcher` per `docs/protocol/commands.md`. Reject invent escalate/sev/deploy/drain/oncall CLI. Desk via `--owner`; no `AGENT_COORD_OWNER` teaching.

