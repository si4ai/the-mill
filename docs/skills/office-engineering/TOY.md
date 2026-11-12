# TOY - office-engineering (Working software / package)

**Pull:** mill-desk + `office-engineering/SKILL.md` only (not RESEARCH.md).  
**Pass bar:** [REMEASURE.md](../REMEASURE.md).

---

## Scenario A - missing Inputs

**Human says:**  
"Ship a fix for the Wall timeout."

**Expected:**
1. Spot Inputs gap -> `replace-body` and/or `send` asker / waiting_on - **do not** produce the product yet
2. After toy fill (below), run day-one spine for this product
3. `pass` / waiting_on / parked as skill Done says - **STOP**

**Toy fill (after agent asks):** use Scenario B facts.

**Fail if:** no card; QA Pass as eng Done; invent pr/merge CLI

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Implement need X: fix mill-wall HERE bearer desk slug. Repo the-mill. Acceptance: mill todo works with `--owner` bare desk id (Bearer from DESK_<desk>.token). Claims ready for QA after ship."

**Expected:** Inputs enough -> `create todo` / `claim` / `send` as skill map -> product Done -> **STOP**.

**Fail if:** no card; QA Pass as eng Done; invent pr/merge CLI

---

## Gates

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Product Done matches skill | | |
| STOP after one job | | |
