# RESEARCH - office-people

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward, dry, cite-first. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-people \| Hired / onboarded \| product** |
| Folder | `docs/skills/office-people/` exists |
| Stub | Thin `SKILL.md` present (Product = Filled req or completed onboarding checklist; Lingo + Must-not + Done; **no Inputs / Handoffs / Scope**) |
| FUNCTION-LINGO.md | Present - S **People / recruiting** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked; reject `open` / `yield` / bare `create` / teaching `done` |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-sales (close-won -> CS onboarding mail/todo); office-ops / office-support RESEARCH shape; README human_required cluster: people (offer) |

**Function:** office-people  
**README product noun:** Hired / onboarded  
**ATS / HRIS:** stay systems of record (candidate PII, stages, offer letters, e-sign) - mill coordinates collab only.  
**human_required:** offer (README + stub + FL sketch).

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Hired** (filled req / offer accepted) | **KEEP** | Half of catalog product. Stub: filled req; FL: offer -> human_required; req -> parent todo. Outcome = person hired, req closed. |
| **Onboarded** (completed onboarding checklist) | **KEEP** | Other half of catalog. Stub: completed onboarding checklist; FL: onboarding -> checklist todos; claim per owner. Distinct artifact after hire. |
| Requisition / req as standalone product | **DROP** | FL sketch: plan or parent todo - **structure**, not the shippable people artifact. Lives under Hired as parent card. |
| Interview loop as product | **DROP** | FL sketch: child todos per interviewer - collab structure for Hired, not a 2nd SKILL product. |
| Interview notes as product | **DROP** | FL product *word*; fulfillment = `replace-body` / mail debrief evidence on loop cards - not mill `score` KPI and not a day-one product noun. |
| Candidate pipeline / ATS board as product | **DROP** | ATS is SoR (README pattern; stub "not an ATS"). Mill links ids; does not clone stages/PII. |
| Offer letter / packet as mill product | **DROP** | Offer = **human_required gate** (FL + README); document/e-sign lives in ATS/HRIS. Mill records gate + outcome, not the letter SoR. |
| Debrief / panel as product | **DROP** | FL sketch: mail thread / replace-body - collab move on Hired spine. |
| Reject / advance as product | **DROP** | Stub + FL collab: `replace-body` + next `assign` - stage motion, not artifact. |
| Time-to-hire / recruiting KPI as product | **DROP** | Optional `score` if office sets KPI; not a product. README score row clusters do not name people day-one. |

**Kept products (day-one): 2 - Hired; Onboarded** (shared lingo spine; sequential but separate Inputs/Done).

---

## Product (kept) - Hired

**Artifact (one sentence):** A requisition is **filled** - candidate advanced through the interview loop, offer cleared via **human_required**, outcome recorded, hiring owner and ATS id linked - not an ATS clone.

**Not the product:** ATS stage board, offer PDF/e-sign SoR, eng interview implementation work, legal clearance of employment docs as primary (hand off), finished onboarding checklist (separate product).

### Inputs (Hired)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Req identity (role, ATS/req id, hiring manager) | **Yes** | parent `create todo` + `detail` (link ATS - don't clone PII dump) |
| Candidate pointer (ATS id / initials per policy) | **Yes** | detail/`replace-body`; minimize PII (stub Must-not) |
| Loop plan (interviewers / panel slots) | Strong | child `create todo` per interviewer (FL); `assign` / `claim` |
| Debrief / advance-reject decision | Before offer | `replace-body` + `send` HM/recruiter; next `assign` |
| Offer packet ready + approver | Before offer | human_required gate; `send` approver; ATS/HRIS for letter |
| Outcome (accepted / declined / withdrawn) | On close | `replace-body` + parent `pass` when filled; or parked/waiting_on |

Not inputs: "fill all reqs," paste full SSN/resume into mill, skip human_required when office requires it, invent ATS inside mill.

### Done looks like (Hired)

- Interview loop children `pass`ed or cleanly dropped/`unclaim`ed with `replace-body`; debrief written on the card (`replace-body`) / mailed.
- Offer: human_required satisfied; outcome written on the card (`replace-body`); ATS updated **outside** mill.
- Parent req card `pass`ed when filled **or** clean `waiting_on` (approver / candidate / legal) - don't fake `pass`.
- On accept: optional handoff -> Onboarded checklist `create todo`s + `assign` owners / `send` people desk.

---

## Product (kept) - Onboarded

**Artifact (one sentence):** New hire **onboarding checklist** complete - each ownership slice claimed and `pass`ed (access, equipment, training, buddy, paperwork pointers) - recorded on mill cards, not an HRIS clone.

**Not the product:** HRIS/ATS onboarding workflow SoR, IT provisioning tool ownership, the hire decision itself (Hired product).

### Inputs (Onboarded)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Hire confirmed (req filled / start date) | **Yes** | link Hired card / ATS id in detail; else `waiting_on` + `send` |
| Checklist items + owners (IT, facilities, manager, people) | **Yes** | child `create todo` per item; `assign` / `claim` per owner (FL) |
| Policy constraints (what may live in mill vs HRIS) | Strong | detail; PII minimization |
| Blockers (equipment, access, paperwork) | When blocked | waiting_on + `send` specialized desk |

Not inputs: "make them productive," dump medical/payroll PII into mill, close parent while children open without policy.

### Done looks like (Onboarded)

- All checklist children `pass`ed (stub: all children passed) **or** explicit parked leftovers with owner.
- Parent onboarding card `pass`ed; stakeholders `send`ed as needed (manager / IT).
- Else clean **waiting_on** - don't fake `pass`.

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `replace-body`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk). Tree `attach` when said - not day-one teaching.  
**Do not confuse** interview "score row" with mill `score` (KPI last vs target).

Sources for rows: **FUNCTION-LINGO.md S People / recruiting** (required - every FL sketch row applied), mill-desk day-one, stub, README (human_required: people offer; escalate = send; waiting_on), sibling sales close-won -> onboarding mail/todo.

Shared spine (one table for the function):

| Their word | Source | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| req / requisition | FL sketch "plan or parent todo"; stub | create todo, detail | **`create todo`** parent + `detail` (ATS/req link) | reject bare `create`; plan row = parent todo day-one (no invent `plan` CLI) |
| candidate | FL product | detail, replace-body | **`detail` / `replace-body`** pointer (ATS id); minimize PII | not a mill command; ATS SoR |
| interview loop | FL sketch "child todos per interviewer"; stub | create todo, assign, claim | child **`create todo`** per interviewer + **`assign`/`claim`** | reject inventing `loop` CLI |
| panel | FL collab; stub panel/debrief | send, replace-body, assign | **`send`** + panelist **`assign`** | - |
| debrief | FL sketch "mail thread / replace-body"; stub | send, replace-body | **`send`** + **`replace-body`** on card | replace-body != mail |
| interview notes | FL product word | replace-body, send | **`replace-body`** ratings/summary (+ `send` HM) | **!=** mill `score`; no invent `score row` CLI |
| hiring manager | FL collab | assign, send, claim | **`assign`/`send`** HM desk; HM may **`claim`** | role on owner, not new command |
| recruiter | FL collab | claim, assign, send | **`claim`/`assign`** recruiter; **`send`** for wakes | - |
| advance | FL collab reject/advance; stub | replace-body, assign | **`replace-body`** decision + **`assign`** next step | - |
| reject (candidate) | FL collab; stub | replace-body, pass, send | **`replace-body`** reason; close loop children; parent may stay open or park | reject teaching `done` |
| offer | FL sketch "human_required gate"; stub; README | human_required, send, replace-body, pass | **human_required** + **`send`** approver + **`replace-body`** outcome; then parent path to **`pass`** | never invent `offer` CLI; letter/e-sign = ATS/HRIS |
| onboarding | FL sketch "checklist todos; claim per owner"; stub | create todo, claim, assign | checklist **`create todo`**s + **`claim`/`assign`** per owner | - |
| done onboarding / checklist complete | stub "all children passed" | pass | children + parent **`pass`** | reject teaching `done` / status speech as command |
| filled req / hired | README product; stub Done | pass, replace-body, send | **`replace-body`** outcome + **`pass`** parent; **`send`** onboarding kickoff | reject teaching `done` |
| drop the claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| exclusive offer-doc edit | TEMPLATE hold; legal-ish rare | hold, drop | **`hold`/`drop`** if the office leases a res for the packet | rare; README hold clusters eng/legal - people only if leased |
| blocked (approver, candidate, IT, legal) | README waiting_on | waiting_on, send, replace-body | **waiting_on** + **`send`** | don't fake `pass` |
| hiring KPI / time-to-hire | optional; not README people cluster | score | optional **`score`** if office sets target | interview notes != this |
| take / give loop card | mill-desk | claim, assign | **`claim` / `assign`** | - |
| progress diary | mill-desk replace-body | replace-body | **`replace-body`** | replace-body != mail |
| find people mail | mill-desk mail | inbox | **`inbox`** | - |
| park / defer req or leftover | mill-desk | create todo parked | **`create todo` `{status:"parked"}`** | reject `open` / bare `create` |
| escalate (to legal/finance/IT) | README escalate = send | send | **`send`** specialized desk (+ optional their `create todo`) | never invent `escalate` command |
| close-won -> CS onboarding (inbound) | sales FL/stub sibling | send, create todo | people may **`inbox`** / receive sales **`send`**; customer onboarding != employee Onboarded - route per office | don't smash CS onboarding into people product without policy |

**Stub lingo gaps this harvest fills:** Inputs, Handoffs, Scope, FL candidate/panel/HM/recruiter/interview notes!=score, waiting_on, assign/unclaim, hold/drop nuance, park, human_required emphasis, ATS SoR outside, reject open/yield/bare create/teaching done, split Hired vs Onboarded Done paths.

---

## Handoffs

| To | When |
|---|---|
| **Hiring manager desk** | Debrief, advance/reject, offer approve (human_required), start-date confirm - `send` / `assign` |
| **Recruiter / people desk** | Loop ownership, offer packet coordination, onboarding kickoff |
| **office-legal** | Employment agreement / compliance hold - `send` + waiting_on (legal owns clear) |
| **office-finance** | Comp band / offer cost approve if office requires - `send` + human_required chain |
| **IT / ops / facilities desks** | Access, laptop, badge onboarding checklist items - `assign` child todos + `send` |
| **office-engineering / function desk** | Interviewer ownership for role-specific loop children; buddy assignment |
| **Asker / stakeholder** | Req status, offer outcome, onboard complete - `send` |
| **Sales -> CS path (adjacent)** | Customer onboarding from close-won is **sales/CS**, not this skill, unless office explicitly routes new-hire-from-acquisition here |

Pattern: README "Escalate always = mill send"; human_required clusters people (offer). People does not replace ATS - mail + link.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- Replace domain SoR: **ATS / HRIS** (Greenhouse, Lever, Workday, etc.), e-sign, background-check vendor - **link** in card text/mail; don't clone stages, full resumes, or payroll.
- Store sensitive candidate PII in mill beyond what policy allows (stub).
- Skip **human_required** on offer if office requires it (stub + README).
- Invent mill commands for recruiting slang (`offer`, `advance`, `reject`, `debrief`, `req`, `loop` as CLI).
- Teach `done` / `open` / `yield` / bare `create` (mill-desk alpha hard-cut).
- Confuse `drop` (hold release) with `unclaim`.
- Confuse interview **score row** with mill **`score`** (KPI).
- Pretend mill *is* the ATS (FUNCTION-LINGO how-to-talk #4).
- Own legal clearance or finance approval - hand off.
- Fake `pass` on parent while offer pending human_required or checklist children open (unless office policy says otherwise).

---

## Done looks like - per product

**Hired**

1. Req + candidate pointer on desk (ATS link; PII minimized).
2. Loop children owned (`claim`/`assign`); debriefs written on the card (`replace-body`) or `send`ed; advance/reject recorded.
3. Offer: human_required cleared; outcome written on the card (`replace-body`); ATS updated outside mill.
4. Parent req `pass`ed when filled **or** clean waiting_on **or** parked - never silent open forever.
5. On accept: onboarding checklist todos created/assigned and/or people `send`ed.

**Onboarded**

1. Hire confirmed + checklist items with owners on desk.
2. Each child `claim`ed/`assign`ed; progress written on the card (`replace-body`); blockers waiting_on + mailed.
3. All required children `pass`ed (or explicit parked leftovers); parent `pass`ed; manager/IT mailed as needed.

---

## Scope note

- **In:** Req parent card; interview loop children; debrief/advance/reject notes+mail; offer human_required gate + outcome; onboarding checklist todos with per-owner claim; waiting_on for approver/candidate/IT/legal; optional hiring KPI `score` if office sets it.
- **Out:** ATS/HRIS as SoR, offer letter authorship/e-sign, background checks, payroll/benefits admin, customer CS onboarding from sales close-won (unless office routes it), inventing recruiting CLI commands.
- **Day-one:** **two** products (Hired; Onboarded); shared one lingo table; req/loop/debrief = structure/collab under Hired, not extra products.
- Adapter stays thin - pull mill-desk first; one card, then STOP.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog row Hired / onboarded; human_required people (offer); escalate = send; waiting_on; hold rare outside eng/legal |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S People / recruiting | **Required** product/collab words + mill sketch (req, interview loop, debrief, offer, onboarding) - every sketch row mapped |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-people/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-sales/SKILL.md` + sales RESEARCH | Close-won -> CS onboarding mail/todo adjacency; dual-product RESEARCH shape |
| `docs/skills/office-ops/RESEARCH.md` (backup mill-docs) | RESEARCH + TEMPLATE brief section pattern |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; replace-body!=mail; drop!=unclaim; create todo always includes todo; no open/yield/teaching done |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| Common ATS practice (req -> pipeline -> interview -> offer -> hire) | Stages stay in ATS; mill mirrors collab ownership + durable handoffs |
| Interview loop / panel / debrief norms | One owner per interview card; debrief = shared card text/mail before offer |
| Offer approval chains | Matches README human_required cluster for people (offer) |
| Onboarding checklist RACI | FL: claim per owner - IT/facilities/manager slices as child todos |

### Guesses (flagged)

- Whether **Hired** and **Onboarded** stay two Product subsections vs one compound "Hired / onboarded" like sales dual-outcome - **guess**; scout allows >1 product with separate Inputs/Done; catalog compounds the noun.
- Parent/child via day-one `create todo` only vs teaching tree `attach` - prefer create + detail link day-one; attach when said.
- `hold` on the offer-packet res - **guess**; rare unless the office leases those resources.
- Whether reject closes parent req or only loop children - office policy (**open Q**).
- Sales CS "onboarding" vs people employee onboarding - treat as different nouns unless office unifies.

---

## Open questions for human / gardener

1. Keep **two** Product subsections (Hired; Onboarded) or one compound **Hired / onboarded** with dual Done paths (sales-style)?
2. On candidate **reject**, does parent req stay open for next candidate, `pass` as unfilled-closed, or `{status:"parked"}`?
3. Is **human_required** always mandatory for offer on every office, or only when policy/label says so (stub: "if office requires it")?
4. Must onboarding parent wait for **all** children `pass`, or may parent `pass` with explicit parked leftovers?
5. Teach tree **`attach`** for req->loop children in Lingo, or day-one only parallel todos + detail links?
6. May mill store interview **score row** ratings in `replace-body`, or must ratings stay ATS-only with mill holding "debrief complete" only?
7. Optional **`score`** (time-to-hire) in day-one Lingo, or omit until office sets KPI?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Inputs section | Absent | Add Inputs per product (Hired + Onboarded) |
| Handoffs section | Absent | Add HM, recruiter, legal, finance, IT/ops, eng interviewers; sales CS adjacency note |
| Scope note | Absent | In/out; two products; ATS outside; day-one thin adapter |
| Product noun | "Filled req or completed onboarding checklist" | Align README **Hired / onboarded**; keep two subsections or dual Done |
| Lingo -> mill table | Partial FL; missing candidate, HM, recruiter, score row!=score, waiting_on, unclaim, hold, park, inbox, escalate | Full FUNCTION-LINGO People harvest + day-one commands only |
| waiting_on / assign / unclaim / hold / park / inbox / score | Missing or implicit | Add; drop!=unclaim; interview notes != mill score |
| human_required | Offer row only | Emphasize in Must-not + Done; wire `send` approver |
| ATS SoR | Implied ("not an ATS") | Explicit Must-not: don't clone ATS/HRIS/e-sign |
| Done | Offer outcome; onboarding owners claimed; req closed | Split Hired vs Onboarded; waiting_on/parked paths; reject teaching `done` |
| Must-not | PII; skip human_required | Add: HINT bypass; invent commands; open/yield/bare create/teaching done; drop!=unclaim; score row!=score; no legal/finance own |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-people/SKILL.md`. Pull mill-desk first. Do not invent commands.

```markdown
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

## Product
**Hired / onboarded** - two day-one artifacts, one spine:

1. **Hired** - requisition filled: interview loop complete, offer cleared via
   **human_required**, outcome recorded (ATS updated outside mill).
2. **Onboarded** - onboarding checklist complete: each owner slice claimed and
   `pass`ed (access, equipment, training, paperwork pointers).

Req / interview loop / debrief are **structure and collab** under Hired, not
extra products. Interview "score row" evidence = `send` - not mill `score`.

## Inputs
On the desk **before** advance/offer/onboard (else `replace-body` gap + `send` / `waiting_on`):

**Hired**
- **Req identity** - role, ATS/req id, hiring manager (`create todo` parent + `detail` link)
- **Candidate pointer** - ATS id / policy-safe label (minimize PII)
- **Loop plan** - interviewers as child `create todo`s; `assign` / `claim`
- Before offer: debrief decision + offer approver path (**human_required**)

**Onboarded**
- **Hire confirmed** - start date / filled-req link (else waiting_on)
- **Checklist + owners** - child `create todo` per item; `assign` / `claim` per owner

Not inputs: paste full resumes/SSN into mill, skip human_required when required,
replace ATS/HRIS, invent recruiting CLI commands.

## Lingo -> mill
| Their word | Mill |
|---|---|
| req / requisition | parent `create todo` + `detail` (ATS link) |
| candidate | `detail` / `replace-body` pointer (minimize PII; ATS SoR) |
| interview loop | child `create todo` per interviewer + `assign` / `claim` |
| panel | `assign` panelists + `send` |
| debrief | `send` + `replace-body` (replace-body != mail) |
| interview notes | `replace-body` (+ `send` HM) - **not** mill `score` |
| hiring manager / recruiter | `assign` / `claim` / `send` |
| advance / reject | `replace-body` decision + next `assign` (or park) |
| drop the claim | `unclaim` |
| offer | **human_required** + `send` approver + `replace-body` outcome |
| onboarding | checklist `create todo`s + `claim` / `assign` per owner |
| blocked (approver / candidate / IT / legal) | waiting_on + `send` |
| escalate | `send` legal/finance/IT (optional their `create todo`) |
| exclusive offer-doc file | `hold` / `drop` (rare; if the office leases a res name) |
| hiring KPI (optional) | `score` last vs target - != interview notes |
| filled req / hired | `replace-body` outcome + parent `pass`; `send` onboarding kickoff |
| checklist complete / onboarded | children + parent `pass` |
| park / defer | `create todo` `{status:"parked"}` |
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
- Skip human_required on offer if office requires it.
- Invent mill commands for recruiting slang (`offer`, `advance`, `loop`, `debrief` as CLI).
- Teach `open` / `yield` / bare `create` / `done`.
- Confuse `drop` (hold) with `unclaim`; confuse interview notes with mill `score`.
- Own legal clearance or finance approval.

## Done looks like
- **Hired:** loop noted; offer human_required cleared; outcome recorded; ATS
  updated outside mill; req card `pass`ed or clean waiting_on/parked; onboarding
  kickoff mailed/todos assigned on accept.
- **Onboarded:** checklist children `pass`ed (or explicit parked leftovers);
  parent `pass`ed; manager/IT mailed as needed.
```
