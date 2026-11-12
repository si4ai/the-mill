# RESEARCH - office-support

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-support \| Resolved ticket \| product** |
| Folder | `docs/skills/office-support/` exists |
| Stub | `SKILL.md` present - Product + forge report table + Lingo->mill + Dogfood + Must-not + Done; **no Inputs / Scope / Handoffs table / score / waiting_on / assign-unclaim / hold nuance**; Product noun drifts ("Resolved user issue" vs README "Resolved ticket") |
| FUNCTION-LINGO.md | Present - S **Support / service desk** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-qa (+ RESEARCH.md), office-ops, office-engineering, office-research read |

**Function:** office-support  
**README product noun:** Resolved ticket  
**Forge Issues:** stay system of record for the public bug; mill coordinates internal collab (stub + README layer rule).

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Resolved ticket** | **KEEP** | Catalog product. FUNCTION-LINGO: ticket / resolution / close. Stub: user unblocked **or** eng/ops owns fix. Align noun to README ("Resolved ticket"); keep "unblocked human / workaround / owned-elsewhere" in body. |
| Incident (user-impact) as separate product | **DROP** (day-one) | ITIL incident vs service request are **intake modes** of the same ticket spine (FUNCTION-LINGO lists both under product words). Detail/labels distinguish; not a 2nd SKILL product. Major / SEV that needs runtime ownership -> **handoff office-ops**, not a support product fork. |
| Service request / how-to fulfill as separate product | **DROP** (day-one) | Same ticket spine; fulfillment = answer/`replace-body`/pass. Catalogue workflows stay SoR (Zendesk/ServiceNow/...). |
| Workaround as product | **DROP** | FUNCTION-LINGO: workaround -> **replace-body** on card. Interim state, not the shippable artifact. |
| Backlog / queue health as product | **DROP** | Queue = open todos for support desk (FL sketch). Motion/coverage, not product. Presence/inbox fulfill "who's here." |
| CSAT / survey score as product | **DROP** | FUNCTION-LINGO: CSAT optional. Maps to **score row** if office sets it - KPI, not product. |
| Knowledge article / KB publish | **DROP** (day-one) | May be a card-text path or marketing/docs SoR later; not catalog product. Revisit if office ships KB as support artifact. |
| Forge Issue / bug database as mill product | **DROP** | Stub + README: forge Issues stay SoR. Mill links URL in detail; does not clone the bug DB. |

**Kept products (day-one): 1 - Resolved ticket.**

---

## Product (kept) - Resolved ticket

**Artifact (one sentence):** A support card whose user/reporter is unblocked (answer or workaround) **or** whose remaining fix is visibly owned elsewhere (eng/ops todo id + forge Issue updated) - then support card `pass`ed.

**Not the product:** full Zendesk/Jira/GitLab Issue DB, ops incident-closed, eng merge/ship, QA Pass/Fail evidence, CSAT dashboard as the shippable thing.

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Ticket / report identity (what broke or what was asked) | **Yes** | `create todo` need + `detail`; if forge-borne -> **forge Issue URL in detail** (stub Must-not) |
| Reporter / user channel (who to unblock; reply path) | **Yes** | detail; later `send` / human_required Wall if human must click |
| Priority signal (impactxurgency) when known | Strong | detail (not a mill priority command); optional score row watch |
| Classification: incident vs service request vs bug | Strong | detail / label; bug -> `label-add ... bug` + forge link |
| Known workaround / answer crumbs | Optional | `replace-body` as found |
| Eng/ops ownership crumbs when escalating | When escalate | eng/ops todo id in `replace-body` + `waiting_on`; forge stays SoR |

Not inputs: "make customers happier," silent close with no ball location, inventing a second bug DB inside mill.

### Done looks like (this product)

- User unblocked (answer/`replace-body` workaround) **or** visible eng/ops todo owns the fix (id in card text) + forge Issue updated when report came from forge.
- Support todo **`pass`**ed **or** clean **`waiting_on`** (reporter info / eng fix / human) **or** parked if deferred - never silent open forever.
- Do **not** `pass` without saying where the ball is (stub Must-not).

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `replace-body`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`, mail as needed.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk). `unpark` exists on mill-desk but is not day-one teach unless human says it.

Sources for rows: **FUNCTION-LINGO.md S Support / service desk** (required), mill-desk day-one, stub, README general mapping (score row cluster includes support SLA; escalate = send; hold rare for support), siblings (qa/ops/eng handoffs).

Shared spine (one table for the function):

| Their word | Source | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| ticket / service record | FL Support product; mill sketch "todo" | create todo, open | **`create todo`** (+ forge URL in detail when forge-borne) | reject `open` / bare `create` |
| new bug / forge Issue report | stub Lingo; mill-desk bug idiom | create todo + label | **`create todo`** + `label-add ... bug`; link Issue in detail | forge Issue stays SoR - don't clone |
| queue | FL sketch "open todos for support desk" | todo list, inbox | **`todo`** (list) / **`inbox`** for mail wake | queue != new command |
| assign / own / triage | FL sketch "claim"; stub triage/own | claim, assign | **`claim`** / **`assign`** | - |
| drop the claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| priority (impactxurgency) | FL collab | detail | **todo `detail`** (text); optional later score watch | no `priority` mill command |
| functional / hierarchical escalation; L1/L2/L3 | FL collab; README "Escalate = send" | send, assign | **`send`** to eng/ops (+ optional eng `create todo` / `assign`); support **`waiting_on`** | reject inventing `escalate` CLI |
| escalate to eng (stub) | stub; qa RESEARCH pattern | send + eng todo | **`send`** + eng **`create todo`/`assign`**; support waiting_on | same as FL escalate |
| need more info | stub | send, waiting_on | **`send`** reporter desk / human_required; **`waiting_on`** | don't fake pass |
| workaround | FL sketch "replace-body on card"; ITIL workaround | replace-body | **`replace-body`** | not a product; not `pass` alone unless user unblocked |
| resolve / close | FL sketch "done when user unblocked **or** bug owned elsewhere"; stub resolved/closed | pass | **`pass`** support card when Done gate met | reject teaching `done`; mill `pass` advances card lifecycle |
| duplicate | stub | replace-body, pass | **`replace-body`** canonical id/URL + **`pass`** | - |
| SLA | FL sketch "score row last vs target"; README score row cluster **support (SLA)** | score | **`score`** (last vs target) | teach - support is in score row cluster |
| CSAT | FL product optional | score | **`score`** only if office sets CSAT KPI | optional; not day-one required |
| backlog | FL product | create todo parked / open list | open todos / **`create todo` `{status:"parked"}`** for defer | not a product |
| incident vs service request | FL product words; ITIL | detail | **detail / label** on same ticket spine | not 2nd product; major SEV -> handoff ops |
| coverage / who's HERE | README presence; ops pattern | presence | presence / agents (glance); mail wake | not inventing coverage command |
| progress / diary / forge comment crumb | mill-desk replace-body | todo --eta/--started/--progress | **`todo <roster> <need> --eta E`** / `--started` / `--progress 9/12` | replace-body != mail; forge comment stays on forge |
| find work / mail wake | mill-desk | inbox | **`inbox`** | - |
| blocked (reporter / eng / vendor) | README waiting_on | waiting_on + send | **`waiting_on` + `send`** | don't fake resolve |
| exclusive shared file (rare) | README "hold rare - don't teach in support unless needed"; TEMPLATE | hold / drop | **`hold` / `drop`** **omit from day-one teach** unless office leases a shared resource | hold != unclaim |
| park / defer ticket | mill-desk | create todo parked | **`create todo` `{status:"parked"}`** | reject `open` |

**Stub lingo gaps this harvest fills:** Inputs, Scope, Handoffs table, waiting_on, assign/unclaim, score (SLA), park, incident vs request as modes, hold rarity, README noun **Resolved ticket**, explicit reject list, FL cites on every row.

---

## Handoffs

| To | When |
|---|---|
| **office-engineering** | Bug/fix needs code; escalate = `send` + eng todo / assign; support waiting_on (stub Dogfood; eng Handoffs already list Support for user-facing regression) |
| **office-ops** | Runtime / prod outage / SEV needs incident ownership; customer-impact but ops owns mitigate (ops Handoffs list Support for customer comms - reverse path) |
| **office-qa** | Need remasure after fix before telling user "fixed"; user-facing regression evidence (qa RESEARCH <-> Support) |
| **Reporter / asker desk / human** | Need more info; workaround delivered; resolve confirmation - `send` / human_required |
| **Auditor** | Rare - policy/spec gap blocked triage (mirror qa/research) |

Pattern borrow: stub Dogfood (Issue -> mill todo -> eng mail + waiting_on -> confirm -> pass -> forge close); README escalate = mill `send`; ops<->support customer-comms mirror; qa Fail ownership may land as support-visible forge link. Escalate always = mill `send`, not a new command.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- Replace domain SoR: Zendesk / ServiceNow / Jira Service Management / **GitLab|GitHub Issues** - **link** in detail; don't duplicate the bug/ticket database inside mill (stub + FL how-to-talk #4).
- Close / `pass` support todo without saying where the ball is (eng/ops todo id **or** answer/workaround) - stub.
- Skip forge link in detail when the report came from GitLab/GitHub - stub.
- Invent mill commands for ITIL/industry slang (`escalate`, `resolve`, `triage`, `priority` as CLI).
- Teach `open` / `yield` / bare `create` / teaching `done`.
- Confuse `drop` (hold release) with `unclaim`.
- Confuse replace-body (card text) with send (mail).
- Pretend mill *is* the service desk product (Zendesk/Jira/...).
- Teach `hold` day-one unless office actually leases shared resources (README: hold rare for support).

---

## Done looks like - per product

**Resolved ticket**

1. Ticket identity + reporter path were on the desk (forge URL when forge-borne) - or waiting_on mailed.
2. User unblocked (answer or workaround written on the card (`replace-body`)) **or** eng/ops visibly owns remaining fix (todo id in card text) and forge Issue updated when applicable.
3. Support card `pass`ed **or** clean waiting_on **or** parked - never silent open forever.
4. SLA/CSAT `score` updated only if office configured those score rows.

---

## Scope note

- **In:** Resolve user/reporter tickets on a mill office; triage/claim; workaround notes; escalate via send to eng/ops; SLA score row; forge-linked bug coordination; confirm unblock then `pass`.
- **Out:** Owning the forge/ITSM bug database; eng ship; ops incident-closed as support's product; QA Pass/Fail ownership; inventing L2/L3 mill commands; teaching hold day-one.
- **Day-one:** single product **Resolved ticket**; incident vs service request = **modes** (detail/label), not 2nd products; major SEV -> handoff ops.
- Adapter stays thin - pull mill-desk first; one card, then STOP.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog **Resolved ticket**; escalate = send; score row cluster includes support (SLA); hold rare for support; waiting_on pattern; presence/coverage |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S Support / service desk | **Required** product/collab words + mill sketch (ticket->todo, queue, claim, escalate->send, workaround->replace-body, resolve/close, SLA->score row) |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-support/SKILL.md` | Stub gap-fill baseline (forge table, Dogfood, Must-not) |
| `docs/skills/office-qa/SKILL.md` + `RESEARCH.md` | RESEARCH shape; Support handoff mirror; forge SoR; waiting_on / pass-sense patterns |
| `docs/skills/office-ops/SKILL.md` | Incident vs support boundary; Support handoff for customer comms |
| `docs/skills/office-engineering/SKILL.md` | Bug label; Support handoff for user-facing regression; hold teaching contrast |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; replace-body!=mail; drop!=unclaim; create todo always includes todo; no open/yield/teaching done |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| ITIL 4 glossary - incident | Unplanned interruption / quality reduction -> ticket **mode** in detail; restore user productivity; mill `create todo` + claim ([ITIL 4 Glossary PDF](https://www.itconcepts.ch/wp-content/uploads/itil4-foundation-glossary-january-2019.pdf)) |
| ITIL 4 - service request | Pre-defined normal service action -> same ticket spine; fulfill via answer/`replace-body`/`pass`, SoR catalogue outside mill |
| ITIL 4 - workaround | Reduces impact when full resolution not yet available -> **`replace-body`** on card (aligns FL) |
| ITIL 4 - escalation | Share awareness or transfer ownership -> mill **`send`** (+ assign/eng todo); not a new command |
| ITIL 4 - SLA | Documented service-level targets -> mill **`score`** last vs target (README support cluster) |
| ITIL 4 - resolution / service desk | Solve incident/problem; service desk captures demand - mill coordinates collab; ITSM/forge remain SoR for the record |
| Functional vs hierarchical escalation (common ITIL practice) | L1->L2 skill handoff vs management notify -> both = **`send`** to dest desk/role; support may `waiting_on` |

### Guesses (flagged)

- Standing **KB article** as 2nd product - **guess**; not in README/FL product list.
- Teaching **`hold`** for support attachments - **guess against**; README says hold rare for support - omit day-one.
- CSAT on day-one scoreboard - **guess**; FL marks CSAT optional; SLA `score` is the catalog-aligned teach.
- Auto-close forge Issue from mill `pass` - **guess / must-not adjacent**; stub Dogfood: human/agent updates forge separately; mill does not replace forge close.

---

## Open questions for human / gardener

1. Confirm product noun: README **Resolved ticket** vs stub **Resolved user issue** - research keeps **Resolved ticket** + unblocked-or-owned-elsewhere body. OK?
2. Keep stub's forge (GitLab/GitHub) report table + Dogfood loop in SKILL, or fold to a short "Inputs / When forge-borne" bullet?
3. Should **incident vs service request** appear only as detail guidance, or get explicit Lingo rows (research: modes, one product)?
4. Day-one **`score`**: SLA only, or SLA + optional CSAT line?
5. May support **`pass`** when eng owns fix **before** user confirms, or require user-confirm / forge-close crumb first? (FL: unblocked **or** bug owned elsewhere - confirm office policy.)
6. Teach **`hold`/`drop`** at all in office-support, or omit entirely per README rarity?
7. L2/L3: always eng/ops desks via `send`, or does this office have distinct support-L2 mill desks?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Product noun | "Resolved user issue" | Align to README **Resolved ticket**; keep unblock/owned-elsewhere in body |
| Inputs section | Absent (has forge how-people-report + Dogfood) | Add Inputs: ticket identity, reporter path, priority crumbs, classification, forge URL when forge-borne |
| Scope note | Absent | In/out; incident/request = modes; forge SoR |
| Handoffs table | Absent (Dogfood implies eng/QA) | Explicit Eng / Ops / QA / Reporter / Auditor |
| Lingo completeness | Good core; missing waiting_on, unclaim, score, park, queue, priority | Full FL harvest; TEMPLATE Their-word -> Mill |
| SLA / score | "KPI score row" one row | Explicit `score` (support is README score row cluster) |
| waiting_on / assign / unclaim | assign implied; waiting_on only in Dogfood prose | Add to Lingo table |
| hold / drop | Absent | Omit day-one teach (README rarity) unless office leases |
| Must-not | Three solid bullets | Add: HINT bypass; no invent commands; replace-body!=mail; drop!=unclaim; don't pretend mill is Zendesk |
| Done | Unblocked or eng owns; pass; forge updated | Add waiting_on/parked alternatives; ball-location gate |
| Reject list | Implicit | Explicit: no open/yield/bare create/teaching done |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-support/SKILL.md`. Pull mill-desk first. Do not invent commands.

```markdown
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

## Product
**Resolved ticket** - user/reporter unblocked (answer or workaround) **or**
remaining fix visibly owned elsewhere (eng/ops todo id) with forge Issue
updated when the report came from GitLab/GitHub.

Incident vs service request are **modes** of this product (detail/label), not
second day-one products. Major SEV / runtime outage -> hand off office-ops.

## Inputs
On the desk **before** triage resolve (else `replace-body` gap + `send` / `waiting_on`):
- **Ticket identity** - what broke or what was asked (`create todo` need + detail)
- **Reporter path** - who to unblock; reply desk or human_required channel
- **Forge URL** - required in detail when report came from GitLab/GitHub Issue
- Strong: priority (impactxurgency) text; incident vs request vs bug classification
  (bug -> `label-add ... bug`)

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
| workaround / progress diary | progress: `todo <roster> <need> --eta E` / `--started` / `--progress 9/12`; the workaround: card text (`replace-body`) |
| need more info | `send` reporter / human_required + `waiting_on` |
| escalate (L1->L2/L3, eng/ops) | `send` + eng/ops todo/`assign`; support `waiting_on` |
| duplicate | `replace-body` canonical + `pass` |
| resolve / close | `pass` when user unblocked **or** fix owned elsewhere |
| blocked (reporter/eng/vendor) | `waiting_on` + `send` |
| park / defer | `create todo` `{status:"parked"}` |
| SLA (and optional CSAT) | `score` last vs target |
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
- Confuse `drop` (hold) with `unclaim`; confuse `replace-body` with `send`.
- Teach `hold` day-one unless the office leases shared resources.

## Done looks like
- User unblocked **or** visible eng/ops todo owns the fix; forge Issue updated when applicable.
- Support card `pass`ed or clean waiting_on or parked.
```
