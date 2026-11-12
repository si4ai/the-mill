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

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for research cards; rare function role; named researcher = `send`/`assign` desk.

## Product
**Decision brief** - path-addressable artifact others can decide from (BLUF, options incl. do-nothing, recommendation, confidence/limits, dated sources).

Findings/recommendation live **inside** the brief, not as separate products. Competitive/market *asks* use this same product (mode in detail) - not a second day-one product.

## Inputs
On the desk **before** draft (else `replace-body` gap + `send` asker / `waiting_on`):
- **Decision ask** - what decide / by when / who decides
- **Audience / decide desk**
- **Scope bounds** - in/out, time window, competitors if competitive mode
- Optional: source hints / prior brief paths; constraints (budget, legal, launch) -> hand off legal/finance if gate

## Scope
- **In:** decision-ready briefs; competitive asks that still end in a decision; synthesis *toward* that brief
- **Out:** wiki maintenance, eng ship, QA Pass/Fail, CRM pipeline, legal clearance, finance approval, marketing publish
- Pull mill-desk first; one card, then STOP

## Lingo -> mill
| Their word | Mill |
|---|---|
| research ask | `create todo` `<roster> <need>` |
| park / later | `create todo` `<roster> <need> --status parked` |
| take / draft | `claim` / `assign` |
| drop the claim | `unclaim` |
| progress / brief path | `todo <roster> <need> --eta E` or `replace-body` (path in body/detail) |
| synthesize / revise | `replace-body` |
| findings | brief section / `replace-body` |
| recommendation | brief section (not a separate card product) |
| decision record | `replace-body` (asker; research if told) - not research Done |
| review | `send` (same as challenge) |
| challenge / review | `send` |
| blocked (SME/source) | waiting_on + `send` |
| check asks / mail | `inbox` |
| deliver brief | `send` asker + `pass` |
| record decision | `replace-body` (asker; research if told) - **not** research Done |
| exclusive brief file | `hold` / `drop` `<resource>` (rare) |

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
| Auditor | Spec/congruence gap blocks the ask |

## Must-not
- Bypass mill-desk HINT routing.
- Replace source/wiki/CRM/Drive SoR - link in detail via `replace-body`.
- Invent mill commands for analyst slang (`brief`, `synthesize`, `decide`).
- Confuse brief delivery with eng ship or QA Pass.
- Endless research without `pass` / waiting_on / parked.
- Confuse `drop` (hold) with `unclaim`.
- Treat marketing creative "brief" or eng design doc as this product.

## Done looks like
- Brief **path** on card; decide desk **mailed**; card `pass`ed (decision-ready) or clean waiting_on or parked.
- Decision **outcome** optional (`replace-body` by asker) - **not** required for research Done.
