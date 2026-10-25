# BETA-CHANGES: beta_ddl.sql against main's tables.sql

Main's `tables.sql` is the baseline (owner rule, 2026-10-24): its table names, column names, types and keys stay
unless a row below says why. Allowed reasons: the three rules (composite (type, id) references, nested-set trees,
label rank), the name restore, trust in the procedures, a measured lab result, or an owner decision. Every row is
**proposed, needs the owner**. A diff to `tables.sql` or `beta_ddl.sql` must update this file, or
`docs/requirements/schema-design.md` for a design change (test F160). Design: `docs/requirements/schema-design.md`.

31 departures (rows 1-37; rows 1, 2, 5, 6, 12 and 25 withdrawn). `beta_ddl.sql` keeps main's table order, except that
the kind tables come first (row 37); new tables sit next to the main table they extend.

| # | main (table.column / key) | beta | why | status |
|---|---|---|---|---|
| 1 | every `BIGINT UNSIGNED` id and id reference (all tables) | ~~`INT UNSIGNED`~~: same as main, `BIGINT UNSIGNED`; the beta-only tables use it too | withdrawn: the owner decision 2026-10-24, ids stay BIGINT UNSIGNED as on main (sizes below) | withdrawn |
| 2 | `name` keys: PRIMARY (id), UNIQUE `idx_type` (type, name) | ~~adds UNIQUE `idx_type_id` (type, id)~~: same as main | withdrawn: same as main since the kind-table rework (the owner decision 2026-10-24); nothing references (type, id) any more | withdrawn |
| 3 | `member`.fk_member_name, fk_member_desk: `(col) REFERENCES name (id)` | fk_member_name `(name_id) REFERENCES roster (id)`, fk_member_desk `(desk_id) REFERENCES seat (desk_id)`, same names and ON DELETE rule | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 4 | `activity`.fk_activity_desk, fk_activity_roster: `(col) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`, `(roster_id) REFERENCES roster (id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 5 | `label`.fk_label_name: `(name_id) REFERENCES name (id)` | ~~typed composite FK~~: same as main | withdrawn: same as main since the kind-table rework (the owner decision 2026-10-24); label has no kind table on main (open question Q1) | withdrawn |
| 6 | `tree`.fk_tree_name: `(name_id) REFERENCES name (id)` | ~~typed composite FK~~: same as main | withdrawn: same as main since the kind-table rework (the owner decision 2026-10-24); tree has no kind table on main (open question Q1) | withdrawn |
| 7 | `watcher`.fk_watcher_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 8 | `mail`.fk_mail_desk, fk_mail_roster: `(col) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`, `(roster_id) REFERENCES roster (id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 9 | `mail_to`.fk_mail_to_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 10 | `tree_read`.fk_tree_read_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`; fk_tree_read_tree stays main's `(tree_id) REFERENCES name (id)` (open question Q1) | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 11 | `todo`.fk_todo_roster, fk_todo_updated, fk_todo_creator, fk_todo_assigned: `(col) REFERENCES name (id)` | `(roster_id) REFERENCES roster (id)`; updated_id, creator_id, assigned_id `REFERENCES seat (desk_id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 12 | `seat`.fk_seat_desk: `(desk_id) REFERENCES name (id)` | ~~typed composite FK~~: same as main; seat is now the desk kind table (row 37) | withdrawn: same as main since the kind-table rework (the owner decision 2026-10-24) | withdrawn |
| 13 | `doing`.fk_doing_desk, fk_doing_roster: `(col) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`, `(roster_id) REFERENCES roster (id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 14 | `hold`.fk_hold_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)`; fk_hold_res stays main's `(resource_id) REFERENCES name (id)` (open question Q1) | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 15 | `score`.fk_score_roster, fk_score_desk: `(col) REFERENCES name (id)` | `(roster_id) REFERENCES roster (id)`, `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 16 | `score_point`.fk_score_point_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 17 | `human_desk`.fk_human_desk_desk: `(desk_id) REFERENCES name (id)` ON DELETE CASCADE | `(desk_id) REFERENCES seat (desk_id)`, same ON DELETE rule | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 18 | `human_member`.fk_human_member_name: `(name_id) REFERENCES name (id)` ON DELETE CASCADE | `(name_id) REFERENCES roster (id)`, same ON DELETE rule | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
| 19 | `push_queue`.fk_push_queue_desk: `(desk_id) REFERENCES name (id)` | `(desk_id) REFERENCES seat (desk_id)` | kind tables (the owner decision 2026-10-24): a desk column FKs to the desk kind table, a roster column to the roster kind table; only kind tables link to name | proposed, needs the owner |
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
| 36 | (none) | table `roster` (id BIGINT UNSIGNED PRIMARY KEY = name.id, fk_roster_name `(id) REFERENCES name (id)` RESTRICT) + seed rows 1 (Office), 2 (Admin); `b_name_mint` writes it with a roster name | kind tables (the owner decision 2026-10-24): main has no roster table, and the owner named roster as a kind table; it is one column (open question Q2) | proposed, needs the owner |
| 37 | table order: `seat` after `todo` | `seat` right after `name` and `roster` (the kind tables first) | kind tables: the desk columns of member, activity, mail and the rest FK to seat (desk_id), so seat is created before them | proposed, needs the owner |

## Names (the owner decision 2026-10-24)

`name` exists only so names cannot confuse or mislead agents or humans. No name history (row 25 withdrawn). Deletion
is hard: Admin retire, the name stays reserved while retired, and reclaim restores the same id. A rename is a plain
update of `name.name`, and related records follow through the id. UNIQUE (type, name) prevents duplicates. A desk may
rename itself. **No hold on a renamed-away name, for any type** (names belong to agents, not humans): the old string
is free for a new mint at once.

## Kind tables (the owner decision 2026-10-24)

A name is not a first-class object, just an isolated column managed in `name`. A table that needs a desk, roster,
tree and so on FKs to that kind's table, never to `name (type, id)`; only a kind table links to `name`. Link shape:
**kind id = name.id, one FK per kind table to `name (id)`**. seat (desk_id, UNIQUE as on main) is the desk kind and
roster (id) the roster kind; every desk and roster column keeps holding the name id, so no id changes and no join
changes. The typed composite FKs to `name (type, id)` (33 at dbef70f, 32 once `name_event` went), the generated
`t_*` columns and `name`'s UNIQUE (type, id) are gone. The beta-only tables follow the same rule: `todo_event`,
`vote` and `vote_cast` FK their desk columns to seat (desk_id), and `vote.roster_id` to roster (id).

| measure (fresh book, information_schema) | main `tables.sql` (943b3c2) | dbef70f (before) | PR #199 head (5d350b9) | after this rework |
|---|---|---|---|---|
| tables | 22 | 30 | 31 (with `office_setting`) | 30 (name_event out, roster in) |
| FKs, all | 35 | 48 | 49 | 47 |
| FKs to `name` | 27 | 34 (33 typed (type, id) + name_event.name_id) | 35 | 6 (seat, roster; label, tree, tree_read, hold) |
| FKs to `seat (desk_id)` / `roster (id)` | 0 / 0 | 0 / 0 | 0 / 0 | 19 / 8 |
| indexes, all (incl. PRIMARY) | 68 | 115 | 117 | 89 |
| secondary indexes | 46 | 85 | 86 | 59 |
| indexes MySQL adds for an FK (named fk_*) | 6 | 36 | 37 | 12 |
| generated `t_*` columns | 0 | 30 | 31 | 0 |
| id columns BIGINT / INT UNSIGNED | 49 / 0 | | 1 / 66 | 64 / 0 (row 1 withdrawn) |

Id width, measured on a throwaway book (MySQL 8.4, 200,000 letters: `mail`, `mail_to` and `activity` rows each,
data + index after ANALYZE): BIGINT ids 102.3 MB, the same as main to the tenth; INT ids 81.2 MB (21% less).
The owner kept BIGINT (row 1 withdrawn).

Scope: only single-kind columns moved (a desk column always holds a desk, a roster column a roster). Every
multi-kind (type, id) composite reference (label, tree, watcher, doing.on_* / waiting_*, activity) is unchanged.

### Open questions for the owner

- Q1. label, tree and res have no kind table on main. Their four references (`label.name_id`, `tree.name_id`,
  `tree_read.tree_id`, `hold.resource_id`) keep main's untyped FK to `name (id)`, so the database does not stop a
  roster id there; the procedures do. Option: one-column kind tables for label, tree and res, like `roster`
  (no new index beyond each PRIMARY). For res, `hold` already has one row per resource (UNIQUE `idx_hold`).
- Q2. `roster` is a new one-column table (main has none). Should `name.n` (the desk count of a roster, main) move to
  `roster.n`, so `name` holds only the name?
- Q3. Typing at the kind table: `seat.desk_id` and `roster.id` FK to `name (id)`, so only the minting procedures make
  sure a seat row is a desk name and a roster row a roster name (the app user is EXECUTE-only). The database could
  check it too, at the cost of `name`'s UNIQUE (type, id) back plus a generated column on seat and roster, or a
  BEFORE INSERT trigger on each. Not done: the owner asked for the fewest indexes.

## Main tables with no change beyond rows 3-19 (kind-table FKs)

name (rows 23-24 triggers), member, activity (row 20), label (row 26 is a comment), tree, watcher,
mail, mail_to, tree_read, todo (row 28), seat (row 37), doing (row 30), hold, score (rows 21-22), score_point,
score_evidence, human, human_desk, human_member, push_queue (row 27 is a comment).

Unchanged entirely: `mill_invite`, `mill_invite_join` (no id columns, no reference to name). See finding F1.

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
- `b_name_mint` writes the `roster` row with a roster name (row 36).
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
