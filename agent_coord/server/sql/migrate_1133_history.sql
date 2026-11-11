-- card 1133: body edit stamps, todo meta and activity_history on an existing book; fresh books use tables.sql.
-- Every step checks the book first, so a second run (or a run after a partial one) does only what is left.

-- 1) activity.act and doing.act gain replace (one list, appended after task).
SET @mill_1133_act := (
  SELECT COLUMN_TYPE FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'activity' AND COLUMN_NAME = 'act'
);
SET @mill_1133_sql := IF(
  @mill_1133_act IS NOT NULL AND @mill_1133_act LIKE 'enum(%' AND @mill_1133_act NOT LIKE '%''replace''%',
  CONCAT('ALTER TABLE activity MODIFY act ', LEFT(@mill_1133_act, CHAR_LENGTH(@mill_1133_act) - 1), ',''replace'') NOT NULL DEFAULT ''create'''),
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

SET @mill_1133_act := (
  SELECT COLUMN_TYPE FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'doing' AND COLUMN_NAME = 'act'
);
SET @mill_1133_sql := IF(
  @mill_1133_act IS NOT NULL AND @mill_1133_act LIKE 'enum(%' AND @mill_1133_act NOT LIKE '%''replace''%',
  CONCAT('ALTER TABLE doing MODIFY act ', LEFT(@mill_1133_act, CHAR_LENGTH(@mill_1133_act) - 1), ',''replace'') NOT NULL DEFAULT ''focus'''),
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

-- 2) mail: body_updated, body_updater_id (FK seat RESTRICT).
SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail' AND COLUMN_NAME = 'body_updated') = 0,
  'ALTER TABLE mail ADD COLUMN body_updated DATETIME(6) NULL AFTER body',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail' AND COLUMN_NAME = 'body_updater_id') = 0,
  'ALTER TABLE mail ADD COLUMN body_updater_id BIGINT UNSIGNED NULL AFTER body_updated',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail' AND INDEX_NAME = 'idx_body_updater') = 0,
  'ALTER TABLE mail ADD KEY idx_body_updater (body_updater_id)',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'mail' AND CONSTRAINT_NAME = 'fk_mail_body_updater') = 0,
  'ALTER TABLE mail ADD CONSTRAINT fk_mail_body_updater FOREIGN KEY (body_updater_id) REFERENCES seat (desk_id) ON DELETE RESTRICT',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

-- 3) todo: meta, body_updated, body_updater_id (FK seat RESTRICT).
SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'todo' AND COLUMN_NAME = 'meta') = 0,
  'ALTER TABLE todo ADD COLUMN meta JSON NULL AFTER body',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'todo' AND COLUMN_NAME = 'body_updated') = 0,
  'ALTER TABLE todo ADD COLUMN body_updated DATETIME(6) NULL AFTER meta',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'todo' AND COLUMN_NAME = 'body_updater_id') = 0,
  'ALTER TABLE todo ADD COLUMN body_updater_id BIGINT UNSIGNED NULL AFTER body_updated',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'todo' AND INDEX_NAME = 'idx_body_updater') = 0,
  'ALTER TABLE todo ADD KEY idx_body_updater (body_updater_id)',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

SET @mill_1133_sql := IF(
  (SELECT COUNT(*) FROM information_schema.TABLE_CONSTRAINTS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'todo' AND CONSTRAINT_NAME = 'fk_todo_body_updater') = 0,
  'ALTER TABLE todo ADD CONSTRAINT fk_todo_body_updater FOREIGN KEY (body_updater_id) REFERENCES seat (desk_id) ON DELETE RESTRICT',
  'SELECT 1'
);
PREPARE mill_1133_stmt FROM @mill_1133_sql; EXECUTE mill_1133_stmt; DEALLOCATE PREPARE mill_1133_stmt;

-- 4) activity_history, as in tables.sql.
CREATE TABLE IF NOT EXISTS activity_history (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type           ENUM('mail','todo') NOT NULL,
  activity_id    BIGINT UNSIGNED NOT NULL,
  old_body       VARCHAR(4096) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  old_updated    DATETIME(6)     NOT NULL,
  old_updater_id BIGINT UNSIGNED NOT NULL,
  replaced_at    DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  replaced_by    BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY idx_item_version (type, activity_id, old_updated),
  KEY idx_old_updater (old_updater_id),
  KEY idx_replaced_by (replaced_by),
  CONSTRAINT fk_history_activity FOREIGN KEY (type, activity_id) REFERENCES activity (type, id) ON DELETE CASCADE,
  CONSTRAINT fk_history_old_updater FOREIGN KEY (old_updater_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_history_replaced_by FOREIGN KEY (replaced_by) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 5) Split each card document not yet split (meta NULL): the detail string, unescaped, becomes body; every other
-- key becomes meta. A body that is not a JSON object is all text with empty meta. Same rule as MILL_BODY_TEXT and
-- MILL_BODY_META (sp_body.sql), written out here so the step does not depend on the routines being loaded.
-- meta is assigned first: MySQL assigns left to right, so body is still the document when meta is computed.
-- updated has ON UPDATE CURRENT_TIMESTAMP: the split is not a card edit, so it keeps updated as it is.
UPDATE todo
   SET updated = updated,
       meta = CASE
         WHEN NOT JSON_VALID(body) THEN JSON_OBJECT()
         WHEN JSON_TYPE(CAST(body AS JSON)) <> 'OBJECT' THEN JSON_OBJECT()
         ELSE JSON_REMOVE(CAST(body AS JSON), '$.detail')
       END,
       body = CASE
         WHEN NOT JSON_VALID(body) THEN body
         WHEN JSON_TYPE(CAST(body AS JSON)) <> 'OBJECT' THEN body
         WHEN JSON_EXTRACT(body, '$.detail') IS NULL THEN ''
         WHEN JSON_TYPE(JSON_EXTRACT(body, '$.detail')) = 'NULL' THEN ''
         WHEN JSON_TYPE(JSON_EXTRACT(body, '$.detail')) = 'STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(body, '$.detail'))
         ELSE CAST(JSON_EXTRACT(body, '$.detail') AS CHAR CHARACTER SET utf8mb4)
       END
 WHERE meta IS NULL;
