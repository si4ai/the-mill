---
name: office-ops
description: >
  Use when this desk owns uptime, deploys, drains, or incidents on a mill
  office. Pull mill-desk first. Thin adapter - not a second mill. Product =
  Uptime / incident closed (stable runtime) - not a status-page essay.
metadata:
  short-description: "Ops: uptime / incident closed via mill"
---

# Office - Ops / SRE -> Uptime / incident closed

Pull **mill-desk** first. One card, then **STOP**.

## Roster
**Roster** each todo/mail under **one** roster name (bare name; type `roster`; `--roster` on send/reply). Day-one board work -> office roster. Shared function intake -> that roster (`add roster NAME`). **Labels** orthogonal (label `bug` where this skill teaches it). Named handoff -> `send`/`assign` desk. Job titles != a mill roster unless Admin created that roster. If the human ask has no roster, **ask them which one** before `create todo` / `send` - do not invent.
Prefer a project for incident/mitigation cards; optional on-call role if host has it; SEV stays in detail/doing (do not invent SEV labels); IC = `claim`/`assign` desk.

## Product
**Uptime / incident closed** - runtime stable again: incident impact stopped and
closed, deploy/rollback finished clean, or intentional drain with clear ETA and
stakeholders informed.

Deploy, drain, and health recovery are **modes** of this product (same spine),
not second day-one products. Postmortem = follow-on or parked todo, not the
primary artifact.

## Inputs
On the desk **before** mitigate/deploy/drain (else `replace-body` gap + `send` / `waiting_on`):
- **Signal** - page/alert/health fail / deploy or drain ask (`inbox` / wake / mail)
- **Impact scope** - service, SEV/priority, blast radius (todo `detail` / `doing`)
- **Owner** - on-call HERE; `claim` / `assign`
- **Mitigation path** - runbook/rollback/drain steps (pointer in detail/`replace-body`; SoR stays outside)
- When deploy: change/artifact id (link forge/CI). When drain: ETA for `note`/`send`.

Not inputs: vague "keep the lights on," silent prod change with no card when
office requires one, reconnect spam as a plan.

## Lingo -> mill
| Their word | Mill |
|---|---|
| on-call / HERE | presence (who's on the floor) |
| page / alert | wake / `send` + `inbox` |
| incident / health fail | `create todo` then `claim` / `assign` |
| SEV / severity / triage | todo `detail` / `doing` + `note` |
| IC / take ownership | `claim` / `assign` |
| drop the claim | `unclaim` |
| progress | `note` |
| mitigate / diary | `replace-body` (not mail) |
| stakeholder comms | `send` (+ `replace-body` on card) |
| escalate | `send` eng/support (optional eng `create todo`) |
| follow-the-sun | `assign` / `unclaim` + `send` next desk |
| deploy / rollback | same spine: `claim` -> `note` -> `pass`; forge/CI SoR |
| drain / deploy window | `note`/`send` ETA + office drain path; `pass` when clear |
| blocked (eng/human/window) | waiting_on + `send` / `note` |
| postmortem | follow-on `create todo` or `{status:"parked"}` |
| SLO / uptime KPI | `score` - a row in the score table (`kpi`, `value`, `target`) |
| exclusive config/runbook file | `hold` / `drop` (rare) |
| close incident / stable | `pass` after mitigate + note/comms |
| park / defer | `create todo` `<roster> <need> --status parked` |

## Handoffs
| To | When |
|---|---|
| Engineering | Code fix / rollback change required |
| QA | Remasure in prod-like / after deploy |
| Support | Customer-facing incident comms; ticket SoR stays support |
| Next on-call | Follow-the-sun coverage handoff |

## Must-not
- Bypass mill-desk HINT routing.
- Silent prod change without a card when office requires it; reconnect spam during drain.
- Replace PagerDuty/status page/CI/runbook SoR - link paths.
- Invent mill commands for SRE slang (`page`, `escalate`, `drain`, `sev` as CLI).
- Teach `open` / `yield` / bare `create` / `done`.
- Confuse `drop` (hold) with `unclaim`.
- Own eng ship or QA Pass/Fail.

## Done looks like
- Service healthy or intentional drain ETA clear; stakeholders mailed; ops card
  `pass`ed or clean waiting_on or parked follow-on (postmortem).
