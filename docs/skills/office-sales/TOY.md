# TOY - office-sales (Close-won / handoff)

**Pull:** mill-desk + `office-sales/SKILL.md` only (not RESEARCH.md).  
**Pass bar:** [REMEASURE.md](../REMEASURE.md).

---

## Scenario A - missing Inputs

**Human says:**  
"Close this deal."

**Expected:**
1. Spot Inputs gap -> `replace-body` and/or `send` asker / waiting_on - **do not** produce the product yet
2. After toy fill (below), run day-one spine for this product
3. `pass` / waiting_on / parked as skill Done says - **STOP**

**Toy fill (after agent asks):** use Scenario B facts.

**Fail if:** clone CRM amounts into mill; invent close/stage CLI; pass while blocked

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Opp CRM-42 Acme. Stage ask: close-won. Owner AE. Next: mail CS onboarding. Amount stays in CRM."

**Expected:** Inputs enough -> `create todo` / `claim` / `send` as skill map -> product Done -> **STOP**.

**Fail if:** clone CRM amounts into mill; invent close/stage CLI; pass while blocked

---

## Gates

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Product Done matches skill | | |
| STOP after one job | | |
