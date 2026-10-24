# BETA-CHANGES: beta_ddl.sql against main's tables.sql

Main's `tables.sql` is the baseline (owner rule, 2026-10-24): its table names, column names, types and keys stay
unless a row below says why. Allowed reasons: the three rules (composite (type, id) references, nested-set trees,
label rank), the name restore, trust in the procedures, a measured lab result, or an owner decision. Every row is
**proposed, needs the owner**. A diff to `tables.sql` or `beta_ddl.sql` must update this file, or
`docs/requirements/schema-design.md` for a design change (test F160). Design: `docs/requirements/schema-design.md`.

36 departures. `beta_ddl.sql` keeps main's table order; new tables sit next to the main table they extend.

| # | main (table.column / key) | beta | why | status |
|---|---|---|---|---|
| 1 | every `BIGINT UNSIGNED` id and id reference (all tables) | `INT UNSIGNED`; `push_queue.id` stays `BIGINT UNSIGNED` | the owner decision (2026-10-24): ids are INT UNSIGNED unless justified; push_queue is a churning queue | proposed, needs the owner |
| 2 | `name` keys: PRIMARY (id), UNIQUE `idx_type` (type, name) | adds UNIQUE `idx_type_id` (type, id), the referenced key | name restore (the owner decision 2026-10-24): every reference is a typed composite FK | proposed, needs the owner |
| 3 | `member`.fk_member_name, fk_member_desk: `(col) REFERENCES name (id)` | generated constant column(s) t_roster, t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 4 | `activity`.fk_activity_desk, fk_activity_roster: `(col) REFERENCES name (id)` | generated constant column(s) t_desk, t_roster; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 5 | `label`.fk_label_name: `(col) REFERENCES name (id)` | generated constant column(s) t_label; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 6 | `tree`.fk_tree_name: `(col) REFERENCES name (id)` | generated constant column(s) t_tree; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 7 | `watcher`.fk_watcher_desk: `(col) REFERENCES name (id)` | generated constant column(s) t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 8 | `mail`.fk_mail_desk, fk_mail_roster: `(col) REFERENCES name (id)` | generated constant column(s) t_desk, t_roster; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 9 | `mail_to`.fk_mail_to_desk: `(col) REFERENCES name (id)` | generated constant column(s) t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 10 | `tree_read`.fk_tree_read_desk, fk_tree_read_tree: `(col) REFERENCES name (id)` | generated constant column(s) t_desk, t_tree; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 11 | `todo`.fk_todo_roster, fk_todo_updated, fk_todo_creator, fk_todo_assigned: `(col) REFERENCES name (id)` | generated constant column(s) t_roster, t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 12 | `seat`.fk_seat_desk: `(col) REFERENCES name (id)` | generated constant column(s) t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 13 | `doing`.fk_doing_desk, fk_doing_roster: `(col) REFERENCES name (id)` | generated constant column(s) t_desk, t_roster; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 14 | `hold`.fk_hold_desk, fk_hold_res: `(col) REFERENCES name (id)` | generated constant column(s) t_desk, t_res; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 15 | `score`.fk_score_roster, fk_score_desk: `(col) REFERENCES name (id)` | generated constant column(s) t_roster, t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 16 | `score_point`.fk_score_point_desk: `(col) REFERENCES name (id)` | generated constant column(s) t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 17 | `human_desk`.fk_human_desk_desk: `(col) REFERENCES name (id)` | generated constant column(s) t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 18 | `human_member`.fk_human_member_name: `(col) REFERENCES name (id)` | generated constant column(s) t_roster; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 19 | `push_queue`.fk_push_queue_desk: `(col) REFERENCES name (id)` | generated constant column(s) t_desk; FK `(t_x, col) REFERENCES name (type, id)`, same name and ON DELETE rule | name restore (the owner decision 2026-10-24): a desk column cannot hold a roster id | proposed, needs the owner |
| 20 | `activity.desk_id` NOT NULL | NULL allowed (NULL = the office itself) | forced by the typed FK: main's system-score activity rows store roster id 2 (Admin) in desk_id | proposed, needs the owner |
| 21 | `score.desk_id` NOT NULL; UNIQUE `idx_score_who` (roster_id, desk_id, kpi) | desk_id NULL allowed; generated `desk_key` = IFNULL(desk_id, 0); UNIQUE `idx_score_who` (roster_id, desk_key, kpi) | forced by the typed FK (system scores used roster id 2 as their desk); desk_key keeps one office row per kpi | proposed, needs the owner |
| 22 | system score seed rows: desk_id = 2 | desk_id = NULL | same reason as the row above | proposed, needs the owner |
| 23 | trigger `name_no_delete` text names mill_name_delete | text names sp_name_retire (same behavior) | name restore: retire is sp_name_retire | proposed, needs the owner |
| 24 | (none) | trigger `name_fixed`: type and id are fixed; a retired name is not renamed | name restore (the owner decision 2026-10-24); admin.md section 4 | proposed, needs the owner |
| 25 | (none) | table `name_event` (append-only history: mint, rename, retire, reclaim; old, new, by whom, trust) + 2 seed rows + triggers `name_event_fixed`, `name_event_kept` | name restore (the owner decision 2026-10-24): history cannot be quietly rewritten | proposed, needs the owner |
| 26 | trust in the server config file (`config.mill_trust`) | table `office_setting` (one row: trust high or limited) | trust-in-SP (the owner decision 2026-10-24): a procedure cannot read the config file; the app user is EXECUTE-only | proposed, needs the owner |
| 27 | `label` comment: 'Gaps stay. Never renumber.' | ordinals with a periodic renumber routine (sp_label_renumber), 0 and 65535 kept | the owner rule (label rank with periodic renumber) | proposed, needs the owner |
| 28 | `push_queue` comment: 30-day delete | 7-day delete (the purge procedure follows) | the owner decision: push retention 7 days | proposed, needs the owner |
| 29 | (none) | `todo.done_when` VARCHAR(1000) NULL | the owner decision: acceptance line on a card (lab gaps, RESULTS.md line 172) | proposed, needs the owner |
| 30 | (none) | table `todo_event` (status history, evidence on ship/done) | the owner decision: pass with evidence (RESULTS.md lines 173-174); lab H5, RESULTS.md line 114 | proposed, needs the owner |
| 31 | `doing` keys | adds UNIQUE `idx_id_desk` (id, desk_id) | target of doing_now's composite FK (next row) | proposed, needs the owner |
| 32 | (none) | table `doing_now` (the desk's current doing) | lab: A2 desk doing 4.6 ms to 0.1 ms at M (RESULTS.md lines 20 and 56) | proposed, needs the owner |
| 33 | (none) | tables `vote`, `vote_option`, `vote_cast` + triggers `vote_cast_open`, `vote_cast_change` | the owner decision: a roster decides by vote (open, cast, close); no lead role | proposed, needs the owner |
| 34 | (none) | table `glance_cache` (relaxed tier, 30 s); no office-wide unread | lab: glance over traces 226 ms at M, 4.1 s at 10x, cached 0.25 ms (RESULTS.md lines 24-25, 52, 57); the owner decision: drop office-wide unread | proposed, needs the owner |
| 35 | (none) | table `sp_deploy` (SP version stamp) | the owner decision: SP version stamp, client warns or refuses on mismatch | proposed, needs the owner |
| 36 | header comment | adds the BETA blocks: three rules, names, trust, ids | documentation of the rows above | proposed, needs the owner |

## Main tables with no change beyond rows 1 and 3-19 (ids and typed FKs)

name (row 2 adds a key; rows 23-24 triggers), member, activity (row 20), label (row 27 is a comment), tree, watcher,
mail, mail_to, tree_read, todo (row 29), seat, doing (row 31), hold, score (rows 21-22), score_point,
score_evidence, human, human_desk, human_member, push_queue (row 28 is a comment).

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

## Findings (not applied; for the owner)

- F1. `mill_invite.created_by` and `mill_invite_join.party_id` store desk names as strings (or 'wall' / 'door'),
  against "no other table stores a name string". Proposal: a desk name id plus a party kind. Not applied.
- F2. On main, `mill_name_rename` / `_delete` / `_reclaim` have no Admin check in SQL (it is in `admin/catalog.py`),
  and `mill_label_put` mints a label with no trust check (it is in `rpc._h_label`). Beta puts both in the procedure.
- F3. On main, trust lives in the server config file; beta reads `office_setting`. `mill trust` set and the
  migration must write the row (L2/L1).
- F4. Main writes roster id 2 (Admin) into desk columns (system score rows and their activity rows). Under typed FKs
  that is refused; beta uses NULL. Any main procedure that writes 2 as a desk must change.
- F5. Lab bad states that main permits and this baseline keeps (not applied, need a decision): a mail reaching or
  sent by a non-member (P4/P17), two read states (`tree_read` and `mail_to.opened`, P1), holds with no card link
  (H6). RESULTS.md lines 64-88 and 115.
