# TOY - office-people (Hired / Onboarded)

**Pull:** mill-desk + `office-people/SKILL.md` only (not RESEARCH.md).  
**Pass bar:** [REMEASURE.md](../REMEASURE.md).

---

## Scenario A - missing Inputs

**Human says:**  
"Hire someone."

**Expected:**
1. Spot Inputs gap -> `replace-body` and/or `send` asker / waiting_on - **do not** produce the product yet
2. After toy fill (below), run day-one spine for this product
3. `pass` / waiting_on / parked as skill Done says - **STOP**

**Toy fill (after agent asks):** use Scenario B facts.

**Fail if:** skip `--receipt` on offer; invent hire CLI; ATS clone

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Req: Loop-1 Scout contractor. ATS id ATS-9. Offer needs `--receipt` (host). Onboard checklist: laptop, mill join, desk token."

**Expected:** Inputs enough -> `create todo` / `claim` / `send` as skill map -> product Done -> **STOP**.

**Fail if:** skip `--receipt` on offer; invent hire CLI; ATS clone

---

## Gates

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Product Done matches skill | | |
| STOP after one job | | |
