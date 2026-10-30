# RESEARCH - office-finance

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward, dry, cite-first. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-finance \| Approved / paid \| product** |
| Folder | `docs/skills/office-finance/` exists |
| Stub | Thin `SKILL.md` present (Product + Lingo + Must-not + Done; **no Inputs / Handoffs / Scope**) |
| FUNCTION-LINGO.md | Present - S **Finance / admin** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked (alpha hard-cut #60) |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-sales (finance pricing/approve handoff); office-legal (human_required sibling); office-ops / office-support RESEARCH shape |

**Function:** office-finance  
**README product noun:** Approved / paid  
**Ledger / ERP / AP-AR:** stays system of record (amounts, GL, payments, period close) - mill coordinates collab only.  
**human_required:** README clusters finance (approve) with people (offer), legal (clear), marketing (brand approve).

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Approved / paid** | **KEEP** | Catalog product. FUNCTION-LINGO: approval -> human_required mail/todo; paid/closed -> done. Stub: approved spend **or** paid invoice. Dual outcome on one spine. |
| Invoice as separate product | **DROP** | FL product *word* - the work item noun for a card (`create todo`), not a second SKILL product. Ledger holds the invoice record. |
| PO (purchase order) as separate product | **DROP** | Same: request/PO -> `create todo`; approval/paid path is the artifact. |
| Budget as product | **DROP** | Constraint / input / KPI context. Not the shippable finance office artifact day-one. |
| Forecast as product | **DROP** | FL sketch "forecast KPI -> score row"; README score row pattern. Fulfillment = `score`, not a product. |
| Accrual as product | **DROP** | Ledger/accounting SoR concept. Mill may `note` accrual ask; don't clone GL. |
| Payment / remittance as separate product | **DROP** (day-one) | Outcome mode of **paid** on the same card after approve. Payment execution stays in ledger/bank SoR. |
| Exception as product | **DROP** | Collab: FL "exception -> escalate mail" = `send`, not an artifact. |
| Coding (GL coding) as product | **DROP** | Collab step: stub "coded / approved -> note". Coding happens in ledger; mill diaries the fact. |
| Close the books / closed period step as separate product | **DROP** (day-one) | Stub lists "closed period step"; FL "paid / closed -> done". Catalog names **Approved / paid** only. Period-close is multi-desk collab / follow-on - fold as optional **mode** (approve a close step) or revisit later. Flag open Q. |
| Approval chain as product | **DROP** | Process shape -> `assign` + human_required + `send`. Not a product noun. |

**Kept products (day-one): 1 - Approved / paid** (dual: human-gated approve **or** paid/closed outcome on one spine).

---

## Product (kept) - Approved / paid

**Artifact (one sentence):** A spend/invoice/PO request reached a durable **approve** outcome (human_required gate cleared or withheld with reason) **or** a **paid/closed** outcome recorded on the mill card with ledger id linked - not a ledger/ERP clone.

**Not the product:** owning GL/AP-AR balances, running payroll, being the bank, forecast spreadsheet as SoR, legal clearance, sales close-won.

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Request identity (invoice / PO / spend ask id or URL) | **Yes** | todo `detail` (link ledger/ERP id - don't clone amounts as SoR) |
| Amount / currency / vendor (glance facts) | Strong | `detail` / `note` crumbs; **ledger remains SoR** for truth |
| Desired outcome (approve, reject/withhold, mark paid, exception path) | **Yes** | need + detail; if missing -> `note` gap + `send` asker / `waiting_on` |
| Approver / chain (who must human-click) | **Yes** for approve | `assign` + **human_required**; `send` next approver |
| Coding / cost center / GL hint | When office requires | `note` (coding executed in ledger) |
| Exception reason / policy cite | When exception | `note` + `send` escalate dest |
| Paid proof pointer (payment id / remittance) | On paid | `note` + link ledger; then `pass` |
| Budget / forecast context | Optional | `score` glance or detail link - not mill SoR |

Not inputs: "manage the books," silent auto-approve without human_required when policy requires it, replacing ERP payment runs inside mill.

### Done looks like (this product)

- **Approved:** human_required gate satisfied; outcome `note`d; dependents `send`ed (sales/ops/askers unblocked); card `pass`ed **or** clean waiting_on next approver.
- **Withheld / rejected:** `note` reason; `send` asker; card `pass` (decision recorded) **or** waiting_on revision - don't fake approve.
- **Paid / closed:** ledger shows paid *outside* mill; card `note`d with payment pointer; card `pass`.
- Else: clean **waiting_on** (approver, coding, exception, bank) - don't fake `pass`.

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `note`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk).  
**human_required** is a gate flag / mail pattern (README), not a new mill CLI command - cite beside approve.

Sources for rows: **FUNCTION-LINGO.md S Finance / admin** (required), mill-desk day-one, stub, README (human_required finance approve; ledger SoR; escalate = send), siblings sales->finance pricing, legal human_required cluster.

Shared spine (one table for the function):

| Their word | Source (FL cite) | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| invoice | FL Finance product words; stub | create todo, open | **`create todo`** (ledger invoice id in detail) | reject `open`; ledger SoR |
| PO / purchase order | FL Finance product words; stub | create todo | **`create todo`** | same spine |
| request / spend ask | stub "invoice / PO / request" | create todo | **`create todo`** | reject bare `create` |
| budget | FL Finance product words | score, detail | **detail / `note`** context; optional **`score`** | not a product; not invent `budget` CLI |
| forecast | FL product + sketch "forecast KPI -> score row"; stub | score | **`score`** (last vs target) | not a product |
| accrual | FL Finance product words | note | **`note`** (+ ledger SoR) | don't clone GL |
| payment / remittance | FL product "payment"; stub paid | note, pass | **`note`** payment pointer + **`pass`** when paid | payment run stays ledger/bank |
| approval / approve | FL sketch "human_required mail / todo"; stub approval chain; README human_required finance | assign, send, human_required, note | **`assign`** + **human_required** + **`send`** / **`note`** outcome | never invent `approve` CLI; never skip human gate |
| approval chain | FL collab; stub | assign, send | **`assign`** next + **`send`**; waiting_on until human clicks | chain = ownership + mail, not new command |
| coding (GL / cost center) | FL collab; stub "coded / approved -> note" | note | **`note`** (coding in ledger) | not invent `code` CLI |
| exception | FL sketch "escalate mail"; stub | send | **`send`** escalate (+ `note` reason) | escalate always = send (README) |
| close the books / period close | FL collab "close the books"; stub closed period | note, pass, create todo | **`note`** / optional close-step todo; **`pass`** when step done | DROP as 2nd product day-one; reject teaching `done` |
| paid / closed | FL sketch "paid / closed -> done"; stub | pass, note | **`note`** + **`pass`** | mill-desk: ship/pass/close -> `pass`; reject teaching `done` |
| own / work the request | mill-desk; support/sales claim | claim, assign | **`claim`** / **`assign`** | - |
| drop the claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| find work / mail landed | mill-desk mail | inbox | **`inbox`** | - |
| ping / tell next approver or asker | mill-desk send; README Need eyes | send | **`send`** | dest=desk/role, not email To:human |
| blocked (approver, bank, coding) | README waiting_on | waiting_on + send | **`waiting_on` + `send`/`note`** | don't fake pass |
| exclusive edit shared invoice pack | TEMPLATE hold; README hold rare (eng/legal/docs) | hold / drop | **omit day-one** (or rare `hold`/`drop` if the office leases a doc res) | don't teach hold unless needed |
| park / defer | mill-desk | create todo parked | **`create todo` `{status:"parked"}`** | reject bare `create` / `open` |
| progress / diary | mill-desk note; stub coded/approved | note | **`note`** | note != mail |

**Stub lingo gaps this harvest fills:** Inputs, Handoffs, Scope, inbox, unclaim vs drop, park, budget/accrual/payment/PO explicit maps, human_required called out on approve, forecast = `score` not product, closed-books folded/dropped as 2nd product, reject open/yield/bare create/teaching done, hold omit-unless-needed.

---

## Handoffs

| To | When |
|---|---|
| **Asker / requesting desk** | Need missing invoice/PO facts, coding, or reject/withhold outcome - `send` / `waiting_on` |
| **Next approver (human or finance desk)** | Approval chain step - `assign` + human_required + `send` |
| **office-sales** | Pricing/discount/approve gate unblocks deal (sales RESEARCH already lists Finance) - `send`; sales owns close-won |
| **office-legal** | Contract/payment terms / compliance block on pay - waiting_on + `send` |
| **office-ops / office-engineering** | Vendor/tool spend tied to infra change or incident cost - `send` when context needed |
| **office-people** | Offer / comp spend that needs finance approve (README human_required people offer) - `send` |
| **office-support** | Vendor or billing ticket from customer side - `send`; support ticket product owns resolve |
| **AP/AR / controller desk (office)** | Exception escalate or period-close step - `send` (ledger work stays outside mill) |

Pattern: README "Escalate always = mill send"; "human_required clusters: ... finance (approve)"; sales blocked on pricing -> finance. Ledger/ERP payment and GL postings happen **outside** mill; `note` the fact on the card.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- **Become the ledger of record** (stub) - amounts, GL, AP/AR, bank, period close SoR stay ERP/ledger; mill links ids.
- **Skip required human approval gates** (stub; README human_required finance approve).
- Invent mill commands for finance slang (`approve`, `pay`, `code`, `accrue`, `close-books`, `exception` as CLI).
- Teach `done` / `open` / `yield` / bare `create` (mill-desk day-one hard-cut).
- Confuse `drop` (hold release) with `unclaim`.
- Teach `hold` day-one unless the office leases a shared invoice/PO doc resource (README: hold rare - eng/legal/docs).
- Fake `pass` while waiting on human approve or bank - use waiting_on + mail.
- Auto-`pass` "approved" without human_required when office policy requires a human click.
- Pretend mill *is* NetSuite/QuickBooks/SAP/Expensify/Stripe.

---

## Done looks like - per product

**Approved / paid**

1. Request identity (invoice/PO/spend) + desired outcome were on the desk (or waiting_on mailed).
2. Owner claimed/assigned; coding/exception `note`d when needed; ledger ids linked not cloned.
3. **Approve path:** human_required satisfied; outcome noted; askers/`send`ed; card `pass` **or** waiting_on next approver.
4. **Withhold/reject:** reason noted; asker mailed; card closed via `pass` or waiting_on revision.
5. **Paid/closed:** payment pointer noted from ledger; card `pass`.
6. Optional KPI: forecast/budget glance via `score` if office sets targets.
7. Never silent open forever - `pass`, clean waiting_on, or parked.

---

## Scope note

- **In:** Spend/invoice/PO collab on a mill office - create/claim/assign/note/send/pass spine; approval chain with **human_required**; exception escalate via `send`; paid/closed card close; forecast/budget glance via `score`.
- **Out:** Ledger/ERP/GL/AP-AR/bank as SoR; payroll engine; legal clear/hold product; sales close-won; owning period-close as a second day-one SKILL product.
- **Day-one:** single dual product (**Approved / paid**); invoice/PO/budget/forecast/accrual/coding/exception/close-books = nouns, steps, score, or modes - not second SKILL products.
- Adapter stays thin - pull mill-desk first; one card, then STOP.
- **Voice:** ops steward - dry, cite-first; product noun = Approved / paid.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog **Approved / paid**; spine create todo->claim->note->send->pass; human_required finance (approve); escalate = send; hold rare; domain SoR outside mill |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S **Finance / admin** | **Required** product words (invoice, PO, budget, forecast, accrual, payment); collab (approval chain, coding, exception, close the books); mill sketch (approval->human_required; exception->escalate mail; paid/closed->done; forecast KPI->score row) |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-finance/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-sales/SKILL.md` + sales RESEARCH | Sibling: finance pricing/approve handoff; CRM SoR pattern analogue to ledger |
| `docs/skills/office-legal/SKILL.md` | Sibling human_required / clear-hold cluster; hold on docs |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; note!=mail; drop!=unclaim; create todo always includes todo; pass = ship/close; no open/yield/teaching done |
| `docs/protocol/commands.md` | Confirm score/pass lifecycle; removed teaching CLI (open/yield/bare create/done) |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| Common AP practice - invoice/PO -> code -> approve -> pay | Stages are **ledger SoR**; mill card tracks ownership, approval chain, exception mail, paid outcome (aligns FL) |
| Approval chain / segregation of duties | Approver = human_required + `assign`/`send`; agent must not silent-approve when policy requires human |
| Exception / policy override | Escalate = mill `send`, not a new command (README) |
| Forecast / budget vs actual | KPI glance -> mill `score` / score rows; detailed forecast stays finance SoR |

### Guesses (flagged)

- **Closed period / close-the-books** as 2nd day-one Product - **guess against** catalog (Approved / paid only); stub lists it - open Q for gardener/human.
- Teaching **`hold`/`drop`** on invoice packs - **guess against** README rarity; omit day-one.
- Whether **reject/withhold** should `pass` the card or leave waiting_on for resubmit - **guess**: `pass` + note when decision final; waiting_on when revision expected.
- **human_required** encoding (mail flag vs office convention vs watcher hint) - **guess**; cite README cluster; gardener follows mill-desk/office convention when known.

---

## Open questions for human / gardener

1. Keep **one dual product** (Approved / paid) or split **Approved** vs **Paid** into two Product subsections with separate Inputs/Done?
2. Should stub's **closed period step** become a day-one Product, a named mode under Approved/paid, or stay out until an office runs standing close desks?
3. On approve: is **human_required** always mandatory for any amount, or only above a policy threshold (threshold lives in ledger/policy SoR)?
4. Reject/withhold: prefer card **`pass`** with note reason, or **waiting_on** until asker revises?
5. Teach **`hold`/`drop`** at all in office-finance, or explicitly omit per README rarity?
6. Where does forecast/budget **`score`** live (office KPI name/target) - finance desk vs shared Wall?
7. Payment execution: may finance desk **`pass`** on "approved, payment queued" or only after ledger shows **paid**?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Inputs section | **Absent** | Add: request id, amount/vendor crumbs, outcome ask, approver/chain, coding, exception reason, paid proof pointer |
| Handoffs section | **Absent** | Add: asker, next approver, sales, legal, ops/eng, people, support, AP/controller |
| Scope note | **Absent** | In/out; dual product; ledger SoR; human_required; hold omit |
| Product noun | "Approved spend, paid invoice, or closed period step" | Align title/README: **Approved / paid**; fold or drop closed-period as 2nd product (open Q) |
| Lingo completeness | Core FL rows; missing inbox/unclaim/park/budget/accrual/payment/PO/waiting_on | Full FL harvest; reject teaching `done` |
| human_required | Implied via "assign + human_required" | Call out explicitly on every approve path; Must-not skip gates |
| hold | Absent (good) | Keep absent day-one unless office leases docs |
| score / forecast | Present as score row | Keep as `score`; not a product |
| Must-not | Ledger SoR + skip human gates | Add: HINT bypass; no invent commands; drop!=unclaim; no fake pass; no teach done/open/yield |
| Done | Approval outcome; paid/closed -> pass; KPI if used | Spell approve / withhold / paid / waiting_on / parked |
| metadata short-description | "Finance: approvals via mill" | Prefer "Finance: Approved / paid via mill" |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-finance/SKILL.md`. Pull mill-desk first. Do not invent commands. Ledger stays SoR. **human_required** on approve.

```markdown
---
name: office-finance
description: >
  Use when this desk moves spend approvals or paid/closed outcomes on a mill
  office. Pull mill-desk first. Thin adapter - not a second mill. Product =
  Approved / paid - not a ledger/ERP clone. human_required for approve.
metadata:
  short-description: "Finance: Approved / paid via mill"
---

# Office - Finance -> Approved / paid

Pull **mill-desk** first. One card, then **STOP**.

## Product
**Approved / paid** - spend/invoice/PO request reached a durable approve
outcome (human_required gate cleared or withheld with reason) **or** a
paid/closed outcome with ledger id linked.

Invoice, PO, budget, forecast, accrual, coding, exception, and period-close
are **nouns, steps, score, or modes** on this spine - not second day-one
products. Ledger/ERP stays system of record for amounts, GL, and payments.

## Inputs
On the desk **before** you can approve or mark paid (else `note` gap + `send` asker / `waiting_on`):
- **Request identity** - invoice / PO / spend id or URL in detail (do not clone ledger amounts as SoR)
- **Outcome ask** - approve, withhold/reject, mark paid, or exception path
- **Approver / chain** - who must human-click (`assign` + human_required)
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
| approval / approve | `assign` + **human_required** + `send` / `note` outcome |
| approval chain | `assign` next + `send`; waiting_on until human clicks |
| coding (GL / cost center) | `note` (ledger executes coding) |
| exception | `send` escalate (+ `note` reason) |
| progress / coded / approved diary | `note` (not mail) |
| find work / mail landed | `inbox` |
| blocked (approver/bank/coding) | waiting_on + `send` / `note` |
| budget / forecast KPI | `score` (last vs target) |
| paid / closed | `note` payment pointer + `pass` |
| withhold / reject | `note` reason + `send` asker; `pass` or waiting_on revision |
| park / later | `create todo` `{status:"parked"}` |
| accrual / period-close step | `note` / optional todo on same spine (ledger SoR) |

Do **not** teach `hold`/`drop` day-one unless the office leases a shared invoice/PO doc.
Never teach `open` / `yield` / bare `create` / `done`.
Never invent `approve` / `pay` / `code` as mill CLI.

## Handoffs
| To | When |
|---|---|
| Asker / requesting desk | Missing facts, withhold outcome, or revision ask |
| Next approver | Approval chain step (human_required) |
| Sales | Pricing / discount / approve unblocks deal |
| Legal | Payment terms / compliance block on pay |
| People | Offer / comp spend needing finance approve |
| Ops / Engineering | Vendor spend tied to infra or incident cost |
| Support | Customer billing ticket (support owns resolve) |
| AP / controller desk | Exception escalate or period-close coordination |

## Must-not
- Bypass mill-desk HINT routing.
- Become the ledger of record (amounts, GL, AP/AR, bank, period close).
- Skip required human approval gates (human_required on approve).
- Invent mill commands for finance slang (`approve`, `pay`, `code`, `close-books` as CLI).
- Fake `pass` while waiting on human approve or bank - use waiting_on + mail.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Approved: human_required satisfied; outcome noted; dependents mailed; card `pass`ed or waiting_on next approver.
- Withheld/rejected: reason noted; asker mailed; card `pass`ed or waiting_on revision.
- Paid/closed: ledger payment pointer noted; card `pass`ed.
- Else clean waiting_on or parked - never silent open. Optional `score` if office sets forecast/budget KPI.
```
