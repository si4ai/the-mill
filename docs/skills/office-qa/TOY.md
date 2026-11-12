# TOY - office-qa (Pass/Fail evidence)

**Pull:** mill-desk + `office-qa/SKILL.md` only (not RESEARCH.md).  
**Pass bar:** [REMEASURE.md](../REMEASURE.md).

---

## Scenario A - missing Inputs

**Human says:**  
"Remasure the Claims for the connect-cloud change."

**Expected:**
1. Spot Inputs gap -> `replace-body` and/or `send` asker / waiting_on - **do not** produce the product yet
2. After toy fill (below), run day-one spine for this product
3. `pass` / waiting_on / parked as skill Done says - **STOP**

**Toy fill (after agent asks):** use Scenario B facts.

**Fail if:** rubber-stamp without remasure; mill pass eng card; invent remasure CLI

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Remasure Claims on need toy-research-connect-cloud. Subject: the installed mill pack on the office host. Method: black-box mill create/claim/pass still works. Evidence: paste CLI transcript path in the card text (mill replace-body). Decide desk: the host."

**Expected:** Inputs enough -> `create todo` / `claim` / `send` as skill map -> product Done -> **STOP**.

**Fail if:** rubber-stamp without remasure; mill pass eng card; invent remasure CLI

---

## Gates

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Product Done matches skill | | |
| STOP after one job | | |
