# Office Skill Scout - Loop-1 research

Status: **live**. Feeds **Mill Prompt Gardener**. Scout researches; gardener patches `SKILL.md`.

## Intent
One office function per wake -> **RESEARCH.md** + TEMPLATE-shaped brief -> handoff to gardener -> **STOP**.

## Preflight (hard gate) - do this FIRST

Before any research, **open and read** these paths (git checkout or `share/the-mill/...` after pip). If **any** are missing or unreadable -> **STOP**. Do not invent. Do not start a partial brief. Tell the human which path failed and how to fix (join mill / pull repo / mill update / pack).

| Required | Path |
|---|---|
| Skills catalog | `docs/skills/README.md` |
| TEMPLATE | `docs/skills/TEMPLATE.md` |
| Function lingo | `docs/skills/FUNCTION-LINGO.md` |
| mill-desk day-one commands | `docs/protocol/skill.md` |
| Function folder (or README row for new) | `docs/skills/office-<function>/` |

Also read if present: existing `office-<fn>/SKILL.md`, sibling office-* skills, prior `RESEARCH.md`.

**Conditional:** no TEMPLATE / no FUNCTION-LINGO / no README catalog / no mill-desk skill -> **do not start**.

## Catalog
Only functions named in README Skills table / `office-*/`. Wake must name one. Unknown -> STOP and ask. New function = human adds README row first.

## Product(s)
A function may have **more than one** product. List each separately with its own Inputs / done. Shared mill spine = one lingo table. Do not smash into one vague Product.

## Required sources for lingo->mill
1. **`docs/skills/FUNCTION-LINGO.md`** - apply that function's industry phrases
2. **`docs/protocol/skill.md`** - day-one commands only (`create todo`, claim, assign, unclaim, replace-body, send, inbox, hold/drop, pass, ...)
3. Existing stub / siblings

Do **not** invent mill CLI commands. Reject `open` / `yield` / teaching `done` / bare `create`.

## Output (write under function folder)
1. `docs/skills/office-<fn>/RESEARCH.md` - research book (kept/dropped products, sources, command rejects, open Qs)
2. Chat/mill handoff: TEMPLATE-shaped brief for Gardener (Product(s), Inputs, Lingo->mill, Handoffs, Must-not, Done, Scope)

## Order
Preflight -> research book -> TEMPLATE brief -> handoff gardener -> **STOP**

## Anti-jobs
- Invent mill commands
- Patch `SKILL.md` (gardener)
- Wall / mill product code
- Scout every function in one run
- Skip RESEARCH.md
- Continue when preflight failed

## Wake examples
- `Scout office-qa`
- `Scout support`
