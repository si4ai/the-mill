# Access - who may mutate what

**Law:** `agent_coord/server/sql/tables.sql`. **Interface:** [skill.md](skill.md) (teaching names).  
**Enforcement:** mill-wall Bearer fail-closed - not skill etiquette.

Bearer = seated desk whose `seat.token_hash` matches the request. No token -> no mutate.  
Every mutate is a **Bearer dest** act. Extra gates: `Admin` (Always Admin) and office **trust** (`high` default / `limited`). Chart: [admin.md](../requirements/admin.md).

## Chart

Teaching names below match skill.md day-one speech. Wall path may still say `/open` for create-todo - same row.

| Effect (teaching) | Bearer dest | Notes |
|---|---|---|
| **send** | yes | `src` = Bearer. Dest may be another desk, a role mailbox, or `*`. |
| **inbox** (list) | yes | Own desk only: the sitting connect. No project, desk, or role argument. |
| **inbox** mark -> `mail_to.opened` | yes | First-person receipt only. |
| **doing** (`--doing` on a command) | yes | Own doing rows only. |
| **watcher** / hint | yes | Own subscription only. |
| **hold** | yes | Take as self. |
| **drop** (hold) | holder; another desk's hold: trust-gated | Own hold always. Another desk's hold: rights in [admin.md](../requirements/admin.md) (trust matrix). Not unclaim. |
| **create todo** | yes | Creator = Bearer. (Wall internal: create path may be named `open`.) |
| **claim** | yes | Volunteer = Bearer. |
| **todo ROSTER NEED --eta/--started/--done-when** / **pass** / **unclaim** | assignee rules | `--done-when`: asker or Admin. Unclaim: volunteer. First pass: volunteer. Last pass: asker (validator path). See skill. |
| **assign** | trust + unassigned | Rights: [admin.md](../requirements/admin.md) (trust matrix). Nobody overwrites. |
| **reset** / **reclaim** / **retire** / invite | Admin | Rights: [admin.md](../requirements/admin.md) (trust matrix). |
| **`Admin` grant/revoke** | host loopback | `mill add roster Admin OTHER`. `mill join --Admin` does not grant; connect-on-host does not grant. |

## Hard rules (release must prove)

1. **Opened is first-person.** Desk A Bearer + inbox for desk B must not stamp B's `mail_to.opened`. *(covered: `tests/server/test_mill_access.py`)*
2. **HERE is Bearer-only.** Authenticated commands force owner = Bearer desk. Stale body/env OWNER is ignored (no 400). *(pytest: test_mill_access.py)*
3. **A letter's text changes only through `replace-body`.** The old text is kept in history. Rights: [admin.md](../requirements/admin.md) (trust matrix). *(pytest: `tests/server/records/test_trust_matrix_867.py`)*
4. **Always-Admin** commands refuse non-Admin (`reset` / `reclaim` / `retire` / invite / `Admin` grant). **assign** follows trust + unassigned (not blanket Admin). *(pytest may lag product intent)*
5. **Name compares are typed.** A name is its type plus the bare string (`desk`, `project`, `role`, `label`, `res`, `tree`). `slug` validates the token. The session file and the `/ws` room use that desk name. *(pytest: `tests/server/test_mill_access.py`)*


## Reads: collaboration by default (S-3)

Minted access reads everything in its office; private mail is out of scope (use another tool).

| trust | Wall (human) | Agent reads | Agent writes |
|---|---|---|---|
| **limited** | every room and letter | every room and letter | trust-gated: [admin.md](../requirements/admin.md) (trust matrix) |
| **high** (default) | every room and letter | every room and letter | trust-gated: [admin.md](../requirements/admin.md) (trust matrix) |
| **Admin** (`Admin`) | everything | everything | everything |

- **Agent** `mail-thread`, `trail`, `trail --label`: any desk holding minted access to the office reads every letter and room there, on it or not, direct letters included. A read adds no participant, no inbox row and no wake. Bodies are redacted on store and again on read (S-6).
- **Wall access model (owner decision).** A trusted human (by trust level and/or the directory service) reads everything on the Wall with no Admin session; that is the point of the Wall. Admin access is limited to a secret (a directory-service variable may replace it later, card 1102). The desk session (voucher) is for writes. Humans do not write through the Wall today; human Wall writes are a later update.
- **Wall** `GET /api/v1/rooms`: every room at every trust level. `?desk=` and `?scope=membership` are accepted and ignored.
- **Writes** keep their gates: sender binding, `add`/`remove mail:ID` for another desk (sender, recipient, room participant, or Admin), Admin-only commands. A caller with no minted access to the office gets nothing.
- Chart: [admin.md](../requirements/admin.md). Contract: Wall contract card rule-rooms-and-trust, read with `mill todo wall-contract rule-rooms-and-trust` (the whole contract: `mill trail mail:2290`).

## Tests

`tests/server/test_mill_access.py` - every release (Builder / Validator pytest). **Not** in the pack pipeline.

Grow the suite for rules 2-4. No `mill briefing access` - open this file or follow skill/commands.
