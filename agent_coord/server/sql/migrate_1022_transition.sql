-- card 1022: transition table + wake as an activity + System desk id 0 + name AUTO_INCREMENT=100.
-- Existing books only; a fresh book uses tables.sql. migrate.ensure() runs this
-- when transition is missing or activity.type lacks 'wake'. A second run is a no-op.
-- from_state/to_state/reason/wake.state/wake.cause are VARCHAR text; Python Enums name them in code.

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

-- card 1022: wake as an activity (one row per wake fired at a desk).
-- state/cause are text in rows; Python Enums (State, WakeCause) are the only names in code.
CREATE TABLE IF NOT EXISTS wake (
  id          BIGINT UNSIGNED NOT NULL,          -- = activity.id where type='wake'
  type        ENUM('mail','todo','doing','hold','score','wake') NOT NULL DEFAULT 'wake',
  desk_id     BIGINT UNSIGNED NOT NULL DEFAULT 0,  -- desk being woken; 0 = System (default desk)
  cause       VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  cause_type  ENUM('mail','todo','doing','hold','score') NULL,   -- what rang it
  cause_id    BIGINT UNSIGNED NULL,
  route       VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,  -- matched route key, e.g. mail:MAIL
  state       VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'push_pending',
  PRIMARY KEY (type, id),
  UNIQUE KEY idx_id (id),
  KEY idx_desk_state (desk_id, state),
  CONSTRAINT fk_wake_activity FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE RESTRICT,
  CONSTRAINT fk_wake_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- card 1022: one row per state change of one activity. desk_id DEFAULT 0 = System (the default desk).
-- from_state/to_state/reason are VARCHAR text in rows (enums only in Python code).
-- from_state defaults to 'none' (never empty string).
CREATE TABLE IF NOT EXISTS transition (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  at            DATETIME(6) NOT NULL DEFAULT (UTC_TIMESTAMP(6)),   -- always UTC (card 1008)
  activity_type ENUM('mail','todo','doing','hold','score','wake') NOT NULL,
  activity_id   BIGINT UNSIGNED NOT NULL,
  from_state    VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT 'none',
  to_state      VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  reason        VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  desk_id       BIGINT UNSIGNED NOT NULL DEFAULT 0,  -- who acted; 0 = System (default desk); never NULL
  role          ENUM('sender','recipient','actor','holder','waiter','office','other') NOT NULL DEFAULT 'actor',
  join_key      VARCHAR(96) CHARACTER SET ascii COLLATE ascii_bin NULL,
  meta          JSON NULL,                     -- small and capped; no text, names or hosts
  PRIMARY KEY (id),
  KEY idx_type_id_at (activity_type, activity_id, at),
  KEY idx_desk_type_at (desk_id, activity_type, at),
  KEY idx_join (join_key, at),
  KEY idx_type_to_at (activity_type, to_state, at),
  CONSTRAINT fk_transition_activity FOREIGN KEY (activity_type, activity_id) REFERENCES activity (type, id) ON DELETE RESTRICT,
  CONSTRAINT fk_transition_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Allowed edges. Seeded to match transition_enums.ALLOWED_TRANSITIONS (text values = enum .value).
CREATE TABLE IF NOT EXISTS transition_edge (
  activity_type ENUM('mail','todo','doing','hold','score','wake') NOT NULL,
  from_state    VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  to_state      VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  reason        VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (activity_type, from_state, to_state, reason)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- System desk id 0 + seat (no token, never connects)
SET @mill_1022_old_mode := @@SESSION.sql_mode;
SET SESSION sql_mode = CONCAT(@@SESSION.sql_mode, ',NO_AUTO_VALUE_ON_ZERO');
INSERT IGNORE INTO name (id, type, name) VALUES (0, 'desk', 'System');
SET SESSION sql_mode = @mill_1022_old_mode;
INSERT IGNORE INTO seat (desk_id, token_hash, delivery_mode, wake_on)
  VALUES (0, NULL, 'polling', 'addressed');

-- reserve name ids 0-99 for built-ins
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
  ('wake','fail','retry_armed','wake_retry'),
  ('wake','idle','push_pending','wake_queue'),
  ('wake','lease_live','expire','wake_expire'),
  ('wake','lease_live','idle','wake_done');
INSERT IGNORE INTO transition_edge (activity_type, from_state, to_state, reason) VALUES
  ('wake','lease_live','idle','wake_sitting'),
  ('wake','lease_live','idle','wake_stale'),
  ('wake','lease_live','trail','wake_trail'),
  ('wake','left','ring','wake_ring'),
  ('wake','none','unread_owed','wake_owed'),
  ('wake','push_pending','drained','wake_deliver'),
  ('wake','push_pending','lease_live','wake_fail'),
  ('wake','push_pending','lease_live','wake_sent'),
  ('wake','retry_armed','drained','wake_drain'),
  ('wake','retry_armed','idle','wake_drain'),
  ('wake','sitting','left','wake_leave'),
  ('wake','unread_owed','lease_live','wake_fail'),
  ('wake','unread_owed','lease_live','wake_sent'),
  ('wake','unread_owed','lost_unread','wake_lost');
