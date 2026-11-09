# TOY - office-legal (Cleared / hold)

**Pull:** mill-desk + `office-legal/SKILL.md` only (not RESEARCH.md).  
**Pass bar:** [REMEASURE.md](../REMEASURE.md).

---

## Scenario A - missing Inputs

**Human says:**  
"Is this OK to ship?"

**Expected:**
1. Spot Inputs gap -> `note` and/or `send` asker / waiting_on - **do not** produce the product yet
2. After toy fill (below), run day-one spine for this product
3. `pass` / waiting_on / parked as skill Done says - **STOP**

**Toy fill (after agent asks):** use Scenario B facts.

**Fail if:** legal hold confused with mill hold; invent clear CLI; clear without `--receipt`

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Clear ask: publish mill beta blog. Artifact: /docs/announce.md. Decide: host desk `--receipt`. Out: no NDA issues in toy."

**Expected:** Inputs enough -> `create todo` / `claim` / `note` / `send` as skill map -> product Done -> **STOP**.

**Fail if:** legal hold confused with mill hold; invent clear CLI; clear without `--receipt`

---

## Gates

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Product Done matches skill | | |
| STOP after one job | | |
