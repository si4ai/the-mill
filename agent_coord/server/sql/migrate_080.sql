-- 0.8.0 (card 868): a main book (0.7.18 tables) moves to the 0.8.0 schema in tables.sql.
-- Existing books only; not in apply_order.txt. A fresh book uses tables.sql.
-- migrate.ensure() (agent_coord/install/migrate.py, apply_080) creates these routines, runs the
-- preflight, then each step in order, then drops them again. The tables are changed in place: no table is
-- renamed or copied, and every id is kept.
--
-- Preflight (mill_migrate_080_preflight): one row per check, action fix (a step below changes it), refuse
-- (bad data no step can fix; the run stops before any change) or schema (a schema step still to do).
-- Steps (mill_migrate_080_step), each one checks the book first, so a second run, or a run after a kill at
-- any point, does only what is left:
--   seat        a token-NULL seat row for every desk name that has none (desk columns FK to seat next).
--   watcher     a watcher row on a roster becomes one row per member desk (same hint), then goes.
--   desk_null   activity.desk_id and score.desk_id may be NULL (the office); a value that is not a desk
--               (main wrote roster 2, Admin, for system rows, and the roster for roster-owned scores) is NULL.
--   score_key   score.desk_key (IFNULL(desk_id, 0)) and idx_score_who on (roster_id, desk_key, kpi).
--   keys_kinds  name idx_id_type, doing idx_id_desk, the 11 kind columns of the kind-checked FKs, then every
--               key 0.8.0 changes or adds on main's tables (each kind column folded into the key that leads
--               with its column; a declared idx_* key for each FK no key covers), one ALTER per table.
--   columns     no new table (the owner, 2026-10-26): activity.act, doing.act (one list), doing.peer_id,
--               doing.evidence (VARCHAR(2000) NULL, move rows only) and seat.doing_id, with their keys
--               (activity idx_updated, doing idx_on (on_type, on_id, id), idx_peer, seat idx_doing).
--   acts        each main row's act: a doing row with text is focus, an empty one on an item is finish (main's
--               mill_doing_finish row), any other empty one is clear; activity says its item's latest move (a card's
--               from its status, a doing row's own act, a hold taken or free, a letter send, a score score).
--   moves       every card gets one move row in doing, its first: by updated_id at updated, act from the status
--               (open create, parked park, claimed claim, or assign when the volunteer is another desk, shipped
--               ship, done done), peer_id the volunteer, evidence the card's evidence byte for byte (or NULL),
--               text empty. Then todo.evidence is dropped. Evidence over 2000 characters is refused by the
--               preflight (EVIDENCE_MAX; nothing is cut).
--   doing_id    seat.doing_id = the desk's newest focus row (focus or clear; created, then id: mill_doing_now's
--               order). A desk whose newest row is a finish row names the focus row that row ended.
--   drop_cols   activity.weight and activity.n go (the owner, 2026-10-26: reply bytes measure token use).
--   fks         the 15 desk FKs on main's tables move to seat (desk_id); the 11 roster, label, tree and res
--               FKs become kind-checked (col, kind) -> name (id, type); doing.fk_doing_peer and seat.fk_seat_doing
--               are added. One ALTER per table to drop, one to add.
--               Then the indexes MySQL made for main's FKs (named after the FK) go: the owner rule is that only
--               PRIMARY and UNIQUE keys are implicit, and every other index is a declared idx_* key.
-- Triggers and the routine reload are migrate.py's (they read the pack's files).
-- Each DML step runs in one transaction, so a kill leaves it done or not done.

DROP PROCEDURE IF EXISTS mill_migrate_080_exec;
DROP PROCEDURE IF EXISTS mill_migrate_080_check;
DROP PROCEDURE IF EXISTS mill_migrate_080_fk_list;
DROP PROCEDURE IF EXISTS mill_migrate_080_key_list;
DROP PROCEDURE IF EXISTS mill_migrate_080_keys;
DROP PROCEDURE IF EXISTS mill_migrate_080_fk_idx_drop;
DROP PROCEDURE IF EXISTS mill_migrate_080_preflight;
DROP PROCEDURE IF EXISTS mill_migrate_080_step;
DROP FUNCTION IF EXISTS mill_migrate_080_col;
DROP FUNCTION IF EXISTS mill_migrate_080_idx;
DROP FUNCTION IF EXISTS mill_migrate_080_tbl;
DROP FUNCTION IF EXISTS mill_migrate_080_fk_has;
DROP FUNCTION IF EXISTS mill_migrate_080_fk_ok;
DROP FUNCTION IF EXISTS mill_migrate_080_cols_ok;

DELIMITER //

CREATE FUNCTION mill_migrate_080_tbl(p_t VARCHAR(64)) RETURNS TINYINT
  NOT DETERMINISTIC READS SQL DATA
BEGIN
  RETURN (SELECT COUNT(*) > 0 FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_t);
END //

CREATE FUNCTION mill_migrate_080_col(p_t VARCHAR(64), p_c VARCHAR(64)) RETURNS TINYINT
  NOT DETERMINISTIC READS SQL DATA
BEGIN
  RETURN (SELECT COUNT(*) > 0 FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_t AND COLUMN_NAME = p_c);
END //

-- The index's columns in order, comma-separated, or NULL when there is no such index.
CREATE FUNCTION mill_migrate_080_idx(p_t VARCHAR(64), p_i VARCHAR(64)) RETURNS VARCHAR(512)
  NOT DETERMINISTIC READS SQL DATA
BEGIN
  RETURN (SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY SEQ_IN_INDEX) FROM information_schema.STATISTICS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_t AND INDEX_NAME = p_i);
END //

-- 1 when every column of the comma-separated list is on the table (a key on a column a later step adds waits).
CREATE FUNCTION mill_migrate_080_cols_ok(p_t VARCHAR(64), p_cols VARCHAR(255)) RETURNS TINYINT
  NOT DETERMINISTIC READS SQL DATA
BEGIN
  RETURN (SELECT COUNT(*) FROM information_schema.COLUMNS
           WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_t AND FIND_IN_SET(COLUMN_NAME, p_cols))
         = LENGTH(p_cols) - LENGTH(REPLACE(p_cols, ',', '')) + 1;
END //

CREATE FUNCTION mill_migrate_080_fk_has(p_t VARCHAR(64), p_name VARCHAR(64)) RETURNS TINYINT
  NOT DETERMINISTIC READS SQL DATA
BEGIN
  RETURN (SELECT COUNT(*) > 0 FROM information_schema.REFERENTIAL_CONSTRAINTS
           WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = p_t AND CONSTRAINT_NAME = p_name);
END //

-- 1 when the FK exists exactly as wanted: columns, referenced table and columns, delete rule.
CREATE FUNCTION mill_migrate_080_fk_ok(p_t VARCHAR(64), p_name VARCHAR(64), p_cols VARCHAR(255),
                                       p_ref VARCHAR(64), p_refcols VARCHAR(255), p_rule VARCHAR(16)) RETURNS TINYINT
  NOT DETERMINISTIC READS SQL DATA
BEGIN
  DECLARE v_c VARCHAR(512) DEFAULT NULL;
  DECLARE v_r VARCHAR(512) DEFAULT NULL;
  IF (SELECT COUNT(*) FROM information_schema.REFERENTIAL_CONSTRAINTS
       WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = p_t AND CONSTRAINT_NAME = p_name
         AND REFERENCED_TABLE_NAME = p_ref AND DELETE_RULE = p_rule) = 0 THEN
    RETURN 0;
  END IF;
  SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION),
         GROUP_CONCAT(REFERENCED_COLUMN_NAME ORDER BY ORDINAL_POSITION)
    INTO v_c, v_r
    FROM information_schema.KEY_COLUMN_USAGE
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_t AND CONSTRAINT_NAME = p_name;
  RETURN v_c = p_cols AND v_r = p_refcols;
END //

CREATE PROCEDURE mill_migrate_080_exec(IN p_sql TEXT)
BEGIN
  SET @m080_sql = p_sql;
  PREPARE m080_stmt FROM @m080_sql;
  EXECUTE m080_stmt;
  DEALLOCATE PREPARE m080_stmt;
END //

-- One preflight row: COUNT(*) over p_from (dynamic, so a column a later step dropped is not compiled in).
CREATE PROCEDURE mill_migrate_080_check(IN p_chk VARCHAR(64), IN p_action VARCHAR(8), IN p_from TEXT)
BEGIN
  SET @m080_n = 0;
  CALL mill_migrate_080_exec(CONCAT('SELECT COUNT(*) INTO @m080_n FROM ', p_from));
  INSERT INTO m080_pf (chk, action, n) VALUES (p_chk, p_action, @m080_n);
END //

-- The FKs on main's tables that change or come: 15 desk FKs to seat, 11 kind-checked FKs to name (id, type),
-- doing's peer FK to seat and seat's focus FK to doing (id, desk_id).
CREATE PROCEDURE mill_migrate_080_fk_list()
BEGIN
  DROP TEMPORARY TABLE IF EXISTS m080_fk;
  CREATE TEMPORARY TABLE m080_fk (
    tbl VARCHAR(64) NOT NULL, name VARCHAR(64) NOT NULL, cols VARCHAR(255) NOT NULL,
    ref VARCHAR(64) NOT NULL, refcols VARCHAR(255) NOT NULL, rule_ VARCHAR(16) NOT NULL,
    PRIMARY KEY (tbl, name)
  );
  INSERT INTO m080_fk VALUES
    ('member',       'fk_member_desk',       'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('activity',     'fk_activity_desk',     'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('watcher',      'fk_watcher_desk',      'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('mail',         'fk_mail_desk',         'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('mail_to',      'fk_mail_to_desk',      'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('tree_read',    'fk_tree_read_desk',    'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('todo',         'fk_todo_updated',      'updated_id',  'seat', 'desk_id', 'RESTRICT'),
    ('todo',         'fk_todo_creator',      'creator_id',  'seat', 'desk_id', 'RESTRICT'),
    ('todo',         'fk_todo_assigned',     'assigned_id', 'seat', 'desk_id', 'RESTRICT'),
    ('doing',        'fk_doing_desk',        'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('hold',         'fk_hold_desk',         'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('score',        'fk_score_desk',        'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('score_point',  'fk_score_point_desk',  'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('push_queue',   'fk_push_queue_desk',   'desk_id',     'seat', 'desk_id', 'RESTRICT'),
    ('human_desk',   'fk_human_desk_desk',   'desk_id',     'seat', 'desk_id', 'CASCADE'),
    ('member',       'fk_member_name',       'name_id,name_kind',         'name', 'id,type', 'RESTRICT'),
    ('activity',     'fk_activity_roster',   'roster_id,roster_kind',     'name', 'id,type', 'RESTRICT'),
    ('label',        'fk_label_name',        'name_id,name_kind',         'name', 'id,type', 'RESTRICT'),
    ('tree',         'fk_tree_name',         'name_id,name_kind',         'name', 'id,type', 'RESTRICT'),
    ('mail',         'fk_mail_roster',       'roster_id,roster_kind',     'name', 'id,type', 'RESTRICT'),
    ('tree_read',    'fk_tree_read_tree',    'tree_id,tree_kind',         'name', 'id,type', 'RESTRICT'),
    ('todo',         'fk_todo_roster',       'roster_id,roster_kind',     'name', 'id,type', 'RESTRICT'),
    ('doing',        'fk_doing_roster',      'roster_id,roster_kind',     'name', 'id,type', 'RESTRICT'),
    ('hold',         'fk_hold_res',          'resource_id,resource_kind', 'name', 'id,type', 'RESTRICT'),
    ('score',        'fk_score_roster',      'roster_id,roster_kind',     'name', 'id,type', 'RESTRICT'),
    ('human_member', 'fk_human_member_name', 'name_id,name_kind',         'name', 'id,type', 'CASCADE'),
    ('doing',        'fk_doing_peer',        'peer_id',                   'seat', 'desk_id', 'RESTRICT'),
    ('seat',         'fk_seat_doing',        'doing_id,desk_id',          'doing', 'id,desk_id', 'RESTRICT');
END //

-- Read only: one row per check (chk, action, n). Nothing in the book changes.
CREATE PROCEDURE mill_migrate_080_preflight()
BEGIN
  DECLARE v_fk INT DEFAULT 0;
  DROP TEMPORARY TABLE IF EXISTS m080_pf;
  CREATE TEMPORARY TABLE m080_pf (chk VARCHAR(64) NOT NULL, action VARCHAR(8) NOT NULL, n BIGINT NOT NULL);

  -- refuse: a desk column that holds an id of another kind, where no step decides what it should be.
  CALL mill_migrate_080_check('desk_seat', 'refuse', 'seat x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_member', 'refuse', 'member x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_mail', 'refuse', 'mail x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_mail_to', 'refuse', 'mail_to x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_tree_read', 'refuse', 'tree_read x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_todo', 'refuse',
    'todo x JOIN name n ON n.id IN (x.updated_id, x.creator_id, x.assigned_id) WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_doing', 'refuse', 'doing x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_hold', 'refuse', 'hold x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_score_point', 'refuse', 'score_point x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('desk_human_desk', 'refuse', 'human_desk x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  IF mill_migrate_080_tbl('push_queue') THEN
    CALL mill_migrate_080_check('desk_push_queue', 'refuse', 'push_queue x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  END IF;
  CALL mill_migrate_080_check('desk_watcher', 'refuse',
    'watcher x JOIN name n ON n.id = x.desk_id WHERE n.type NOT IN (''desk'', ''roster'')');
  -- refuse: a kind-checked column that holds a name of another kind.
  CALL mill_migrate_080_check('kind_member', 'refuse', 'member x JOIN name n ON n.id = x.name_id WHERE n.type <> ''roster''');
  CALL mill_migrate_080_check('kind_activity', 'refuse', 'activity x JOIN name n ON n.id = x.roster_id WHERE n.type <> ''roster''');
  CALL mill_migrate_080_check('kind_label', 'refuse', 'label x JOIN name n ON n.id = x.name_id WHERE n.type <> ''label''');
  CALL mill_migrate_080_check('kind_tree', 'refuse', 'tree x JOIN name n ON n.id = x.name_id WHERE n.type <> ''tree''');
  CALL mill_migrate_080_check('kind_mail', 'refuse', 'mail x JOIN name n ON n.id = x.roster_id WHERE n.type <> ''roster''');
  CALL mill_migrate_080_check('kind_tree_read', 'refuse', 'tree_read x JOIN name n ON n.id = x.tree_id WHERE n.type <> ''tree''');
  CALL mill_migrate_080_check('kind_todo', 'refuse', 'todo x JOIN name n ON n.id = x.roster_id WHERE n.type <> ''roster''');
  CALL mill_migrate_080_check('kind_doing', 'refuse', 'doing x JOIN name n ON n.id = x.roster_id WHERE n.type <> ''roster''');
  CALL mill_migrate_080_check('kind_hold', 'refuse', 'hold x JOIN name n ON n.id = x.resource_id WHERE n.type <> ''res''');
  CALL mill_migrate_080_check('kind_score', 'refuse', 'score x JOIN name n ON n.id = x.roster_id WHERE n.type <> ''roster''');
  CALL mill_migrate_080_check('kind_human_member', 'refuse',
    'human_member x JOIN name n ON n.id = x.name_id WHERE n.type <> ''roster''');
  -- refuse: two scores of one roster and kpi whose owners both become the office (desk NULL) would collide
  -- on the new UNIQUE idx_score_who (roster_id, desk_key, kpi). Retired rows count: the index holds them too.
  CALL mill_migrate_080_check('score_collapse', 'refuse',
    '(SELECT s.roster_id, s.kpi FROM score s LEFT JOIN name n ON n.id = s.desk_id
       WHERE s.desk_id IS NULL OR n.type <> ''desk'' GROUP BY s.roster_id, s.kpi HAVING COUNT(*) > 1) g');
  IF mill_migrate_080_col('todo', 'evidence') THEN
    -- refuse: evidence longer than doing.evidence / EVIDENCE_MAX (2000 characters); nothing is cut.
    CALL mill_migrate_080_check('todo_evidence_long', 'refuse', 'todo WHERE CHAR_LENGTH(evidence) > 2000');
    -- fix: every card gets its one move row (step moves).
    CALL mill_migrate_080_check('todo_moves', 'fix', 'todo');
  END IF;

  -- fix: what the steps change.
  CALL mill_migrate_080_check('seat_backfill', 'fix',
    'name n WHERE n.type = ''desk'' AND NOT EXISTS (SELECT 1 FROM seat s WHERE s.desk_id = n.id)');
  CALL mill_migrate_080_check('watcher_roster', 'fix', 'watcher x JOIN name n ON n.id = x.desk_id WHERE n.type = ''roster''');
  CALL mill_migrate_080_check('activity_desk_null', 'fix', 'activity x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('score_desk_null', 'fix', 'score x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  IF mill_migrate_080_col('seat', 'doing_id') AND mill_migrate_080_col('doing', 'act') THEN
    CALL mill_migrate_080_check('seat_doing_id', 'fix',
      '(SELECT DISTINCT d.desk_id FROM doing d JOIN seat s ON s.desk_id = d.desk_id
         WHERE s.doing_id IS NULL AND d.act IN (''focus'', ''clear'')) g');
  ELSE
    CALL mill_migrate_080_check('seat_doing_id', 'fix',
      '(SELECT DISTINCT desk_id FROM doing WHERE text <> '''' OR on_type IS NULL) g');
  END IF;

  -- schema: what the schema steps still have to do (metadata only).
  INSERT INTO m080_pf (chk, action, n) VALUES
    ('schema_activity_desk', 'schema', (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
       AND COLUMN_NAME = 'desk_id' AND TABLE_NAME IN ('activity', 'score') AND IS_NULLABLE = 'NO')),
    ('schema_desk_key', 'schema', 1 - mill_migrate_080_col('score', 'desk_key')
       + IF(IFNULL(mill_migrate_080_idx('score', 'idx_score_who'), '')
            IN ('roster_id,desk_key,kpi', 'roster_id,roster_kind,desk_key,kpi'), 0, 1)),
    ('schema_keys', 'schema', IF(IFNULL(mill_migrate_080_idx('name', 'idx_id_type'), '') = 'id,type', 0, 1)
       + IF(IFNULL(mill_migrate_080_idx('doing', 'idx_id_desk'), '') = 'id,desk_id', 0, 1)),
    ('schema_kind_cols', 'schema', 11 - (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
       AND (TABLE_NAME, COLUMN_NAME) IN (('member', 'name_kind'), ('activity', 'roster_kind'), ('label', 'name_kind'),
            ('tree', 'name_kind'), ('mail', 'roster_kind'), ('tree_read', 'tree_kind'), ('todo', 'roster_kind'),
            ('doing', 'roster_kind'), ('hold', 'resource_kind'), ('score', 'roster_kind'), ('human_member', 'name_kind')))),
    ('schema_columns', 'schema', 6 - mill_migrate_080_col('activity', 'act') - mill_migrate_080_col('doing', 'act')
       - mill_migrate_080_col('doing', 'peer_id') - mill_migrate_080_col('doing', 'evidence')
       - mill_migrate_080_col('seat', 'doing_id') - mill_migrate_080_col('name', 'trashed')
       + mill_migrate_080_col('activity', 'weight') + mill_migrate_080_col('activity', 'n')),
    ('schema_todo_evidence', 'schema', mill_migrate_080_col('todo', 'evidence')),
    ('schema_triggers', 'schema', 1 - (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()
       AND TRIGGER_NAME IN ('name_fixed'))
       + (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()
           AND TRIGGER_NAME = 'name_no_delete' AND ACTION_STATEMENT NOT LIKE '%sp_name_retire%'));
  CALL mill_migrate_080_fk_list();
  SELECT COUNT(*) INTO v_fk FROM m080_fk f
   WHERE mill_migrate_080_tbl(f.tbl)
     AND NOT mill_migrate_080_fk_ok(f.tbl, f.name, f.cols, f.ref, f.refcols, f.rule_);
  INSERT INTO m080_pf (chk, action, n) VALUES ('schema_fks', 'schema', v_fk);
  DROP TEMPORARY TABLE IF EXISTS m080_fk;
  -- keys 0.8.0 changes or adds (a kind column it needs not there yet counts as to do), and indexes named after an FK.
  CALL mill_migrate_080_key_list();
  INSERT INTO m080_pf (chk, action, n)
    SELECT 'schema_key_shape', 'schema', COUNT(*) FROM m080_key k
     WHERE IFNULL(mill_migrate_080_idx(k.tbl, k.idx), '') <> k.cols;
  DROP TEMPORARY TABLE IF EXISTS m080_key;
  INSERT INTO m080_pf (chk, action, n)
    SELECT 'schema_fk_index', 'schema', COUNT(DISTINCT s.TABLE_NAME, s.INDEX_NAME)
      FROM information_schema.STATISTICS s
      JOIN information_schema.REFERENTIAL_CONSTRAINTS r
        ON r.CONSTRAINT_SCHEMA = s.TABLE_SCHEMA AND r.TABLE_NAME = s.TABLE_NAME AND r.CONSTRAINT_NAME = s.INDEX_NAME
     WHERE s.TABLE_SCHEMA = DATABASE();

  SELECT chk, action, n FROM m080_pf ORDER BY action, chk;
  DROP TEMPORARY TABLE IF EXISTS m080_pf;
END //

-- The keys 0.8.0 changes or adds on main's tables (tables.sql is the source; the migrated-equals-fresh test checks
-- it), in the temporary table m080_key.
CREATE PROCEDURE mill_migrate_080_key_list()
BEGIN
  DROP TEMPORARY TABLE IF EXISTS m080_key;
  CREATE TEMPORARY TABLE m080_key (
    tbl VARCHAR(64) NOT NULL, idx VARCHAR(64) NOT NULL, kind VARCHAR(8) NOT NULL, cols VARCHAR(255) NOT NULL,
    PRIMARY KEY (tbl, idx)
  );
  INSERT INTO m080_key VALUES
    ('activity',     'idx_roster',      'KEY',     'roster_id,roster_kind,type,updated'),
    ('activity',     'idx_updated',     'KEY',     'updated'),
    ('doing',        'idx_on',          'KEY',     'on_type,on_id,id'),
    ('doing',        'idx_peer',        'KEY',     'peer_id'),
    ('seat',         'idx_doing',       'KEY',     'doing_id,desk_id'),
    ('doing',        'idx_roster',      'KEY',     'roster_id,roster_kind'),
    ('hold',         'idx_desk',        'KEY',     'desk_id'),
    ('hold',         'idx_hold',        'UNIQUE',  'resource_id,resource_kind'),
    ('human_member', 'idx_role',        'KEY',     'name_id,name_kind,human_id'),
    ('label',        'idx_label_ord',   'KEY',     'name_id,name_kind,ord,created'),
    ('mail',         'idx_mail_roster', 'KEY',     'roster_id,roster_kind'),
    ('member',       'PRIMARY',         'PRIMARY', 'name_id,name_kind,desk_id'),
    ('score',        'idx_desk',        'KEY',     'desk_id'),
    ('score',        'idx_score_who',   'UNIQUE',  'roster_id,roster_kind,desk_key,kpi'),
    ('todo',         'idx_assigned',    'KEY',     'assigned_id'),
    ('todo',         'idx_creator',     'KEY',     'creator_id'),
    ('todo',         'idx_roster',      'KEY',     'roster_id,roster_kind,status,updated'),
    ('todo',         'idx_updated',     'KEY',     'updated_id'),
    ('tree',         'PRIMARY',         'PRIMARY', 'name_id,name_kind,type,id'),
    ('tree_read',    'idx_tree',        'KEY',     'tree_id,tree_kind');
END //

-- A key in m080_key whose columns differ is dropped and added in the same ALTER, so an FK it serves is never uncovered.
-- A key on a column a later step adds (step columns) waits for that step.
-- Adds the number of tables changed to @m080_rows.
CREATE PROCEDURE mill_migrate_080_keys()
BEGIN
  DECLARE v_done INT DEFAULT 0;
  DECLARE v_t VARCHAR(64);
  DECLARE v_alter TEXT;
  DECLARE v_cur CURSOR FOR SELECT DISTINCT tbl FROM m080_key ORDER BY tbl;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;
  CALL mill_migrate_080_key_list();
  OPEN v_cur;
  key_loop: LOOP
    FETCH v_cur INTO v_t;
    IF v_done THEN
      LEAVE key_loop;
    END IF;
    SELECT GROUP_CONCAT(CONCAT(
             IF(mill_migrate_080_idx(k.tbl, k.idx) IS NULL, '',
                IF(k.kind = 'PRIMARY', 'DROP PRIMARY KEY, ', CONCAT('DROP INDEX `', k.idx, '`, '))),
             CASE k.kind WHEN 'PRIMARY' THEN 'ADD PRIMARY KEY (`'
                         WHEN 'UNIQUE' THEN CONCAT('ADD UNIQUE KEY `', k.idx, '` (`')
                         ELSE CONCAT('ADD KEY `', k.idx, '` (`') END,
             REPLACE(k.cols, ',', '`, `'), '`)') ORDER BY k.idx SEPARATOR ', ')
      INTO v_alter
      FROM m080_key k
     WHERE k.tbl = v_t AND IFNULL(mill_migrate_080_idx(k.tbl, k.idx), '') <> k.cols
       AND mill_migrate_080_cols_ok(k.tbl, k.cols);
    IF v_alter IS NOT NULL THEN
      CALL mill_migrate_080_exec(CONCAT('ALTER TABLE `', v_t, '` ', v_alter));
      SET @m080_rows = @m080_rows + 1;
    END IF;
  END LOOP;
  CLOSE v_cur;
  DROP TEMPORARY TABLE IF EXISTS m080_key;
END //

-- Indexes named after an FK (MySQL made them for main's FKs, or for an FK no declared key covered) are not declared
-- in tables.sql, so they go. Runs after the FK step: every FK is then covered by a declared key. Adds the count.
CREATE PROCEDURE mill_migrate_080_fk_idx_drop()
BEGIN
  DECLARE v_done INT DEFAULT 0;
  DECLARE v_t VARCHAR(64);
  DECLARE v_i VARCHAR(64);
  DECLARE v_cur CURSOR FOR
    SELECT DISTINCT s.TABLE_NAME, s.INDEX_NAME
      FROM information_schema.STATISTICS s
      JOIN information_schema.REFERENTIAL_CONSTRAINTS r
        ON r.CONSTRAINT_SCHEMA = s.TABLE_SCHEMA AND r.TABLE_NAME = s.TABLE_NAME AND r.CONSTRAINT_NAME = s.INDEX_NAME
     WHERE s.TABLE_SCHEMA = DATABASE()
     ORDER BY 1, 2;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;
  OPEN v_cur;
  idx_loop: LOOP
    FETCH v_cur INTO v_t, v_i;
    IF v_done THEN
      LEAVE idx_loop;
    END IF;
    CALL mill_migrate_080_exec(CONCAT('ALTER TABLE `', v_t, '` DROP INDEX `', v_i, '`'));
    SET @m080_rows = @m080_rows + 1;
  END LOOP;
  CLOSE v_cur;
END //

-- One step by name. @m080_rows: rows (or schema objects) it changed.
CREATE PROCEDURE mill_migrate_080_step(IN p_step VARCHAR(16))
BEGIN
  DECLARE v_done INT DEFAULT 0;
  DECLARE v_t VARCHAR(64);
  DECLARE v_drop TEXT;
  DECLARE v_add TEXT;
  DECLARE v_fk CURSOR FOR SELECT DISTINCT tbl FROM m080_fk WHERE mill_migrate_080_tbl(tbl) ORDER BY tbl;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  SET @m080_rows = 0;

  IF p_step = 'seat' THEN
    START TRANSACTION;
    INSERT INTO seat (desk_id)
    SELECT n.id FROM name n
     WHERE n.type = 'desk' AND NOT EXISTS (SELECT 1 FROM seat s WHERE s.desk_id = n.id)
     ORDER BY n.id;
    SET @m080_rows = ROW_COUNT();
    COMMIT;

  ELSEIF p_step = 'watcher' THEN
    START TRANSACTION;
    INSERT IGNORE INTO watcher (type, id, desk_id, hint, updated)
    SELECT w.type, w.id, m.desk_id, w.hint, w.updated
      FROM watcher w
      JOIN name n ON n.id = w.desk_id AND n.type = 'roster'
      JOIN member m ON m.name_id = w.desk_id;
    SET @m080_rows = ROW_COUNT();
    DELETE w FROM watcher w JOIN name n ON n.id = w.desk_id AND n.type = 'roster';
    SET @m080_rows = @m080_rows + ROW_COUNT();
    COMMIT;

  ELSEIF p_step = 'desk_null' THEN
    IF (SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
         AND TABLE_NAME = 'activity' AND COLUMN_NAME = 'desk_id') = 'NO' THEN
      ALTER TABLE activity MODIFY COLUMN desk_id BIGINT UNSIGNED NULL;
    END IF;
    IF (SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
         AND TABLE_NAME = 'score' AND COLUMN_NAME = 'desk_id') = 'NO' THEN
      ALTER TABLE score MODIFY COLUMN desk_id BIGINT UNSIGNED NULL;
    END IF;
    START TRANSACTION;
    -- updated = updated: the owner move is not an edit (ON UPDATE CURRENT_TIMESTAMP must not fire).
    UPDATE activity a JOIN name n ON n.id = a.desk_id AND n.type <> 'desk'
       SET a.desk_id = NULL, a.updated = a.updated;
    SET @m080_rows = ROW_COUNT();
    UPDATE score s JOIN name n ON n.id = s.desk_id AND n.type <> 'desk'
       SET s.desk_id = NULL, s.updated = s.updated;
    SET @m080_rows = @m080_rows + ROW_COUNT();
    COMMIT;

  ELSEIF p_step = 'score_key' THEN
    IF NOT mill_migrate_080_col('score', 'desk_key') THEN
      ALTER TABLE score
        ADD COLUMN desk_key BIGINT UNSIGNED AS (IFNULL(desk_id, 0)) STORED AFTER unit,
        DROP INDEX idx_score_who,
        ADD UNIQUE KEY idx_score_who (roster_id, desk_key, kpi);
      SET @m080_rows = 1;
    ELSEIF IFNULL(mill_migrate_080_idx('score', 'idx_score_who'), '')
           NOT IN ('roster_id,desk_key,kpi', 'roster_id,roster_kind,desk_key,kpi') THEN
      ALTER TABLE score DROP INDEX idx_score_who, ADD UNIQUE KEY idx_score_who (roster_id, desk_key, kpi);
      SET @m080_rows = 1;
    END IF;

  ELSEIF p_step = 'keys_kinds' THEN
    IF mill_migrate_080_idx('name', 'idx_id_type') IS NULL THEN
      ALTER TABLE name ADD UNIQUE KEY idx_id_type (id, type);
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF mill_migrate_080_idx('doing', 'idx_id_desk') IS NULL THEN
      ALTER TABLE doing ADD UNIQUE KEY idx_id_desk (id, desk_id);
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('member', 'name_kind') THEN
      ALTER TABLE member ADD COLUMN name_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster'
        CHECK (name_kind = 'roster') AFTER name_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('activity', 'roster_kind') THEN
      ALTER TABLE activity ADD COLUMN roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster'
        CHECK (roster_kind = 'roster') AFTER roster_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('label', 'name_kind') THEN
      ALTER TABLE label ADD COLUMN name_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'label'
        CHECK (name_kind = 'label') AFTER name_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('tree', 'name_kind') THEN
      ALTER TABLE tree ADD COLUMN name_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'tree'
        CHECK (name_kind = 'tree') AFTER name_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('mail', 'roster_kind') THEN
      ALTER TABLE mail ADD COLUMN roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster'
        CHECK (roster_kind = 'roster') AFTER roster_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('tree_read', 'tree_kind') THEN
      ALTER TABLE tree_read ADD COLUMN tree_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'tree'
        CHECK (tree_kind = 'tree') AFTER tree_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('todo', 'roster_kind') THEN
      ALTER TABLE todo ADD COLUMN roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster'
        CHECK (roster_kind = 'roster') AFTER roster_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('doing', 'roster_kind') THEN
      ALTER TABLE doing ADD COLUMN roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster'
        CHECK (roster_kind = 'roster') AFTER roster_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('hold', 'resource_kind') THEN
      ALTER TABLE hold ADD COLUMN resource_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'res'
        CHECK (resource_kind = 'res') AFTER resource_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('score', 'roster_kind') THEN
      ALTER TABLE score ADD COLUMN roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster'
        CHECK (roster_kind = 'roster') AFTER roster_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('human_member', 'name_kind') THEN
      ALTER TABLE human_member ADD COLUMN name_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster'
        CHECK (name_kind = 'roster') AFTER name_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    CALL mill_migrate_080_keys();

  ELSEIF p_step = 'columns' THEN
    -- Same shape as tables.sql (test_migrate_080_book compares the two through information_schema).
    IF NOT mill_migrate_080_col('activity', 'act') THEN
      ALTER TABLE activity ADD COLUMN act ENUM('create','send','reply','note','park','claim','unclaim','assign','unpark','ship','done','back','hold','drop','focus','clear','finish','score','retire','reclaim','remove','delete','restore','purge','rename') NOT NULL DEFAULT 'create' AFTER roster_kind;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('doing', 'act') THEN
      ALTER TABLE doing ADD COLUMN act ENUM('create','send','reply','note','park','claim','unclaim','assign','unpark','ship','done','back','hold','drop','focus','clear','finish','score','retire','reclaim','remove','delete','restore','purge','rename') NOT NULL DEFAULT 'focus' AFTER waiting_why;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('doing', 'peer_id') THEN
      ALTER TABLE doing ADD COLUMN peer_id BIGINT UNSIGNED NULL AFTER act;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('doing', 'evidence') THEN
      ALTER TABLE doing ADD COLUMN evidence VARCHAR(2000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL AFTER peer_id;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    -- CHECK: focus/clear/finish keep evidence NULL (the owner, 2026-10-26).
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
       WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = 'doing' AND CONSTRAINT_NAME = 'chk_doing_evidence'
    ) THEN
      ALTER TABLE doing ADD CONSTRAINT chk_doing_evidence
        CHECK (evidence IS NULL OR act NOT IN ('focus', 'clear', 'finish'));
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('seat', 'doing_id') THEN
      ALTER TABLE seat ADD COLUMN doing_id BIGINT UNSIGNED NULL AFTER time_disconnect;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF NOT mill_migrate_080_col('name', 'trashed') THEN
      ALTER TABLE name ADD COLUMN trashed DATETIME(6) NULL AFTER deleted;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    CALL mill_migrate_080_keys();

  ELSEIF p_step = 'acts' THEN
    -- Before step moves, so every doing row here is main's (act still focus, clear or finish). updated = updated:
    -- setting the act is not an edit of the item (ON UPDATE CURRENT_TIMESTAMP must not fire).
    START TRANSACTION;
    UPDATE doing SET act = IF(text <> '', 'focus', IF(on_type IS NOT NULL, 'finish', 'clear'))
     WHERE act IN ('focus', 'clear', 'finish')
       AND act <> IF(text <> '', 'focus', IF(on_type IS NOT NULL, 'finish', 'clear'));
    SET @m080_rows = ROW_COUNT();
    IF mill_migrate_080_col('todo', 'evidence') THEN
      UPDATE activity a JOIN todo t ON a.type = 'todo' AND a.id = t.id
         SET a.act = ELT(FIELD(t.status, 'open', 'parked', 'claimed', 'shipped', 'done'), 'create', 'park',
                         IF(t.assigned_id <=> t.updated_id, 'claim', 'assign'), 'ship', 'done'),
             a.updated = a.updated
       WHERE a.act = 'create';
      SET @m080_rows = @m080_rows + ROW_COUNT();
    END IF;
    UPDATE activity a JOIN doing d ON a.type = 'doing' AND a.id = d.id
       SET a.act = d.act, a.updated = a.updated WHERE a.act = 'create';
    SET @m080_rows = @m080_rows + ROW_COUNT();
    UPDATE activity a JOIN hold h ON a.type = 'hold' AND a.id = h.id
       SET a.act = IF(h.desk_id IS NULL, 'drop', 'hold'), a.updated = a.updated WHERE a.act = 'create';
    SET @m080_rows = @m080_rows + ROW_COUNT();
    UPDATE activity SET act = IF(type = 'mail', 'send', 'score'), updated = updated
     WHERE type IN ('mail', 'score') AND act = 'create';
    SET @m080_rows = @m080_rows + ROW_COUNT();
    COMMIT;

  ELSEIF p_step = 'moves' THEN
    IF mill_migrate_080_col('todo', 'evidence') THEN
      START TRANSACTION;
      -- A card that has a move row already (a kill after this commit, before the drop) gets none again.
      CALL mill_migrate_080_exec(
        'INSERT INTO doing (created, desk_id, roster_id, text, on_type, on_id, act, peer_id, evidence)
         SELECT t.updated, t.updated_id, t.roster_id, '''', ''todo'', t.id,
                ELT(FIELD(t.status, ''open'', ''parked'', ''claimed'', ''shipped'', ''done''), ''create'', ''park'',
                    IF(t.assigned_id <=> t.updated_id, ''claim'', ''assign''), ''ship'', ''done''),
                t.assigned_id, t.evidence
           FROM todo t
          WHERE NOT EXISTS (SELECT 1 FROM doing d WHERE d.on_type = ''todo'' AND d.on_id = t.id
                              AND d.act NOT IN (''focus'', ''clear'', ''finish''))
          ORDER BY t.id');
      SET @m080_rows = ROW_COUNT();
      COMMIT;
      ALTER TABLE todo DROP COLUMN evidence;
    END IF;

  ELSEIF p_step = 'doing_id' THEN
    START TRANSACTION;
    UPDATE seat s JOIN (
      SELECT x.desk_id, x.id FROM (
        SELECT d.desk_id, d.id,
               ROW_NUMBER() OVER (PARTITION BY d.desk_id ORDER BY d.created DESC, d.id DESC) AS rn
          FROM doing d WHERE d.act IN ('focus', 'clear')) x
       WHERE x.rn = 1) f ON f.desk_id = s.desk_id
       SET s.doing_id = f.id, s.updated = s.updated
     WHERE s.doing_id IS NULL;
    SET @m080_rows = ROW_COUNT();
    COMMIT;

  ELSEIF p_step = 'drop_cols' THEN
    IF mill_migrate_080_col('activity', 'weight') THEN
      ALTER TABLE activity DROP COLUMN weight;
      SET @m080_rows = @m080_rows + 1;
    END IF;
    IF mill_migrate_080_col('activity', 'n') THEN
      ALTER TABLE activity DROP COLUMN n;
      SET @m080_rows = @m080_rows + 1;
    END IF;

  ELSEIF p_step = 'fks' THEN
    CALL mill_migrate_080_fk_list();
    OPEN v_fk;
    fk_loop: LOOP
      FETCH v_fk INTO v_t;
      IF v_done THEN
        LEAVE fk_loop;
      END IF;
      SET v_drop = NULL, v_add = NULL;
      SELECT GROUP_CONCAT(IF(mill_migrate_080_fk_has(f.tbl, f.name), CONCAT('DROP FOREIGN KEY `', f.name, '`'), NULL)
                          ORDER BY f.name SEPARATOR ', '),
             GROUP_CONCAT(CONCAT('ADD CONSTRAINT `', f.name, '` FOREIGN KEY (`', REPLACE(f.cols, ',', '`, `'),
                                 '`) REFERENCES `', f.ref, '` (`', REPLACE(f.refcols, ',', '`, `'),
                                 '`) ON DELETE ', f.rule_) ORDER BY f.name SEPARATOR ', '),
             COUNT(*)
        INTO v_drop, v_add, @m080_n
        FROM m080_fk f
       WHERE f.tbl = v_t AND mill_migrate_080_tbl(f.tbl)
         AND NOT mill_migrate_080_fk_ok(f.tbl, f.name, f.cols, f.ref, f.refcols, f.rule_);
      IF v_drop IS NOT NULL THEN
        CALL mill_migrate_080_exec(CONCAT('ALTER TABLE `', v_t, '` ', v_drop));
      END IF;
      IF v_add IS NOT NULL THEN
        CALL mill_migrate_080_exec(CONCAT('ALTER TABLE `', v_t, '` ', v_add));
        SET @m080_rows = @m080_rows + @m080_n;
      END IF;
    END LOOP;
    CLOSE v_fk;
    DROP TEMPORARY TABLE IF EXISTS m080_fk;
    CALL mill_migrate_080_fk_idx_drop();

  ELSE
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'migrate_080: unknown step';
  END IF;
END //

DELIMITER ;
