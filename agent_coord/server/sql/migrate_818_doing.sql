-- #818 (0.7.16): join becomes doing. Existing books only; not in apply_order.txt.
-- A fresh book uses tables.sql. migrate.ensure() runs this file when the book
-- still has a `join` table or a type column that lists 'join', then reloads
-- every routine. A second run finds nothing to do and changes nothing.
--
-- 1. seat: new table, one row per desk, not an activity. Copied from `join`
--    (token, delivery, webhook url/key, wake_on, lan, connect stamps).
-- 2. Activity type join -> doing on every type list (activity, label, tree,
--    mail, mail_to, todo, join, hold, score, watcher): add 'doing' at the end,
--    move the rows, then the final list drops 'join'. 'doing' takes the place
--    'join' had, so ENUM sort order is unchanged. Three FKs name a type
--    column (label and tree to activity, mail_to to mail); each is dropped
--    for the move and added back with its delete rule. Each list is read from
--    the book, so a value an older pack left (watcher name on some books) stays.
-- 3. The `join` table becomes the append-only `doing` table: same ids, the old
--    doing text kept as text, no source (on_*) and no waiting (waiting_*).
--    Per-desk columns and the unique desk key go; seat holds them now.
-- Ids, activity rows and watcher rows keep their ids, so every pointer resolves.

DROP PROCEDURE IF EXISTS mill_migrate_818_doing;
DROP PROCEDURE IF EXISTS mill_migrate_818_retype;

DELIMITER //

-- One table's type column. The list is read from the book, not assumed, so a
-- book whose list has drifted from tables.sql (an extra value left by an older
-- pack) keeps its other values and rows. widen appends 'doing'; final drops
-- 'join' and puts 'doing' where 'join' was. Each is a no-op once done.
CREATE PROCEDURE mill_migrate_818_retype(IN p_table VARCHAR(64), IN p_step VARCHAR(8))
BEGIN
  DECLARE v_ct TEXT DEFAULT NULL;
  DECLARE v_def TEXT DEFAULT NULL;
  DECLARE v_new TEXT DEFAULT NULL;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_ct = NULL;
  SELECT COLUMN_TYPE, COLUMN_DEFAULT INTO v_ct, v_def
    FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = p_table AND COLUMN_NAME = 'type';
  IF v_ct IS NOT NULL AND v_ct LIKE 'enum(%' AND v_ct LIKE '%''join''%' THEN
    IF p_step = 'widen' AND v_ct NOT LIKE '%''doing''%' THEN
      SET v_new = CONCAT(LEFT(v_ct, CHAR_LENGTH(v_ct) - 1), ',''doing'')');
    ELSEIF p_step = 'final' THEN
      SET v_new = REPLACE(REPLACE(v_ct, ',''doing''', ''), '''join''', '''doing''');
      IF v_def = 'join' THEN
        SET v_def = 'doing';
      END IF;
    END IF;
    IF v_new IS NOT NULL THEN
      SET @mill_818_sql = CONCAT('ALTER TABLE `', p_table, '` MODIFY type ', v_new, ' NOT NULL',
                                 IF(v_def IS NULL, '', CONCAT(' DEFAULT ''', v_def, '''')));
      PREPARE mill_818_stmt FROM @mill_818_sql;
      EXECUTE mill_818_stmt;
      DEALLOCATE PREPARE mill_818_stmt;
    END IF;
  END IF;
END //

CREATE PROCEDURE mill_migrate_818_doing()
BEGIN
  -- 1. seat (same shape as tables.sql).
  CREATE TABLE IF NOT EXISTS seat (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    desk_id         BIGINT UNSIGNED NOT NULL,
    created         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
    token_hash      CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    delivery_mode   ENUM('websocket','webhook','polling') NOT NULL DEFAULT 'polling',
    endpoint_url    VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
    endpoint_key    VARCHAR(512) CHARACTER SET ascii COLLATE ascii_bin NULL,
    wake_on         ENUM('all','addressed') NOT NULL DEFAULT 'all',
    lan_ip          VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NULL,
    time_connect    DATETIME(6) NULL,
    time_disconnect DATETIME(6) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY idx_desk (desk_id),
    KEY idx_lan_updated (lan_ip, updated),
    KEY idx_token_hash (token_hash),
    CONSTRAINT fk_seat_desk FOREIGN KEY (desk_id) REFERENCES name (id) ON DELETE RESTRICT
  ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

  -- Copy while `join` still carries the per-desk columns. INSERT IGNORE: a
  -- re-run after a partial first run copies nothing twice. seat.id = join.id.
  IF (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join') > 0 AND (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join' AND COLUMN_NAME = 'token_hash') > 0 THEN
    INSERT IGNORE INTO seat (id, desk_id, created, updated, token_hash, delivery_mode,
                             endpoint_url, endpoint_key, wake_on, lan_ip,
                             time_connect, time_disconnect)
    SELECT j.id, j.desk_id, j.created, j.updated, j.token_hash, j.delivery_mode,
           j.endpoint_url, j.endpoint_key, j.wake_on, j.lan_ip,
           j.time_connect, j.time_disconnect
      FROM `join` j;
  END IF;

  -- 2. join -> doing on every type list. label/tree FKs off for the move.
  IF (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'label' AND CONSTRAINT_NAME = 'fk_label_activity' AND CONSTRAINT_TYPE = 'FOREIGN KEY') > 0 THEN
    ALTER TABLE label DROP FOREIGN KEY fk_label_activity;
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tree' AND CONSTRAINT_NAME = 'fk_tree_activity' AND CONSTRAINT_TYPE = 'FOREIGN KEY') > 0 THEN
    ALTER TABLE tree DROP FOREIGN KEY fk_tree_activity;
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail_to' AND CONSTRAINT_NAME = 'fk_mail_to_mail' AND CONSTRAINT_TYPE = 'FOREIGN KEY') > 0 THEN
    ALTER TABLE mail_to DROP FOREIGN KEY fk_mail_to_mail;
  END IF;

  -- 2a. Add 'doing' at the end (metadata only).
  CALL mill_migrate_818_retype('activity', 'widen');
  CALL mill_migrate_818_retype('label', 'widen');
  CALL mill_migrate_818_retype('tree', 'widen');
  CALL mill_migrate_818_retype('mail', 'widen');
  CALL mill_migrate_818_retype('mail_to', 'widen');
  CALL mill_migrate_818_retype('todo', 'widen');
  CALL mill_migrate_818_retype('join', 'widen');
  CALL mill_migrate_818_retype('hold', 'widen');
  CALL mill_migrate_818_retype('score', 'widen');
  CALL mill_migrate_818_retype('watcher', 'widen');

  -- 2b. Move the rows. updated = updated: the type move is not an edit, so
  -- ON UPDATE CURRENT_TIMESTAMP must not stamp every moved row as new.
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'activity' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE activity SET type = 'doing', updated = updated WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'label' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE label SET type = 'doing' WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tree' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE tree SET type = 'doing' WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE mail SET type = 'doing' WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail_to' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE mail_to SET type = 'doing' WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'todo' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE todo SET type = 'doing', updated = updated WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE `join` SET type = 'doing', updated = updated WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'hold' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE hold SET type = 'doing', updated = updated WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'score' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE score SET type = 'doing', updated = updated WHERE type = 'join';
  END IF;
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'watcher' AND COLUMN_NAME = 'type' AND COLUMN_TYPE LIKE '%''join''%') > 0 THEN
    UPDATE watcher SET type = 'doing', updated = updated WHERE type = 'join';
  END IF;

  -- 2c. Drop 'join'; 'doing' takes its place in the list.
  CALL mill_migrate_818_retype('activity', 'final');
  CALL mill_migrate_818_retype('label', 'final');
  CALL mill_migrate_818_retype('tree', 'final');
  CALL mill_migrate_818_retype('mail', 'final');
  CALL mill_migrate_818_retype('mail_to', 'final');
  CALL mill_migrate_818_retype('todo', 'final');
  CALL mill_migrate_818_retype('join', 'final');
  CALL mill_migrate_818_retype('hold', 'final');
  CALL mill_migrate_818_retype('score', 'final');
  CALL mill_migrate_818_retype('watcher', 'final');

  IF NOT (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'label' AND CONSTRAINT_NAME = 'fk_label_activity' AND CONSTRAINT_TYPE = 'FOREIGN KEY') > 0 THEN
    ALTER TABLE label ADD CONSTRAINT fk_label_activity
      FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE CASCADE;
  END IF;
  IF NOT (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tree' AND CONSTRAINT_NAME = 'fk_tree_activity' AND CONSTRAINT_TYPE = 'FOREIGN KEY') > 0 THEN
    ALTER TABLE tree ADD CONSTRAINT fk_tree_activity
      FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE RESTRICT;
  END IF;
  IF NOT (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail_to' AND CONSTRAINT_NAME = 'fk_mail_to_mail' AND CONSTRAINT_TYPE = 'FOREIGN KEY') > 0 THEN
    ALTER TABLE mail_to ADD CONSTRAINT fk_mail_to_mail
      FOREIGN KEY (type, id) REFERENCES mail (type, id) ON DELETE CASCADE;
  END IF;

  -- 3. `join` becomes the append-only doing table. Same ids.
  IF (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join') > 0 AND NOT (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'doing') > 0 THEN
    IF (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join' AND CONSTRAINT_NAME = 'fk_join_desk' AND CONSTRAINT_TYPE = 'FOREIGN KEY') > 0 THEN
      ALTER TABLE `join` DROP FOREIGN KEY fk_join_desk;
    END IF;
    IF (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join' AND CONSTRAINT_NAME = 'fk_join_activity' AND CONSTRAINT_TYPE = 'FOREIGN KEY') > 0 THEN
      ALTER TABLE `join` DROP FOREIGN KEY fk_join_activity;
    END IF;
    IF (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join' AND INDEX_NAME = 'idx_desk') > 0 THEN
      ALTER TABLE `join` DROP INDEX idx_desk;
    END IF;
    IF (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join' AND INDEX_NAME = 'idx_lan_updated') > 0 THEN
      ALTER TABLE `join` DROP INDEX idx_lan_updated;
    END IF;
    IF (SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join' AND INDEX_NAME = 'idx_token_hash') > 0 THEN
      ALTER TABLE `join` DROP INDEX idx_token_hash;
    END IF;
    -- guarded: a run killed after this one ALTER resumes at the roster copy.
    IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'join' AND COLUMN_NAME = 'doing') > 0 THEN
    -- A doing entry's time is when its text was last set: join.updated, not
    -- join.created (when the seat was made; seat keeps that). Same values on a re-run.
    UPDATE `join` SET created = updated, updated = updated;
    ALTER TABLE `join`
      RENAME COLUMN doing TO text,
      ADD COLUMN roster_id BIGINT UNSIGNED NOT NULL DEFAULT 1 AFTER desk_id,
      ADD COLUMN on_type ENUM('mail','todo','hold','score') NULL AFTER text,
      ADD COLUMN on_id BIGINT UNSIGNED NULL AFTER on_type,
      ADD COLUMN waiting_type ENUM('mail','todo','hold','desk') NULL AFTER on_id,
      ADD COLUMN waiting_id BIGINT UNSIGNED NULL AFTER waiting_type,
      ADD COLUMN waiting_why VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL AFTER waiting_id,
      DROP COLUMN updated,
      DROP COLUMN token_hash,
      DROP COLUMN delivery_mode,
      DROP COLUMN endpoint_url,
      DROP COLUMN endpoint_key,
      DROP COLUMN wake_on,
      DROP COLUMN lan_ip,
      DROP COLUMN time_connect,
      DROP COLUMN time_disconnect,
      ADD KEY idx_desk_created (desk_id, created),
      ADD KEY idx_on (on_type, on_id),
      ADD CONSTRAINT fk_doing_desk FOREIGN KEY (desk_id) REFERENCES name (id) ON DELETE RESTRICT,
      ADD CONSTRAINT fk_doing_roster FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT;
    END IF;
    -- The entry's roster is the one its activity row already carries.
    UPDATE `join` j
      JOIN activity a ON a.type = 'doing' AND a.id = j.id
       SET j.roster_id = a.roster_id;
    RENAME TABLE `join` TO doing;
  END IF;

  -- 4. on_type points at any activity but doing (a book migrated by an earlier
  -- build of this file has mail/todo only). Widening keeps every value.
  IF (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'doing' AND COLUMN_NAME = 'on_type' AND COLUMN_TYPE <> 'enum(''mail'',''todo'',''hold'',''score'')') > 0 THEN
    ALTER TABLE doing MODIFY on_type ENUM('mail','todo','hold','score') NULL;
  END IF;
END //

DELIMITER ;

-- Triggers move with a renamed table; these name the old type. ensure()
-- adds doing_no_delete_in_tree from tables.sql. join_ad_activity is a
-- leftover from an older pack on some books; doing rows are never deleted.
DROP TRIGGER IF EXISTS join_no_delete_in_tree;
DROP TRIGGER IF EXISTS join_ad_activity;
CALL mill_migrate_818_doing();
DROP PROCEDURE IF EXISTS mill_migrate_818_doing;
DROP PROCEDURE IF EXISTS mill_migrate_818_retype;
