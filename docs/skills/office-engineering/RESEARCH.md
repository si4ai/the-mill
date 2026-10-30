# RESEARCH - office-engineering

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward, dry, cite-first. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-engineering \| Working software (not other eng) \| product** |
| Folder | `docs/skills/office-engineering/` exists |
| Stub | Thin `SKILL.md` present (Product = Working software; Inputs; When + Verbs; Handoffs; Must-not; Done - no Scope; Lingo is need-oriented Verbs table, not TEMPLATE Their-word -> Mill; When!=TEMPLATE-only Inputs) |
| FUNCTION-LINGO.md | Present - S **Engineering / build** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked; reject `open` / `yield` / bare `create` / teaching `done` |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-qa (`RESEARCH.md` + SKILL), office-ops (`RESEARCH.md` + SKILL) read |

**Function:** office-engineering  
**README product noun:** Working **software** (not other eng). Wake note: working software/package; **Forge PRs stay SoR**.

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Working software / package** | **KEEP** | Catalog product. Stub: change users/agents can run (merged code, published package, live service behavior). README: working software (not other eng). Wake: software/package. |
| Pull request / change as product | **DROP** | FL sketch: PR/change -> todo (implement) + hold on tree. Forge PR is **SoR** (README wake; stub Must-not: invent commands for git/CI slang - PR/merge stay forge SoR + card). Card coordinates; PR is not the mill artifact. |
| Code review / approve as product | **DROP** | FL collab + sketch: review/approve -> mail handoff; optional second desk claim. Collab move, not shippable eng artifact. |
| Merge / ship ceremony as product | **DROP** | FL sketch: note progress; done after Pass/pack gate. Merge stays forge SoR; mill `pass` closes card after gate. |
| RC / release / GA / changelog as product | **DROP** (day-one) | FL sketch: RC/release -> pack cut; Validator remasure Last. Mode of ship path (pack + QA), not 2nd SKILL product. Changelog = note/SoR. |
| Hotfix as separate product | **DROP** (day-one) | FL sketch: urgent todo + ops handoff. Same implement spine + priority in detail; not a 2nd product. |
| Deploy as eng product | **DROP** | Runtime deploy/uptime = **office-ops** product. Eng may hand off; does not own "deploy succeeded." |
| Build artifact / CI green alone | **DROP** | Build/CI checks are forge/CI SoR + evidence paths; product is **runnable** change, not a green check badge. |
| Mechanical / electrical / civil eng | **DROP** | Stub Scope + description: software only; other disciplines need their own office-* later. |
| Spec / design doc as product | **DROP** | Spec clarity -> Auditor handoff (stub). Research owns decision brief. Not eng shippable. |

**Kept products (day-one): 1 - Working software / package** (modes: implement change, fix after Validator Fail, pack/tag prep after `pass` shipped - stub When).

---

## Product (kept) - Working software / package

**Artifact (one sentence):** Software that runs - merged change, published package/wheel/image, or live service behavior users/agents can exercise - coordinated on a mill card; forge PRs/CI stay systems of record.

**Not the product:** Forge PR itself, review theater, CI green badge alone, ops deploy/uptime, QA Pass/Fail evidence, mechanical/other eng disciplines.

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Card (claimed or assigned; need + detail locked enough to build, or explicit spike) | **Yes** | `claim` / `assign`; else `send` asker / park (`create todo` `{status:"parked"}`) - stub Inputs |
| Scope crumbs (repo/path, pack, or service named; acceptance in detail or linked Claims) | **Yes** | todo `detail` / `note`; link forge SoR - don't clone tree into mill |
| If remasure Fail - Validator Fail mail + evidence paths | When fix-after-fail | `inbox` Fail mail; `note` repro paths (stub; qa->eng handoff) |
| If touching shared files - ready to `hold` those paths before write | When shared tree | `hold` / `drop` on the res name (FL: PR/change + hold on tree; stub) |
| Claims / acceptance pointer for remasure ask | Before ask remasure | detail / Claims; then `send` validator (stub Ask remasure) |

Not inputs: vague "make it better," no card, implementing while QA owns Pass/Fail (stub).

### Done looks like (this product)

- Behavior/package exists; Claims mail has evidence; card closable after Pass (stub Done).
- Implement card: `pass` (claimed->shipped) after work ready for remasure/pack; `pass` again to done after Pass gate / office close path (mill-desk: `pass` advances shipped->done; stub "Close after Pass").
- Or clean `waiting_on` (blocked on review/QA/ops/human) **or** parked - never silent open forever / claimed+100% without `pass` (stub Must-not).
- Forge PR merged/published package is **evidence in SoR**, pointed from `note`/`send` - mill does not become GitHub.

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `note`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk). `label-add` for bugs is mill-desk idiomatic (stub) - cite, not invent. Tree attach/move = when said, not day-one teach (mill-desk).

Sources for rows: **FUNCTION-LINGO.md S Engineering / build** (required), mill-desk day-one, stub, README (working software; hold rare eng trees; Prove it -> Claims + QA; escalate = send; forge SoR), siblings (qa Claims/Fail; ops deploy/incident).

Shared spine (one table for the function):

| Their word | Source | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| change / implement work | FL product; stub Product | create todo, claim | **`create todo`** then **`claim`/`assign`** | reject bare `create` / `open` |
| branch | FL product | note, detail | **`note`/detail** pointer to forge branch | branch lives in forge SoR - no `branch` mill command |
| pull request (PR) | FL sketch "todo (implement) + hold on tree"; README forge PR SoR | create todo, hold, note | **todo card** + optional **`hold`** on tree/paths; **link PR in `note`/detail** | reject inventing `pr`/`open-pr` CLI; PR != mill product |
| review / code review | FL collab + sketch "mail handoff; optional second desk claim" | send, claim | **`send`** reviewer desk; optional second **`claim`** | collab, not product |
| approve / request changes | FL product/collab | send, note | **`send`** + **`note`** on card | forge review UI stays SoR |
| merge | FL sketch "note progress; done after Pass/pack gate" | note, pass | **`note`** merge/link; **`pass`** after Pass/pack gate | merge = forge SoR action |
| ship | FL collab; mill-desk "ship it" -> pass | pass, note, send | **`pass`** (lifecycle); Claims **`send`** as needed | reject teaching `done` |
| build / CI checks | FL product/collab | note, waiting_on | **`note`** CI links/paths; **`waiting_on`** if red blocks | CI = SoR; no `ci` command |
| artifact (wheel/image/package) | FL product; stub published package | note, pass | **`note`** artifact path/id; card **`pass`** when shippable | package is product mode of working software |
| release candidate (RC) / release / GA | FL sketch "pack cut; Validator remasure Last" | note, send, pass | pack cut + **`send`** validator (Last remasure); **`pass`** after gate | not 2nd product; reject `release` CLI |
| hotfix | FL sketch "urgent todo + ops handoff" | create todo, claim, send | **`create todo`** (priority in detail) -> **`claim`** -> **`send`** ops when runtime | same spine |
| changelog | FL product | note | **`note`** / SoR doc link | not a command |
| contributor / maintainer | FL collab | claim, assign, presence | **`claim`/`assign`**; presence glance | roles, not commands |
| reviewer | FL collab | send, claim | **`send`** / optional **`claim`** | - |
| merge queue | FL collab | waiting_on, note | **`waiting_on` + `note`** | forge queue SoR |
| bug / issue | mill-desk; stub New eng card/bug | create todo + label | **`create todo`** + `label-add ... bug` | - |
| take card / I'll implement | mill-desk; stub Take card | claim, assign | **`claim` / `assign`** | - |
| drop the claim | mill-desk; stub | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| exclusive tree/file | FL hold on tree; stub; README hold rare eng | hold / drop | **`hold` / `drop`** | hold = lock resource; drop != unclaim |
| progress / Claims paths | stub; mill-desk note | note | **`note`** | note != mail |
| ask remasure / Claims ready | stub Handoffs/Verbs; README Prove it | send | **`send`** -> validator/QA with Claims | escalate pattern = send |
| Validator Fail / fix after remasure | stub Inputs/When; qa RESEARCH | inbox, claim, note | **`inbox`** Fail -> **`claim`**/`note` fix -> re-`send` Claims | - |
| close after Pass | stub; mill-desk pass lifecycle | pass | **`pass`** (again to done per office) | reject teaching `done` |
| blocked (review/QA/CI/ops) | README waiting_on | waiting_on + send | **`waiting_on` + `send`/`note`** | don't fake `pass` |
| park / spike later | mill-desk; stub park | create todo parked | **`create todo` `{status:"parked"}`** | reject `open` / bare `create` |
| find eng mail / Fail | mill-desk mail | inbox | **`inbox`** | - |
| eng KPI (optional) | README score row clusters exclude eng | score | **`score`** only if office sets eng KPI | omit unless office KPI - not README cluster |
| deploy / incident runtime | FL deploy word; stub Handoffs Ops | send | **`send`** ops - eng does not own uptime product | ops SoR/runtime |

**Stub lingo gaps this harvest fills:** TEMPLATE Their-word table (vs need-only Verbs); FL PR/review/merge/RC/hotfix/ship mapped with forge-SoR discipline; waiting_on; assign explicit; park; score optional; reject open/yield/bare create/teaching done; CI/merge queue; changelog; contributor roles; deploy!=eng product.

---

## Handoffs

| To | When |
|---|---|
| **Validator / office-qa** | Claims ready - `send` with Claims/evidence ask; remasure (stub; qa inbox Claims) |
| **office-ops** | Deploy/incident needs runtime; hotfix runtime impact (stub; FL hotfix -> ops handoff) |
| **office-support** | User-facing regression context (stub) |
| **Auditor** | Spec unclear / congruence (stub) |
| **Reviewer desk (eng peer)** | Review/approve ask - `send`; optional second claim (FL) |
| **Asker** | Blocked / need clarification - `send` + waiting_on |

Pattern: README "Escalate always = mill send"; qa Fail->Engineering; ops->Engineering for code fix. Eng does not steal QA Pass/Fail or ops uptime - mail + card ownership stay clear.

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- Final Pass/Fail (QA hat) - stub.
- Ship without a visible card - stub.
- Leave claimed+100% without `pass` - stub.
- Invent mill commands for git/CI slang (`pr`, `merge`, `rebase`, `ci`, `release` as CLI) - stub; FL how-to-talk #4.
- Replace forge (GitHub/GitLab), CI, artifact registry, package index - **link** in note/mail; don't clone.
- Teach `open` / `yield` / bare `create` / `done` (mill-desk alpha hard-cut #60).
- Confuse `drop` (hold release) with `unclaim`.
- Confuse forge "approve/merge" with mill `pass` - `pass` closes/advances the **card** after office Pass/pack gate.
- Own ops deploy/uptime or QA remasure verdict - hand off.
- Pretend mill *is* Jira/GitHub (FUNCTION-LINGO how-to-talk #4).
- Scope-creep into mechanical/electrical/civil eng (stub).

---

## Done looks like - per product

**Working software / package**

1. Card + scope crumbs were on the desk (or waiting_on/parked mailed).
2. Implement under claim; `hold`/`drop` shared paths when needed; progress/`note`d (PR/artifact links in SoR).
3. Claims `send`ed to validator when remasure needed; Fail path: inbox -> fix -> re-send.
4. Behavior/package runnable; evidence paths on Claims mail; card `pass`ed after Pass/pack gate (shipped->done as office says) **or** clean waiting_on **or** parked - never silent claimed forever.
5. Ops/support/auditor mailed when ball leaves eng.

---

## Scope note

- **In:** Software implement on claimed cards; bug/`create todo`; shared-tree `hold`; Claims ask + fix-after-Fail; pack/tag prep after shipped; hotfix as urgent same spine + ops handoff.
- **Out:** QA Pass/Fail ownership, ops deploy/uptime product, forge PR database, other eng disciplines, inventing git CLI as mill commands.
- **Day-one:** single product **Working software / package**; RC/release/hotfix/review = **modes** or collab, not second SKILL products. Forge PRs stay SoR.
- Adapter stays thin - pull mill-desk first; one card, then STOP.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog row Working software; hold rare eng trees; Prove it -> Claims + QA; escalate = send; forge coordination layer |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S Engineering / build | **Required** product/collab words + mill sketch (PR/change, review/approve, merge/ship, RC/release, hotfix) |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-engineering/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-qa/SKILL.md` + `RESEARCH.md` | Claims/Fail handoff mirror; Pass mail -> asker/eng `pass`; RESEARCH shape |
| `docs/skills/office-ops/SKILL.md` + `RESEARCH.md` | Deploy/incident handoff; hotfix runtime; RESEARCH shape |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; note!=mail; drop!=unclaim; create todo always includes todo; pass lifecycle; no open/yield/teaching done |
| `docs/protocol/commands.md` | Confirm create todo / unclaim replaces yield / pass shipped->done; hold/drop; score |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| GitHub PR / review glossary (PR, review, approve, request changes, merge) | PR + review UI = forge SoR; mill card + mail handoff for collab intent - aligns FL sketch + README "Forge PRs stay SoR" |
| Release / RC / GA common practice | Pack/cut + validation gate before GA - FL RC/release -> pack cut + Validator remasure Last |
| Hotfix practice | Urgent change + runtime awareness - FL urgent todo + ops handoff |

### Guesses (flagged)

- Whether **published package** vs **merged service change** should split into two Product subsections - **guess**; catalog/stub treat as one "working software"; wake says software/package as one noun family.
- Teaching **`pass` twice** (shipped then done) in Lingo vs one "close after Pass" row - mill-desk lifecycle is two `pass` advances; gardener should stay accurate without teaching `done`.
- Eng desk **`score`** (cycle time, escape) - **guess**; README score row cluster excludes eng - omit unless office sets KPI.
- `hold` granularity (repo vs file res name) - **guess**; office names resources; stub says paths before write.

---

## Open questions for human / gardener

1. Keep **one** product (Working software / package with implement / Fail-fix / pack modes), or split **merged change** vs **published package** into two Product subsections now?
2. After Validator Pass mail: does eng **`pass`** implement card to done, or does asker/validator close per office policy? (Stub: eng closes after Pass; qa RESEARCH favors asker - confirm.)
3. Is **`pass` -> shipped** the remasure-ready state (Claims sent), with second `pass` -> done only after Pass - teach both in Lingo?
4. Where do artifact paths live as SoR (wheel index, container registry, forge release)? Affects Done path line and hold teaching.
5. Should `score` appear in office-engineering map day-one (lead time / fail rate)?
6. Hotfix: always `send` ops, or only when runtime/prod impact?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Lingo -> mill table | "Verbs (mill)" need-oriented | TEMPLATE Their word -> Mill; full FUNCTION-LINGO Engineering/build harvest |
| Scope note | Partial in intro ("software... other disciplines") | Explicit In/out; RC/hotfix/review = modes/collab; forge PR SoR |
| waiting_on / assign / park / inbox | assign implicit; waiting_on/park/inbox thin or absent in Verbs | Add explicitly; park = create todo parked |
| FL rows: review, merge, RC, hotfix, CI, changelog | Missing or only ship/pass | Map with forge-SoR discipline |
| score | Absent | Optional/omit unless office KPI |
| Product noun | "Working software..." | Align README + wake: **Working software / package**; forge PRs stay SoR in Must-not/Product |
| Done | Behavior/package; Claims evidence; closable after Pass | Add waiting_on/parked; pass lifecycle shipped->done; no silent claimed+100% |
| Must-not | Pass/Fail; no card; claimed+100%; invent git commands | Add: HINT bypass; drop!=unclaim; no open/yield/done; no ops/QA ownership; SoR link-only |
| Inputs | Present and strong | Keep; fold When triggers lightly; ensure Fail-mail + hold called out (already) |
| Multi-product clarity | Single Product OK | Explicit one kept; dropped listed in RESEARCH only |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-engineering/SKILL.md`. Pull mill-desk first. Do not invent commands.

```markdown
---
name: office-engineering
description: >
  Use when this desk is shipping working software (code, package, API, service
  behavior) on a mill office. Pull mill-desk first. Thin adapter - not a second
  mill. Product = working software/package - not forge PR theater or other eng
  disciplines. Forge PRs stay SoR.
metadata:
  short-description: "Software eng: working software/package via mill"
---

# Office - Engineering (software) -> Working software / package

Pull **mill-desk** first. One card, then **STOP**.

**Scope:** software that runs (merged change, wheel/image, service behavior).
Other engineering disciplines = different product + inputs -> separate skills later.
Forge PRs/CI stay systems of record; mill coordinates the card.

## Product
**Working software / package** - change users/agents can run (merged code,
published package, live service behavior).

Review, RC/release, and hotfix are **modes or collab** on this spine (same
commands), not second day-one products. The PR object lives in forge SoR - link it.

## Inputs
On the desk **before** implement (else `note` gap + `send` asker / `waiting_on`
or `create todo` `{status:"parked"}`):
- **Card** - claimed or assigned; need + detail locked enough to build (or explicit spike)
- **Scope crumbs** - repo/path, pack, or service named; acceptance in detail or linked Claims
- **If remasure Fail** - Validator Fail mail + evidence paths (`inbox`)
- **If touching shared files** - ready to `hold` those paths before write

Not inputs: vague "make it better," no card, or implementing while QA owns Pass/Fail.

## Lingo -> mill
| Their word | Mill |
|---|---|
| change / bug / feature | `create todo` (+ `label-add ... bug` when bug) |
| take / give work | `claim` / `assign` |
| drop the claim | `unclaim` |
| PR / branch | todo card + link in `detail`/`note`; forge SoR (not a mill PR command) |
| exclusive tree/file | `hold` / `drop` |
| progress / CI links / artifact path | `note` (diary; not mail) |
| review / approve / request changes | `send` reviewer (+ optional second `claim`); forge review SoR |
| ask remasure / Claims ready | `send` -> validator/QA with Claims |
| Validator Fail / re-fix | `inbox` -> fix on card -> `note` -> re-`send` Claims |
| merge / ship | `note` forge merge/link; `pass` after Pass/pack gate |
| RC / release / pack Last | pack cut + `send` validator; `pass` after gate |
| hotfix | urgent `create todo`/`claim` + `send` ops when runtime |
| blocked (review/QA/CI/ops) | waiting_on + `send` / `note` |
| park / spike later | `create todo` `{status:"parked"}` |
| find Fail / eng mail | `inbox` |
| close after Pass | `pass` (shipped->done per mill-desk; no teaching `done`) |
| eng KPI | `score` (only if office sets it) |

## Handoffs
| To | When |
|---|---|
| Validator / QA | Claims ready; remasure ask |
| Ops | Deploy/incident needs runtime; hotfix prod impact |
| Support | User-facing regression context |
| Auditor | Spec unclear / congruence |
| Reviewer (peer) | Review/approve ask |

## Must-not
- Bypass mill-desk HINT routing.
- Final Pass/Fail (QA hat); own ops uptime/deploy product.
- Ship without a visible card; leave claimed+100% without `pass`.
- Replace forge/CI/registry SoR - link paths; invent git/CI mill commands (`pr`, `merge`, `release` as CLI).
- Teach `open` / `yield` / bare `create` / `done`.
- Confuse `drop` (hold) with `unclaim`; confuse forge approve/merge with mill `pass`.

## Done looks like
- Behavior/package exists; Claims mail has evidence paths; implement card `pass`ed
  after Pass/pack gate (or clean waiting_on / parked).
```
