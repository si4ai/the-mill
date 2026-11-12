# TOY - office-marketing (Launch / campaign)

**Pull:** mill-desk + `office-marketing/SKILL.md` only (not RESEARCH.md).  
**Pass bar:** [REMEASURE.md](../REMEASURE.md).

---

## Scenario A - missing Inputs

**Human says:**  
"Launch the campaign."

**Expected:**
1. Spot Inputs gap -> `replace-body` and/or `send` asker / waiting_on - **do not** produce the product yet
2. After toy fill (below), run day-one spine for this product
3. `pass` / waiting_on / parked as skill Done says - **STOP**

**Toy fill (after agent asks):** use Scenario B facts.

**Fail if:** CMS clone; asset as 2nd product; invent publish CLI

---

## Scenario B - happy path (Inputs given)

**Human says:**  
"Campaign: mill beta announce. Channel: blog+X. KPI owner: host desk. Asset path: /docs/announce.md. Publish when legal clear (none needed for toy)."

**Expected:** Inputs enough -> `create todo` / `claim` / `send` as skill map -> product Done -> **STOP**.

**Fail if:** CMS clone; asset as 2nd product; invent publish CLI

---

## Gates

| Gate | A | B |
|---|---|---|
| Inputs before produce | | |
| Day-one commands only | | |
| Product Done matches skill | | |
| STOP after one job | | |
