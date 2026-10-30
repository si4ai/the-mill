# Office-function skills

Pack may lag office-host until next ship.

## Layer
1. **mill-desk** - universal floor (HINT->command, one job, STOP). The coordination meta-layer.
2. **office-*** - thin adapters: **product**, **inputs**, lingo -> mill, done.
3. **model-*** - runtime delta only. Not a second office. Index: [models/README.md](../protocol/models/README.md).
4. Domain systems (GitHub, Zendesk, CRM...) stay systems of record; mill coordinates.

**PM is not a peer product.** Roadmap/RACI/standup language folds into mill-desk + Auditor.


## Install (office desks)

After `pip install the-mill` / `mill update`, adapters ship under the pack share (not mill-desk itself):

`share/the-mill/docs/skills/office-<function>/SKILL.md`

Copy the one your desk needs beside mill-desk (vendor skill path ? see [howto-ai.md](../protocol/howto-ai.md)). Always pull **mill-desk** (`docs/protocol/skill.md`) first.

## Skills

| Skill | Product | Status |
|---|---|---|
| [office-engineering](office-engineering/SKILL.md) | Working **software** (not other eng) | product |
| [office-qa](office-qa/SKILL.md) | Pass/Fail evidence | product |
| [office-ops](office-ops/SKILL.md) | Uptime / incident closed | product |
| [office-support](office-support/SKILL.md) | Resolved ticket | product |
| [office-sales](office-sales/SKILL.md) | Close-won / handoff | product |
| [office-marketing](office-marketing/SKILL.md) | Launch / publish | product |
| [office-people](office-people/SKILL.md) | Hired / onboarded | product |
| [office-legal](office-legal/SKILL.md) | Cleared / hold | product |
| [office-finance](office-finance/SKILL.md) | Approved / paid | product |
| [office-research](office-research/SKILL.md) | Decision brief | product |

Template: [TEMPLATE.md](TEMPLATE.md). Lingo research: [FUNCTION-LINGO.md](FUNCTION-LINGO.md). Scout standing prompt: [MILL-OFFICE-SKILL-SCOUT.md](MILL-OFFICE-SKILL-SCOUT.md). Remeasure: [REMEASURE.md](REMEASURE.md).

## General mapping pattern (human language ? mill)

Across functions the same **collab moves** recur; only **nouns** change:

| Human collab move | Mill command set | Notes |
|---|---|---|
| There's work | `create todo` | doing = artifact-oriented |
| I'll take it | `claim` / `assign` | one owner |
| Need eyes / help | mill `send` | handoff ? claim steal |
| Don't touch my file | `hold` / `drop` | eng/legal/docs |
| Waiting on X | waiting_on + mail | don't fake pass |
| Prove it | Claims + QA remasure | eng?qa |
| We're green / red | `score` | a row in the score table (`kpi`, `value`, `target`) |
| Finished the artifact | `pass` | after office close path |
| Who's here | presence | ops/support coverage |
| Human must click | human_required | offer, spend, legal |

**Overlap / reuse**
- `create todo -> claim -> note -> send -> pass` is the spine for almost every function.
- hold is rare (eng trees, legal docs) - don't teach it in sales/support unless needed.
- human_required clusters: people (offer), finance (approve), legal (clear), marketing (brand approve).
- score rows (`kpi`, `value`, `target`): ops (SLO), support (SLA), sales (forecast), marketing.
- "Escalate" always = mill send to a more specialized desk, not a new mill command.

**Approach for new domains**
1. Name the **artifact** (one sentence).
2. List 8-15 native lingo terms (product + collab).
3. Map each to the smallest mill command set above.
4. Write must-not: what SoR stays outside mill.
5. Stop - do not invent mill commands per industry.

## How mill *fulfills* the activity (deeper than commands)

Don't only translate slang ? CLI. Ask: **what office fact does mill record so collaboration can continue without the chat?**

| Human need | Mill representation (fulfillment) | Typical commands (optional) |
|---|---|---|
| Know who's working | **Presence / HERE** on the floor | connect, agents |
| Shared work item | **Todo card** (doing, detail, owner, state) | `create todo`, claim, assign, note, `pass` |
| "It's yours / eyes on this" | **Mail** to desk/role (durable handoff) | send, inbox |
| Don't collide on a file | **Hold** on a station | hold, drop |
| We're blocked | Card **waiting_on** + mail | note, send |
| Prove quality / trust | **Claims mail** + Validator remasure (evidence paths) | send, (qa skill) |
| Are we healthy vs target? | **score row** (`kpi`, `value`, `target`) | `score` |
| Human glance | **Wall** over the same records | - |
| Coverage | Presence + mail, not a side DM as SoR | send, inbox |

**Pattern:** human language names the **intent**; mill stores the **shared fact** (who, what, waiting, evidence, score row). Commands are just how agents write those facts.

**Overlap:** every function's "assign / escalate / approve / pass" collapses to card ownership + mail + optional human_required - the product noun in `doing`/`detail` is what differs.
