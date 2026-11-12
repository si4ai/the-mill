# RESEARCH - office-qa

Scout: Office Skill Scout (Loop-1). Date: 2026-09-20 PT.  
Voice: ops steward. Gap-fill for stub `SKILL.md`. Do **not** patch SKILL.md here - Gardener owns that.

---

## Function name + catalog check

| Check | Result |
|---|---|
| Catalog row | `docs/skills/README.md` Skills table: **office-qa \| Pass/Fail evidence \| product** |
| Folder | `docs/skills/office-qa/` exists |
| Stub | Thin `SKILL.md` present (When + Verbs; no Inputs / Scope / full Lingo->mill; When!=TEMPLATE Inputs) |
| FUNCTION-LINGO.md | Present - S **QA / validation** (product + collab + mill sketch) |
| mill-desk | `docs/protocol/skill.md` - day-one commands locked |
| Standing SoR | `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` - research book -> TEMPLATE brief -> gardener; no SKILL patch |
| Sibling handoff / RESEARCH shape | office-engineering, office-support, office-ops, office-research (+ `office-research/RESEARCH.md`) read |

**Function:** office-qa  
**README product noun:** Pass/Fail evidence

---

## Products considered -> kept / dropped

A function may have >1 product. Day-one prefer 1-2. Shared mill command spine stays **one** table. Do not smash into one vague Product.

| Candidate | Verdict | Why |
|---|---|---|
| **Pass/Fail evidence** | **KEEP** | Catalog product. FUNCTION-LINGO: pass/fail + evidence + remasure. Stub: independent evidence Claims hold (Pass / Fail / Pass-with-warnings) + how remasured. |
| Test case / suite as product | **DROP** | Test case is **method/input** (ISTQB: preconditions, inputs, expected results) - not the shippable office artifact. Paths of cases run live inside evidence. |
| Defect / bug report as product | **DROP** (as QA product) | Defect is eng/support SoR path: `create todo` + label `bug` + forge link. QA **files or returns** Fail with repro; does not own "resolved bug." |
| Sign-off as separate product | **DROP** | FUNCTION-LINGO: sign-off = Pass mail; asker may `pass`. Collab move, not a second artifact. |
| Regression pack as separate product | **DROP** (day-one) | FUNCTION-LINGO: regression -> leftover / follow-on todo. Same Pass/Fail evidence spine after change; not a 2nd SKILL product. Revisit if office runs standing regression cadence. |
| Acceptance-testing ceremony / exit-criteria checklist | **DROP** | Exit criteria = Done gate language (ISTQB), not a product. Acceptance testing = **mode** of remasure when Claims say accept. |

**Kept products (day-one): 1 - Pass/Fail evidence.**

---

## Product (kept) - Pass/Fail evidence

**Artifact (one sentence):** Independent verdict that named Claims hold or fail - Pass / Fail / Pass-with-warnings - plus remasure method and path-addressable evidence; not Builder's suite alone, not process theater.

**Not the product:** eng merge/ship, ops uptime, support ticket resolve, research decision brief, rubber-stamp without remasure.

### Inputs (per kept product)

| Input | Required? | Mill fulfillment |
|---|---|---|
| Claims (what to remasure - acceptance criteria / expected behavior) | **Yes** | Mail body and/or todo `detail`; if missing -> `replace-body` gap + `send` asker / `waiting_on` |
| Subject under test (build, pack Last, path, env, version) | **Yes** | detail; link SoR (forge, artifact store) - don't clone |
| How to remasure (black-box steps, cases, or pointer to suite) | Strong | detail; else asker mail |
| Evidence sink (where paths will live) | Strong | paths in card text on verdict; optional `hold` if exclusive write to shared evidence file |
| Prior Fail / re-test context | When re-test | same card after eng fix; Fail mail + evidence paths (eng Inputs mirror) |

Not inputs: "make quality better," implement while remasuring, Builder suite as sole proof.

### Done looks like (this product)

- Verdict **mailed** (`send`) to asker/builder: Pass / Fail / Pass-with-warnings + method + evidence paths.
- Card for the **QA remasure work**: `pass` when verdict delivered **or** clean `waiting_on` (blocked on Claims/env/human) **or** parked if deferred.
- Eng implement card: QA does **not** `pass` eng cards to done unless office policy says validator closes - asker/eng `pass` after Pass mail (FUNCTION-LINGO sign-off; stub Close row).
- Fail -> eng owns fix (handoff + optional `create todo` / bug label); re-test stays same spine when fix returns.

---

## Lingo harvest -> mill map

Day-one commands **only:** `create todo`, `claim`, `assign`, `unclaim`, `replace-body`, `send`, `inbox`, `hold`, `drop`, `pass`, `score`, `waiting_on`, mail as needed.  
**Reject:** `open`, `yield`, bare `create`, teaching `done`.  
`park` speech -> `create todo` with `status:"parked"` (mill-desk). `unpark` exists on mill-desk but is not day-one teach unless human says it.

Sources for rows: **FUNCTION-LINGO.md S QA / validation** (required), mill-desk day-one, stub, README general mapping ("Prove it -> Claims + QA remasure"), siblings.

Shared spine (one table for the function):

| Their word | Source | Candidate commands | Chosen day-one | Reject / notes |
|---|---|---|---|---|
| acceptance criteria | FUNCTION-LINGO QA product; mill sketch "todo detail / Claims" | detail, replace-body, create todo | **todo `detail` / Claims mail** (`replace-body` if amending) | not a CLI command; live on card/mail |
| test case | FUNCTION-LINGO QA product; ISTQB test case | replace-body paths | **`replace-body`** (case id/path + expected vs actual in evidence) | no `test` / `case` mill command |
| expected vs actual | FUNCTION-LINGO QA product | replace-body, send body | **`replace-body`** + verdict **`send`** | - |
| pass / fail (verdict) | FUNCTION-LINGO sketch "mail verdict + evidence paths"; stub Verdict | send, pass | **`send`** asker/builder (verdict + paths) | reject teaching mill `pass` as synonym for test Pass - different senses |
| remasure / independent verify | FUNCTION-LINGO collab; stub Remasure | claim, inbox, replace-body | **`inbox`** (Claims) -> **`claim`** remasure card -> black-box work -> **`replace-body`** evidence | Validator desk; **no implement** |
| confirmation test / re-test | FUNCTION-LINGO sketch "same card after eng fix" | claim, replace-body, send | **same card**: `claim`/`send` again | not a new command; not auto-`pass` eng |
| regression | FUNCTION-LINGO sketch "leftover / follow-on todo" | create todo, leftover | **`create todo`** follow-on (or leftover) + same remasure spine | reject inventing `regress` command |
| defect / bug | FUNCTION-LINGO product; mill-desk bug idiom | create todo + label | **`create todo`** + `label-add ... bug`; **`send`** eng | SoR may also be forge Issue (support pattern) |
| reject / send back | FUNCTION-LINGO collab | send | **`send`** Fail + repro/evidence | handoff != claim steal |
| sign-off | FUNCTION-LINGO sketch "Pass mail; asker may pass" | send, pass | **`send`** Pass mail; **asker/eng `pass`** card | QA `pass` only on *QA* remasure card unless office says validator closes |
| pair testing | FUNCTION-LINGO collab | send, claim | **`send`** / second desk; **`replace-body`** | rare day-one |
| exit criteria | FUNCTION-LINGO product; ISTQB | - | Done gate language in Done / waiting_on | not a mill command |
| evidence | FUNCTION-LINGO product; README "Prove it" | replace-body, send | **`replace-body`** paths + **`send`** body | paths in SoR; mill stores pointer |
| Claims landed / find work | stub Find Claims; mill-desk mail | inbox | **`inbox`** | - |
| take remasure card | mill-desk; eng claim | claim, assign | **`claim`** / **`assign`** | - |
| drop the claim | mill-desk | unclaim | **`unclaim`** | never confuse with `drop` (hold) |
| progress / method diary | mill-desk replace-body | replace-body | **`replace-body`** | replace-body != mail |
| blocked (env, Claims, access) | README waiting_on pattern | waiting_on + send | **`waiting_on` + `send`** | don't fake Pass or card `pass` |
| exclusive evidence file | eng hold pattern; TEMPLATE | hold / drop | **`hold` / `drop`** | rare; hold = lock file, not unclaim |
| quality KPI / escape rate | README score row clusters | score | **`score`** optional | QA not in README score row cluster (ops/support/sales/marketing) - omit unless office sets KPI |
| park / defer remasure | mill-desk | create todo parked | **`create todo` `{status:"parked"}`** | reject `open` / bare `create` |

**Stub lingo gaps this harvest fills:** Inputs, acceptance criteria->detail/Claims, defect=`create todo`+bug, regression=follow-on todo, re-test=same card, sign-off vs mill `pass` split, waiting_on, assign/unclaim, hold/drop nuance, score optional, park.

---

## Handoffs

| To | When |
|---|---|
| **Asker / builder (usually office-engineering)** | Verdict ready - `send` Pass/Fail/Pass-with-warnings + method + evidence paths; or Claims incomplete |
| **office-engineering** | Fail with repro; defect `create todo` / bug label; eng Inputs already list Validator Fail mail |
| **office-ops** | Prod-only / runtime signal; need remasure in prod-like (ops Handoffs already list QA) |
| **office-support** | User-facing regression context; forge Issue already SoR - don't duplicate DB |
| **Auditor** | Spec/congruence gap blocked remasure (stub; same spirit as research->Auditor) |
| **office-research** | Rare - remasure question about a brief claim (research Handoffs list QA) |

Pattern borrow: eng "Ask remasure -> send validator"; support "escalate = send + eng todo + waiting_on"; stub Fail->Engineering / Prod->Ops / Spec->Auditor. Escalate always = mill `send`, not a new command (README).

---

## Must-not - SoR outside mill

- Bypass mill-desk HINT routing.
- Implement product fixes (stub; FUNCTION-LINGO remasure = no implement).
- Rubber-stamp without remasure; rely on Builder's suite alone (stub).
- Replace domain SoR: forge Issues/PRs, CI logs, test runners, artifact stores - **link paths** in card text/mail; don't clone suites into mill.
- Invent mill commands for ISTQB/industry slang (`remasure`, `sign-off`, `regress`, `defect` as CLI).
- Teach mill `pass` as the test Pass verdict - verdict is **mail**; card `pass` closes QA work (or eng card after asker policy).
- `pass` eng cards to done unless office says validator closes (stub Close).
- Confuse `drop` (hold release) with `unclaim`.
- Pretend mill *is* Jira/TestRail/GitHub Checks (FUNCTION-LINGO how-to-talk #4).

---

## Done looks like - per product

**Pass/Fail evidence**

1. Claims + subject under test were on the desk (or waiting_on mailed).
2. Remasure ran independent of Builder suite; method + evidence **paths** on card/`send`.
3. Asker/builder mailed with Pass / Fail / Pass-with-warnings.
4. QA remasure card `pass`ed **or** clean waiting_on **or** parked - never silent open forever.
5. On Fail: eng/support owns next (todo id or mail); re-test when fix returns.

---

## Scope note

- **In:** Independent Pass/Fail evidence on a mill office; Claims remasure; re-test after eng fix; regression as follow-on todo using the same spine; black-box / congruence checks (no implement).
- **Out:** Eng ship, ops incident close, support ticket resolve, research decision brief, owning the bug database, writing product code to clear Fail.
- **Day-one:** single product map; regression / acceptance testing = **modes** of Pass/Fail evidence, not second SKILL products.
- Adapter stays thin - pull mill-desk first; one card, then STOP.

---

## Sources

### Mill (on box)

| Source | Used for |
|---|---|
| `docs/skills/README.md` | Catalog row Pass/Fail evidence; Prove it -> Claims + QA remasure; escalate = send; waiting_on pattern |
| `docs/skills/TEMPLATE.md` | Required SKILL shape: Product, Inputs, Lingo, Handoffs, Must-not, Done |
| `docs/skills/FUNCTION-LINGO.md` S QA / validation | **Required** product/collab words + mill sketch (acceptance criteria, remasure, pass/fail, re-test, regression, sign-off) |
| `docs/skills/MILL-OFFICE-SKILL-SCOUT.md` | Loop-1 SoR: RESEARCH + TEMPLATE brief; no SKILL patch; day-one command reject list |
| `docs/skills/office-qa/SKILL.md` | Stub gap-fill baseline |
| `docs/skills/office-engineering/SKILL.md` | Claims handoff; Fail mail as eng Input; hold; asker `pass` after Pass |
| `docs/skills/office-support\|ops\|research/SKILL.md` | Handoff mirrors; waiting_on; forge SoR; research RESEARCH.md shape |
| `docs/protocol/skill.md` (mill-desk) | Day-one command lock; replace-body!=mail; drop!=unclaim; create todo always includes todo; no open/yield/teaching done |

### Public industry practice (thin)

| Cite | Takeaway for mill map |
|---|---|
| ISTQB glossary - acceptance criteria | Conditions a work product must satisfy for acceptance -> live in Claims / todo detail, not a mill command ([ISTQB Glossary Foundation PDF](https://www.erikvanveenendaal.nl/site/wp-content/uploads/ISTQB-Glossary-Foundation-V4.1-2023.pdf)) |
| ISTQB - test case | Preconditions, inputs, actions, expected results, postconditions -> evidence/`replace-body` content |
| ISTQB - passed / failed | Actual matches vs does not match expected -> verdict in **mail**, not card-status slang collision |
| ISTQB - confirmation (re-test) vs regression | Re-test = same failing case after fix; regression = side effects elsewhere -> same card vs follow-on `create todo` (aligns FUNCTION-LINGO) |
| ISTQB - pass/fail criteria | Decision rules for pass/fail ([istqb-glossary.page](https://istqb-glossary.page/pass-fail-criteria/)) -> office Claims / exit language |
| ISTQB - exit criteria | Conditions to complete a test task -> Done looks like / waiting_on, not a command |

### Guesses (flagged)

- Standing **regression cadence** as 2nd product - **guess**; README names one product; FUNCTION-LINGO maps regression to leftover/follow-on.
- QA desk **`score`** for escape rate / remasure SLA - **guess**; README score row cluster excludes QA.
- `hold` on evidence files - **guess** unless office leases those resources; rare like research briefs.
- Pass-with-warnings as first-class enum - **from stub**, not FUNCTION-LINGO sketch (sketch says pass/fail only) - keep stub ternary unless gardener drops it.

---

## Open questions for human / gardener

1. Is **Pass/Fail evidence** the only day-one product, or should regression cadence / acceptance pack get its own Product subsection now?
2. May the validator desk **`pass` eng cards** after Pass mail, or only mail + let asker/eng `pass`? (Stub + FUNCTION-LINGO favor asker; confirm office policy.)
3. Keep stub **Pass-with-warnings** ternary, or collapse to Pass/Fail + warnings in card text?
4. Where do evidence artifacts live as SoR (CI log URL, pack path, Drive)? Affects hold teaching and Done path line.
5. Should `score` appear in office-qa map day-one (escape rate / remasure latency)?
6. Defect filing: always QA `create todo`+bug, or prefer support/forge Issue then mill link only?

---

## Gaps vs existing SKILL.md (gardener checklist)

| Gap | Stub today | Research says |
|---|---|---|
| Inputs section | Absent (has When triggers) | Add Inputs: Claims, subject under test, remasure method, evidence sink; When can stay thin or fold |
| Scope note | Absent | In/out; regression/acceptance = modes not 2nd product |
| Lingo -> mill table | "Verbs (mill)" need-oriented, incomplete | TEMPLATE-shaped Their word -> Mill; full FUNCTION-LINGO harvest |
| acceptance criteria / test case / defect / regression / sign-off | Missing or implicit | Map explicitly; sign-off != mill pass on eng |
| waiting_on / assign / unclaim / hold / park | Missing | Add; drop!=unclaim |
| score | Absent | Optional/omit unless office KPI |
| Multi-product clarity | Single mushy Product OK-ish | Explicit one kept; dropped listed in RESEARCH only |
| Done | Verdict mail; asker knows next | Add QA card `pass`/waiting_on/parked; eng `pass` policy; Fail ownership |
| Must-not | Implement / rubber-stamp / Builder suite | Add: no invent commands; SoR outside mill; pass-sense collision; HINT bypass |
| Product noun | "Independent evidence..." | Align title/README: **Pass/Fail evidence**; keep independent/remasure in body |

---

## TEMPLATE brief (for Gardener)

Paste/adapt into `docs/skills/office-qa/SKILL.md`. Pull mill-desk first. Do not invent commands.

```markdown
---
name: office-qa
description: >
  Use when this desk remasures Claims and returns Pass/Fail evidence on a mill
  office. Pull mill-desk first. Thin adapter - not a second mill. Product =
  Pass/Fail evidence (independent remasure) - not eng ship or Builder suite alone.
metadata:
  short-description: "QA: Pass/Fail evidence via mill"
---

# Office - QA / validation -> Pass/Fail evidence

Pull **mill-desk** first. One card, then **STOP**.

## Product
**Pass/Fail evidence** - independent verdict that named Claims hold or fail
(Pass / Fail / Pass-with-warnings) + remasure method + path-addressable evidence.

Regression and acceptance testing are **modes** of this product (same spine), not
second day-one products. Re-test = same card after eng fix.

## Inputs
On the desk **before** remasure (else `replace-body` gap + `send` asker / `waiting_on`):
- **Claims** - acceptance criteria / expected behavior (mail and/or todo detail)
- **Subject under test** - build, pack Last, path, env, version (link SoR)
- **Remasure method** - black-box steps or pointer to cases/suite
- Optional: evidence sink path; prior Fail mail when re-testing

Not inputs: vague "improve quality," implement-while-checking, Builder suite as sole proof.

## Lingo -> mill
| Their word | Mill |
|---|---|
| Claims / acceptance criteria | todo `detail` / Claims mail (`replace-body` to amend) |
| find Claims / remasure ask | `inbox` |
| take remasure | `claim` / `assign` |
| drop the claim | `unclaim` |
| test case / expected vs actual / evidence paths | `replace-body` |
| remasure (independent verify) | black-box work on Validator desk - **no implement** |
| pass / fail verdict | `send` asker/builder (verdict + method + paths) |
| sign-off | Pass `send`; asker/eng may `pass` the implement card |
| reject / send back | `send` Fail + repro |
| defect / bug | `create todo` + bug label; `send` eng |
| re-test / confirmation | same card after eng fix (`claim` / `send`) |
| regression | follow-on `create todo` (leftover) + same spine |
| blocked (Claims/env) | waiting_on + `send` |
| park / defer | `create todo` `{status:"parked"}` |
| exclusive evidence file | `hold` / `drop` (rare) |
| close QA remasure card | `pass` (QA card only unless office says validator closes eng) |
| quality KPI | `score` (only if office sets it) |

## Handoffs
| To | When |
|---|---|
| Asker / Engineering | Verdict ready; or Fail with repro |
| Ops | Prod-only / runtime remasure signal |
| Support | User-facing regression; forge Issue stays SoR |
| Auditor | Spec/congruence gap blocked remasure |

## Must-not
- Bypass mill-desk HINT routing.
- Implement product fixes; rubber-stamp without remasure; rely on Builder suite alone.
- Replace CI/forge/test-runner SoR - link evidence paths.
- Invent mill commands for ISTQB slang (`remasure`, `sign-off`, `regress` as CLI).
- Confuse test Pass/Fail (mail verdict) with mill `pass` (card close).
- `pass` eng cards unless office says validator closes.
- Confuse `drop` (hold) with `unclaim`.

## Done looks like
- Verdict mailed (Pass / Fail / Pass-with-warnings) with method + evidence paths; asker knows next (fix / ship / rewrite).
- QA remasure card `pass`ed or clean waiting_on or parked.
```
