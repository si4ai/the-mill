-- card 1022: fold push_queue into wake activity + transition + System desk 0.
-- Existing books only. Moves push_queue rows into activity+wake, then drops push_queue.

-- 1) widen activity.type with wake
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

-- 2) widen activity.act with ring
SET @mill_1022_act2 := (
  SELECT COLUMN_TYPE FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'activity' AND COLUMN_NAME = 'act'
);
SET @mill_1022_sql := IF(
  @mill_1022_act2 IS NOT NULL AND @mill_1022_act2 LIKE 'enum(%' AND @mill_1022_act2 NOT LIKE '%''ring''%',
  CONCAT('ALTER TABLE activity MODIFY act ', LEFT(@mill_1022_act2, CHAR_LENGTH(@mill_1022_act2) - 1), ',''ring'') NOT NULL DEFAULT ''create'''),
  'SELECT 1'
);
PREPARE mill_1022_stmt FROM @mill_1022_sql;
EXECUTE mill_1022_stmt;
DEALLOCATE PREPARE mill_1022_stmt;


-- 2b) widen doing.act with ring (same list as activity.act)
SET @mill_1022_act3 := (
  SELECT COLUMN_TYPE FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'doing' AND COLUMN_NAME = 'act'
);
SET @mill_1022_sql := IF(
  @mill_1022_act3 IS NOT NULL AND @mill_1022_act3 LIKE 'enum(%' AND @mill_1022_act3 NOT LIKE '%''ring''%',
  CONCAT('ALTER TABLE doing MODIFY act ', LEFT(@mill_1022_act3, CHAR_LENGTH(@mill_1022_act3) - 1), ',''ring'') NOT NULL DEFAULT ''focus'''),
  'SELECT 1'
);
PREPARE mill_1022_stmt FROM @mill_1022_sql;
EXECUTE mill_1022_stmt;
DEALLOCATE PREPARE mill_1022_stmt;

-- 3) label / tree / watcher gain wake
SET @mill_1022_sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'label' AND COLUMN_NAME = 'type' AND COLUMN_TYPE NOT LIKE '%''wake''%') > 0,
  'ALTER TABLE label MODIFY type ENUM(''mail'',''todo'',''doing'',''hold'',''score'',''wake'') NOT NULL',
  'SELECT 1'
);
PREPARE mill_1022_stmt FROM @mill_1022_sql; EXECUTE mill_1022_stmt; DEALLOCATE PREPARE mill_1022_stmt;

SET @mill_1022_sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'tree' AND COLUMN_NAME = 'type' AND COLUMN_TYPE NOT LIKE '%''wake''%') > 0,
  'ALTER TABLE tree MODIFY type ENUM(''mail'',''todo'',''doing'',''hold'',''score'',''wake'') NOT NULL',
  'SELECT 1'
);
PREPARE mill_1022_stmt FROM @mill_1022_sql; EXECUTE mill_1022_stmt; DEALLOCATE PREPARE mill_1022_stmt;

SET @mill_1022_sql := IF(
  (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'watcher' AND COLUMN_NAME = 'type' AND COLUMN_TYPE NOT LIKE '%''wake''%') > 0,
  'ALTER TABLE watcher MODIFY type ENUM(''todo'',''doing'',''hold'',''score'',''wake'') NOT NULL',
  'SELECT 1'
);
PREPARE mill_1022_stmt FROM @mill_1022_sql; EXECUTE mill_1022_stmt; DEALLOCATE PREPARE mill_1022_stmt;

-- 4) Drop early-1022 wake lacking payload so folded shape can replace it
SET @mill_1022_sql := IF(
  (SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wake') = 1
  AND (SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wake' AND COLUMN_NAME = 'payload') = 0,
  'DROP TABLE wake',
  'SELECT 1'
);
PREPARE mill_1022_stmt FROM @mill_1022_sql; EXECUTE mill_1022_stmt; DEALLOCATE PREPARE mill_1022_stmt;

CREATE TABLE IF NOT EXISTS wake (
  id          BIGINT UNSIGNED NOT NULL,
  type        ENUM('mail','todo','doing','hold','score','wake') NOT NULL DEFAULT 'wake',
  desk_id     BIGINT UNSIGNED NOT NULL,
  cause       VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  cause_type  ENUM('mail','todo','doing','hold','score') NULL,
  cause_id    BIGINT UNSIGNED NULL,
  route       VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
  state       VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'queued',
  payload     JSON NOT NULL,
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (type, id),
  UNIQUE KEY idx_id (id),
  KEY idx_desk (desk_id, id),
  KEY idx_desk_state (desk_id, state),
  CONSTRAINT fk_wake_activity FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE RESTRICT,
  CONSTRAINT fk_wake_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS transition (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  at            DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),
  activity_type ENUM('mail','todo','doing','hold','score','wake') NOT NULL,
  activity_id   BIGINT UNSIGNED NOT NULL,
  from_state    VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'none',
  to_state      VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  reason        VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  desk_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,
  role          ENUM('sender','recipient','actor','holder','waiter','office','other') NOT NULL DEFAULT 'actor',
  join_key      VARCHAR(96) CHARACTER SET ascii COLLATE ascii_bin NULL,
  meta          JSON NULL,
  PRIMARY KEY (id),
  KEY idx_type_id_at (activity_type, activity_id, at),
  KEY idx_desk_type_at (desk_id, activity_type, at),
  KEY idx_join (join_key, at),
  KEY idx_type_to_at (activity_type, to_state, at),
  CONSTRAINT fk_transition_activity FOREIGN KEY (activity_type, activity_id) REFERENCES activity (type, id) ON DELETE RESTRICT,
  CONSTRAINT fk_transition_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS transition_edge (
  activity_type ENUM('mail','todo','doing','hold','score','wake') NOT NULL,
  from_state    VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  to_state      VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  reason        VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (activity_type, from_state, to_state, reason)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

SET @mill_1022_old_mode := @@SESSION.sql_mode;
SET SESSION sql_mode = CONCAT(@@SESSION.sql_mode, ',NO_AUTO_VALUE_ON_ZERO');
INSERT IGNORE INTO name (id, type, name) VALUES (0, 'desk', 'System');
SET SESSION sql_mode = @mill_1022_old_mode;
INSERT IGNORE INTO seat (desk_id, token_hash, delivery_mode, wake_on)
  VALUES (0, NULL, 'polling', 'addressed');
ALTER TABLE name AUTO_INCREMENT = 100;

INSERT IGNORE INTO transition_edge (activity_type, from_state, to_state, reason) VALUES
  ('doing','active','active','doing_newer'),
  ('doing','active','failed','tw_failed'),
  ('doing','active','finished','finish_drop'),
  ('doing','active','finished','finish_pass'),
  ('doing','active','finished','finish_reply'),
  ('doing','active','finished','tw_finished'),
  ('doing','active','stale','tw_stale'),
  ('doing','active','waiting','doing_wait'),
  ('doing','active','waiting','tw_wait'),
  ('doing','any','cleared','clear'),
  ('doing','connected','seated','disconnect'),
  ('doing','idle','active','doing_put'),
  ('doing','idle','active','tw_start'),
  ('doing','no_seat','seated','join'),
  ('doing','seated','connected','connect'),
  ('doing','seated','reset','reset_seat'),
  ('doing','waiting','active','tw_resume'),
  ('doing','waiting','failed','tw_failed'),
  ('doing','waiting','finished','tw_finished'),
  ('doing','waiting','stale','tw_stale');
INSERT IGNORE INTO transition_edge (activity_type, from_state, to_state, reason) VALUES
  ('doing','waiting','waiting','wait_cycle'),
  ('hold','any','refused','hold_refuse'),
  ('hold','any','same','hold_peek'),
  ('hold','free','held','hold_grant'),
  ('hold','held','expired','hold_expire'),
  ('hold','held','free','hold_drop'),
  ('hold','held','free','hold_force'),
  ('hold','held','held','hold_refresh'),
  ('hold','no_row','held','hold_grant'),
  ('hold','refused','held','hold_wait_acquire'),
  ('mail','any','refused','orphan_refuse'),
  ('mail','any','refused','size_limit'),
  ('mail','delivered','woken','woken'),
  ('mail','handled','answered','answered'),
  ('mail','handled','handled','mark'),
  ('mail','handled','removed','remove_recipient'),
  ('mail','live','deleted','delete_probe'),
  ('mail','live','delivered','delivered'),
  ('mail','none','live','reply'),
  ('mail','none','live','send_or_queue');
INSERT IGNORE INTO transition_edge (activity_type, from_state, to_state, reason) VALUES
  ('mail','none','unread','add_recipient'),
  ('mail','none','unread','send_or_queue'),
  ('mail','unread','answered','answered'),
  ('mail','unread','handled','mark'),
  ('mail','unread','handled','thread_read'),
  ('mail','unread','removed','remove_recipient'),
  ('mail','unread','unread','preview'),
  ('score','any','refused','score_refuse'),
  ('score','defined','live','score_point'),
  ('score','defined','retired','score_retire'),
  ('score','live','live','score_point'),
  ('score','live','live','score_retarget'),
  ('score','live','retired','score_retire'),
  ('score','none','defined','score_define'),
  ('score','none','live','score_point'),
  ('score','retired','defined','score_revive'),
  ('score','retired','live','score_revive'),
  ('todo','any','retired','retire'),
  ('todo','any','same','note'),
  ('todo','claimed','claimed','take_over');
INSERT IGNORE INTO transition_edge (activity_type, from_state, to_state, reason) VALUES
  ('todo','claimed','open','unclaim'),
  ('todo','claimed','shipped','pass_ship'),
  ('todo','done','shipped','pass_back'),
  ('todo','live','deleted','delete_probe'),
  ('todo','none','open','create'),
  ('todo','none','parked','create_parked'),
  ('todo','open','claimed','assign'),
  ('todo','open','claimed','claim'),
  ('todo','parked','open','unpark'),
  ('todo','retired','prior','reclaim'),
  ('todo','shipped','claimed','pass_back'),
  ('todo','shipped','done','pass_done'),
  ('todo','shipped','open','pass_back'),
  ('wake','any','coalesced','wake_coalesce'),
  ('wake','any','sitting','wake_sit'),
  ('wake','any','skipped','wake_skip'),
  ('wake','error','taken','wake_deliver'),
  ('wake','fail','retry_armed','wake_retry'),
  ('wake','idle','push_pending','wake_queue'),
  ('wake','lease_live','expire','wake_expire');
INSERT IGNORE INTO transition_edge (activity_type, from_state, to_state, reason) VALUES
  ('wake','lease_live','idle','wake_done'),
  ('wake','lease_live','idle','wake_sitting'),
  ('wake','lease_live','idle','wake_stale'),
  ('wake','lease_live','trail','wake_trail'),
  ('wake','left','ring','wake_ring'),
  ('wake','missed','taken','wake_deliver'),
  ('wake','none','queued','wake_queue'),
  ('wake','none','unread_owed','wake_owed'),
  ('wake','push_pending','drained','wake_deliver'),
  ('wake','push_pending','lease_live','wake_fail'),
  ('wake','push_pending','lease_live','wake_sent'),
  ('wake','queued','error','wake_fail'),
  ('wake','queued','missed','wake_owed'),
  ('wake','queued','sent','wake_sent'),
  ('wake','queued','taken','wake_deliver'),
  ('wake','retry_armed','drained','wake_drain'),
  ('wake','retry_armed','idle','wake_drain'),
  ('wake','sent','missed','wake_owed'),
  ('wake','sent','taken','wake_deliver'),
  ('wake','sitting','left','wake_leave');
INSERT IGNORE INTO transition_edge (activity_type, from_state, to_state, reason) VALUES
  ('wake','unread_owed','lease_live','wake_fail'),
  ('wake','unread_owed','lease_live','wake_sent'),
  ('wake','unread_owed','lost_unread','wake_lost');
