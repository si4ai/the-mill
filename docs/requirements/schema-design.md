# Schema design decisions

**DRAFT, proposed by Builder, owned by the office human; edits need their OK.**

These are the standing decisions behind `agent_coord/server/sql/tables.sql` (main) and `beta/beta_ddl.sql` (0.8 beta, a proposal outside the pack).
Each section gives the decision, why, what it costs, and what a proposer must show to change it. To change a
decision, bring **a measured lab result plus the owner's OK**, and record the change in
[BETA-CHANGES.md](beta/BETA-CHANGES.md) (or here, for a design change). The design-invariant
test (`tests/install/test_schema_invariants_868.py`, regression row F160) fails a schema diff that touches neither.

Related: [admin.md](admin.md) (trust matrix), [BETA-CHANGES.md](beta/BETA-CHANGES.md)
(every departure from main), lab results `beta-norm/schema-lab/RESULTS.md` (box, card 868), read/write ratio
`beta-norm/rw-ratio/README.md` (box).

## 1. No universal id table: polymorphic references are (kind ENUM, id BIGINT UNSIGNED)

- **Decision.** There is no table of every id. A reference that can point at several kinds is the composite
  (type ENUM, id), as on main's `activity`, `label`, `tree`, `watcher` and `doing.on_*` / `waiting_*`. Ids and id
  references are `BIGINT UNSIGNED`, as on main (owner decision 2026-10-24; the INT narrowing is withdrawn).
- **Why.** Performance: a read joins straight to the payload's own table; no hop through a registry of everything.
- **Cost.** A small insert hit (one ENUM byte, a wider key), and the writing procedure checks the target exists
  because one FK cannot cover several tables. Accepted.
- **To change it.** A lab run at tier M showing the registry is faster on the measured command mix, plus the owner's OK.

## 2. Trees are Celko nested sets, not graphs

- **Decision.** Plans and mail rooms/threads are nested sets (`tree`: name_id, type, id, lft, rgt), one lft/rgt
  line per tree name. A read is one range scan. Every write runs under that tree's lock.
- **Why.** Performance, in the owner's words: reads far outnumber writes in the shared memory, so reads get the
  cheap shape and writes carry the known cost. Measured (Oct 7-22, `rw-ratio/README.md`): all reads to writes 4.3 : 1;
  tree reads to tree writes 2.7 : 1 narrow and 7.0 : 1 counting every card list; tree writes about 105 a day, 29% of
  command writes, 92% of them room-thread letters.
- **Cost.** An insert or move shifts lft/rgt for the rest of its tree (serialised per tree).
- **To change it.** A lab run showing the tree write rate has made the per-tree lock the limiter, plus the owner's OK.

## 3. Graphs are transposed into spanning trees; nothing else is an edge

- **Decision.** A relation that looks like a graph is held as a spanning tree (a nested set) or as a field on a
  row. There is no edge, link or adjacency table. Whatever cannot be spanned is flagged in a comment (a NOT SPANNED
  note), not stored as an edge.
- **Why.** Integrity and performance: one shape to read, no cycles to guard, no second structure that can drift.
- **Cost.** A node reached two ways sits on two trees (allowed, as on main); the trees are not linked.
- **To change it.** A use case no spanning tree or row field can hold, shown in the lab, plus the owner's OK.

## 4. Label rank is the ordering fast path

- **Decision.** Ordered reads a tree does not answer use `label` (type, id, name_id, ord SMALLINT UNSIGNED;
  0 pinned, 65535 unplaced); a desk's focus list is a label. Ordinals are renumbered by a routine
  (`sp_label_renumber`) when a gap runs out, keeping 0 and 65535.
- **Why.** Performance: (name_id, ord, created) gives the order from the index alone.
- **Cost.** An occasional renumber of one label's rows.
- **To change it.** A measured order read that label rank cannot serve, plus the owner's OK.

## 5. One name table is the one place names are managed

- **Decision.** Every name (desk, roster, label, tree, res) is one row of `name`, UNIQUE (type, name). A name is
  not a first-class object, just an isolated column managed in `name`. No other table stores a name string.
  Rename, retire and reclaim go only through `sp_name_*`. There is no name history (no `name_event`).
  Rules: admin.md sections 1, 2 and 4, rows F60, F65, F92, F135.
  - Delete is hard to do: Admin retires (soft, `name.deleted`; a trigger refuses DELETE), the name stays reserved
    while retired, and an Admin reclaim restores the same id.
  - Rename is a plain update; related records follow through the id. Admin renames; a desk may rename itself.
  - No hold on a renamed-away name, for any type: names belong to agents, not humans, so the old string is free
    for a new mint at once.
- **Why.** Integrity, in the owner's words: the name table exists only so names cannot confuse or mislead agents
  or humans. UNIQUE (type, name) stops duplicates, the id keeps records attached through a rename, and a hard
  delete would orphan what the name meant. A history table adds nothing to that goal (owner decision 2026-10-24).
- **Cost.** None beyond main's table and the procedures.
- **To change it.** The owner's OK; a performance claim also needs a lab result.

## 5a. Kind tables: only a kind table links to name

- **Scope.** The rework narrows single-kind FKs only: a column that always points at ONE kind (a desk_id that is
  always a desk, a roster_id that is always a roster) FKs to that kind table instead of `name (type, id)`. The
  composite-reference design (section 1) is intact: every reference that can point at several kinds (label and tree
  nodes, watchers, `doing.on_*` / `waiting_*`, the activity timeline) stays a (type ENUM, id) composite, unchanged.
  The isolated name table, nested-set trees (section 2) and label rank (section 4) are unchanged too.
- **Decision.** A table that needs a desk, a roster, a tree and so on FKs to that kind's table, never to `name`.
  Only a kind table links to `name`, with one FK. The desk kind is `seat` (desk_id, UNIQUE as on main); the roster
  kind is `roster` (id). label, tree and res have no kind table on main, so their four references keep main's FK
  to `name (id)` (open question Q1 in BETA-CHANGES.md).
- **Link shape: kind id = name.id, one FK per kind table to `name (id)`.** Chosen because it keeps ids shared:
  every desk and roster column still holds the name id, so no column, join or procedure argument changes, and a
  kind row needs no id of its own. The other shape (kind.name_id UNIQUE with the kind's own id) would add a second
  id per desk and roster and a translation at every write. seat keeps main's own `id` column; its UNIQUE desk_id
  is the referenced key, so the same rule holds with no new index.
- **Why.** The typed composite FK to `name (type, id)` made `name` the hub of every relation and cost a generated
  column plus an index per reference. A kind table carries the same guarantee (a desk column cannot hold a roster
  id) with plain one-column FKs that reuse the indexes main already has. Counts on a fresh book, before
  (dbef70f) and after: FKs to `name` 34 -> 6, all indexes 115 -> 89, FK-only indexes 36 -> 12, generated type
  columns 30 -> 0 (BETA-CHANGES.md, Kind tables).
- **Cost.** One one-column table (`roster`). Whether a seat row is a desk name and a roster row a roster name is
  the minting procedures' job (open question Q3).
- **To change it.** The owner's OK.

## 6. High / limited trust with Admin applies to every command, enforced in the procedures

- **Decision.** Every command procedure applies admin.md sections 1-3 (always Admin; trust-gated; any desk) itself,
  reading the level from `b_trust()`. No procedure takes trust as an argument, so the frozen signatures stay as they
  are. Where the level comes from is section 9. Admin grant is the host path only.
- **Why.** Integrity: the app database user holds EXECUTE only, so the procedure is the only place a guard can stand,
  and a guard that reads an app argument can be lied to.
- **Cost.** A function call per guarded command (no table read).
- **To change it.** The owner's OK.

## 7. The office is a hard boundary

- **Decision.** One office is one book. No table references another office; nothing crosses offices by id.
- **Why.** Integrity: an id means one thing, in one office.
- **Cost.** Cross-office work is a message, not a join.
- **To change it.** The owner's OK.

## 8. One procedure call per command

- **Decision.** Each mill command is one stored-procedure call (one round trip); the server reads its last result.
- **Why.** Performance and integrity: the guards, the writes and the answer share one call and one transaction.
- **Cost.** Procedures carry the logic; the server maps refusal codes to full text (MESSAGE_TEXT holds 128 characters).
- **To change it.** A measured command that needs two calls, plus the owner's OK.

## 9. Office settings live in config.toml

- **Decision.** Office settings, trust included, live in the server's `config.toml`, as on main. No table holds
  them. The key is `trust`; see "The trust key" below.
- **Why not a table.** It is main's design, the office human edits that file, and one source of truth means a
  setting cannot say one thing in the file and another in the book (owner review, PR #199).
- **What `b_trust()` is.** One SQL function in the book, `b_trust()`, DETERMINISTIC and NO SQL, whose whole body is
  `RETURN 'high'` or `RETURN 'limited'`. Procedures call it to read the level. It holds no state of its own: it is
  a copy of the file, made by the server.
- **When it is made.** One routine does it (`agent_coord/server/records/trust_fn.py`, `init_trust_fn`):
  - at server startup, before the server accepts any request;
  - on `mill trust high|limited` (Admin): the server writes `config.toml` first, then re-creates the function.
  It runs under the `config.toml` login, the one `migrate.ensure` uses to install routines, never the EXECUTE-only
  app user. `mill install sql --apply` installs it with the default body `high`; the next start sets it from the file.
- **A hand edit of `config.toml` takes effect at the next server restart.** Until then the procedures keep the
  level of the last start or `mill trust`. There is no stamp and no drift check; startup is the one init point.
  (`AGENT_COORD_TRUST` still overrides the file, as on main.)
- **Startup failure.** If `trust` holds anything but a trust level, the server does not start: it logs and exits
  with `config.toml trust = '...' is not a trust level: use high or limited`. If the key is absent, main's default
  `high` (admin.md) applies and the server logs that it used the default. If the book cannot be reached, the server
  starts as on main (`/health` is 503 until the book is back) and logs that `b_trust()` was not initialised; the
  function keeps its last value until the next restart or `mill trust`.
- **`mill trust` failure.** If re-creating the function fails, the server puts `config.toml` back as it was and the
  command returns the error, so the file and the function do not disagree.
- **Main's books.** A book with no `b_trust()` (main's shape) is left alone at startup and on `mill trust`.
  `b_trust()` is also left out of the routines fingerprint, so a re-init never makes `mill install sql` report the
  book as changed.
- **Cost.** One DROP and CREATE FUNCTION per start and per `mill trust`.
- **To change it.** The owner's OK.

### The trust key

`trust` in `config.toml`: `high` (the default when the key is absent) or `limited`. Main's spellings `low` and
`strict` also mean `limited`. Any other value stops the server at startup. Set it with `mill trust high|limited`
(Admin), or edit the file and restart the server.
