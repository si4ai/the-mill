# Remeasure office-function skills (Loop-1)

Not pytest. Cold dogfood + paper check. Toys live **beside** each `office-<fn>/` (not under `tests/`).

## Who
| Role | Does |
|---|---|
| Office Skill Scout | RESEARCH.md + TEMPLATE brief |
| Mill Prompt Gardener | Patch SKILL.md; paper check |
| Human / Validator (later) | Cold dogfood or accept toy Pass |
| Toy runner (any desk) | Run `office-<fn>/TOY.md` scenario on mill |

## Paper check (before toy)
- [ ] Product(s) clear; not mush
- [ ] Inputs named
- [ ] Lingo -> day-one mill commands only; FUNCTION-LINGO consulted
- [ ] Handoffs / must-not / Done present; Done matches product (not wrong SoR)
- [ ] RESEARCH.md kept/dropped + rejects

Fail -> gap-check / re-scout. Do not toy yet.

## Actors (required)

A TOY with one desk talking to itself is **not** a Pass. Name real mill desks in the cast.

| Seat | Mill desk | Does |
|---|---|---|
| **Asker** | named desk (or host desk for the human) | States the ask; gets `send` for Inputs gap / deliverable |
| **Producer** | cold desk under test (mill-desk + that office-*) | Creates/claims card; produces product |
| **Handoff** (when skill says) | named peer desk | Gets `assign` and/or `send` - never only self-mail |

Score on mill SoR: mail **src!=dst** (Asker/Handoff) + Producer `activity` in t0-t1 (writer desk). Self-only `send` = Fail. Do not require Asker's desk_id on activity (recipients do not write activity rows).

TOY.md must list **Cast:** Asker=... Producer=... Handoff=... (omit handoff only if product has none).

## Run identity (required - activity join)

`activity` is keyed by **desk_id** + **updated**. A shared Producer desk mixes runs. Before the first mill command, record a run header (mill note on #50 or child, and/or row in `COLD-RUN-RESULTS.md`):

| Field | Rule |
|---|---|
| `batch_id` | Short unique id for the batch (e.g. `cold-20260921-a`) |
| `hypo_id` / TOY scenario | `H01` or `A`/`B` |
| `Producer` | Prefer a **fresh desk** per Producer under test (or per batch). Reusing `gardener` for smoke is not a scored cold run |
| `Asker` / `Handoff` | Named desks (bare desk name) |
| `t0` / `t1` | Wall-clock **start** and **end** (office local). Join: `activity.desk_id IN cast AND updated BETWEEN t0 AND t1` |

**Prefer unique Producer desk_id.** Timestamp window is the fallback when desks must be reused - then window + cast must be recorded or the trail is ambiguous.

Card `need` slug should include `batch_id` + `hypo_id` so todo rows also join without guessing.

## Cold dogfood (toy)
1. New chat / cold desk = **Producer**: mill-desk + that `office-*` only
2. Follow `office-<fn>/TOY.md` (human-lingo ask; Cast filled; some Inputs missing on purpose)
3. Score:
   - Asks for Inputs before acting? (`send` **Asker**, not invent)
   - Right commands / CLI shapes?
   - One card -> handoff/`pass`/waiting_on/parked -> **STOP**?
   - **Collab:** mail src!=dst to Asker/Handoff (not Producer self-mail)
   - Trail joins via **Producer desk_id** (preferred) or recorded **t0-t1** + cast - no ambiguous mixed window
   - No invented mill commands / wrong product?
4. Pass / Fail -> mill note on #50 (or child); smallest SKILL patch if Fail

## COLD rule (all 100)

Every hypo / TOY row that counts toward **Pass rate** must be **COLD**:

1. Producer is a desk whose only skills for that turn are **mill-desk** + that one `office-*` (new chat / virgin context - no gardener thread memory, no prior hypo residue).
2. One hypo per cold turn. Then **STOP**.
3. Cast + run identity recorded (`batch_id`, Producer desk, Asker/Handoff, `t0`/`t1`).
4. Mill trail proves the work (todo + mail src!=dst; activity = writer desk).

**Scripted command smoke** (pre-written create/claim/send/pass) is **not** COLD. Keep it as optional plumbing check; **do not** count it in Pass rate / Inputs / Command / STOP gates.

Batch size for a scored cold run: one cold turn per hypo the batch names, each cold. Smaller batches are pilots - label `pilot`, not Pass rate.

## Report gates (cold-run / TOY batch)

Write the batch gates on #50 (or child) + `COLD-RUN-RESULTS.md`.

| Gate | Definition |
|---|---|
| **Pass rate** | % scenarios where every per-run gate below (Inputs, Collab, Joinable trail, Command hygiene, STOP) passes; no partial credit |
| **Inputs gate** | % gap runs that `send` Asker / waiting_on before produce |
| **Collab** | % runs with mail **src!=dst** (Producer->Asker/Handoff); activity.desk_id is writer-only |
| **Joinable trail** | % runs with unique Producer desk_id **or** recorded t0-t1 + cast |
| **Command hygiene** | % day-one commands only (no invented CLI) |
| **STOP** | % one card then STOP |

Secondary (optional): median t1-t0 happy-path; Fail-if trap hits by function.

Prior one-desk self-mail smoke is **invalid** under Actors + joinable trail - do not count toward Pass rate.

Process note: measure / judge / report stay under Loop-1 tweak until evaluation is fine enough; prefer delete/merge over new gates.


## Day-one speech (JOIN / skill / commands / connect / howto-ai)

Paper check for the cold path. Surfaces: `docs/JOIN.md`, `docs/protocol/skill.md`, `docs/protocol/commands.md`, `docs/protocol/connect.md`, `docs/protocol/howto-ai.md` (Bot mill-desk SKILL must match skill.md). Not office-* TOY. Quiet on green; Fail -> one garden pass then STOP. Do not invent mill CLI. Multi-mill purpose: the office book uses `--office <alias>` (invite join; activities + daily dogfood); the test book uses a different alias with `--office <test-alias>` (local test / COLD throwaway only).

| # | Gate | Pass | Fail |
|---|---|---|---|
| D1 | **No register cold path** | Wakeup / Desk-name teach `mill join` then `mill connect` only. No `mill register` as day-one. | Wakeup or Desk-name teaches `mill register` / register-as-token path |
| D2 | **Welcome link / join -> connect** | Agent door = seat welcome link: `mill join --office <alias> --link-file LINKFILE` (`https://<wall>/welcome?desk=&seat=&project=&pem=`). Invite key `/?invite=<KEY>` is the human Wall door only. Order: pip/update -> copy skill -> reload -> `mill join` -> `mill connect` | Missing welcome-link form; invite key taught as a join argument; register between join and connect; skips join |
| D3 | **`--office` multi-mill** | `--office <alias>` on join/connect/commands; local aliases only; one connect process per office; `.mill/active` + `.mill/alias/` pointed (JOIN and/or skill) | No `--office` speech; teaches a single shared office only |
| D3b | **Office vs test mill** | Speech steers purpose: real office work / activities coordinator / daily Bot dogfood -> office book `--office <alias>` via a **seat welcome link** (the host mints more seats when needed). Throwaway COLD / virgin measure desks -> a different test-book alias `--office <test-alias>` (local test; not office SoR). Do not invent CLI | Speaks test book as office SoR; steers real Bot dogfood onto the test book; omits the office-book welcome link for office work; conflates test and office Walls |
| D4 | **ASCII speech** | Day-one surfaces are ASCII-only (no mojibake / smart punctuation in pack speech) | Non-ASCII in JOIN/skill/commands/connect/howto teaching lines |
| D5 | **Roster ask-if-omit** | One roster name (bare name; type `roster`); labels orthogonal; if ask omits roster, **ask** before create/send - do not invent | Invents a roster; uses a label as roster |
| D6 | **Hold** | `hold` / `drop` taught; drop != unclaim | Hold missing; drop/unclaim confused |
| D7 | **Any-activity (not todo-only)** | `label-add` / watcher / tree apply to mail\|todo\|doing\|hold\|score - not todo-only | Taught as todo-only |
| D8 | **Admin / trust DO** | Speech matches [admin.md](../requirements/admin.md): trust high default; Always-Admin list; mint/member-other/assign trust-gated; assign only when unassigned (no overwrite); `join --role Admin` does not grant; `mill trust high`/`limited` = Admin set (show any seated desk) | Contradicts lock (Admin-only mint under high; assign overwrite; join --role Admin grants) |

**Overall day-one paper:** Pass iff D1-D8 and D3b all Pass. Cite evidence under `~/.mill/evidence/garden-measure-<date>/` or remasure batch. Standing weekday measure: routine `garden-measure` (8:50 local) runs this paper check (+ optional live `--owner` / `--office` smoke on the purpose-correct mill); office-* remasure below stays unchanged.

## Layout

```
docs/skills/
  REMEASURE.md
  FUNCTION-LINGO.md
  TEMPLATE.md
  office-<fn>/
    SKILL.md
    RESEARCH.md
    TOY.md
```
