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

## 1. No universal id table: polymorphic references are (kind ENUM, id INT UNSIGNED)

- **Decision.** There is no table of every id. A reference that can point at several kinds is the composite
  (type ENUM, id), as on main's `activity`, `label`, `tree`, `watcher` and `doing.on_*` / `waiting_*`. Beta (0.8): ids are
  `INT UNSIGNED`; a wider id needs a stated reason (`push_queue.id`, a churning queue). Main: `BIGINT UNSIGNED`.
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
  0 pinned, 65535 unplaced); a desk's focus list is a label. Beta (0.8): ordinals are renumbered by a routine
  (`sp_label_renumber`) when a gap runs out, keeping 0 and 65535. Main never renumbers.
- **Why.** Performance: (name_id, ord, created) gives the order from the index alone.
- **Cost.** An occasional renumber of one label's rows.
- **To change it.** A measured order read that label rank cannot serve, plus the owner's OK.

## 5. One name table is the one place names are managed

- **Decision.** Every name (desk, roster, label, tree, res) is one row of `name`, UNIQUE (type, name), referenced by
  (type, id) through a typed composite FK (beta 0.8; main: a plain FK to `name(id)`), so a desk column cannot hold a roster. No other table stores a name
  string. Rename, retire and reclaim go only through `sp_name_*`, each writes `name_event` (old, new, by whom, trust
  then; beta 0.8, main has no `name_event`), and delete is soft (`name.deleted`; a trigger refuses DELETE). Reuse of a retired name is an Admin reclaim
  of the same id. Rules: admin.md sections 1, 2 and 4, rows F60, F65, F92, F135.
- **Why.** Integrity, in the owner's words: names are everything in the activities, and renaming or deleting a name
  is an easy way to mislead; one table plus one procedure family is the single choke point.
- **Cost.** A generated type column per referencing table and a (type, id) key.
- **To change it.** The owner's OK; a performance claim also needs a lab result.

## 6. High / limited trust with Admin applies to every command, enforced in the procedures

- **Decision.** The office trust setting lives in the book (`office_setting`). Every command procedure reads it
  itself and applies admin.md sections 1-3 (always Admin; trust-gated; any desk). Admin grant is the host path only.
- **Why.** Integrity: the app database user holds EXECUTE only, so the procedure is the only place a guard can stand;
  a guard that reads an app argument can be lied to.
- **Cost.** One indexed read per command.
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
