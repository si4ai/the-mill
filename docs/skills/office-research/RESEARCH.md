# RESEARCH - office-research

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward. Gap-fill for thin stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-research \| Decision brief \| product** |
| Folder | `docs/skills/office-research/` exists |
| Stub | Thin `SKILL.md` present (product mush; no Handoffs / Inputs / Scope) |
| FUNCTION-LINGO.md | **Absent** on box (`docs/FUNCTION-LINGO.md` missing; README still links it) - lingo harvested from stub + siblings + mill-desk + public practice |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked |
| Sibling handoff patterns | office-qa, office-support, office-engineering, office-ops read |

**Function:** office-research  
**README product noun:** Decision brief

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table.

| Candidate | Verdict | Why |
|---|---|---|
| **Decision brief** | **KEEP** | Catalog product. Named ask -> options/recommendation -> answerable decision. Matches industry BLUF / exec-brief shape. |
| Competitive / market scan | **DROP** (as separate product) | Without a decision ask it becomes a wiki dump / newsletter. When the ask *is* competitive, treat as **Decision brief mode** (same card spine; detail names competitors + decision). Revisit as 2nd product only if office runs standing CI cadence. |
| Literature / source synthesis | **DROP** | Synthesis is a **step** inside a brief, not a shippable product. Alone = library dump. |
| Due diligence pack | **DROP** (day-one) | Overlaps office-legal / office-finance SoR and human_required gates. Research may *feed* diligence via handoff; not own the cleared/hold product. |
| Eng design docs / QA evidence / wiki dump | **DROP** | Wrong desk: eng / qa / none. Stub already warns against eng-ship confusion. |

**Kept products (day-one): 1 - Decision brief.**

---

## Product (kept) - Decision brief

**Artifact (one sentence):** A path-addressable brief others can decide from - BLUF, options (incl. do-nothing), recommendation, confidence/limits, dated sources - not a research diary.

**Not the product:** raw notes piles, unread source dumps, eng design docs, QA Pass/Fail packs, marketing "brief" (that's a campaign ask on office-marketing).

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Decision ask (what decide / by when / who decides) | **Yes** | `create todo` need+detail; if missing -> `replace-body` gap + mill `send` asker / `waiting_on` |
| Audience / decide desk | Yes | detail + later `send` |
| Scope bounds (in/out, competitors, time window) | Strong | detail |
| Source hints / prior briefs | Optional | detail URLs; SoR stays outside mill |
| Constraints (budget, legal, launch date) | When known | detail; hand off legal/finance if gate |

### Done looks like (this product)

- Brief **path** on card (`replace-body` / detail).
- Asker (or decide desk) **mailed** (`send`) with path + the ask restated.
- Card **`pass`** when brief is decision-ready **or** clean **`waiting_on`** (SME/source/human) **or** **`parked`** (deferred ask - no fake done).
- Decision *outcome* is **not** required for research Done - asker notes decide / park; research may `replace-body` the decision if told, then `pass` if still open.

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `replace-body`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`, mail as needed.  
**Do not teach:** `open`, `yield`, bare `create`, `done` as speech.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk). `unpark` exists on mill-desk but is not in the day-one teaching list above - mention only if human says unpark; do not invent.

Shared spine (one table for the function):

| Their word | Source | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| research ask / intake | stub; CI practice "set the decision first" | create todo, open | **`create todo`** | reject `open` (not day-one teach) |
| park / file for later | mill-desk; stub "park" | create todo parked, plan upcoming | **`create todo` `{status:"parked"}`** | reject stub "plan upcoming / parked" - not a mill command |
| take / draft brief | stub | claim, assign | **`claim`** (+ `assign` if given) | - |
| drop claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| progress / path / diary | stub "replace-body path"; mill-desk | todo --eta/--started/--progress | **`todo <roster> <need> --eta E`** / `--started` / `--progress 9/12` | replace-body != mail |
| synthesize / revise findings | stub | replace-body, detail update | **`replace-body`** (path + deltas) | no new command |
| challenge / peer review | stub | send, claim steal | **`send`** | handoff != steal; reviewer claims own card or replies mail |
| need eyes / escalate | README pattern | send | **`send`** | escalate always = send to specialized desk |
| blocked on SME / source / access | README waiting_on | waiting_on + send | **`waiting_on` + `send`** | don't fake `pass` |
| check mail / review ask landed | mill-desk; qa inbox pattern | inbox | **`inbox`** | - |
| deliver brief / ready to decide | industry "ends in ask"; mill pass | pass, send | **`send`** asker + **`pass`** | stub conflated deliver with "decide" - split |
| decide / record decision | stub | replace-body, pass | **`replace-body`** decision (asker or research if told) | research does not invent a decide command; optional `pass` if card still open |
| exclusive edit of shared brief file | eng hold pattern | hold / drop | **`hold` / `drop`** | rare; only if office uses resource lease on brief path |
| throughput / brief SLA | README score clusters | score | **`score`** optional | research not in README score row cluster - teach thin or omit day-one unless office sets KPI |
| unpark / reopen | mill-desk | unpark | *(not day-one teach)* | if human says it, mill-desk covers; don't put in office map unless needed |

**Stub lingo gaps this harvest fills:** waiting_on, inbox/mail, hold/drop nuance, pass vs decide split, park = create todo parked, score optional, assign/unclaim.

---

## Handoffs

| To | When |
|---|---|
| **Asker / decide desk** (often eng lead, sales, marketing, ops, office human) | Brief ready - `send` path + restated ask; or missing decision criteria |
| **office-engineering** | Brief recommends build/fix; spawn/assign eng todo or mail eng with brief path |
| **office-qa** | Brief claims need remasure (rare) - evidence question, not implement |
| **office-ops** | Runtime/incident/capacity question in brief |
| **office-support** | Customer/field signal needed for the ask |
| **office-sales / office-marketing** | Competitive or launch decision owned there; research delivers brief, they own stage/launch |
| **office-legal / office-finance** | Diligence, spend, contract, clearance gates - do not clear inside research |
| **Auditor / mill-desk patterns** | Spec/congruence gap blocks the ask (same spirit as qa->Auditor) |

Pattern borrow: support "escalate = send + eng todo + waiting_on"; eng/qa Handoffs tables. Research never "ships" eng.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- Invent mill commands for analyst slang (no `brief`, `synthesize`, `decide` CLI).
- Replace domain SoR: source repos, Drive/wikis, CI databases, CRM, ticketing - **link in detail**, don't clone.
- Confuse brief delivery with **eng ship** or **QA Pass**.
- Endless research with no `pass` / `waiting_on` / `parked` path.
- Treat marketing creative "brief" or eng design doc as this product.
- Rubber-stamp a decision without a path-addressable artifact the asker can open.
- Use `drop` to mean unclaim (hold-only).

---

## Done looks like - per product

**Decision brief**

1. Card exists; owner claimed while drafting.
2. Brief path on card; sources dated in brief (artifact), not only in chat.
3. Decide desk mailed; waiting_on clear if blocked.
4. `pass` when decision-ready **or** parked when deferred **or** waiting_on when blocked - never silent open forever.

---

## Scope note

- **In:** Decision-ready briefs on a mill office; competitive/market *asks* that still end in a decision; source synthesis *as work toward* that brief.
- **Out:** Standing wiki maintenance, eng implementation, QA remasure, CRM pipeline, legal clearance, finance approval, marketing publish.
- **Day-one:** single product map; competitive scan is a **mode** of Decision brief, not a second SKILL product.
- Adapter stays thin - pull mill-desk first; one card, then STOP.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog row; general mapping; waiting_on + score row patterns; FUNCTION-LINGO link (file missing) |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Lingo, Handoffs, Must-not, Done |
| `docs/skills/office-research/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-qa|support|engineering|ops/SKILL.md` | Handoff / inbox / waiting_on / must-not patterns |
| `docs/skills/office-sales|marketing/SKILL.md` | waiting_on + score; "brief" noun collision (marketing) |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; park = create todo parked; replace-body!=mail; drop!=unclaim |
| `docs/protocol/improve.md` | Decide -> one create todo; parked pile anti-pattern |
| `/workspace/mill-docs/MILL-OFFICE-SKILL-SCOUT.md` | Scout loop: research book -> TEMPLATE brief -> gardener |
| `/workspace/mill-docs/MILL-PROMPT-GARDENER.md` | Gardener owns SKILL patch; no invent commands |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| Flares - CI Executive Brief template | One-page; decision + deadline + owner; options incl. do-nothing; ends in answerable ask; link full analysis - **not** a report dump ([flares.tech CI executive brief](https://www.flares.tech/templates/competitive-intelligence-executive-brief-template)) |
| Seeto - CI report template 2026 | Recommendations specific/owned/time-bound; claims traceable to dated sources; interpretation > description ([seeto.ai](https://seeto.ai/blog/competitive-intelligence-report-template-2026)) |
| Unkover - CI practitioner guide 2026 | Set the decision before collecting data; summary first; cadence != product ([unkover.com](https://unkover.com/blog/competitive-intelligence-report/)) |
| 1200km CTI exec summary fields | decision, bottom_line, why_now, confidence, impact, actions, limits, owner - good brief checklist ([1200km](https://1200km.com/cti-analyst-field-manual/docs/templates/executive-summary/)) |

### Guesses (flagged)

- Office may later want standing **CI cadence** as 2nd product - **guess**; not evidenced in README.
- Research KPI via `score` - **guess**; README does not cluster research with score row functions.
- `hold` on brief files - **guess** unless office resources lease doc paths; eng-shaped, rare here.

---

## Open questions for human / gardener

1. Is **Decision brief** the only day-one product, or should competitive scan get its own Product subsection now?
2. Does research Done require the **decision outcome** noted, or only **brief delivered + mailed**? (Research recommends the latter.)
3. Where do brief files live as SoR (Drive, repo path, mill resource)? Affects hold teaching.
4. Restore or drop README link to missing `FUNCTION-LINGO.md`?
5. Any office-standard brief template path to cite inside SKILL Done line?
6. Should `score` appear in the office-research map at all for day-one?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Handoffs section | Absent | Add table (asker, eng, qa, ops, support, sales/marketing, legal/finance) |
| Inputs | Absent | Decision ask, audience, scope, sources |
| Scope note | Absent | In/out; competitive = mode not 2nd product |
| Product separation | "Brief / findings / recommendation" mush | Single product: **Decision brief**; findings/recommendation are sections inside it |
| Lingo thin | 6 rows | Expand: waiting_on, inbox, pass vs decide, park=create todo parked, assign/unclaim, optional hold/score |
| mail / waiting_on / score | Missing | send+inbox; waiting_on+mail; score optional/omit |
| Multi-product | N/A mush | Explicit one kept; dropped listed in RESEARCH only |
| Done | "decision noted or parked" | Prefer brief path + mail + pass/waiting_on/parked; decision is asker's |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-research/SKILL.md`. Pull mill-desk first. Do not invent commands.

```markdown
---
name: office-research
description: >
  Use when this desk produces decision-ready briefs on a mill office.
  Pull mill-desk first. Thin adapter - not a second mill. Product = Decision
  brief (path + options + ask) - not a wiki dump, eng ship, or QA pack.
metadata:
  short-description: "Research: Decision brief via mill"
---

# Office - Research -> Decision brief

Pull **mill-desk** first. One card, then STOP.

## Product
**Decision brief** - path-addressable artifact others can decide from (BLUF, options incl. do-nothing, recommendation, confidence/limits, dated sources).

Competitive/market *asks* use this same product (mode in detail), not a second product.

## Inputs
- Decision ask (what / by when / who decides) - if missing: `replace-body` + `send` asker / `waiting_on`
- Audience / decide desk; scope bounds; optional source hints

## Lingo -> mill
| Their word | Mill |
|---|---|
| research ask | `create todo` |
| park / later | `create todo` `{status:"parked"}` |
| take / draft | `claim` / `assign` |
| drop the claim | `unclaim` |
| progress / brief path | `todo <roster> <need> --eta E` / `--started` / `--progress 9/12`; the brief path is card text (`replace-body`) |
| synthesize / revise | `replace-body` |
| challenge / review | mill `send` |
| blocked (SME/source) | `waiting_on` + `send` |
| check asks / review mail | `inbox` |
| deliver brief | `send` asker + `pass` |
| record decision | `replace-body` (asker; research if told) |
| exclusive brief file | `hold` / `drop` (rare) |
| throughput KPI | `score` (only if office sets it) |

## Handoffs
| To | When |
|---|---|
| Asker / decide desk | Brief ready or ask incomplete |
| Engineering | Brief recommends build/fix |
| QA | Remasure question (not implement) |
| Ops | Runtime / capacity in ask |
| Support | Field/customer signal needed |
| Sales / Marketing | They own pipeline/launch decision |
| Legal / Finance | Clearance, spend, diligence gates |

## Must-not
- Bypass mill-desk HINT routing.
- Replace source/wiki/CRM/Drive SoR - link in detail.
- Invent mill commands for analyst slang.
- Confuse brief delivery with eng ship or QA Pass.
- Endless research without `pass` / `waiting_on` / `parked`.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Brief path on card; decide desk mailed; card `pass`ed (decision-ready) or clean `waiting_on` or `parked`.
- Decision outcome optional on card (`replace-body`) - not required for research Done.
```

## FUNCTION-LINGO gap-check (2026-09-20, mill 0.4.10)

Preflight: README, TEMPLATE, `docs/skills/FUNCTION-LINGO.md`, protocol/skill.md - all readable on share.

### What FUNCTION-LINGO says (Research / knowledge)

Product words: brief, findings, decision record, recommendation.  
Collab words: review, challenge, synthesize, decide, park.  
Sketch map: brief->todo deliverable path; challenge->mail/second desk; decision->card text (replace-body) + optional plan park; park->plan upcoming / parked.

### Filter vs prior harvest (sources already in book)

| FL item | Prior RESEARCH/SKILL | Delta if FL filter ON |
|---|---|---|
| Product noun **brief** | Kept as **Decision brief** | **None** - aligned |
| **findings** / **recommendation** as product words | Collapsed to sections inside Decision brief (not SKILL products) | **None on product count** - FL lists artifact nouns, not separate mill products. Stub mush came from treating them as peers; FL+TEMPLATE still want one Product. Add **lingo rows** only (findings->card text/brief section; recommendation->brief section) |
| **decision record** | Mapped decide->`replace-body` (asker); not research Done | **Wording only** - name "decision record" in lingo as asker `replace-body` (ADR-style if office uses it). Still not a research Product |
| **challenge** / **review** | `send` | **None** - aligned (review = same collab intent) |
| **synthesize** | `replace-body` | **None** - FL lists collab word, no separate mill sketch; our fill stands |
| **park** -> "plan upcoming / parked" | `create todo` `{status:parked}`; rejected "plan upcoming" as command | **Keep our map** - FL sketch is looser; mill-desk day-one wins. Document reject of FL's "plan upcoming" phrasing as CLI |
| **decide** | `replace-body` (not a decide command) | **None** |
| waiting_on / inbox / unclaim / assign / hold / pass+send deliver | Harvested from mill-desk + siblings; **absent from FL research sketch** | **No retract** - FL is floor not ceiling. Keep expansions |
| score | Optional / omit day-one | **None** - FL research section has no score row |

### Judgment answer (host)

Would judgment change with FUNCTION-LINGO filter on? **Mostly no.**

- **Products kept/dropped:** unchanged (Decision brief only).
- **Done:** unchanged (brief path + mail + pass/waiting_on/parked; decision outcome optional).
- **Command spine:** unchanged; FL's "plan upcoming" must still be rejected against protocol/skill.md.
- **Small additive only:** surface FL's product/collab nouns as explicit Lingo rows (findings, recommendation, decision record, review) so the skill eats the dogfood glossary - no new mill commands, no second product.

Sources for this gap: `docs/skills/FUNCTION-LINGO.md` S Research/knowledge; this RESEARCH.md lingo harvest + TEMPLATE brief; current `office-research/SKILL.md` (gardener 4bc7fa3-era patch); `docs/protocol/skill.md` day-one commands.

### Gardener patch (thin, optional)

If patching: add to Lingo table only:

| Their word | Mill |
|---|---|
| findings | brief section / `replace-body` |
| recommendation | brief section (not a separate card product) |
| decision record | `replace-body` (asker; research if told) |
| review | `send` (same as challenge) |

No full redo. No product change.

