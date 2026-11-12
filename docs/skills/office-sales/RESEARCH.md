# RESEARCH - office-sales

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward, dry, cite-first. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-sales \| Close-won / handoff \| product** |
| Folder | `docs/skills/office-sales/` exists |
| Stub | Thin `SKILL.md` present (Product + Lingo + Must-not + Done; **no Inputs / Handoffs / Scope**) |
| FUNCTION-LINGO.md | Present - S **Sales / pipeline (common CRM)** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked (alpha hard-cut #60) |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-support, office-marketing stubs; office-qa / office-research RESEARCH.md shape read |

**Function:** office-sales  
**README product noun:** Close-won / handoff  
**CRM:** stays system of record (amounts, accounts, stage history) - mill coordinates collab only.

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Close-won / handoff** | **KEEP** | Catalog product. FUNCTION-LINGO: close-won -> done + mail CS onboarding; handoff SDR->AE->CS -> mail + assign. Stub already dual: closed deal **or** clean next-stage handoff. |
| Lead / MQL / SQL as product | **DROP** | FUNCTION-LINGO product *words*, not shippable mill artifact. Lead intake = `create todo` (or CRM create + mill link). Qualification is a **stage note**, not a second SKILL product. |
| Pipeline (as view/product) | **DROP** | Pipeline is CRM SoR / Wall glance over cards - not an office artifact mill ships. |
| Proposal / quote pack | **DROP** (day-one) | Proposal is a **step** inside an opportunity card (`replace-body` path + optional legal/finance handoff). Alone overlaps office-legal / finance SoR. Revisit if office runs standing proposal desk. |
| Forecast as product | **DROP** | Collab/KPI: README score row cluster "sales (forecast)" -> `score`, not a product. |
| Account / renewal as separate product | **DROP** (day-one) | Account lives in CRM. Renewal = same opportunity spine (new/renewed opp todo) or CS handoff - not a 2nd day-one product unless office splits AE vs CS renewals later. |
| Close-lost as separate product | **DROP** | Outcome mode of the same card: `pass` + `replace-body` why (stub). Not a second artifact. |

**Kept products (day-one): 1 - Close-won / handoff** (dual outcome on one spine).

---

## Product (kept) - Close-won / handoff

**Artifact (one sentence):** A pipeline opportunity advanced to **close-won** (deal closed; next owner mailed) **or** a **clean stage handoff** (SDR->AE->CS/delivery) with owner, next step, and CRM id linked - not a CRM clone.

**Not the product:** lead-gen campaigns (marketing), support tickets, legal clearance, finance approval, forecast spreadsheet as SoR.

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Opportunity identity (CRM id / account / deal name) | **Yes** | todo `detail` (link CRM URL/id - don't clone amounts) |
| Stage / desired outcome (advance, close-won, close-lost, handoff dest) | **Yes** | need + detail; if missing -> `replace-body` gap + `send` asker / `waiting_on` |
| Owner / role path (SDR, AE, CS, delivery) | Strong | `claim` / `assign`; handoff dest in detail |
| Next step (call, demo, proposal, legal, pricing) | Strong | `todo <roster> <need> --eta E` / `--started` |
| Blockers (legal, pricing, security review) | When blocked | waiting_on + `send` specialized desk |
| Close facts (won/lost reason; CS onboarding ask) | On close | `replace-body` + `send` CS/`create todo` onboarding |

Not inputs: "grow pipeline," replace CRM amounts, fan-out assign to `*` + role + desk.

### Done looks like (this product)

- **Close-won:** card `pass`; CRM updated *outside* mill; CS/delivery **mailed** (`send`) and/or onboarding `create todo` + `assign`.
- **Close-lost:** card `pass` with `replace-body` why; no fake waiting_on.
- **Stage handoff:** next owner `assign`ed and/or `send` mailed; prior owner `unclaim` if needed; waiting_on cleared; CRM stage advanced outside mill.
- Else: clean **waiting_on** (legal/pricing/human) - don't fake `pass`.

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `replace-body`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk). `unpark` exists but is not day-one teach unless human says it.

Sources for rows: **FUNCTION-LINGO.md S Sales / pipeline** (required), mill-desk day-one, stub, README general mapping (score row = sales forecast; hold rare for sales), siblings support/marketing.

Shared spine (one table for the function):

| Their word | Source (FL cite) | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| lead | FL Sales product words | create todo, open | **`create todo`** (link CRM lead id in detail) | reject `open`; CRM remains SoR |
| MQL / SQL | FL Sales product words | replace-body, create todo | **`replace-body`** stage on opp todo (or new todo if office splits) | not mill commands; qualification != invent `qualify` |
| opportunity | FL mill sketch "todo (or plan row for big deals)" | create todo | **`create todo`** | plan row = later/not day-one teach; stub "lead / opportunity -> create todo" |
| pipeline | FL Sales product words | todo list, wall | **`todo`** glance / Wall - not a write product | reject inventing `pipeline` command |
| proposal | FL Sales product words | replace-body, send, hold | **`replace-body`** path + optional `send` legal/finance | hold rare (README: don't teach hold in sales unless needed) |
| account | FL Sales product words | detail link | **detail / `replace-body`** CRM account id | SoR = CRM; don't clone account DB |
| renewal | FL Sales product words | create todo, send CS | **`create todo`** renew opp **or** `send` CS | same spine; not 2nd product day-one |
| next step | FL mill sketch "progress / replace-body"; stub | todo --eta/--started | **`todo <roster> <need> --eta E`** / `--started` | replace-body != mail |
| handoff (SDR->AE->CS) | FL mill sketch "mail + assign"; stub; FL collab | send, assign | **`send` + `assign`** | escalate always = send (README); not claim steal |
| blocked (legal/pricing) | FL mill sketch "waiting_on"; FL collab; stub | waiting_on + send | **`waiting_on` + `send`** | don't fake pass |
| forecast | FL collab; README score row "sales (forecast)"; stub | score | **`score`** (last vs target) | not a product |
| close-won | FL mill sketch "done; mail CS onboarding todo"; stub | pass, send, create todo | **`pass`** + **`send`** CS + optional onboarding **`create todo`/`assign`** | reject teaching `done` as speech - mill-desk: ship/pass/close -> `pass` |
| close-lost | stub | pass + replace-body | **`pass`** + **`replace-body`** why | same card close path |
| own / work deal | stub; mill-desk claim | claim, assign | **`claim`** / **`assign`** | - |
| drop the claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| find work / mail landed | mill-desk mail; support inbox pattern | inbox | **`inbox`** | - |
| ping / tell next owner | mill-desk send; README "Need eyes" | send | **`send`** | dest=desk/role, not email To:human |
| exclusive edit shared file | TEMPLATE hold; README hold rare sales | hold / drop | **omit day-one** (or rare `hold`/`drop` if office leases proposal doc) | README: don't teach hold in sales/support unless needed |
| park / file for later | mill-desk | create todo parked | **`create todo` `{status:"parked"}`** | reject bare `create` / `open` |

**Stub lingo gaps this harvest fills:** Inputs, Handoffs, Scope, inbox, unclaim vs drop, park, lead/MQL/SQL/account/renewal/proposal/pipeline explicit maps, close-won vs teaching `done`, hold omit-unless-needed, score = forecast not product.

---

## Handoffs

| To | When |
|---|---|
| **CS / delivery / onboarding desk** | Close-won - `send` + optional onboarding `create todo`/`assign` (FL sketch; stub) |
| **office-legal** | Blocked on contract/redline/clear - waiting_on + `send` (FL collab "blocked on legal") |
| **office-finance** | Blocked on pricing/discount/approve - waiting_on + `send` (FL "blocked on ... pricing"; finance approval = human_required cluster README) |
| **office-marketing** | Need launch/asset or inbound MQL context - `send` (marketing Handoffs spirit; MQL from campaign) |
| **office-support** | Post-sale user issue - `send`; support ticket product owns resolve (support stub) |
| **office-engineering / office-qa** | Security review, POC build, or Claims remasure for deal - `send` (+ eng/qa todo if work) |
| **Asker / AE / SDR peer** | Missing stage outcome, CRM id, or next-step criteria - `send` / `waiting_on` |

Pattern borrow: support "escalate = mill send"; README "Escalate always = mill send to a more specialized desk"; marketing <-> sales handoff is mail, not new command. CRM stage/amount updates happen **in CRM**, then `replace-body` the fact on the mill card.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- **Replace CRM** as system of record for amounts, accounts, stage history, forecasts-of-record (stub; FUNCTION-LINGO how-to-talk #4; README domain SoR).
- Fan-out the same assign to `*` + role + desk (stub).
- Invent mill commands for CRM slang (`qualify`, `forecast`, `close`, `pipeline`, `stage` as CLI).
- Teach `done` / `open` / `yield` / bare `create` (mill-desk day-one hard-cut).
- Confuse `drop` (hold release) with `unclaim`.
- Teach `hold` day-one for sales unless the office leases a shared proposal/doc resource (README: hold rare - eng/legal).
- Fake `pass` while blocked on legal/pricing - use waiting_on + mail.
- Pretend mill *is* Salesforce/HubSpot/Dynamics.

---

## Done looks like - per product

**Close-won / handoff**

1. CRM id + stage/outcome were on the desk (or waiting_on mailed).
2. Progress/`next step` noted; blockers mailed to specialized desks when needed.
3. **Close-won:** card `pass`; CS/delivery mailed and/or onboarding todo created/assigned; CRM closed-won outside mill.
4. **Close-lost:** card `pass` + reason in card text.
5. **Handoff:** next owner assigned and/or mailed; prior claim cleared; CRM stage advanced outside mill.
6. Never silent open forever - `pass`, clean waiting_on, or parked.

---

## Scope note

- **In:** Opportunity collab on a mill office - create/claim/replace-body/send/pass spine; SDR->AE->CS handoffs; blocked->waiting_on; forecast glance via `score`; close-won/lost card close with CS mail on win.
- **Out:** CRM data model, quote engines, marketing launch product, support resolve, legal clear/hold, finance approve/paid, eng ship, QA Pass/Fail evidence.
- **Day-one:** single dual product (close-won **or** clean handoff); lead/MQL/SQL/proposal/renewal/forecast = inputs, stages, steps, or score - not second SKILL products.
- Adapter stays thin - pull mill-desk first; one card, then STOP.
- **Voice:** ops steward - dry, cite-first; product noun = Close-won / handoff.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog **Close-won / handoff**; spine create todo->claim->todo --eta->send->pass; hold rare sales/support; score row cluster sales forecast; escalate = send |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S **Sales / pipeline (common CRM)** | **Required** product words (lead, MQL/SQL, opportunity, pipeline, proposal, close-won/lost, account, renewal); collab (handoff SDR->AE->CS, next step, blocked legal/pricing, forecast); mill sketch rows |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-sales/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-support/SKILL.md` | Sibling: escalate = send; SoR outside mill; waiting_on pattern |
| `docs/skills/office-marketing/SKILL.md` | Sibling: launch/publish; KPI score row; handoff-to-sales spirit |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; replace-body!=mail; drop!=unclaim; create todo always includes todo; pass = ship/close; no open/yield/teaching done |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| Common CRM practice (Salesforce/HubSpot-style) - lead -> MQL/SQL -> opportunity -> close | Stages are **CRM SoR**; mill card tracks collab ownership + next step + handoff mail (aligns FL) |
| Close-won / close-lost | Terminal opportunity outcomes -> mill `pass` + reason in card text; win triggers CS onboarding handoff (FL sketch) |
| SDR / AE / CS handoff | Role chain = mill `send` + `assign`, not a new command |
| Sales forecast | Pipeline coverage / commit vs target -> mill `score` / score rows (README cluster), CRM keeps detailed forecast SoR |

### Guesses (flagged)

- **Proposal desk** as 2nd product - **guess**; day-one keep as step inside opportunity.
- **Renewal** as 2nd product (CS-owned) - **guess**; README names one dual product; revisit if office splits.
- Teaching **`hold`** on proposal docs - **guess against** README "don't teach hold in sales unless needed"; omit day-one.
- Big-deal **plan row** (FL "or plan row for big deals") - **not day-one teach**; stick to `create todo`.

---

## Open questions for human / gardener

1. Keep **one dual product** (Close-won / handoff) or split **close-won** and **stage handoff** into two Product subsections with separate Inputs/Done?
2. On close-won, is **CS onboarding `create todo`** required every time, or is `send` mail enough unless office policy says otherwise?
3. Should **renewal** get its own day-one product (CS renewals) or stay same opportunity spine?
4. Teach **`hold`/`drop`** at all in office-sales, or explicitly omit per README rarity?
5. Where does **forecast `score`** live (office KPI name / target) - sales desk vs ops Wall?
6. MQL from marketing: does sales **`create todo`** on accept, or only `claim` a card marketing already filed?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Inputs section | **Absent** | Add: CRM id, stage/outcome, owner path, next step, blockers, close facts |
| Handoffs section | **Absent** | Add: CS/delivery, legal, finance, marketing, support, eng/qa |
| Scope note | **Absent** | In/out; dual product; CRM SoR; hold omit |
| Product noun | "Close-won opportunity (or ... handoff)" | Align title/README: **Close-won / handoff** |
| Lingo completeness | Good core; missing inbox/unclaim/park/pipeline/MQL/account/renewal/proposal | Full FL harvest; reject teaching `done` |
| hold | Absent (good) | Keep absent day-one unless office leases docs |
| score / forecast | Present as score row | Keep as `score`; not a product |
| close-won path | pass + mail CS onboarding todo | Keep; clarify `send` vs required onboarding todo (open Q) |
| Must-not | CRM + fan-out assign | Add: HINT bypass; no invent commands; drop!=unclaim; no fake pass; no teach done/open/yield |
| Done | Stage advanced or closed; next owner mailed | Spell close-won / close-lost / handoff / waiting_on / parked |
| metadata short-description | "Sales: opportunities via mill" | Prefer "Sales: Close-won / handoff via mill" |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-sales/SKILL.md`. Pull mill-desk first. Do not invent commands. CRM stays SoR.

```markdown
---
name: office-sales
description: >
  Use when this desk is moving pipeline to close-won or a clean stage handoff
  on a mill office. Pull mill-desk first. Thin adapter - not a second mill.
  Product = Close-won / handoff - not a CRM clone.
metadata:
  short-description: "Sales: Close-won / handoff via mill"
---

# Office - Sales -> Close-won / handoff

Pull **mill-desk** first. One card, then **STOP**.

## Product
**Close-won / handoff** - opportunity advanced to close-won (deal closed; CS/delivery
mailed) **or** a clean stage handoff (SDR->AE->CS/delivery) with owner + next step.
CRM stays system of record for amounts, accounts, and stage history.

Lead/MQL/SQL, proposal, renewal, and forecast are **stages, steps, or score** on
this spine - not second day-one products. Close-lost = same card `pass` + reason in card text.

## Inputs
On the desk **before** you can advance or close (else `replace-body` gap + `send` asker / `waiting_on`):
- **CRM identity** - opportunity/account id or URL in detail (do not clone amounts)
- **Stage / outcome ask** - advance, close-won, close-lost, or handoff destination
- **Owner path** - SDR / AE / CS / delivery (for claim/assign)
- **Next step** - call, demo, proposal, legal, pricing (`todo <roster> <need> --eta E` as you go)
- When blocked: legal/pricing/security context for waiting_on mail
- On close-won: CS onboarding ask (who/what to mail or todo)

Not inputs: "grow the pipeline," CRM data entry as mill's job, fan-out assign.

## Lingo -> mill
| Their word | Mill |
|---|---|
| lead / opportunity | `create todo` (CRM id in detail) |
| MQL / SQL / stage | `replace-body` on opp card (CRM stage outside mill) |
| own / work deal | `claim` / `assign` |
| drop the claim | `unclaim` |
| next step / progress | `todo <roster> <need> --eta E` / `--started` |
| find work / mail landed | `inbox` |
| handoff SDR->AE->CS | `send` + `assign` |
| blocked (legal/pricing) | waiting_on + `send` |
| proposal path | `replace-body` (+ `send` legal/finance if gate) |
| forecast / KPI | `score` |
| close-won | `pass` + `send` CS/delivery (+ optional onboarding `create todo` / `assign`) |
| close-lost | `pass` + `replace-body` why |
| park / later | `create todo` `{status:"parked"}` |
| renewal | same spine: `create todo` renew opp **or** `send` CS |

Do **not** teach `hold`/`drop` day-one unless the office leases a shared proposal doc.
Never teach `open` / `yield` / bare `create` / `done`.

## Handoffs
| To | When |
|---|---|
| CS / delivery | Close-won - mail + optional onboarding todo |
| Legal | Contract / redline / clear gate |
| Finance | Pricing / discount / approve gate |
| Marketing | Launch asset or inbound MQL context |
| Support | Post-sale user issue (ticket product owns resolve) |
| Engineering / QA | POC, security review, or Claims remasure |

## Must-not
- Bypass mill-desk HINT routing.
- Replace CRM as SoR for amounts/accounts/stage/forecast-of-record.
- Fan-out the same assign to `*` + role + desk.
- Invent mill commands for CRM slang (`qualify`, `pipeline`, `close`, `stage` as CLI).
- Fake `pass` while blocked - use waiting_on + mail.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Close-won: card `pass`ed; CS/delivery mailed (and/or onboarding todo assigned); CRM closed outside mill.
- Close-lost: card `pass`ed with the reason in card text.
- Handoff: next owner assigned and/or mailed; waiting_on cleared or explicit.
- Else clean waiting_on or parked - never silent open.
```
