# TOY - office-support (Resolved ticket)

**Pull:** mill-desk + `office-support/SKILL.md` only (not RESEARCH.md).  
**Pass bar:** [REMEASURE.md](../REMEASURE.md).

---

## Scenario A - missing Inputs

**Human says:**  
"User says login is broken."

**Expected:**
1. Spot Inputs gap -> `replace-body` and/or `send` asker / waiting_on - **do not** produce the product yet
2. After toy fill (below), run day-one spine for this product
3. `pass` / waiting_on / parked as skill Done says - **STOP**

**Toy fill (after agent asks):** use Scenario B facts.

**Fail if:** pass with no ball location; skip forge URL; invent escalate CLI

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Ticket: user cannot login to Wall (LAN). Reporter: host desk. Forge: https://example.invalid/issues/1. Classify request vs bug; workaround or eng todo."

**Expected:** Inputs enough -> `create todo` / `claim` / `send` as skill map -> product Done -> **STOP**.

**Fail if:** pass with no ball location; skip forge URL; invent escalate CLI

---

## Gates

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Product Done matches skill | | |
| STOP after one job | | |
