# RESEARCH - office-marketing

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward, dry, cite-first. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-marketing \| Launch / publish \| product** |
| Folder | `docs/skills/office-marketing/` exists |
| Stub | Thin `SKILL.md` present (Product + Lingo + Must-not + Done; **no Inputs / Handoffs / Scope**) |
| FUNCTION-LINGO.md | Present - S **Marketing / content** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked (alpha hard-cut #60) |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-sales RESEARCH.md (Loop-1 shape); office-sales / office-support stubs |

**Function:** office-marketing  
**README product noun:** Launch / publish  
**Wake / scout noun (this run):** launch / campaign (same spine; publish = close path for campaign or asset)  
**CMS / analytics:** stay systems of record (content store, channel metrics) - mill coordinates collab only.

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Launch / campaign** | **KEEP** | Catalog = Launch / publish. FL product words: campaign, launch, publish. Stub: live campaign or published asset. Dual outcome on one spine (campaign go-live **or** asset published) - like sales Close-won / handoff. |
| Published asset as separate product | **DROP** (day-one) | Same close path as launch (`pass` + optional Wall). Asset work = claim/replace-body (+ rare hold) **inside** the campaign/launch card. Revisit if office runs standing creative desk vs launch desk. |
| Brief as product | **DROP** | FL mill sketch: brief -> todo **detail**. Input/raw material, not the shippable artifact. |
| Creative asset (alone) as product | **DROP** (day-one) | FL product *word*; collab step under launch. DAM/CMS holds the binary - mill does not. |
| Channel / calendar as product | **DROP** | Channel is detail; calendar is motion/planning - not mill artifact. |
| KPI / analytics dashboard as product | **DROP** | FL: KPI -> score row. README score row cluster "marketing (KPI)". Analytics SoR outside mill. |
| CMS / DAM as mill product | **DROP** | Stub Must-not: "Treat mill as DAM/CMS." README domain SoR. |
| Brand book / guidelines DB as product | **DROP** | Policy input; brand approve = human_required mail gate (README human_required cluster: marketing brand approve). |
| Review cycle as product | **DROP** | Collab motion -> `send` / claim; not an artifact. |
| Embargo release as separate product | **DROP** | Embargo = waiting_on until gate; then same launch `pass`. |

**Kept products (day-one): 1 - Launch / campaign** (dual: campaign live **or** asset published; README "Launch / publish").

---

## Product (kept) - Launch / campaign

**Artifact (one sentence):** A marketing card whose **campaign is live** or whose **asset is published** under the office review/approve gate, with KPI owner pointed at the score row - not a CMS/analytics clone.

**Not the product:** CMS/DAM binary store, analytics warehouse, sales pipeline close, support ticket, legal clear, finance media-spend approve-as-SoR.

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Brief / ask (what to launch or publish) | **Yes** | todo `detail` (FL: brief -> todo detail) |
| Campaign or asset identity (name, CMS/DAM id or URL) | **Yes** | detail link - don't clone CMS |
| Channel / audience / date (or embargo) | Strong | detail + `replace-body`; embargo -> waiting_on |
| Review / approve path (who must greenlight; brand?) | Strong | `send`; human_required if policy (FL + README) |
| KPI name / target (reach, conversion, ...) | When office tracks | `score` / score row (FL: KPI -> score row) |
| Handoff dest (sales enablement, support FAQ, eng for landing) | When handoff | `send` + optional `assign` / `create todo` |

Not inputs: "grow reach," replace CMS uploads, replace analytics dashboards, invent mill commands (`publish`, `launch`, `approve` as CLI).

### Done looks like (this product)

- **Launch / publish:** review gate satisfied (or explicit waiting_on cleared); card `pass`; CMS/channel live *outside* mill; optional Wall glance; KPI owner knows score row (`score` if set).
- **Embargo / blocked on brand:** clean **waiting_on** + `send` - don't fake `pass`.
- **Handoff to sales/support:** next owner `send`/`assign`ed; prior `unclaim` if needed.
- Else: parked (`create todo` `{status:"parked"}`) - never silent open.

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `replace-body`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk). `unpark` exists but is not day-one teach unless human says it.

Sources for rows: **FUNCTION-LINGO.md S Marketing / content** (required), mill-desk day-one, stub, README general mapping (human_required = marketing brand approve; score row = marketing KPI; hold for exclusive creative when needed), sibling office-sales RESEARCH.

Shared spine (one table for the function) - **every row cites FL**:

| Their word | Source (FL cite) | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| brief | FL Marketing product words; FL mill sketch "todo detail" | create todo, open | **`create todo`** + detail | reject `open`; brief != product |
| creative / asset | FL Marketing product words; stub | claim, hold, replace-body | **`claim`** + **`replace-body`**; **`hold`/`drop`** if exclusive write on shared asset station | CMS/DAM = SoR for binary; don't invent `upload` |
| campaign | FL Marketing product words; README Launch / publish | create todo | **`create todo`** (campaign id/URL in detail) | not a second product noun beyond Launch / campaign |
| launch | FL Marketing product words; FL mill sketch "done + optional wall" | pass, done | **`pass`** (+ optional Wall glance) | reject teaching `done`; mill-desk: ship/pass/close -> `pass` |
| publish | FL Marketing product words; FL mill sketch "done + optional wall"; stub | pass | **`pass`** | same close path as launch; CMS publish outside mill |
| channel | FL Marketing product words | replace-body, detail | **`replace-body`** / detail | not a mill command; not a product |
| KPI (reach/conversion) | FL Marketing product words; FL mill sketch "score row"; README score row cluster | score | **`score`** | analytics SoR outside; score = last vs target glance |
| review cycle | FL Marketing collab words | send, claim | **`send`** (+ second desk `claim` if needed) | not invent `review` CLI |
| approval / approve | FL Marketing collab; FL mill sketch "mail; human_required if needed"; README human_required marketing brand | send | **`send`**; **human_required** if brand/policy | reject inventing `approve` command |
| embargo | FL Marketing collab; stub | waiting_on | **`waiting_on`** + `send` | don't fake pass |
| handoff to sales/support | FL Marketing collab; README escalate = send | send, assign | **`send` + `assign`** | same pattern as sales handoff |
| own / take the launch | mill-desk claim; stub creative claim | claim, assign | **`claim`** / **`assign`** | - |
| drop the claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| find work / mail landed | mill-desk mail | inbox | **`inbox`** | - |
| ping / tell reviewer or next owner | mill-desk send; README "Need eyes" | send | **`send`** | dest=desk/role, not email To:human |
| progress / diary on card | mill-desk replace-body | replace-body | **`replace-body`** | replace-body != mail |
| exclusive edit shared creative | stub "hold if exclusive"; TEMPLATE hold | hold, drop | **`hold`** / **`drop`** when office leases asset station | README: hold rare - teach only for exclusive creative write, not day-one chatter |
| park / file for later | mill-desk | create todo parked | **`create todo` `{status:"parked"}`** | reject bare `create` / `open` |
| Wall glance after launch | FL mill sketch "optional wall glance" | - (wall) | optional Wall - not a write command | wall = human glance (FL legend) |

**Stub lingo gaps this harvest fills:** Inputs, Handoffs, Scope, inbox, unclaim vs drop, park, channel/campaign/KPI explicit FL maps, launch/publish -> `pass` not teaching `done`, CMS/analytics SoR, human_required brand gate, sales/support handoff rows, score = KPI not product.

---

## Handoffs

| To | When |
|---|---|
| **office-sales** | Enablement / launch asset for pipeline or inbound MQL context - `send` (FL collab "handoff to sales"; sales RESEARCH <-> marketing) |
| **office-support** | FAQ / known-issue / customer-facing copy after publish - `send` (FL "handoff to ... support") |
| **office-legal** | Claims review, trademark, disclosure, embargo legal - waiting_on + `send` |
| **office-finance** | Media spend / budget approve gate - waiting_on + `send` (README human_required finance; spend) |
| **office-engineering** | Landing page, tracking pixels, release-tied launch - `send` (+ eng todo if build) |
| **office-qa** | Claims remasure / evidence on marketing Claims - `send` |
| **office-research** | Insights brief feeding campaign ask - `send` / consume research brief as input |
| **Asker / brand human** | Missing brief, approve gate, or embargo lift - `send` / human_required / `waiting_on` |

Pattern: escalate always = mill `send` (README). CMS publish and analytics updates happen **in CMS/analytics**, then `replace-body` the fact on the mill card. Brand approve = human_required mail, not a new command.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- **Treat mill as DAM/CMS** (stub; content binaries and publish state stay in CMS/DAM).
- **Treat mill as analytics SoR** - KPI glance via `score` only; dashboards stay outside.
- Invent mill commands for marketing slang (`publish`, `launch`, `approve`, `embargo`, `schedule` as CLI).
- Teach `done` / `open` / `yield` / bare `create` (mill-desk day-one hard-cut).
- Confuse `drop` (hold release) with `unclaim`.
- Launch without the review gate the office requires (stub).
- Fake `pass` while embargoed or waiting brand/legal/finance - use waiting_on + mail.
- Pretend mill *is* HubSpot Marketing / Marketo / Contentful / GA.

---

## Done looks like - per product

**Launch / campaign**

1. Brief + campaign/asset identity were on the desk (or waiting_on mailed).
2. Review/approve path completed (`send` / human_required) or explicit waiting_on.
3. **Live / published:** card `pass`; CMS/channel updated outside mill; optional Wall glance; KPI `score` set or owner told.
4. Handoffs to sales/support mailed when enablement needed.
5. Never silent open forever - `pass`, clean waiting_on, or parked.

---

## Scope note

- **In:** Launch/campaign collab on a mill office - create/claim/replace-body/send/pass spine; review/approve mail; embargo waiting_on; brand human_required; KPI via `score`; rare hold on shared creative station; handoffs to sales/support/legal/finance/eng.
- **Out:** CMS/DAM content store, analytics warehouses, sales close-won product, support resolve, legal clear/hold-as-product, finance paid, eng ship, QA Pass/Fail evidence.
- **Day-one:** single dual product (campaign launch **or** asset publish); brief/creative/channel/KPI/embargo/review = inputs, steps, gates, or score - not second SKILL products.
- Adapter stays thin - pull mill-desk first; one card, then STOP.
- **Voice:** ops steward - dry, cite-first; product noun = Launch / campaign (README Launch / publish).

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog **Launch / publish**; spine create todo->claim->todo --eta->send->pass; human_required cluster marketing brand approve; score row cluster marketing KPI; escalate = send |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S **Marketing / content** | **Required** product words (brief, creative asset, campaign, launch, publish, channel, KPI); collab (review cycle, approval, embargo, handoff to sales/support); mill sketch rows |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-marketing/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-sales/SKILL.md` + `RESEARCH.md` | Sibling: handoff <-> marketing; RESEARCH shape; score/waiting_on/inbox/unclaim patterns |
| `docs/skills/office-support/SKILL.md` | Sibling: escalate = send; SoR outside mill |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; replace-body!=mail; drop!=unclaim; create todo always includes todo; pass = ship/close; no open/yield/teaching done |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| Common marketing ops (campaign brief -> creative -> review/approve -> publish/launch -> measure) | Stages after brief are **collab + CMS SoR**; mill card tracks ownership, review mail, embargo wait, launch `pass` |
| Embargo / brand approval | Gate = waiting_on + human_required mail - not invent `approve`/`embargo` CLI (aligns FL) |
| KPI (reach, conversion) | Measure SoR = analytics; mill `score` last vs target (README cluster) |
| Handoff to sales (enablement) / support (FAQ) | Role handoff = mill `send` + `assign` (FL collab) |

### Guesses (flagged)

- **Published asset** as 2nd product - **guess against** day-one; keep dual under Launch / campaign unless office splits creative vs launch desks.
- Teaching **`hold`/`drop`** for all creative work - **guess**; teach only when exclusive asset station lease (stub allows; README hold rare).
- Required **finance** handoff on every paid media launch - **guess**; only when office policy / spend gate.
- **Wall glance** mandatory on every `pass` - **guess against** FL "optional"; keep optional.

---

## Open questions for human / gardener

1. Align catalog title to **Launch / publish** (README) or **Launch / campaign** (this wake) - keep dual body either way?
2. Split **campaign launch** vs **asset publish** into two Product subsections with separate Inputs/Done, or keep one dual product?
3. Teach **`hold`/`drop`** day-one for creative stations, or omit unless office leases shared assets (sales omitted)?
4. Is **brand human_required** always on before `pass`, or only when policy/label says so?
5. Where does marketing **`score`** KPI live (office KPI name / target) - marketing desk vs shared Wall?
6. After launch, is **`send` sales/support** required every time, or only when enablement/FAQ is in the brief?
7. MQL -> sales: does marketing **`create todo`** for sales, or only `send` and let sales file the opp card?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Inputs section | **Absent** | Add: brief, campaign/asset id, channel/date/embargo, review path, KPI, handoff dest |
| Handoffs section | **Absent** | Add: sales, support, legal, finance, eng, qa, research, brand human |
| Scope note | **Absent** | In/out; dual Launch/campaign; CMS/analytics SoR; hold rare |
| Product noun | "Live campaign or published asset" | Align README: **Launch / publish**; wake: **Launch / campaign** - dual spine |
| Lingo completeness | Core FL rows; missing inbox/unclaim/park/channel/campaign explicit, score command | Full FL harvest; reject teaching `done`; `pass` for launch/publish |
| hold | "claim + hold if exclusive" | Keep **conditional** - exclusive asset station only |
| score / KPI | Present as score row | Keep as `score`; not a product; analytics SoR outside |
| Must-not | DAM/CMS + launch-without-gate | Add: HINT bypass; analytics SoR; no invent commands; drop!=unclaim; no fake pass; no teach done/open/yield |
| Done | Asset/campaign live; pass; KPI owner | Spell pass / waiting_on / parked / handoff mail |
| metadata short-description | "Marketing: launches via mill" | Prefer "Marketing: Launch / campaign via mill" |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-marketing/SKILL.md`. Pull mill-desk first. Do not invent commands. CMS and analytics stay SoR.

```markdown
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

## Product
**Launch / campaign** - campaign live **or** asset published under the office
review/approve gate, with KPI owner pointed at the score row.
README catalog noun: Launch / publish. CMS/DAM and analytics stay systems of
record; mill coordinates collab only.

Brief, creative work, channel, embargo, and KPI are **inputs, steps, gates, or
score** on this spine - not second day-one products.

## Inputs
On the desk **before** you can launch or publish (else `replace-body` gap + `send` asker / `waiting_on`):
- **Brief / ask** - what ships (in todo detail)
- **Campaign or asset identity** - name + CMS/DAM id or URL (do not clone CMS)
- **Channel / date** - and embargo if any
- **Review / approve path** - who must greenlight (brand -> human_required if policy)
- **KPI** - name/target when the office tracks (for `score`)
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
| progress / diary | `replace-body` |
| find work / mail landed | `inbox` |
| review cycle | `send` (+ second desk claim if needed) |
| approval / brand approve | `send`; human_required if policy |
| embargo / wait | waiting_on + `send` |
| channel | detail / `replace-body` |
| handoff to sales/support | `send` + `assign` |
| KPI (reach/conversion) | `score` |
| publish / launch | `pass` (+ optional Wall glance) |
| park / later | `create todo` `{status:"parked"}` |

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
| Brand human | Approve gate / embargo lift (human_required) |

## Must-not
- Bypass mill-desk HINT routing.
- Treat mill as DAM/CMS or as analytics SoR.
- Invent mill commands for marketing slang (`publish`, `launch`, `approve`, `embargo` as CLI).
- Launch without the review gate the office requires.
- Fake `pass` while embargoed or waiting brand/legal/finance - use waiting_on + mail.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Launch/publish: card `pass`ed; CMS/channel live outside mill; optional Wall glance; KPI owner knows score row (`score` if set).
- Handoff: sales/support (etc.) mailed and/or assigned when brief requires.
- Else clean waiting_on or parked - never silent open.
```
