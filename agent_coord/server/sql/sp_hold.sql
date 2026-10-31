-- One lock per resource_id. desk_id NULL means free. p_project is not part of the lock.
-- Acquire locks that row and sets desk_id only when it is NULL.
-- Release sets desk_id NULL only when it is the owning desk. The row and activity id stay.
-- Activity roster is Office.

DROP PROCEDURE IF EXISTS mill_hold_upsert;
DROP PROCEDURE IF EXISTS mill_hold_delete;
DROP PROCEDURE IF EXISTS mill_hold_select;
DROP PROCEDURE IF EXISTS mill_hold_release_desk;
DROP PROCEDURE IF EXISTS mill_hold_release_other;

DELIMITER //

CREATE PROCEDURE mill_hold_upsert(
  IN p_project  VARCHAR(64),
  IN p_desk     VARCHAR(64),
  IN p_resource VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_res BIGINT UNSIGNED;
  DECLARE v_held BIGINT UNSIGNED;
  DECLARE v_n INT DEFAULT 0;
  DECLARE v_ok TINYINT DEFAULT 1;
  DECLARE v_move BIGINT UNSIGNED;
  DECLARE v_tok CHAR(64);
  DECLARE v_disc DATETIME(6);
  DECLARE v_refreshed TINYINT DEFAULT 0;
  DECLARE v_since DATETIME(6);
  DECLARE CONTINUE HANDLER FOR NOT FOUND BEGIN SET v_id = NULL; SET v_held = NULL; END;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_res = MILL_NAME_PUT('res', p_resource);
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  -- Lock order (F183): the taking desk's seat first, then the hold, as retire (name, seat, hold) does.
  -- F186 (spin D07): re-check a live token under the seat lock so a retire that commits after
  -- auth cannot still take a hold.
  SELECT id, token_hash, time_disconnect INTO v_move, v_tok, v_disc FROM seat WHERE desk_id = v_desk FOR UPDATE;
  -- F186 (spin D07): a reset or retired desk (token cleared, disconnect stamped) cannot take a hold.
  IF v_tok IS NULL AND v_disc IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: desk has no live seat';
  END IF;
  SET v_move = NULL;
  SET v_id = NULL;
  SET v_held = NULL;
  SELECT id, desk_id INTO v_id, v_held
    FROM hold
   WHERE resource_id = v_res
   FOR UPDATE;
  IF v_id IS NULL THEN
    INSERT INTO hold (updated, desk_id, resource_id)
    VALUES (v_ts, v_desk, v_res);
    SET v_id = LAST_INSERT_ID();
    SET v_held = v_desk;
    CALL mill_activity_put('hold', v_id, v_ts, v_desk, 1, 'hold', NULL);
    CALL mill_doing_move(v_desk, 1, 'hold', v_id, 'hold', NULL, '', v_ts, v_move);
    CALL mill_watcher_put('hold', v_id, v_desk);
    SET v_ok = 1;
    SET v_since = v_ts;
    SET v_refreshed = 0;
  ELSEIF v_held IS NULL THEN
    UPDATE hold
       SET desk_id = v_desk, updated = v_ts
     WHERE id = v_id AND desk_id IS NULL;
    SET v_n = ROW_COUNT();
    IF v_n = 1 THEN
      SET v_held = v_desk;
      CALL mill_activity_put('hold', v_id, v_ts, v_desk, 1, 'hold', NULL);
      CALL mill_doing_move(v_desk, 1, 'hold', v_id, 'hold', NULL, '', v_ts, v_move);
      CALL mill_watcher_put('hold', v_id, v_desk);
      SET v_ok = 1;
      SET v_since = v_ts;
      SET v_refreshed = 0;
    ELSE
      SET v_ok = 0;
      SELECT desk_id INTO v_held FROM hold WHERE id = v_id;
    END IF;
  ELSEIF v_held = v_desk THEN
    -- Same holder again refreshes the row (#194). It does not stack a second lock and writes no move row.
    -- Card 853: bump updated for #194, but report since as the take time (activity.updated),
    -- so a second hold keeps since and sets refreshed true.
    SELECT a.updated INTO v_since FROM activity a WHERE a.type = 'hold' AND a.id = v_id;
    IF v_since IS NULL THEN
      SELECT updated INTO v_since FROM hold WHERE id = v_id;
    END IF;
    UPDATE hold SET updated = v_ts WHERE id = v_id;
    SET v_ok = 1;
    SET v_refreshed = 1;
  ELSE
    SET v_ok = 0;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, v_res AS resource_id,
         IF(v_ok = 1, v_desk, v_held) AS desk_id, v_ok AS ok,
         v_refreshed AS refreshed, v_since AS since;
END //

CREATE PROCEDURE mill_hold_delete(
  IN p_id   BIGINT UNSIGNED,
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_gone INT DEFAULT 0;
  DECLARE v_move BIGINT UNSIGNED;
  DECLARE v_roster BIGINT UNSIGNED;
  DECLARE v_tok CHAR(64);
  DECLARE v_disc DATETIME(6);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  SELECT id, token_hash, time_disconnect INTO v_move, v_tok, v_disc FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF v_tok IS NULL AND v_disc IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: desk has no live seat';
  END IF;
  UPDATE hold
     SET desk_id = NULL, updated = v_ts
   WHERE id = p_id AND desk_id = v_desk;
  SET v_gone = ROW_COUNT();
  IF v_gone = 1 THEN
    -- NULL roster: keep the hold's activity roster (not 1/Office).
    CALL mill_activity_put('hold', p_id, v_ts, v_desk, NULL, 'drop', NULL);
    SET v_roster = (SELECT roster_id FROM activity WHERE type = 'hold' AND id = p_id);
    CALL mill_doing_move(v_desk, v_roster, 'hold', p_id, 'drop', NULL, '', v_ts, v_move);
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, IF(v_gone = 1, 'released', 'kept') AS op, IF(v_gone = 1, 1, 0) AS ok;
END //

-- Card 842: free every hold one desk owns (reset). The caller owns the transaction and has locked the
-- seat. Each freed hold gets a drop move row by the acting desk p_by (C5; peer = the holder when another
-- desk acts) and its activity row is stamped the way a drop stamps it (roster kept). p_n = holds freed.
CREATE PROCEDURE mill_hold_release_desk(
  IN p_desk BIGINT UNSIGNED,
  IN p_by   BIGINT UNSIGNED,
  IN p_ts   DATETIME(6),
  OUT p_n   INT
)
BEGIN
  DECLARE v_n INT DEFAULT 0;
  -- Lock the holds first (X), so the read under the INSERT below never upgrades a shared lock.
  SELECT COUNT(*) INTO v_n FROM hold WHERE desk_id = p_desk FOR UPDATE;
  INSERT INTO doing (created, desk_id, roster_id, text, on_type, on_id, act, peer_id)
  SELECT p_ts, p_by, IFNULL(a.roster_id, 1), '', 'hold', h.id, 'drop', NULLIF(p_desk, p_by)
    FROM hold h LEFT JOIN activity a ON a.type = 'hold' AND a.id = h.id
   WHERE h.desk_id = p_desk
   ORDER BY h.id;
  UPDATE activity a JOIN hold h ON a.type = 'hold' AND a.id = h.id
     SET a.updated = p_ts, a.desk_id = p_by, a.act = 'drop'
   WHERE h.desk_id = p_desk;
  UPDATE hold SET desk_id = NULL, updated = p_ts WHERE desk_id = p_desk;
  SET p_n = ROW_COUNT();
END //


-- Card 931 / F223: release one hold owned by another desk. Auth (Admin, or high-trust stale)
-- is checked in Python before this call. The drop move row is by p_by with peer_id = the holder;
-- the holder's seat token is untouched. p_stale_days is accepted for the call signature / future
-- SQL-side checks; the age gate runs in Python today (hold_stale_days config).
CREATE PROCEDURE mill_hold_release_other(
  IN p_id   BIGINT UNSIGNED,
  IN p_by   VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_by BIGINT UNSIGNED;
  DECLARE v_holder BIGINT UNSIGNED;
  DECLARE v_gone INT DEFAULT 0;
  DECLARE v_move BIGINT UNSIGNED;
  DECLARE v_roster BIGINT UNSIGNED;
  DECLARE v_tok CHAR(64);
  DECLARE v_disc DATETIME(6);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_by = MILL_NAME_GET('desk', p_by);
  IF v_by IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  -- Actor must have a live seat (same gate as mill_hold_delete).
  SELECT id, token_hash, time_disconnect INTO v_move, v_tok, v_disc FROM seat WHERE desk_id = v_by FOR UPDATE;
  IF v_tok IS NULL AND v_disc IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: desk has no live seat';
  END IF;
  SET v_holder = NULL;
  SELECT desk_id INTO v_holder FROM hold WHERE id = p_id FOR UPDATE;
  IF v_holder IS NULL OR v_holder = v_by THEN
    SET v_gone = 0;
  ELSE
    UPDATE hold
       SET desk_id = NULL, updated = v_ts
     WHERE id = p_id AND desk_id = v_holder;
    SET v_gone = ROW_COUNT();
    IF v_gone = 1 THEN
      CALL mill_activity_put('hold', p_id, v_ts, v_by, NULL, 'drop', NULL);
      SET v_roster = (SELECT roster_id FROM activity WHERE type = 'hold' AND id = p_id);
      CALL mill_doing_move(v_by, v_roster, 'hold', p_id, 'drop', v_holder, '', v_ts, v_move);
    END IF;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, IF(v_gone = 1, 'released', 'kept') AS op, IF(v_gone = 1, 1, 0) AS ok,
         v_holder AS was_holder;
END //

CREATE PROCEDURE mill_hold_select(IN p_project VARCHAR(64))
BEGIN
  -- labels: JSON array of names in label order, from the label primary key (#274).
  -- Stable sort by id; holds list flat by default.
  SELECT h.type, h.id, h.created, h.updated, h.desk_id, h.resource_id,
         dn.name AS desk, dn.type AS desk_type,
         an.name AS roster, an.type AS roster_type,
         rn.name AS resource, rn.type AS resource_type,
         (SELECT CONCAT('[', GROUP_CONCAT(JSON_QUOTE(ln.name) ORDER BY l.ord, ln.name SEPARATOR ','), ']')
            FROM label l JOIN name ln ON ln.id = l.name_id
           WHERE l.type = 'hold' AND l.id = h.id) AS labels
    FROM hold h
    LEFT JOIN activity a ON a.type = 'hold' AND a.id = h.id
    LEFT JOIN name dn ON dn.id = h.desk_id
    LEFT JOIN name an ON an.id = a.roster_id
    LEFT JOIN name rn ON rn.id = h.resource_id
   ORDER BY h.id;
END //

DELIMITER ;
