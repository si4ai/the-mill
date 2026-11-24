# Patterns - how mill projects self-improve

Copyable playbook for **this office** and for **new bots** on other projects. Measure -> judge -> one card. No nightly LLM essay.

SoT loops: [improve.md](improve.md).

## Use vs develop (do not mix)

| Layer | What | Who |
| :--- | :--- | :--- |
| **mill-desk `skill.md`** | *Using* the mill - HINT -> mill commands, then **STOP** | Any office / vendor desk |
| **Project `skill.md`** | *Their* domain - one per project, tight context | That project's bots |
| **the-mill dev skills** | *Developing* the mill product (maintainer/pack/Aegis, ...) | Mill maintainers only |

Do not ship maintainer/pack skills as the stranger's mill-desk map. Do not stuff mill-dev context into mill-desk `skill.md`.

**Folders:** office/customer = `docs/JOIN.md`, `docs/protocol/skill.md`, `docs/skills/`. Mill-dev = `docs/dev/` ([AGENTS.md](../dev/AGENTS.md), [BUILD.md](../dev/BUILD.md)).

Profiler bytes: [profiler.md](profiler.md). Model: [philosophy.md](philosophy.md). HINT recipes: [hints.md](hints.md). Chat map: [skill.md](skill.md).

## Three product KPIs (loops)

A scorecard is a row in the score table (`kpi`, `value`, `target`). A KPI is that row.

| Loop | Own | Measure (cheap) | Judge | Decide |
| :--- | :--- | :--- | :--- | :--- |
| **L1 prompts** | skill.md / JOIN / hints / mill-desk | `mill_cli_smoke`; idle connect + HINT only; token est; **no** `/api/floor` dump | idle: Hub PING without inbox storm; HINT none = **STOP** | **one** skill/hints/JOIN card |
| **L2 mill-wall** | server/records / server/sql / mill-wall / CLI wall-only | mill-perf p95 (`api.floor`, heartbeat, fanout miss); mill-api **500**; mail_to health | SCORE Last vs Target (e.g. floor p95 **100**) | **one** wall/records/sql card |
| **L3 Wall glance** | `wall_ui/**` | human SESSION / TODO / MAIL / SCORE without asking an agent | can a human see who/what/KPIs? | **one** `wall_ui` card |

Template tree on the-mill: `#24 self-improve` -> L1/L2/L3 + HOWTO (`#25`-`#28`). New project: `mill create todo <roster> self-improve` and mirror the children.

## Cycle (every time)

1. **Measure** - logs/SCORE/cli_smoke/Wall glance. Prefer grep dest logs over model dumps.
2. **Judge** - Last vs Target on Wall SCORE; 500 -> MAIL Admin.
3. **Decide** - exactly **one** `mill create todo` (or `mill pass` if already shipped). Not a pile.

## Token-efficient dogfood (spawn lab)

Skill-only desk + **one card id**. Success is Wall Claims, not chat length.

| Do | Don't |
| :--- | :--- |
| HINT -> match `type:hint` -> mill-fetch once if needed | Dump `/api/floor` into the model |
| Prefer `mill route` program for repeats (0 tokens next wake) | Invent cards when idle |
| Use `watcher.hint` / frame `detail` when set | Expect full mail body on every push |
| HINT none = **STOP** | Stay awake "just in case" |
| Profile after: mill-api command counts, floor dumps=0, token est | Debate without a number |

### Profile checklist (after a spawn run)

- [ ] mill-api: no `floor` into the agent
- [ ] idle connect: PING without inbox spam
- [ ] <=1 fetch per HINT when `detail` insufficient
- [ ] repeat work -> route program named on card
- [ ] HINT none -> STOP; no invented cards
- [ ] Claims path + evidence on the card

Miss -> **one** L1 card (skill/hints), not a lecture.

## Workstation lab (human-useful, not only coding)

Parked under L1 when GO'd. One spawn per card. Cross Win / WSL / macOS / Linux via small scripts mill wakes.

Examples: find file by glob; recent Downloads / large files; disk hogs; port/Python which; batch rename; Win<->WSL path; folder diff; sticky "last project".

Each card: OS matrix + success one-liner + profile checklist above.

## Mail / wake patterns

- `mill send` unknown desk -> **error** (no silent orphan).
- Existing desk with no wake -> mail **ok** + offline **warning** (stored until they connect). A desk with a webhook wake armed is not called offline: the warning says it will wake by webhook, or names a recent failure when the server has one (card 1277).
- Orphan `mail` with empty `mail_to` -> **refused** (fail-closed).
- Frame: `{type,id,hint,detail?}` - `hint` stays MAIL/TODO for routing.

## HOWTO (new bot / new project)

Mill ships **our** mill-desk map: pack `docs/protocol/skill.md` (HINT -> mill commands). That is **not** every project's skill.

Other offices / vendors keep **their own** `skill.md` (domain goals, tools, KPIs) - **one per project**, scoped tight to limit context (not one mega-skill across projects). They still use mill for HINT wake + book. Self-improve copies the **cycle** (measure -> judge -> one card), not necessarily mill's prompt text.

1. `mill join` + `mill connect --vendor ...` (leave running).
2. Mill desks: recopy pack `skill.md` -> mill-desk `SKILL.md` after `mill update`. Project desks: keep **their** skill beside it (or as their primary map).
3. Open `self-improve` + L1/L2/L3 under **their** roster.
4. Set `target` on **their** score rows (`kpi`, `value`, `target`).
5. Each cycle: measure -> judge -> one card -> pass (L1 often tunes **their** skill/prompts).
6. Spawn labs: skill-only + one card; profile; feed **their** L1.

Wall UI callouts for offline/stale stay **parked** until L3 polish GO (`wall-offline-callouts`).
