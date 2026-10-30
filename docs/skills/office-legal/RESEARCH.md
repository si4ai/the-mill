# RESEARCH - office-legal

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward, dry, cite-first. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-legal \| Cleared / hold \| product** |
| Folder | `docs/skills/office-legal/` exists |
| Stub | Thin `SKILL.md` present (Product = Clearance or hold; Lingo 6 rows; Must-not 2; Done 1; **no Inputs / Handoffs / Scope**; no `human_required`; no Contract SoR callout) |
| FUNCTION-LINGO.md | Present - S **Legal / compliance** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked; reject `open` / `yield` / bare `create` / teaching `done` |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-ops, office-qa, office-engineering, office-research, office-sales, office-finance, office-people read |

**Function:** office-legal  
**README product noun:** Cleared / hold  
**README clusters:** hold rare (eng trees, **legal docs**); human_required (people offer, finance approve, **legal clear**, marketing brand); escalate = mill `send`

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Cleared / hold** (clearance decision) | **KEEP** | Catalog product. Stub: Clearance (ship/sign allowed) or hold (blocked with reason). FL product/collab: clear / withhold, hold, approval. |
| Contract as product | **DROP** | FL product word **contract** - but contract/CLM suite is **SoR outside mill** (user + stub "not a CLM suite"). Mill coordinates clearance on a card; contract text lives in CLM/Drive/repo. |
| Redline as product | **DROP** (day-one) | FL product **redline** = exclusive edit mode -> `hold`/`drop` on doc station. Same spine under review; not a 2nd SKILL product. |
| Legal opinion / memo as product | **DROP** (day-one) | FL product **opinion** - deliverable is `note`/mail body or SoR link under the clearance card. Mode of review, not second artifact. |
| Audit trail as product | **DROP** | FL sketch: audit trail -> mail + notes (SoR). Fulfillment crumbs, not the product noun. |
| Approval / signatory chain as product | **DROP** | Collab; README human_required for clear. Gate on the clearance card, not a separate product. |
| Compliance program / policy library | **DROP** | Standing wiki/policy SoR; not day-one office artifact. |
| Litigation / discovery matter | **DROP** | Out of day-one office scope; would need human catalog row if ever. |
| NDA inventory / template bank | **DROP** | CLM/Drive SoR; card may point at one NDA clearance. |

**Kept products (day-one): 1 - Cleared / hold** (modes: clear/approve ship-or-sign; withhold/hold with reason; redline under exclusive `hold`; counsel escalate as handoff).

---

## Product (kept) - Cleared / hold

**Artifact (one sentence):** A durable clearance decision - **cleared** (ship/sign/close allowed) or **hold/withheld** (blocked with reason) - mailed so eng/sales/finance dependents can unlock or stay `waiting_on`; not a CLM suite and not silent greenlight.

**Not the product:** owning the contract file as SoR, rewriting eng ship, CRM stage advances, finance ledger approve, policy-wiki authorship.

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Review ask (contract/compliance/ship gate) | **Yes** | `inbox` / mail; or human chat -> `create todo` |
| Artifact pointer (contract id, doc path, PR/ship card, deal id) | **Yes** | todo `detail` / `doing`; **link** CLM/Drive/forge SoR - don't paste full contract |
| What is being gated (ship / sign / close / publish) | **Yes** | detail; name dependent eng/sales/finance cards if known |
| Owner / counsel desk | **Yes** | `claim` / `assign` |
| Redline / exclusive edit need | When editing shared doc | `hold` / `drop` on the doc res name (FL: review -> claim + hold on doc) |
| Human signatory / clear authority | **When clearing** | **`human_required`** gate (README cluster: legal clear) before Pass-equivalent mail |
| Counsel / specialist dest | When escalate | `send` dest=desk/role |
| Dependent cards to unblock or keep waiting | When clear or withhold | waiting_on on eng/sales (+ note); unlock via mail after clear |

Not inputs: "just approve this" with no artifact pointer, silent clear in chat with no mail, full contract body dumped into mill as SoR.

### Done looks like (this product)

- **Clear:** human_required satisfied (when office requires); clear/approve mailed (Pass-equivalent); dependent eng/sales cards unblocked; legal card `pass`ed.
- **Hold / withhold:** reason `note`d + mailed; dependent ship/deal cards left `waiting_on` with owner; legal card `pass`ed (decision rendered) **or** stays claimed if still negotiating - never silent open with no mail.
- Redline mode: `hold` taken before exclusive edit; `drop` after; trail in `note`/mail (SoR crumbs).
- Never unlock ship while legal `waiting_on` remains (stub Must-not).

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `note`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
Also cite (not invent as CLI): **`human_required`** (gate pattern from README/people/finance - not a new mill command).  
`park` speech -> `create todo` with `status:"parked"` (mill-desk).

Sources for rows: **FUNCTION-LINGO.md S Legal / compliance** (required), mill-desk day-one, stub, README (Cleared / hold; hold rare legal docs; human_required legal clear; escalate = send), siblings (sales blocked legal -> waiting_on; research -> legal diligence handoff; finance human_required; eng hold on trees).

**Disambiguation (ops steward):** legal speech **"hold"** != mill `hold`.  
- **mill `hold`/`drop`** = exclusive write lease on a doc station (redline).  
- **legal hold / block ship / withhold** = `waiting_on` on the ship/deal card + withhold mail - **not** inventing a `hold-ship` CLI.

Shared spine (one table for the function):

| Their word | Source | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| contract | FL product; stub "not a CLM suite" | create todo, detail | **`create todo`** + pointer in **detail**/`note`; **CLM/Drive SoR** | reject inventing `contract` CLI; contract != mill product |
| review / review request | FL collab + sketch "claim + hold on doc"; stub | create todo, claim, inbox | **`inbox`** / **`create todo`** -> **`claim`** / **`assign`** | reject bare `create` / `open` |
| redline / exclusive edit | FL product; stub; README hold rare legal | hold, drop, note | **`hold` / `drop`** on doc station + **`note`** | hold = lock resource; drop != unclaim |
| approval (sign / clear authority) | FL product; README human_required legal clear | human_required, send, assign | **`human_required`** + **`send`** / **`assign`** as needed | not invent `approve` CLI |
| hold / block ship / withhold | FL sketch "waiting_on ship card"; stub | waiting_on, send, note | **`waiting_on`** on eng/sales card + **`send`/`note`** reason | **!=** mill `hold`; reject inventing `block`/`withhold` CLI |
| clear / approve / clear ship | FL sketch "mail Pass-equivalent; unlock eng/sales"; stub; README human_required | send, pass, human_required | **`human_required`** then **`send`** clear verdict; unlock dependents; legal card **`pass`** | reject silent clear; reject teaching `done` |
| opinion | FL product | note, send | **`note`** and/or **`send`** memo/link | deliverable under clearance card |
| audit trail | FL sketch "mail + notes (SoR)"; stub | send, note | **`send`** + **`note`** crumbs; SoR stays CLM/Drive | not a product |
| escalate to counsel | FL collab; stub | send | **`send`** counsel/specialist desk (+ optional `assign`) | never invent `escalate` command |
| take / give review | mill-desk; support/sales assign | claim, assign | **`claim` / `assign`** | - |
| drop the claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| progress / diary / redline summary | mill-desk note | note | **`note`** | note != mail |
| find review mail | mill-desk mail; stub | inbox | **`inbox`** | - |
| blocked waiting on eng/sales/finance answer | README waiting_on | waiting_on + send | **`waiting_on` + `send`/`note`** | don't fake `pass` |
| park / defer (non-urgent review) | mill-desk | create todo parked | **`create todo` `{status:"parked"}`** | reject `open` / bare `create` |
| compliance KPI / cycle time (optional) | README score row clusters elsewhere | score | **`score`** optional if office sets legal KPI | not a product; rare day-one |
| unlock eng/sales after clear | FL clear sketch; stub Done | send, pass | **`send`** unlock/Pass-equivalent; dependents clear waiting_on | never unlock while waiting_on legal remains |

**Stub lingo gaps this harvest fills:** Inputs; Handoffs; Scope; Contract SoR outside; **human_required for clear**; hold!=waiting_on disambiguation; assign/unclaim; note!=mail; pass after decision; park; optional score; reject open/yield/bare create/teaching done; opinion/audit-trail/contract as non-products.

---

## Handoffs

| To | When |
|---|---|
| **office-engineering** | Ship/release blocked or cleared; waiting_on on eng card or unlock after clear (FL: unlock eng) |
| **office-sales** | Deal/sign blocked on legal or cleared to close (sales stub: blocked legal -> waiting_on; FL: unlock sales) |
| **office-finance** | Spend/PO/contract commercial terms need finance gate; do not own ledger |
| **office-research** | Diligence facts needed before clear (research RESEARCH already hands diligence -> legal) |
| **office-marketing** | Publish/embargo / brand-legal review when policy says |
| **Counsel / specialist desk** | Escalate to counsel - `send` (stub); optional `assign` |
| **Asker / human signatory** | human_required clear; questions on redline - `send` / Wall human_required |

Pattern: README "Escalate always = mill send"; sales already maps blocked(legal) -> waiting_on + mail. Legal does not steal eng/sales claim - mail + waiting_on / unlock.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- **Silent clear without mail** (stub).
- **Unlock ship while waiting_on legal remains** (stub).
- Replace domain **Contract / CLM / e-sign / Drive doc** SoR - **link** in detail/note/mail; don't clone the contract body into mill.
- Invent mill commands for legal slang (`clear`, `withhold`, `redline`, `escalate`, `counsel` as CLI).
- Teach `done` / `open` / `yield` / bare `create` (mill-desk alpha hard-cut).
- Confuse mill **`drop`** (hold release) with **`unclaim`**.
- Confuse legal speech **"hold"** (block ship -> waiting_on) with mill **`hold`** (doc lease).
- Skip **`human_required`** on clear when office policy requires a human click.
- Pretend mill *is* Ironclad/DocuSign/CLM (FUNCTION-LINGO how-to-talk #4).
- Own eng ship, CRM stage, or finance ledger approve - hand off.

---

## Done looks like - per product

**Cleared / hold**

1. Review ask + artifact pointer were on the desk (or gap `note`d + `send`/`waiting_on`).
2. Owner `claim`ed/`assign`ed; redline used `hold`/`drop` when exclusive edit needed.
3. **Clear path:** human_required satisfied -> clear verdict `send`ed -> dependents unlocked -> legal card `pass`ed.
4. **Hold path:** reason `note`d + `send`ed; eng/sales cards stay `waiting_on` with owner; legal card `pass`ed or still claimed if negotiating - never silent open forever.
5. Audit crumbs = mail + notes; Contract SoR unchanged outside mill.

---

## Scope note

- **In:** Contract/compliance/ship-gate review -> clear or withhold; redline under doc `hold`; counsel escalate via `send`; unlock eng/sales after clear; human_required on clear.
- **Out:** CLM/e-sign as SoR, eng implement/merge, CRM pipeline stages, finance ledger, writing standing policy libraries, litigation matter management.
- **Day-one:** single product **Cleared / hold**; redline/opinion/audit = modes or crumbs, not 2nd SKILL products.
- Adapter stays thin - pull mill-desk first; one card, then STOP.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog Cleared / hold; hold rare legal docs; human_required legal clear; escalate = send; waiting_on |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S Legal / compliance | **Required** product/collab words + mill sketch (review, hold/block, clear, audit trail) |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-legal/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-sales/SKILL.md` | blocked (legal/price) -> waiting_on + mail |
| `docs/skills/office-finance/SKILL.md` | human_required approval pattern sibling |
| `docs/skills/office-people/SKILL.md` | human_required gate sibling (offer) |
| `docs/skills/office-research/RESEARCH.md` | Diligence -> legal handoff; hold rare |
| `docs/skills/office-engineering/SKILL.md` | hold on shared files pattern; ship gate peer |
| `docs/skills/office-ops/RESEARCH.md` | RESEARCH + TEMPLATE brief shape |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; note!=mail; drop!=unclaim; create todo always includes todo; no open/yield/teaching done |
| `docs/protocol/commands.md` | Confirm hold/drop/pass/score lifecycle; removed teaching CLI |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| Common CLM / contract lifecycle (review -> redline -> approve/sign) | Review = claim (+ hold on doc); approve/sign = human_required + mail; CLM stays SoR |
| Sales "blocked on legal" practice | waiting_on on deal card until clear - aligns sales stub + FL hold/block sketch |
| Compliance "hold / withhold ship" language | Distinct from mutex hold; map to waiting_on + withhold mail |

### Guesses (flagged)

- Whether **clear** always requires `human_required` vs office-optional - **user said human_required for clear**; treat as day-one default; gardener may soften per office.
- Whether legal card **`pass`es on withhold** (decision rendered) or stays open until clear - **guess**; prefer pass-on-decision + waiting_on on dependents so board doesn't fake green.
- `hold` granularity on docs (res path vs whole CLM id) - **guess**; office names resources.
- Teaching **`score`** for legal cycle-time - **guess**; optional only if office sets KPI.
- Opinion memo as optional 2nd Product later - **guess**; day-one fold under clearance card.

---

## Open questions for human / gardener

1. Is **`human_required` on every clear** hard policy, or only above a risk threshold (NDA vs MSA vs customer DPA)?
2. On **withhold**: should the legal card **`pass`** (decision done) while eng/sales stay `waiting_on`, or remain claimed until renegotiation ends?
3. Where do contract artifacts live as SoR (CLM URL, Drive path, repo res name)? Affects hold teaching and Inputs pointer line.
4. May agents **`pass`** legal after mailing clear without a human click when office has no signatory bot policy - or always block on human_required?
5. Should **opinion** ever become a 2nd Product subsection, or stay `note`/`send` under Cleared / hold?
6. Counsel escalate: prefer **`send` only** vs **`assign`** counsel desk as owner - office policy?
7. Include optional **`score`** (review cycle time) in day-one Lingo, or omit until an office sets the KPI?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Product noun | "Clearance (ship/sign allowed) or hold..." | Align README: **Cleared / hold**; keep clear vs withhold modes in body |
| Inputs section | **Absent** | Add: review ask, artifact pointer (SoR link), gated action, owner, redline hold need, human_required for clear, counsel dest, dependent cards |
| Handoffs section | **Absent** | Add table: eng, sales, finance, research, marketing, counsel, asker/signatory |
| Scope note | **Absent** | In/out; Contract SoR outside; redline/opinion/audit = modes/crumbs |
| human_required | **Missing** | Required on clear (README + user); mirror people/finance |
| Contract SoR | Implied ("not a CLM suite") | Explicit Must-not: don't replace CLM/e-sign/Drive; link only |
| Lingo -> mill | 6 rows; thin | Full FL Legal harvest; disambiguate hold vs waiting_on; assign/unclaim/note/pass/park/score |
| clear mapping | "mail verdict" only | human_required -> `send` Pass-equivalent -> unlock -> legal `pass` |
| hold / block ship | waiting_on only | Keep; stress != mill `hold` |
| Must-not | Silent clear; unlock while waiting_on | Add: SoR outside; no invent commands; HINT; drop!=unclaim; hold!=waiting_on; no skip human_required; no teaching done/open/yield |
| Done | Clear/hold mailed; dependents | Add human_required; pass-on-decision paths; no silent open |
| score / park / unclaim | Absent | Add per harvest (score optional) |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-legal/SKILL.md`. Pull mill-desk first. Do not invent commands.

```markdown
---
name: office-legal
description: >
  Use when this desk clears contracts or compliance holds on a mill office.
  Pull mill-desk first. Thin adapter - not a second mill. Product = Cleared /
  hold - not a CLM suite.
metadata:
  short-description: "Legal: cleared / hold via mill"
---

# Office - Legal -> Cleared / hold

Pull **mill-desk** first. One card, then **STOP**.

## Product
**Cleared / hold** - durable clearance decision: **cleared** (ship/sign/close
allowed) or **hold/withheld** (blocked with reason), mailed so eng/sales
dependents unlock or stay waiting_on.

Redline, opinion memo, and audit crumbs are **modes/crumbs** of this product
(same spine), not second day-one products. Contract file stays **SoR outside**
mill (CLM / e-sign / Drive) - link, don't clone.

## Inputs
On the desk **before** clear/withhold (else `note` gap + `send` / `waiting_on`):
- **Review ask** - contract/compliance/ship gate (`inbox` / mail / `create todo`)
- **Artifact pointer** - contract id, doc path, PR/ship or deal card (link SoR)
- **Gated action** - ship / sign / close / publish; name dependent cards if known
- **Owner** - `claim` / `assign`
- When redlining shared doc: ready to `hold` / `drop` the doc station
- When **clearing**: **human_required** signatory/authority before Pass-equivalent mail
- When escalate: counsel/specialist dest for `send`

Not inputs: "just approve" with no pointer; silent chat greenlight; full contract
body dumped into mill as SoR.

## Lingo -> mill
| Their word | Mill |
|---|---|
| review request | `inbox` / `create todo` -> `claim` / `assign` |
| contract (pointer) | todo `detail` / `note` link; **CLM SoR outside** |
| redline / exclusive edit | `hold` / `drop` on doc station (+ `note`) |
| approval / clear authority | `human_required` (+ `assign` / `send` as needed) |
| escalate to counsel | `send` (optional `assign`) |
| hold / block ship / withhold | waiting_on on eng/sales card + `send`/`note` reason (**!=** mill `hold`) |
| clear / approve | `human_required` -> `send` Pass-equivalent -> unlock dependents -> legal `pass` |
| opinion | `note` and/or `send` memo/link |
| audit trail | `send` + `note` crumbs (SoR stays outside) |
| drop the claim | `unclaim` |
| progress / diary | `note` (not mail) |
| blocked on others | waiting_on + `send` / `note` |
| park / defer | `create todo` `{status:"parked"}` |
| cycle-time KPI (optional) | `score` |

## Handoffs
| To | When |
|---|---|
| Engineering | Ship/release blocked or cleared |
| Sales | Deal/sign blocked on legal or cleared to close |
| Finance | Commercial/PO terms need finance gate |
| Research | Diligence facts before clear |
| Marketing | Publish/embargo legal review |
| Counsel desk | Escalate to counsel |
| Asker / human signatory | human_required clear; redline questions |

## Must-not
- Bypass mill-desk HINT routing.
- Silent clear without mail; unlock ship while waiting_on legal remains.
- Replace Contract/CLM/e-sign/Drive SoR - link paths only.
- Invent mill commands for legal slang (`clear`, `withhold`, `redline`, `escalate` as CLI).
- Teach `open` / `yield` / bare `create` / `done`.
- Confuse `drop` (hold) with `unclaim`; confuse legal "hold" (block ship) with mill `hold`.
- Skip `human_required` on clear when office requires it.
- Own eng ship, CRM stages, or finance ledger.

## Done looks like
- Clear or withhold mailed; human_required satisfied on clear; dependents
  unlocked or still waiting_on with owner; legal card `pass`ed or clean
  waiting_on - never silent open forever.
```
