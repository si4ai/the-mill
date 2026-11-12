# TOY - office-research (Decision brief)

**Pull (Producer):** mill-desk + `office-research/SKILL.md` only.  
**Product under test:** Decision brief.  
**Pass bar:** [REMEASURE.md](../REMEASURE.md) cold dogfood score (Actors required).

**Cast (mill desks - not fiction names):**
| Seat | Desk |
|---|---|
| Asker | `gardener` (or host desk) |
| Producer | cold research desk under test |
| Handoff | none day-one (brief to Asker via `send`; if recommend build/fix then `send` eng - do not own ship) |

**Run header (before first command):** `batch_id`, Producer desk (prefer fresh), Asker/Handoff, `t0` - then after STOP record `t1`. Join activity on cast x window (or unique Producer desk_id alone).

---

## Scenario A - missing Inputs (must ask, not invent)

**Human says:**  
"Research whether we should put mill connect in the cloud."

**Expected (agent):**
1. Notice Inputs gap (no decide-by / who decides / scope) -> `replace-body` gap and/or `send` asker / waiting_on - **do not** invent a recommendation yet
2. When Inputs filled (toy fill below), `create todo` + `claim`
3. Draft brief path on card via `replace-body`
4. `send` asker with path + restated ask
5. `pass` (decision-ready) - **not** required to record the decision outcome

**Toy fill (after agent asks):**  
Decide by Friday; asker = office human; scope = Bot vs LAN host only; out = rewriting mill-wall.

**Fail if:** ships a long answer with no card; uses `open`/`yield`; treats eng ship or QA Pass as Done; endless notes with no pass/waiting_on/parked.

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Decision brief: Should we require FUNCTION-LINGO in Scout preflight? Decide: host desk. By: this week. Scope: Loop-1 Scout only. Options must include do-nothing."

**Expected:**
1. `create todo` (need slug ok) with detail carrying ask
2. `claim` -> brief file/path -> `replace-body` path
3. Brief has BLUF + options incl. do-nothing + recommendation + limits
4. `send` the host/asker + `pass`

**Fail if:** competitive "scan" as second product; `done` instead of `pass`; decision outcome required for Done.

---

## Gates (check when done)

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Brief path on card | | |
| Asker mailed (not Producer self-only) | | |
| >=2 desks on activity trail | | |
| Activity join (desk_id and/or t0-t1) | | |
| pass / waiting_on / parked | | |
| STOP after one job | | |
