# BETA-CHANGES: beta_ddl.sql against main's tables.sql

Main's `tables.sql` is the baseline (owner rule, 2026-10-24): its table names, column names, types and keys stay
unless a row below says why. Allowed reasons: the three rules (composite (type, id) references, nested-set trees,
label rank), the name restore, trust in the procedures, a measured lab result, or an owner decision. Every row is
**proposed, needs the owner**. A diff to `tables.sql` or `beta_ddl.sql` must update this file, or
`docs/requirements/schema-design.md` for a design change (test F160). Design: `docs/requirements/schema-design.md`.

31 departures (rows 1-39; rows 1, 2, 5, 6, 12, 18, 25 and 36 withdrawn). `beta_ddl.sql` keeps main's table order, except
that seat, the desk kind table, comes right after name (row 37); new tables sit next to the main table they extend.

| # | main (table.column / key) | beta | why | status |
|---|---|---|---|---|
| 1 | every `BIGINT UNSIGNED` id and id reference (all tables) | ~~`INT UNSIGNED`~~: same as main, `BIGINT UNSIGNED`; the beta-only tables use it too | withdrawn: the owner decision 2026-10-24, ids stay BIGINT UNSIGNED as on main (sizes below) | withdrawn |
| 2 | `name` keys: PRIMARY (id), UNIQUE `idx_type` (type, name) | ~~adds UNIQUE `idx_type_id` (type, id)~~: same as main | withdrawn: same as main since the kind-table rework (the owner decision 2026-10-24); nothing references (type, id) any more | withdrawn |
| 3 | `member`.fk_member_name, fk_member_desk: `(col) REFERENCES name (id)` | fk_member_name `(name_id, name_kind) REFERENCES name (id, type)` (row 38), fk_member_desk `(desk_id) REFERENCES seat (desk_id)`, same names and ON DELETE rule | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 4 | `activity`.fk_activity_desk, fk_activity_roster: `(col) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`, `(roster_id, roster_kind) REFERENCES name (id, type)` (row 38) | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 5 | `label`.fk_label_name: `(name_id) REFERENCES name (id)` | ~~typed composite FK~~: same as main | withdrawn: same as main since the kind-table rework (the owner decision 2026-10-24); label has no kind table on main (open question Q1) | withdrawn |
| 6 | `tree`.fk_tree_name: `(name_id) REFERENCES name (id)` | ~~typed composite FK~~: same as main | withdrawn: same as main since the kind-table rework (the owner decision 2026-10-24); tree has no kind table on main (open question Q1) | withdrawn |
| 7 | `watcher`.fk_watcher_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 8 | `mail`.fk_mail_desk, fk_mail_roster: `(col) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`, `(roster_id, roster_kind) REFERENCES name (id, type)` (row 38) | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 9 | `mail_to`.fk_mail_to_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 10 | `tree_read`.fk_tree_read_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`; fk_tree_read_tree `(tree_id, tree_kind) REFERENCES name (id, type)` (row 38) | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 11 | `todo`.fk_todo_roster, fk_todo_updated, fk_todo_creator, fk_todo_assigned: `(col) REFERENCES name (id)` | `(roster_id, roster_kind) REFERENCES name (id, type)` (row 38); updated_id, creator_id, assigned_id `REFERENCES seat (desk_id)` | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 12 | `seat`.fk_seat_desk: `(desk_id) REFERENCES name (id)` | ~~typed composite FK~~: same as main; seat is now the desk kind table (row 37) | withdrawn: same as main since the kind-table rework (the owner decision 2026-10-24) | withdrawn |
| 13 | `doing`.fk_doing_desk, fk_doing_roster: `(col) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`, `(roster_id, roster_kind) REFERENCES name (id, type)` (row 38) | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 14 | `hold`.fk_hold_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`; fk_hold_res `(resource_id, resource_kind) REFERENCES name (id, type)` (row 38) | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 15 | `score`.fk_score_roster, fk_score_desk: `(col) REFERENCES name (id)` | `(roster_id, roster_kind) REFERENCES name (id, type)` (row 38), `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 16 | `score_point`.fk_score_point_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 17 | `human_desk`.fk_human_desk_desk: `(desk_id) REFERENCES name (id)` ON DELETE CASCADE | `(desk_id) REFERENCES seat (desk_id)`, same ON DELETE rule | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 18 | `human_member`.fk_human_member_name: `(name_id) REFERENCES name (id)` ON DELETE CASCADE | ~~`(name_id) REFERENCES roster (id)`~~: same as main | withdrawn with row 36 (the owner rule 2026-10-25): a roster has no kind table | withdrawn |
| 19 | `push_queue`.fk_push_queue_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner rule 2026-10-25): a desk column FKs to seat, the desk kind table, which has real desk data; a roster has no data of its own, so roster columns FK to name with a kind check (row 38) | proposed, needs the owner |
| 20 | `activity.desk_id` NOT NULL | NULL allowed (NULL = the office itself) | forced by the desk FK to seat (desk_id): main's system-score activity rows store roster id 2 (Admin) in desk_id, and a roster is not a seat | proposed, needs the owner |
| 21 | `score.desk_id` NOT NULL; UNIQUE `idx_score_who` (roster_id, desk_id, kpi) | desk_id NULL allowed; generated `desk_key` = IFNULL(desk_id, 0); UNIQUE `idx_score_who` (roster_id, desk_key, kpi) | forced by the desk FK to seat (system scores used roster id 2 as their desk); desk_key keeps one office row per kpi | proposed, needs the owner |
| 22 | system score seed rows: desk_id = 2 | desk_id = NULL | same reason as the row above | proposed, needs the owner |
| 23 | trigger `name_no_delete` text names mill_name_delete | text names sp_name_retire (same behavior) | name restore: retire is sp_name_retire | proposed, needs the owner |
| 24 | (none) | trigger `name_fixed`: type and id are fixed; a retired name is not renamed | name restore (the owner decision 2026-10-24); admin.md section 4 | proposed, needs the owner |
| 25 | (none) | ~~table `name_event` (append-only name history) + 2 seed rows + triggers `name_event_fixed`, `name_event_kept`~~ | withdrawn: the owner decision 2026-10-24, no name history (see Names below) | withdrawn |
| 26 | `label` comment: 'Gaps stay. Never renumber.' | ordinals with a periodic renumber routine (sp_label_renumber), 0 and 65535 kept | the owner rule (label rank with periodic renumber) | proposed, needs the owner |
| 27 | `push_queue` comment: 30-day delete | 7-day delete (the purge procedure follows) | the owner decision: push retention 7 days | proposed, needs the owner |
| 28 | (none) | `todo.done_when` VARCHAR(1000) NULL | the owner decision: acceptance line on a card (lab gaps, RESULTS.md line 172) | proposed, needs the owner |
| 29 | (none) | table `todo_event` (status history, evidence on ship/done) | the owner decision: pass with evidence (RESULTS.md lines 173-174); lab H5, RESULTS.md line 114 | proposed, needs the owner |
| 30 | `doing` keys | adds UNIQUE `idx_id_desk` (id, desk_id) | target of doing_now's composite FK (next row) | proposed, needs the owner |
| 31 | (none) | table `doing_now` (the desk's current doing) | lab: A2 desk doing 4.6 ms to 0.1 ms at M (RESULTS.md lines 20 and 56) | proposed, needs the owner |
| 32 | (none) | tables `vote`, `vote_option`, `vote_cast` + triggers `vote_cast_open`, `vote_cast_change` | the owner decision: a roster decides by vote (open, cast, close); no lead role | proposed, needs the owner |
| 33 | (none) | table `glance_cache` (relaxed tier, 30 s); no office-wide unread; its columns are the keys the shipped client reads (`at`, `letters_1d`, `card_moves_1d`, `doings_1d`, `holds_1d`, `points_1d`, `agent_coord/server/beta_client.py`) | lab: glance over traces 226 ms at M, 4.1 s at 10x, cached 0.25 ms (RESULTS.md lines 24-25, 52, 57); the owner decision: drop office-wide unread | proposed, needs the owner |
| 34 | (none) | table `sp_deploy` (SP version stamp) | the owner decision: SP version stamp, client warns or refuses on mismatch | proposed, needs the owner |
| 35 | header comment | adds the BETA blocks: three rules, names, kind tables, trust, ids | documentation of the rows above | proposed, needs the owner |
| 36 | (none) | ~~table `roster` (id = name.id, FK to `name (id)`) + seed rows 1 (Office), 2 (Admin), written by `b_name_mint`~~ | withdrawn: the owner rule (2026-10-25), a name kind gets its own table only if the thing has its own data; a roster has none, so the eight roster columns keep main's FK to `name (id)` (F167) | withdrawn |
| 37 | table order: `seat` after `todo` | `seat` right after `name` (the desk kind table first) | kind tables: the desk columns of member, activity, mail and the rest FK to seat (desk_id), so seat is created before them | proposed, needs the owner |
| 38 | `name` keys; the twelve single-kind name references (member.name_id, human_member.name_id; roster_id on activity, mail, todo, doing, score, vote; tree.name_id, tree_read.tree_id; label.name_id; hold.resource_id): `(col) REFERENCES name (id)` | `name` adds UNIQUE `idx_id_type` (id, type); each of the twelve tables adds a `<x>_kind` ENUM('desk','roster','label','tree','res') NOT NULL with DEFAULT and CHECK pinned to its kind, and its FK is `(col, <x>_kind) REFERENCES name (id, type)`, same constraint name and ON DELETE rule (human_member CASCADE, the rest RESTRICT); `seat.desk_id` stays `(desk_id) REFERENCES name (id)` | the owner's review (2026-10-25): the database refuses a wrong-kind name id (F168); UNIQUE only because MySQL 8.4 needs a unique key as an FK target (id is already the PK) | approved by the owner |
| 39 | keys covering the FKs (1de63ea had 23 indexes MySQL created for FKs, not declared in the DDL) | folded: member PRIMARY (name_id, desk_id) -> (name_id, name_kind, desk_id); activity idx_roster (roster_id, type, updated) -> (roster_id, roster_kind, type, updated); label idx_label_ord (name_id, ord, created) -> (name_id, name_kind, ord, created); tree PRIMARY (name_id, type, id) -> (name_id, name_kind, type, id); mail idx_mail_roster (roster_id) -> (roster_id, roster_kind); tree_read idx_tree (tree_id) -> (tree_id, tree_kind); todo idx_roster (roster_id, status, updated) -> (roster_id, roster_kind, status, updated); hold UNIQUE idx_hold (resource_id) -> (resource_id, resource_kind); score UNIQUE idx_score_who (roster_id, desk_key, kpi) -> (roster_id, roster_kind, desk_key, kpi); vote idx_roster_open (roster_id, closed, deadline) -> (roster_id, roster_kind, closed, deadline); human_member idx_role (name_id, human_id) -> (name_id, name_kind, human_id). Declared: todo idx_updated (updated_id), idx_creator (creator_id), idx_assigned (assigned_id); todo_event idx_desk (desk_id), idx_assigned (assigned_id); doing idx_roster (roster_id, roster_kind); doing_now idx_doing (doing_id, desk_id); hold idx_desk (desk_id); score idx_desk (desk_id); vote idx_desk (desk_id), idx_result (id, result_opt); vote_cast idx_opt (vote_id, opt) | owner rule: no implicit indexes beyond PK/UNIQUE (2026-10-25); a kind column is constant, so a PRIMARY or UNIQUE key extended by it keeps the same uniqueness; an FK that leads a PRIMARY or UNIQUE key needs no idx_* | approved by the owner |
| 40 | `agent_coord/server/sql/tables.sql` is main's 22 tables | `tables.sql` is this DDL (0.8.0 lane A): same tables, columns, keys, FKs and triggers; comments say 0.8.0 for BETA and the header names all 29 tables. A main book moves in place with `migrate_080.sql` (F170) | the release ships the reviewed schema; a fresh install and a migrated book are the same (information_schema) | lane A, PR into release/0.8.0 |

## Names (the owner decision 2026-10-24)

`name` exists only so names cannot confuse or mislead agents or humans. No name history (row 25 withdrawn). Deletion
is hard: Admin retire, the name stays reserved while retired, and reclaim restores the same id. A rename is a plain
update of `name.name`, and related records follow through the id. UNIQUE (type, name) prevents duplicates. A desk may
rename itself. **No hold on a renamed-away name, for any type** (names belong to agents, not humans): the old string
is free for a new mint at once.

## Kind tables (the owner rule 2026-10-25)

**A name kind gets its own table only if the thing has its own data; otherwise references go to `name`, kind-checked.** A name
is not a first-class object, just an isolated column managed in `name`. seat (desk_id, UNIQUE as on main) has real
desk data (token, wake, connect stamps), so it is the desk kind table: it links to `name (id)` with one FK (kind id =
name.id), and every desk column FKs to seat (desk_id), so a desk column cannot hold a roster id. A roster, label, tree
or res has no data of its own (a roster's desk count is `name.n`, as on main), so none of them has a kind table.
Their twelve columns are kind-checked instead (row 38, the owner's review 2026-10-25): the eight roster columns
(member.name_id, activity, mail, todo, doing, score, vote roster_id, human_member.name_id) and label.name_id,
tree.name_id, tree_read.tree_id, hold.resource_id each sit next to a plain `<x>_kind` ENUM pinned by DEFAULT and
CHECK, and the FK is `(col, <x>_kind) REFERENCES name (id, type)`, against `name`'s UNIQUE `idx_id_type` (id, type).
A wrong-kind name id is refused by the database (F168). Every column keeps holding the name id, so no id changes and
no join changes, and a writer that leaves the kind column out gets its DEFAULT (no procedure changes). The older
typed composite FKs to `name (type, id)` (33 at dbef70f, 32 once `name_event` went) and the generated `t_*` columns
stay gone. The beta-only tables follow the same rule: `todo_event`, `vote` and `vote_cast` FK their desk columns to
seat (desk_id), and `vote.roster_id` is kind-checked. f316ac0f (2026-10-24) had a `roster` kind table; the owner
dropped it on 2026-10-25 (row 36).

| measure (fresh book, information_schema) | main `tables.sql` (943b3c2) | dbef70f (before) | PR #199 head (5d350b9) | f316ac0f (roster table) | no roster table (a1cda5f) | kind-checked (1de63ea) | explicit indexes (now) |
|---|---|---|---|---|---|---|---|
| tables | 22 | 30 | 31 (with `office_setting`) | 30 (name_event out, roster in) | 29 (roster out) | 29 | 29 |
| FKs, all | 35 | 48 | 49 | 47 | 46 | 46 | 46 |
| FKs to `name` | 27 | 34 (33 typed (type, id) + name_event.name_id) | 35 | 6 (seat, roster; label, tree, tree_read, hold) | 13 (seat; 8 roster columns; label, tree, tree_read, hold) | 13 (seat plain; 12 kind-checked) | 13 |
| FKs to `seat (desk_id)` / `roster (id)` | 0 / 0 | 0 / 0 | 0 / 0 | 19 / 8 | 19 / 0 | 19 / 0 | 19 / 0 |
| indexes, all (incl. PRIMARY) | 68 | 115 | 117 | 89 | 88 | 100 | 89 |
| secondary indexes | 46 | 85 | 86 | 59 | 59 | 71 | 60 |
| indexes MySQL adds for an FK (named fk_*) | 6 | 36 | 37 | 12 | 12 | 23 | 0 |
| kind columns (`*_kind`) / CHECK constraints | | | | | 0 / 7 | 12 / 19 | 12 / 19 |
| generated `t_*` columns | 0 | 30 | 31 | 0 | 0 | 0 | 0 |
| id columns BIGINT / INT UNSIGNED | 49 / 0 | | 1 / 66 | 64 / 0 (row 1 withdrawn) | 63 / 0 | 63 / 0 | 63 / 0 |

Indexes, now (row 39): 89, one more than a1cda5f (`name.idx_id_type`), and none of them implicit. At 1de63ea MySQL
created 23 indexes for FKs (not declared in the DDL): 12 already at a1cda5f on desk and other FKs, and 11 for the new
composite FKs. Row 39 folds each kind column into the PRIMARY, UNIQUE or idx_* key that leads with its column (9
keys plus 2 PRIMARY keys) and declares an idx_* key for the 12 FKs no key covered (test F169).

Reads on a folded key (measured with EXPLAIN on a fresh MySQL 8.4 book): the kind
column now sits right after the referenced column, and MySQL does not read a CHECK as a constant. A read that
filters only the column uses the first key part, so `label` by `ord` sorts with a filesort, and the score, member
and tree key lookups become a lookup on the first column instead of the whole key. Adding `AND <x>_kind = '<kind>'`
to the read restores the full key (no filesort; const lookups). Procedures ported onto this schema add that
predicate to reads on these keys.

Id width, measured on a throwaway book (MySQL 8.4, 200,000 letters: `mail`, `mail_to` and `activity` rows each,
data + index after ANALYZE): BIGINT ids 102.3 MB, the same as main to the tenth; INT ids 81.2 MB (21% less).
The owner kept BIGINT (row 1 withdrawn).

Scope: only single-kind columns moved (a desk column always holds a desk, a roster column a roster). Every
multi-kind (type, id) composite reference (label, tree, watcher, doing.on_* / waiting_*, activity) is unchanged.

### Open questions for the owner

- Q1 and Q2 are answered by the rule above (2026-10-25): no kind table for label, tree, res or roster, and
  `name.n` stays on `name`. Since the owner's review (row 38) the database also stops a wrong-kind id in those
  twelve columns (F168).
- Q3. Typing at the kind table: `seat.desk_id` FKs to `name (id)`, so only the minting procedure makes
  sure a seat row is a desk name (the app user is EXECUTE-only). The database could
  check it too with the row 38 pattern (`name.idx_id_type` is already there, so the cost is a `desk_kind`
  column and CHECK on seat, folded into its UNIQUE `idx_desk`), or a BEFORE INSERT trigger. Not done: the owner
  kept `seat.desk_id` a plain FK (2026-10-25).

### Drop when ported (main's guards the kind-checked FKs make redundant)

Main lacks row 38, so main's procedures stay as they are. When they are ported onto this schema, these by-id kind
checks can become the constant they confirm. Office (id 1) is never retired, and `roster_id` is kind-checked by
fk_*_roster, so `SELECT id FROM name WHERE id = 1 AND type = 'roster'` can only return 1:

- `agent_coord/server/sql/sp_activity.sql:226` (Office by id, also `AND deleted IS NULL`; fk_activity_roster)
- `agent_coord/server/sql/sp_score.sql:93`, `:529`, `:636` (Office by id; fk_score_roster)

These stay: name lookups within a kind (`mill_roster_id`, the mint, rename, retire and reclaim selects), the
desk-or-roster routing in `sp_mail.sql:28`, `:74`, `:149` (mail_to recipients and add/remove WHO are not among the
twelve columns), and read filters and sorts (`sp_activity.sql:92`, `sp_tree.sql:404`, `sp_score.sql:367-415`).
`beta_sp.sql` has no such guard: its `name` selects are lookups by name within a kind, plus the Admin row lock in
`sp_admin_set`.

## Main tables with no change beyond rows 3-19 and 38 (kind-table FKs, kind-checked name FKs)

name (rows 23-24 triggers, row 38 key), member, activity (row 20), label (row 26 is a comment), tree, watcher,
mail, mail_to, tree_read, todo (row 28), seat (row 37), doing (row 30), hold, score (rows 21-22), score_point,
score_evidence, human, human_desk, human_member, push_queue (row 27 is a comment).

Unchanged entirely: `mill_invite`, `mill_invite_join` (no id columns, no reference to name). See finding F1.

## Not in any book yet

- `uc_a6_glance_cached`: `agent_coord/server/beta_client.py` (`read_cached_glance`, behind `mill glance`) calls it,
  but neither main's `server/sql` nor `beta_sp.sql` defines it. Until a book does, the glance refuses with
  "glance: the cached glance is not installed" (test `test_glance_refuses_when_the_read_is_missing`). Row 33 is only
  the `glance_cache` table it would read. Test F166 fails if the client calls a procedure that is neither defined
  in a book nor listed here.

## Reverted to main in this push (were in beta_ddl.sql at 9ab69e3)

- Design B's split and renames: `desk`, `room` (the fold), `room_member` (left_at), `grp`, `grp_member`,
  `letter` / `letter_to` (back to `mail` / `mail_to`, `asked` instead of kind named/copied), `card` / `card_event`
  (back to `todo`; history kept as the smaller `todo_event`, without the status composite FK and the claimed_at
  CHECKs), `tree` + `tree_node` (back to main's one `tree`), `label_name` (a label is a name row again),
  `resource` (a resource is a name row again), `hold` "no row = free" + `hold_event` (back to main's hold),
  `doing` on_kind/wait_kind (back to main's on_type/waiting_*), `push` (back to `push_queue`), the `activity`
  sequence timeline (back to main's (type, id) activity), `decision` names (now `vote`, `vote_option`, `vote_cast`).
- Restored main tables beta had dropped: `watcher`, `tree_read`.
- Dropped beta triggers: letter sender is a current member, letter room fixed, Office stays, room_member no delete,
  thread letter in its room. Those guards move into the procedures (trust-in-SP).
- `mill_invite.created_by` back to main's VARCHAR (see F1).

## beta_sp.sql in this push

- No `name_event`: mint, rename, retire and reclaim change the `name` row only (`b_name_event` is dropped).
- `b_name_mint` writes only the `name` row for a roster (no `roster` table, row 36).
- Trust has no table: `b_trust()` installs as `RETURN 'high'` and the server re-creates it from `config.toml`
  (schema-design.md section 9). `cmd_trust` shows `b_trust()` to any seated desk; a set is guarded there (Admin, high
  or limited) and answers the level, and the server writes `config.toml` and re-creates the function.
- Every id parameter and variable is `BIGINT UNSIGNED`.

## Suggested requirement edits, needs the owner

admin.md is owned by the office human; Builder does not edit it. Suggested line, after the **Trust:** paragraph at
the top of admin.md:

- "Trust is stored in the server's `config.toml` (`trust = high|limited`). The server copies it into the SQL
  function `b_trust()` at startup and after `mill trust`; a hand edit of the file takes effect at the next restart.
  Procedures read `b_trust()` and never take trust as an argument."

## Findings (not applied; for the owner)

- F1. `mill_invite.created_by` and `mill_invite_join.party_id` store desk names as strings (or 'wall' / 'door'),
  against "no other table stores a name string". Proposal: a desk name id plus a party kind. Not applied.
- F2. On main, `mill_name_rename` / `_delete` / `_reclaim` have no Admin check in SQL (it is in `admin/catalog.py`),
  and `mill_label_put` mints a label with no trust check (it is in `rpc._h_label`). Beta puts both in the procedure.
- F3. Withdrawn: trust in config.toml is main's design and stays (owner review, PR #199). Beta keeps it there;
  the server re-creates `b_trust()` from it at startup and on `mill trust` (schema-design.md section 9).
- F4. Main writes roster id 2 (Admin) into desk columns (system score rows and their activity rows). Under typed FKs
  that is refused; beta uses NULL. Any main procedure that writes 2 as a desk must change.
- F5. Lab bad states that main permits and this baseline keeps (not applied, need a decision): a mail reaching or
  sent by a non-member (P4/P17), two read states (`tree_read` and `mail_to.opened`, P1), holds with no card link
  (H6). RESULTS.md lines 64-88 and 115.
