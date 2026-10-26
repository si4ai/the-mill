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
--   tables      the 7 new tables (todo_event, doing_now, vote, vote_option, vote_cast, glance_cache, sp_deploy).
--   todo_event  each todo.evidence becomes one todo_event row; then todo.evidence is dropped.
--   doing_now   the newest doing row per desk (created, then id: mill_doing_now's order).
--   fks         the 15 desk FKs on main's tables move to seat (desk_id); the 11 roster, label, tree and res
--               FKs become kind-checked (col, kind) -> name (id, type). One ALTER per table to drop, one to add.
--               Then the indexes MySQL made for main's FKs (named after the FK) go: the owner rule is that only
--               PRIMARY and UNIQUE keys are implicit, and every other index is a declared idx_* key.
-- Triggers, the routine reload and the sp_deploy stamp are migrate.py's (they read the pack's files).
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

-- The FKs on main's tables that change: 15 desk FKs to seat, 11 kind-checked FKs to name (id, type).
-- The 4 new tables bring their own FKs (CREATE TABLE in step tables).
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
    ('human_member', 'fk_human_member_name', 'name_id,name_kind',         'name', 'id,type', 'CASCADE');
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
  CALL mill_migrate_080_check('desk_push_queue', 'refuse', 'push_queue x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
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
    -- refuse: evidence on a card that is not shipped or done (cmd_pass clears it on a step back);
    -- todo_event's CHECK keeps evidence to shipped and done.
    CALL mill_migrate_080_check('todo_evidence_status', 'refuse',
      'todo WHERE evidence IS NOT NULL AND status NOT IN (''shipped'', ''done'')');
    CALL mill_migrate_080_check('todo_evidence', 'fix', 'todo WHERE evidence IS NOT NULL');
  END IF;

  -- fix: what the steps change.
  CALL mill_migrate_080_check('seat_backfill', 'fix',
    'name n WHERE n.type = ''desk'' AND NOT EXISTS (SELECT 1 FROM seat s WHERE s.desk_id = n.id)');
  CALL mill_migrate_080_check('watcher_roster', 'fix', 'watcher x JOIN name n ON n.id = x.desk_id WHERE n.type = ''roster''');
  CALL mill_migrate_080_check('activity_desk_null', 'fix', 'activity x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  CALL mill_migrate_080_check('score_desk_null', 'fix', 'score x JOIN name n ON n.id = x.desk_id WHERE n.type <> ''desk''');
  IF mill_migrate_080_tbl('doing_now') THEN
    CALL mill_migrate_080_check('doing_now', 'fix',
      '(SELECT DISTINCT d.desk_id FROM doing d WHERE NOT EXISTS (SELECT 1 FROM doing_now w WHERE w.desk_id = d.desk_id)) g');
  ELSE
    CALL mill_migrate_080_check('doing_now', 'fix', '(SELECT DISTINCT desk_id FROM doing) g');
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
    ('schema_tables', 'schema', 7 - (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()
       AND TABLE_NAME IN ('todo_event', 'doing_now', 'vote', 'vote_option', 'vote_cast', 'glance_cache', 'sp_deploy'))
       + IF(mill_migrate_080_tbl('vote') AND NOT mill_migrate_080_fk_has('vote', 'fk_vote_result'), 1, 0)),
    ('schema_todo_evidence', 'schema', mill_migrate_080_col('todo', 'evidence')),
    ('schema_triggers', 'schema', 3 - (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()
       AND TRIGGER_NAME IN ('name_fixed', 'vote_cast_open', 'vote_cast_change'))
       + (SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = DATABASE()
           AND TRIGGER_NAME = 'name_no_delete' AND ACTION_STATEMENT NOT LIKE '%sp_name_retire%'));
  CALL mill_migrate_080_fk_list();
  SELECT COUNT(*) INTO v_fk FROM m080_fk f
   WHERE NOT mill_migrate_080_fk_ok(f.tbl, f.name, f.cols, f.ref, f.refcols, f.rule_);
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
     WHERE k.tbl = v_t AND IFNULL(mill_migrate_080_idx(k.tbl, k.idx), '') <> k.cols;
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
  DECLARE v_fk CURSOR FOR SELECT DISTINCT tbl FROM m080_fk ORDER BY tbl;
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

  ELSEIF p_step = 'tables' THEN
    -- Same shape as tables.sql (test_migrate_080_book compares the two through information_schema).
    CREATE TABLE IF NOT EXISTS todo_event (
      id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      todo_id     BIGINT UNSIGNED NOT NULL,
      created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      desk_id     BIGINT UNSIGNED NOT NULL,
      from_status ENUM('parked','open','claimed','shipped','done') NULL,
      to_status   ENUM('parked','open','claimed','shipped','done') NOT NULL,
      assigned_id BIGINT UNSIGNED NULL,
      evidence    VARCHAR(2000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
      PRIMARY KEY (id),
      KEY idx_todo (todo_id, id),
      KEY idx_desk (desk_id),
      KEY idx_assigned (assigned_id),
      CONSTRAINT ck_todo_event_evidence CHECK (evidence IS NULL OR to_status IN ('shipped','done')),
      CONSTRAINT fk_todo_event_todo FOREIGN KEY (todo_id) REFERENCES todo (id) ON DELETE RESTRICT,
      CONSTRAINT fk_todo_event_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
      CONSTRAINT fk_todo_event_assigned FOREIGN KEY (assigned_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
    CREATE TABLE IF NOT EXISTS doing_now (
      desk_id     BIGINT UNSIGNED NOT NULL,
      doing_id    BIGINT UNSIGNED NOT NULL,
      PRIMARY KEY (desk_id),
      KEY idx_doing (doing_id, desk_id),
      CONSTRAINT fk_doing_now_doing FOREIGN KEY (doing_id, desk_id) REFERENCES doing (id, desk_id) ON DELETE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
    CREATE TABLE IF NOT EXISTS vote (
      id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      desk_id     BIGINT UNSIGNED NOT NULL,
      roster_id   BIGINT UNSIGNED NOT NULL,
      roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (roster_kind = 'roster'),
      mail_id     BIGINT UNSIGNED NOT NULL,
      question    VARCHAR(400) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
      deadline    DATETIME(6) NOT NULL,
      closed      DATETIME(6) NULL,
      outcome     ENUM('decided','deadlock','no_show') NULL,
      result_opt  TINYINT UNSIGNED NULL,
      members_n   SMALLINT UNSIGNED NULL,
      escalated   DATETIME(6) NULL,
      PRIMARY KEY (id),
      UNIQUE KEY idx_mail (mail_id),
      KEY idx_roster_open (roster_id, roster_kind, closed, deadline),
      KEY idx_due (closed, deadline),
      KEY idx_desk (desk_id),
      KEY idx_result (id, result_opt),
      CONSTRAINT ck_vote_deadline CHECK (deadline > created),
      CONSTRAINT ck_vote_closed CHECK ((closed IS NULL) = (outcome IS NULL) AND (closed IS NULL) = (members_n IS NULL)),
      CONSTRAINT ck_vote_result CHECK ((outcome = 'decided') <=> (result_opt IS NOT NULL) OR (outcome IS NULL AND result_opt IS NULL)),
      CONSTRAINT ck_vote_escalated CHECK (escalated IS NULL OR outcome IN ('deadlock','no_show')),
      CONSTRAINT fk_vote_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
      CONSTRAINT fk_vote_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES name (id, type) ON DELETE RESTRICT,
      CONSTRAINT fk_vote_mail FOREIGN KEY (mail_id) REFERENCES mail (id) ON DELETE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
    CREATE TABLE IF NOT EXISTS vote_option (
      vote_id     BIGINT UNSIGNED NOT NULL,
      opt         TINYINT UNSIGNED NOT NULL,
      label       VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
      PRIMARY KEY (vote_id, opt),
      UNIQUE KEY idx_label (vote_id, label),
      CONSTRAINT ck_vote_option_opt CHECK (opt BETWEEN 1 AND 16),
      CONSTRAINT fk_vote_option_vote FOREIGN KEY (vote_id) REFERENCES vote (id) ON DELETE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
    IF NOT mill_migrate_080_fk_has('vote', 'fk_vote_result') THEN
      ALTER TABLE vote ADD CONSTRAINT fk_vote_result FOREIGN KEY (id, result_opt) REFERENCES vote_option (vote_id, opt);
      SET @m080_rows = @m080_rows + 1;
    END IF;
    CREATE TABLE IF NOT EXISTS vote_cast (
      vote_id     BIGINT UNSIGNED NOT NULL,
      desk_id     BIGINT UNSIGNED NOT NULL,
      opt         TINYINT UNSIGNED NOT NULL,
      created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      note        VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
      PRIMARY KEY (vote_id, desk_id),
      KEY idx_desk (desk_id),
      KEY idx_opt (vote_id, opt),
      CONSTRAINT fk_vote_cast_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
      CONSTRAINT fk_vote_cast_opt FOREIGN KEY (vote_id, opt) REFERENCES vote_option (vote_id, opt) ON DELETE RESTRICT
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
    CREATE TABLE IF NOT EXISTS glance_cache (
      id          TINYINT UNSIGNED NOT NULL DEFAULT 1,
      at          DATETIME(6) NOT NULL,
      refresh_us  INT UNSIGNED NOT NULL,
      present     INT UNSIGNED NOT NULL,
      held        INT UNSIGNED NOT NULL,
      open_n      INT UNSIGNED NOT NULL,
      claimed_n   INT UNSIGNED NOT NULL,
      parked_n    INT UNSIGNED NOT NULL,
      shipped_n   INT UNSIGNED NOT NULL,
      done_n      INT UNSIGNED NOT NULL,
      letters_1d  INT UNSIGNED NOT NULL,
      card_moves_1d INT UNSIGNED NOT NULL,
      doings_1d   INT UNSIGNED NOT NULL,
      holds_1d    INT UNSIGNED NOT NULL,
      points_1d   INT UNSIGNED NOT NULL,
      open_votes  INT UNSIGNED NOT NULL,
      PRIMARY KEY (id),
      CONSTRAINT ck_glance_cache_one CHECK (id = 1)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
    CREATE TABLE IF NOT EXISTS sp_deploy (
      id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
      version     CHAR(15) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
      file        VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
      created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      by_user     VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT (CURRENT_USER()),
      PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

  ELSEIF p_step = 'todo_event' THEN
    IF mill_migrate_080_col('todo', 'evidence') THEN
      START TRANSACTION;
      CALL mill_migrate_080_exec(
        'INSERT INTO todo_event (todo_id, created, desk_id, from_status, to_status, assigned_id, evidence)
         SELECT t.id, t.updated, t.updated_id, NULL, t.status, t.assigned_id, t.evidence
           FROM todo t
          WHERE t.evidence IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM todo_event e WHERE e.todo_id = t.id AND e.evidence = t.evidence)
          ORDER BY t.id');
      SET @m080_rows = ROW_COUNT();
      COMMIT;
      ALTER TABLE todo DROP COLUMN evidence;
    END IF;

  ELSEIF p_step = 'doing_now' THEN
    START TRANSACTION;
    INSERT INTO doing_now (desk_id, doing_id)
    SELECT x.desk_id, x.id
      FROM (SELECT d.desk_id, d.id,
                   ROW_NUMBER() OVER (PARTITION BY d.desk_id ORDER BY d.created DESC, d.id DESC) AS rn
              FROM doing d) x
     WHERE x.rn = 1 AND NOT EXISTS (SELECT 1 FROM doing_now w WHERE w.desk_id = x.desk_id);
    SET @m080_rows = ROW_COUNT();
    COMMIT;

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
       WHERE f.tbl = v_t AND NOT mill_migrate_080_fk_ok(f.tbl, f.name, f.cols, f.ref, f.refcols, f.rule_);
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
