DROP PROCEDURE IF EXISTS mill_join_upsert;
DROP PROCEDURE IF EXISTS mill_join_delete;
DROP PROCEDURE IF EXISTS mill_join_reset;
DROP PROCEDURE IF EXISTS mill_join_select;
DROP PROCEDURE IF EXISTS mill_join_doing;
DROP PROCEDURE IF EXISTS mill_join_connect;
DROP PROCEDURE IF EXISTS mill_join_socket;
DROP PROCEDURE IF EXISTS mill_join_lan;
DROP PROCEDURE IF EXISTS mill_join_wake_arm;
DROP PROCEDURE IF EXISTS mill_join_wake_off;
DROP PROCEDURE IF EXISTS mill_join_wake_state;
DROP PROCEDURE IF EXISTS mill_join_wake_target;
DROP PROCEDURE IF EXISTS mill_join_touch;
DROP PROCEDURE IF EXISTS mill_doing_anchor;
DROP PROCEDURE IF EXISTS mill_doing_move;
DROP PROCEDURE IF EXISTS mill_doing_clear;
DROP PROCEDURE IF EXISTS mill_doing_insert;

-- 0.8.0: every desk name has a seat row from its mint (desk columns FK to seat). A desk has joined
-- when its seat has a token or was reset or retired: (token_hash IS NOT NULL OR time_disconnect IS NOT NULL).
DELIMITER //

-- #818: the seat is per-desk state (not an activity). Card 1207 (the owner, 2026-11-13): a doing row is one
-- tw.exe run (sp_doing.sql mill_doing_task); join, clock-out, reset and the heartbeats (connect, touch, socket,
-- lan) write no doing row and there is no seat pointer. Clock-out and reset end the desk's live doings
-- (mill_doing_clear_live). A heartbeat leaves activity alone.
CREATE PROCEDURE mill_join_upsert(
  IN p_project    VARCHAR(64),
  IN p_desk       VARCHAR(64),
  IN p_role       VARCHAR(64),
  IN p_token_hash CHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_seat BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_have CHAR(64);
  DECLARE v_del DATETIME(6);
  DECLARE v_lock BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  -- #674: the reserved Admin roster (id 2) is granted only by member-add on the
  -- office host. Never by join, as the project or the role, in any spelling the
  -- name collation resolves to it. Refuse before any write.
  IF MILL_NAME_GET('roster', p_project) = 2
     OR (IFNULL(p_role, '') <> '' AND (LOWER(p_role) = 'admin' OR MILL_NAME_GET('roster', p_role) = 2)) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'Admin is not granted by join: roster Admin is granted only by member-add on the office host';
  END IF;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_proj = MILL_NAME_PUT('roster', p_project);
  SET v_desk = MILL_NAME_PUT('desk', p_desk);
  -- F186 / F195 (spin N03, card 906): hold the name row and read deleted in the same
  -- locking read so a concurrent retire cannot leave a retired desk with a fresh token.
  -- A plain re-check after FOR UPDATE is not enough under REPEATABLE READ.
  SELECT id, deleted INTO v_desk, v_del FROM name WHERE id = v_desk FOR UPDATE;
  IF v_del IS NOT NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'name retired: mill reclaim NAME NAME --yes (mill host only)';
  END IF;
  SET v_seat = NULL;
  SET v_have = NULL;
  SELECT id, token_hash INTO v_seat, v_have FROM seat WHERE desk_id = v_desk LIMIT 1 FOR UPDATE;
  IF v_have IS NOT NULL AND p_token_hash IS NOT NULL AND v_have <> p_token_hash THEN
    ROLLBACK;
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'desk live: token required (no steal)';
  END IF;
  IF v_seat IS NULL THEN
    INSERT INTO seat (updated, desk_id, token_hash, delivery_mode)
    VALUES (v_ts, v_desk, p_token_hash, 'websocket');
  ELSE
    UPDATE seat
       SET updated = v_ts,
           token_hash = IFNULL(p_token_hash, token_hash),
           delivery_mode = IF(delivery_mode = 'polling', 'websocket', delivery_mode)
     WHERE id = v_seat;
  END IF;
  -- The member insert locks name(id). Hold that roster first, then count the new member.
  SELECT id INTO v_lock FROM name WHERE id = 1 FOR UPDATE;
  INSERT IGNORE INTO member (name_id, desk_id) VALUES (1, v_desk);
  IF ROW_COUNT() = 1 THEN
    UPDATE name SET n = n + 1 WHERE id = 1;
  END IF;
  IF v_proj IS NOT NULL AND v_proj <> 1 AND v_proj <> 2 THEN
    SELECT id INTO v_lock FROM name WHERE id = v_proj FOR UPDATE;
    INSERT IGNORE INTO member (name_id, desk_id) VALUES (v_proj, v_desk);
    IF ROW_COUNT() = 1 THEN
      UPDATE name SET n = n + 1 WHERE id = v_proj;
    END IF;
  END IF;
  IF p_role IS NOT NULL AND p_role <> '' THEN
    IF LOWER(IFNULL(p_role, '')) = 'admin' THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Admin is not granted by join';
    END IF;
    SET @v_role := MILL_NAME_PUT('roster', p_role);
    SELECT id INTO v_lock FROM name WHERE id = @v_role FOR UPDATE;
    INSERT IGNORE INTO member (name_id, desk_id) VALUES (@v_role, v_desk);
    IF ROW_COUNT() = 1 THEN
      UPDATE name SET n = n + 1 WHERE id = @v_role;
    END IF;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_ts AS updated, v_desk AS desk_id, p_desk AS owner;
END //

-- Clock-out: the desk's live doings end as cleared (card 1207), the seat stays.
CREATE PROCEDURE mill_join_delete(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_lock BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  -- Lock order (card 1113): the seat exclusive before the joined check (IF EXISTS in a routine
  -- reads shared, and the UPDATE below then wanted the row exclusive).
  SELECT id INTO v_lock FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF v_desk IS NOT NULL AND EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    CALL mill_doing_clear_live(v_desk, v_desk, 'clockout');
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_desk AS owner, 'clocked-out' AS op;
END //

-- p_by: the desk running the reset (an admin), NULL when unknown. Card 1207 (Validator): a reset of another
-- desk frees its holds as hold_force with meta.by, as a retire does; the desk's own reset (or no p_by) is hold_drop.
CREATE PROCEDURE mill_join_reset(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64),
  IN p_by      VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_by BIGINT UNSIGNED;
  DECLARE v_released INT DEFAULT 0;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_desk = NULL;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  -- #608: a retired desk resolves too, so reset still revokes its seat.
  SELECT id INTO v_desk FROM name WHERE type = 'desk' AND name = TRIM(p_desk) LIMIT 1;
  -- #96: reset is a disconnect stamp. Never DELETE the seat, a doing row or its activity.
  -- #618: a reset seat keeps no webhook wake; the next holder arms its own.
  UPDATE seat SET token_hash = NULL, time_disconnect = v_ts,
         delivery_mode = IF(delivery_mode = 'webhook', 'websocket', delivery_mode),
         endpoint_url = NULL, endpoint_key = NULL
   WHERE desk_id = v_desk;
  IF v_desk IS NOT NULL AND EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    CALL mill_doing_clear_live(v_desk, v_desk, 'reset');
  END IF;
  -- Card 842: a reset desk owns no lock. Free its holds like a drop would; the rows name the holder, and
  -- meta.by the resetting desk when it is another one (hold_force).
  SET v_by = NULL;
  IF NULLIF(TRIM(IFNULL(p_by, '')), '') IS NOT NULL THEN
    SELECT id INTO v_by FROM name WHERE type = 'desk' AND name = TRIM(p_by) LIMIT 1;
  END IF;
  IF v_desk IS NOT NULL THEN
    CALL mill_hold_release_desk(v_desk, IFNULL(v_by, v_desk), v_ts, v_released);
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_desk AS owner, 'reset' AS op, v_released AS released;
END //

-- Seats. id is the desk id; doing_n is how many doings the desk is running (live tw runs, card 1207).
CREATE PROCEDURE mill_join_select(IN p_project VARCHAR(64))
BEGIN
  DECLARE v_proj BIGINT UNSIGNED;
  SET v_proj = NULL;
  IF NOT (p_project IS NULL OR p_project = '') THEN
    SET v_proj = IFNULL(MILL_NAME_GET('roster', p_project), 0);
  END IF;
  SELECT 'seat' AS type, h.desk_id AS id, h.created, h.updated, h.desk_id, h.token_hash,
         (SELECT COUNT(*) FROM doing g WHERE g.desk_id = h.desk_id AND MILL_DOING_LIVE(g.id)) AS doing_n,
         h.delivery_mode, h.endpoint_url, h.lan_ip, h.time_connect, h.time_disconnect,
         dsk.name AS desk, dsk.type AS desk_type,
         IF(ra.id IS NULL, NULL, JSON_OBJECT(
           'type', ra.type,
           'id', ra.id,
           'roster_id', ra.roster_id,
           'roster', aff.name,
           'roster_type', aff.type,
           'thing', CASE ra.type
             WHEN 'mail' THEN LEFT(ml.body, 80)
             WHEN 'todo' THEN LEFT(td.body, 80)
             WHEN 'hold' THEN hr.name
             WHEN 'score' THEN sc.kpi
             WHEN 'doing' THEN jd.name
             ELSE NULL
           END
         )) AS recent_activity
  FROM seat h
  LEFT JOIN name dsk ON dsk.id = h.desk_id
  LEFT JOIN LATERAL (
    SELECT type, id, roster_id, updated
    FROM activity USE INDEX (idx_desk_updated)
    WHERE desk_id = h.desk_id
    ORDER BY updated DESC
    LIMIT 1
  ) ra ON TRUE
  LEFT JOIN name aff ON aff.id = ra.roster_id
  LEFT JOIN mail ml ON ra.type = 'mail' AND ml.id = ra.id
  LEFT JOIN todo td ON ra.type = 'todo' AND td.id = ra.id
  LEFT JOIN hold ho ON ra.type = 'hold' AND ho.id = ra.id
  LEFT JOIN name hr ON hr.id = ho.resource_id
  LEFT JOIN score sc ON ra.type = 'score' AND sc.id = ra.id
  LEFT JOIN doing js ON ra.type = 'doing' AND js.id = ra.id
  LEFT JOIN name jd ON jd.id = js.desk_id
  -- 0.8.0: a named desk has a seat row from its mint; only a joined one (token, or reset or retired) lists.
  WHERE (h.token_hash IS NOT NULL OR h.time_disconnect IS NOT NULL)
    AND (v_proj IS NULL
     OR EXISTS (SELECT 1 FROM member m WHERE m.desk_id = h.desk_id AND m.name_id = v_proj))
  ORDER BY h.updated DESC;
END //

CREATE PROCEDURE mill_join_connect(
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_lock BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  -- Lock order (card 1113): the seat exclusive before the joined check (IF EXISTS in a routine
  -- reads shared, and the UPDATE below then wanted the row exclusive).
  SELECT id INTO v_lock FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF v_desk IS NULL OR NOT EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    ROLLBACK;
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'mill connect: desk has not joined';
  END IF;
  -- 0.8.0 (the owner, 2026-10-26): a heartbeat writes no doing row and leaves activity alone; seat.updated is
  -- the desk's last-seen clock.
  UPDATE seat SET updated = v_ts WHERE desk_id = v_desk;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_ts AS updated, v_desk AS desk_id;
END //

-- A command that writes nothing else (#635): bump the seat (0.8.0: activity is left alone). No doing row.
CREATE PROCEDURE mill_join_touch(
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_joined TINYINT DEFAULT 0;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_lock BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  -- Lock order (card 1113): the seat exclusive before the joined check (IF EXISTS in a routine
  -- reads shared, and the UPDATE below then wanted the row exclusive).
  SELECT id INTO v_lock FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF v_desk IS NOT NULL AND EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    UPDATE seat SET updated = v_ts WHERE desk_id = v_desk;
    SET v_joined = 1;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_ts AS updated, IF(v_joined = 1, v_desk, NULL) AS desk_id;
END //

CREATE PROCEDURE mill_join_socket(
  IN p_desk VARCHAR(64),
  IN p_up   TINYINT
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF p_up = 1 THEN
    UPDATE seat SET time_connect = v_ts, time_disconnect = NULL WHERE desk_id = v_desk;
  ELSE
    UPDATE seat SET time_disconnect = v_ts WHERE desk_id = v_desk;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_ts AS updated, v_desk AS desk_id, p_up AS up;
END //

CREATE PROCEDURE mill_join_lan(
  IN p_desk VARCHAR(64),
  IN p_ip   VARCHAR(45)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  UPDATE seat SET lan_ip = LEFT(IFNULL(p_ip, ''), 45) WHERE desk_id = v_desk;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_ts AS updated, v_desk AS desk_id, p_ip AS lan_ip;
END //

-- #618 webhook wake. The URL is checked by the wall before arm (https, host
-- allowlist, no IP literal). updated = updated: arming is not a heartbeat.
CREATE PROCEDURE mill_join_wake_arm(
  IN p_desk VARCHAR(64),
  IN p_url  VARCHAR(512),
  IN p_key  VARCHAR(512),
  IN p_wake_on VARCHAR(16)
)
BEGIN
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_lock BIGINT UNSIGNED;
  IF IFNULL(p_url, '') = '' OR IFNULL(p_key, '') = '' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'wake arm: url and key required';
  END IF;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  -- Lock order (card 1113): the seat exclusive before the joined check (IF EXISTS in a routine
  -- reads shared, and the UPDATE below then wanted the row exclusive).
  SELECT id INTO v_lock FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF v_desk IS NULL OR NOT EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'wake: desk has not joined';
  END IF;
  IF IFNULL(p_wake_on, 'addressed') NOT IN ('all', 'addressed') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'wake arm: wake_on is all or addressed';
  END IF;
  UPDATE seat
     SET delivery_mode = 'webhook', endpoint_url = p_url, endpoint_key = p_key,
         wake_on = IFNULL(p_wake_on, 'addressed'), updated = updated
   WHERE desk_id = v_desk;
  SELECT TRIM(p_desk) AS desk, 'webhook' AS delivery_mode, IFNULL(p_wake_on, 'addressed') AS wake_on;
END //

CREATE PROCEDURE mill_join_wake_off(
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_lock BIGINT UNSIGNED;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  -- Lock order (card 1113): the seat exclusive before the joined check (IF EXISTS in a routine
  -- reads shared, and the UPDATE below then wanted the row exclusive).
  SELECT id INTO v_lock FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF v_desk IS NULL OR NOT EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'wake: desk has not joined';
  END IF;
  UPDATE seat
     SET delivery_mode = IF(delivery_mode = 'webhook', 'websocket', delivery_mode),
         endpoint_url = NULL, endpoint_key = NULL, wake_on = 'addressed', updated = updated
   WHERE desk_id = v_desk;
  SELECT TRIM(p_desk) AS desk, 'off' AS wake;
END //

-- What a reader may see: armed or not and the host. Never the path or the key.
CREATE PROCEDURE mill_join_wake_state(
  IN p_desk VARCHAR(64)
)
BEGIN
  SELECT TRIM(p_desk) AS desk,
         (j.delivery_mode = 'webhook' AND j.endpoint_url IS NOT NULL AND j.endpoint_key IS NOT NULL) AS armed,
         IF(j.endpoint_url IS NULL, NULL,
            SUBSTRING_INDEX(SUBSTRING_INDEX(SUBSTRING_INDEX(j.endpoint_url, '://', -1), '/', 1), ':', 1)) AS host,
         j.wake_on
    FROM seat j
    JOIN name d ON d.id = j.desk_id AND d.type = 'desk' AND d.deleted IS NULL
   WHERE d.name = TRIM(p_desk)
     AND (j.token_hash IS NOT NULL OR j.time_disconnect IS NOT NULL)
   LIMIT 1;
END //

-- POST time only: the one read that returns the key. A live, armed desk only.
CREATE PROCEDURE mill_join_wake_target(
  IN p_desk VARCHAR(64)
)
BEGIN
  SELECT j.endpoint_url, j.endpoint_key
    FROM seat j
    JOIN name d ON d.id = j.desk_id AND d.type = 'desk' AND d.deleted IS NULL
   WHERE d.name = TRIM(p_desk)
     AND (j.token_hash IS NOT NULL OR j.time_disconnect IS NOT NULL)
     AND j.delivery_mode = 'webhook'
     AND j.endpoint_url IS NOT NULL
     AND j.endpoint_key IS NOT NULL
   LIMIT 1;
END //

DELIMITER ;
