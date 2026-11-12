# TOY - office-finance (Approved / paid)

**Pull:** mill-desk + `office-finance/SKILL.md` only (not RESEARCH.md).  
**Pass bar:** [REMEASURE.md](../REMEASURE.md).

---

## Scenario A - missing Inputs

**Human says:**  
"Pay this invoice."

**Expected:**
1. Spot Inputs gap -> `replace-body` and/or `send` asker / waiting_on - **do not** produce the product yet
2. After toy fill (below), run day-one spine for this product
3. `pass` / waiting_on / parked as skill Done says - **STOP**

**Toy fill (after agent asks):** use Scenario B facts.

**Fail if:** ledger clone; invent approve/pay CLI; skip `--receipt`

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Invoice INV-100 $50 vendor X. Approve path: the host `--receipt`. Ledger SoR outside. Pay when approved."

**Expected:** Inputs enough -> `create todo` / `claim` / `send` as skill map -> product Done -> **STOP**.

**Fail if:** ledger clone; invent approve/pay CLI; skip `--receipt`

---

## Gates

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Product Done matches skill | | |
| STOP after one job | | |
