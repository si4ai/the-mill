-- card 1022: transition table + wake as an activity + System desk id 0.
-- Existing books only; a fresh book uses tables.sql. migrate.ensure() runs this
-- when transition is missing or activity.type lacks 'wake'. A second run is a no-op.

-- 1) widen activity.type
SET @mill_1022_act := (
  SELECT COLUMN_TYPE FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'activity' AND COLUMN_NAME = 'type'
);
SET @mill_1022_sql := IF(
  @mill_1022_act IS NOT NULL AND @mill_1022_act LIKE 'enum(%' AND @mill_1022_act NOT LIKE '%''wake''%',
  CONCAT('ALTER TABLE activity MODIFY type ', LEFT(@mill_1022_act, CHAR_LENGTH(@mill_1022_act) - 1), ',''wake'') NOT NULL'),
  'SELECT 1'
);
PREPARE mill_1022_stmt FROM @mill_1022_sql;
EXECUTE mill_1022_stmt;
DEALLOCATE PREPARE mill_1022_stmt;

-- 2) wake payload
CREATE TABLE IF NOT EXISTS wake (
  id          BIGINT UNSIGNED NOT NULL,
  type        ENUM('mail','todo','doing','hold','score','wake') NOT NULL DEFAULT 'wake',
  desk_id     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  cause       ENUM('mail','hint','receipt','room','retry','test') NOT NULL,
  cause_type  ENUM('mail','todo','doing','hold','score') NULL,
  cause_id    BIGINT UNSIGNED NULL,
  route       VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  state       VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'queued',
  PRIMARY KEY (id),
  KEY idx_desk_state (desk_id, state),
  CONSTRAINT fk_wake_activity FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE RESTRICT,
  CONSTRAINT fk_wake_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 3) transition
CREATE TABLE IF NOT EXISTS transition (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  at            DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
  activity_type ENUM('mail','todo','doing','hold','score','wake') NOT NULL,
  activity_id   BIGINT UNSIGNED NOT NULL,
  from_state    VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT '',
  to_state      VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  reason        VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  desk_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
  role          ENUM('sender','recipient','actor','holder','waiter','office','other') NOT NULL DEFAULT 'actor',
  join_key      VARCHAR(96) CHARACTER SET ascii COLLATE ascii_bin NULL,
  meta          JSON NULL,
  PRIMARY KEY (id),
  KEY idx_type_id_at   (activity_type, activity_id, at),
  KEY idx_desk_type_at (desk_id, activity_type, at),
  KEY idx_join         (join_key, at),
  KEY idx_type_to_at   (activity_type, to_state, at),
  CONSTRAINT fk_transition_activity FOREIGN KEY (activity_type, activity_id) REFERENCES activity (type, id) ON DELETE RESTRICT,
  CONSTRAINT fk_transition_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 4) System desk id 0 + seat (no token, never connects)
SET @mill_1022_old_mode := @@SESSION.sql_mode;
SET SESSION sql_mode = CONCAT(@@SESSION.sql_mode, ',NO_AUTO_VALUE_ON_ZERO');
INSERT IGNORE INTO name (id, type, name) VALUES (0, 'desk', 'System');
SET SESSION sql_mode = @mill_1022_old_mode;
INSERT IGNORE INTO seat (desk_id, token_hash, delivery_mode, wake_on)
  VALUES (0, NULL, 'polling', 'addressed');

-- card 1022: reserve name ids 0-99 for built-ins. MySQL only raises AUTO_INCREMENT
-- when the current counter is below 100; live offices with max(id) in 3..99 keep those ids.
ALTER TABLE name AUTO_INCREMENT = 100;
