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

-- #818: the seat is per-desk state (not an activity). doing rows are the
-- activity: append-only. 0.8.0 (the owner, 2026-10-26): a focus row (act focus: the desk's own --doing
-- text; act clear: its focus emptied) or a move row (any other act: a card or hold move by the desk, on
-- (on_type, on_id)). seat.doing_id names the desk's newest focus row, never a move row. A heartbeat
-- (connect, touch, socket, lan) writes no doing row and leaves activity alone.
-- mill_doing_insert is the one writer of a focus row. It locks the desk's seat row first (FOR UPDATE), so a
-- desk's focus writes, finish, clear and its moves are serialized, and sets seat.doing_id in the same UPDATE
-- (p_seen also stamps seat.updated, the desk's last-seen clock; NULL keeps it). A row that is not newer than
-- the seat's (an older clock) leaves seat.doing_id as it is. A watcher on the desk's current entry follows it.
CREATE PROCEDURE mill_doing_insert(
  IN  p_desk   BIGINT UNSIGNED,
  IN  p_roster BIGINT UNSIGNED,
  IN  p_text   VARCHAR(512),
  IN  p_ts     DATETIME(6),
  OUT p_id     BIGINT UNSIGNED
)
BEGIN
  DECLARE v_prev BIGINT UNSIGNED;
  DECLARE v_prev_at DATETIME(6);
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_prev_at = NULL;
  SET v_prev = NULL;
  SET v_prev_at = NULL;
  SELECT doing_id INTO v_prev FROM seat WHERE desk_id = p_desk FOR UPDATE;
  IF v_prev IS NOT NULL THEN
    SELECT created INTO v_prev_at FROM doing WHERE id = v_prev;
  END IF;
  INSERT INTO doing (created, desk_id, roster_id, text, act)
  VALUES (p_ts, p_desk, IFNULL(p_roster, 1), LEFT(IFNULL(p_text, ''), 512), IF(IFNULL(p_text, '') = '', 'clear', 'focus'));
  SET p_id = LAST_INSERT_ID();
  IF v_prev IS NULL OR p_ts > v_prev_at OR (p_ts = v_prev_at AND p_id > v_prev) THEN
    UPDATE seat SET doing_id = p_id, updated = updated WHERE desk_id = p_desk;
  END IF;
  IF v_prev IS NOT NULL THEN
    INSERT IGNORE INTO watcher (type, id, desk_id, hint)
    SELECT 'doing', p_id, w.desk_id, w.hint FROM watcher w
     WHERE w.type = 'doing' AND w.id = v_prev;
  END IF;
END //

-- 0.8.0: the one writer of a move row (the owner, 2026-10-26): a card status or volunteer change, or a hold take
-- or drop, by the acting desk p_desk on (p_on_type, p_on_id), with the act, the second desk (p_peer) and the
-- evidence (p_text). It locks the acting desk's seat row first, as mill_doing_insert does, and never touches
-- seat.doing_id: a move is not a focus. The item's own activity row carries the act (the caller's put).
-- A text over 512 characters is refused, never cut: where longer evidence goes is pending the owner.
CREATE PROCEDURE mill_doing_move(
  IN  p_desk    BIGINT UNSIGNED,
  IN  p_roster  BIGINT UNSIGNED,
  IN  p_on_type VARCHAR(8),
  IN  p_on_id   BIGINT UNSIGNED,
  IN  p_act     VARCHAR(16),
  IN  p_peer    BIGINT UNSIGNED,
  IN  p_text    VARCHAR(2000),
  IN  p_ts      DATETIME(6),
  OUT p_id      BIGINT UNSIGNED
)
BEGIN
  DECLARE v_seat BIGINT UNSIGNED;
  IF CHAR_LENGTH(IFNULL(p_text, '')) > 512 THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'evidence: over 512 characters; where longer evidence goes is pending the owner';
  END IF;
  SELECT id INTO v_seat FROM seat WHERE desk_id = p_desk FOR UPDATE;
  INSERT INTO doing (created, desk_id, roster_id, text, on_type, on_id, act, peer_id)
  VALUES (p_ts, p_desk, IFNULL(p_roster, 1), IFNULL(p_text, ''), p_on_type, p_on_id, p_act, NULLIF(p_peer, p_desk));
  SET p_id = LAST_INSERT_ID();
END //

CREATE PROCEDURE mill_doing_anchor(
  IN  p_desk BIGINT UNSIGNED,
  IN  p_text VARCHAR(512),
  OUT p_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET p_id = NULL;
  SET p_id = NULL;
  -- 0.8.0: the desk's focus is seat.doing_id.
  SELECT doing_id INTO p_id FROM seat WHERE desk_id = p_desk;
  IF p_id IS NULL THEN
    CALL mill_doing_insert(p_desk, 1, p_text, MILL_NOW(), p_id);
  END IF;
END //


-- Clock-out and reset end the current doing: an empty entry, unless the
-- current one is already empty. p_id is the entry that is current after;
-- p_roster is the roster on the ended entry's activity row (the new entry keeps it).
CREATE PROCEDURE mill_doing_clear(
  IN  p_desk   BIGINT UNSIGNED,
  IN  p_ts     DATETIME(6),
  OUT p_id     BIGINT UNSIGNED,
  OUT p_roster BIGINT UNSIGNED
)
BEGIN
  DECLARE v_text VARCHAR(512);
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET p_id = NULL;
  SET p_id = NULL;
  SET v_text = NULL;
  SELECT g.id, g.text INTO p_id, v_text
    FROM seat dn JOIN doing g ON g.id = dn.doing_id WHERE dn.desk_id = p_desk;
  SET p_roster = IFNULL((SELECT roster_id FROM activity WHERE type = 'doing' AND id = p_id), 1);
  IF p_id IS NULL OR IFNULL(v_text, '') <> '' THEN
    CALL mill_doing_insert(p_desk, p_roster, '', p_ts, p_id);
  END IF;
END //

CREATE PROCEDURE mill_join_upsert(
  IN p_project    VARCHAR(64),
  IN p_desk       VARCHAR(64),
  IN p_role       VARCHAR(64),
  IN p_token_hash CHAR(64),
  IN p_doing      VARCHAR(512)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_seat BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_have CHAR(64);
  DECLARE v_text VARCHAR(512);
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
  -- F186 (spin N03): hold the name row while writing the seat so a concurrent retire
  -- cannot leave a retired desk with a fresh token.
  SELECT id INTO v_desk FROM name WHERE id = v_desk FOR UPDATE;
  IF (SELECT deleted FROM name WHERE id = v_desk) IS NOT NULL THEN
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
  -- #818: a doing text on join is a new entry unless it is already the current one.
  SET v_id = NULL;
  SET v_text = NULL;
  SELECT g.id, g.text INTO v_id, v_text
    FROM seat dn JOIN doing g ON g.id = dn.doing_id WHERE dn.desk_id = v_desk;
  IF v_id IS NULL OR (p_doing IS NOT NULL AND v_text <> LEFT(p_doing, 512)) THEN
    CALL mill_doing_insert(v_desk, 1, p_doing, v_ts, v_id);
  END IF;
  INSERT IGNORE INTO member (name_id, desk_id) VALUES (1, v_desk);
  IF ROW_COUNT() = 1 THEN
    UPDATE name SET n = n + 1 WHERE id = 1;
  END IF;
  IF v_proj IS NOT NULL AND v_proj <> 1 AND v_proj <> 2 THEN
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
    INSERT IGNORE INTO member (name_id, desk_id) VALUES (@v_role, v_desk);
    IF ROW_COUNT() = 1 THEN
      UPDATE name SET n = n + 1 WHERE id = @v_role;
    END IF;
  END IF;
  CALL mill_activity_put('doing', v_id, v_ts, v_desk, 1, 'focus', NULL);
  CALL mill_watcher_put('doing', v_id, v_desk);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, v_desk AS desk_id, p_desk AS owner;
END //

-- Clock-out: the current doing ends (an empty entry), the seat stays.
CREATE PROCEDURE mill_join_delete(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_roster BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NOT NULL AND EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    CALL mill_doing_clear(v_desk, v_ts, v_id, v_roster);
    CALL mill_activity_put('doing', v_id, v_ts, v_desk, 1, 'clear', NULL);
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_desk AS owner, 'clocked-out' AS op;
END //

CREATE PROCEDURE mill_join_reset(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_roster BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
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
    CALL mill_doing_clear(v_desk, v_ts, v_id, v_roster);
    -- Keep the ended entry's activity roster (not 1/Office).
    CALL mill_activity_put('doing', v_id, v_ts, v_desk, v_roster, 'clear', NULL);
  END IF;
  -- Card 842: a reset desk owns no lock. Free its holds like a drop would. Reset takes no actor, so the
  -- drop rows name the reset desk itself.
  IF v_desk IS NOT NULL THEN
    CALL mill_hold_release_desk(v_desk, v_desk, v_ts, v_released);
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_desk AS owner, 'reset' AS op, v_released AS released;
END //

-- Seat plus the desk's current doing (newest entry). type/id name that entry.
CREATE PROCEDURE mill_join_select(IN p_project VARCHAR(64))
BEGIN
  DECLARE v_proj BIGINT UNSIGNED;
  SET v_proj = NULL;
  IF NOT (p_project IS NULL OR p_project = '') THEN
    SET v_proj = IFNULL(MILL_NAME_GET('roster', p_project), 0);
  END IF;
  SELECT 'doing' AS type, cur.id, h.created, h.updated, h.desk_id, h.token_hash,
         IFNULL(cur.text, '') AS doing,
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
  -- 0.8.0: the desk's focus is seat.doing_id (no sort; never a move row).
  LEFT JOIN doing cur ON cur.id = h.doing_id
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
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NULL OR NOT EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    ROLLBACK;
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'mill connect: desk has not joined';
  END IF;
  -- 0.8.0 (the owner, 2026-10-26): a heartbeat writes no doing row and leaves activity alone; seat.updated is
  -- the desk's last-seen clock. id is the desk's focus row (seat.doing_id; NULL before its first).
  UPDATE seat SET updated = v_ts WHERE desk_id = v_desk;
  SELECT doing_id INTO v_id FROM seat WHERE desk_id = v_desk;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, v_desk AS desk_id;
END //

-- A command that writes nothing else (#635): bump the seat (0.8.0: activity is left alone). No doing row.
CREATE PROCEDURE mill_join_touch(
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_id = NULL;
  IF v_desk IS NOT NULL AND EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    UPDATE seat SET updated = v_ts WHERE desk_id = v_desk;
    SELECT doing_id INTO v_id FROM seat WHERE desk_id = v_desk;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, v_desk AS desk_id;
END //

CREATE PROCEDURE mill_join_socket(
  IN p_desk VARCHAR(64),
  IN p_up   TINYINT
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_id = NULL;
  IF p_up = 1 THEN
    UPDATE seat SET time_connect = v_ts, time_disconnect = NULL WHERE desk_id = v_desk;
  ELSE
    UPDATE seat SET time_disconnect = v_ts WHERE desk_id = v_desk;
  END IF;
  IF v_desk IS NOT NULL AND EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    SELECT doing_id INTO v_id FROM seat WHERE desk_id = v_desk;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, v_desk AS desk_id, p_up AS up;
END //

CREATE PROCEDURE mill_join_lan(
  IN p_desk VARCHAR(64),
  IN p_ip   VARCHAR(45)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_id = NULL;
  UPDATE seat SET lan_ip = LEFT(IFNULL(p_ip, ''), 45) WHERE desk_id = v_desk;
  IF v_desk IS NOT NULL AND EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk AND (token_hash IS NOT NULL OR time_disconnect IS NOT NULL)) THEN
    SELECT doing_id INTO v_id FROM seat WHERE desk_id = v_desk;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, v_desk AS desk_id, p_ip AS lan_ip;
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
  IF IFNULL(p_url, '') = '' OR IFNULL(p_key, '') = '' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'wake arm: url and key required';
  END IF;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
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
  SET v_desk = MILL_NAME_GET('desk', p_desk);
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
