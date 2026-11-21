-- One lock per resource_id. desk_id NULL means free. p_project is not part of the lock.
-- Acquire locks that row and sets desk_id only when it is NULL.
-- Release requires the grant key hash, or the trust-matrix override. The row and activity id stay.
-- Activity roster is Office.

DROP PROCEDURE IF EXISTS mill_hold_upsert;
DROP PROCEDURE IF EXISTS mill_hold_delete;
DROP PROCEDURE IF EXISTS mill_hold_drop;
DROP FUNCTION IF EXISTS MILL_HOLD_KH;
DROP PROCEDURE IF EXISTS mill_hold_select;
DROP PROCEDURE IF EXISTS mill_hold_release_desk;
DROP PROCEDURE IF EXISTS mill_hold_release_other;
DROP PROCEDURE IF EXISTS mill_hold_free_transition;

DELIMITER //

-- Card 1267: the live key generation is the newest grant or hand-off on this hold.
CREATE FUNCTION MILL_HOLD_KH(p_id BIGINT UNSIGNED) RETURNS CHAR(64)
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  DECLARE v_kh CHAR(64) DEFAULT NULL;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_kh = NULL;
  SELECT JSON_UNQUOTE(JSON_EXTRACT(meta, '$.kh')) INTO v_kh
    FROM transition
   WHERE activity_type = 'hold' AND activity_id = p_id
     AND reason IN ('hold_grant', 'hold_refresh')
   ORDER BY id DESC LIMIT 1;
  RETURN v_kh;
END //

-- Card 1267: the take and its key hash (meta.kh) commit together. A held row
-- is refused for every caller, including its holder's desk. The row never expires.
CREATE PROCEDURE mill_hold_upsert(
  IN p_project  VARCHAR(64),
  IN p_desk     VARCHAR(64),
  IN p_resource VARCHAR(64),
  IN p_kh       CHAR(64),
  IN p_old_kh   CHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_res BIGINT UNSIGNED;
  DECLARE v_held BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_since DATETIME(6);
  DECLARE v_ok TINYINT DEFAULT 0;
  DECLARE v_new TINYINT DEFAULT 0;
  DECLARE v_move BIGINT UNSIGNED;
  DECLARE v_tok CHAR(64);
  DECLARE v_disc DATETIME(6);
  DECLARE v_race TINYINT DEFAULT 0;
  DECLARE v_errno INT;
  DECLARE v_msg TEXT;
  DECLARE v_saved CHAR(64) DEFAULT NULL;
  DECLARE v_from BIGINT UNSIGNED DEFAULT NULL;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_id = NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;

  IF p_kh IS NULL OR NOT REGEXP_LIKE(p_kh, '^[0-9a-f]{64}$', 'c') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: kh must be a sha256; use mill hold NAME';
  END IF;
  IF p_old_kh IS NOT NULL AND NOT REGEXP_LIKE(p_old_kh, '^[0-9a-f]{64}$', 'c') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: old key hash must be a sha256';
  END IF;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  -- Lock order: actor seat, then resource/hold. A reset/retire cannot race a take.
  SELECT id, token_hash, time_disconnect INTO v_move, v_tok, v_disc
    FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF v_tok IS NULL AND v_disc IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: desk has no live seat';
  END IF;
  -- First ever takes may collide while minting the resource or inserting the hold.
  -- InnoDB rolls the victim transaction back on 1213. The victim never retries a
  -- take: it re-reads under locks and records a refusal in a fresh transaction.
  BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
      GET DIAGNOSTICS CONDITION 1 v_errno = MYSQL_ERRNO, v_msg = MESSAGE_TEXT;
      IF @mill_req_tx IS NULL AND (v_errno IN (1062, 1213)
          OR (v_errno = 1644 AND v_msg = 'name insert lost a race')) THEN
        ROLLBACK;
        START TRANSACTION;
        SET v_race = 1;
      ELSE
        RESIGNAL;
      END IF;
    END;
    SET v_res = MILL_NAME_PUT('res', p_resource);
    -- Serialize even a never-held name on its existing name row, avoiding gap
    -- lock upgrades on hold. No extra mutex, column or process identity is needed.
    SELECT id INTO v_res FROM name WHERE id = v_res FOR UPDATE;
    SET v_id = NULL;
    SELECT id, desk_id, updated INTO v_id, v_held, v_since
      FROM hold WHERE resource_id = v_res FOR UPDATE;
    IF v_id IS NULL THEN
      INSERT INTO hold (updated, desk_id, resource_id)
      VALUES (v_ts, v_desk, v_res);
      SET v_id = LAST_INSERT_ID();
      SET v_new = 1;
      SET v_ok = 1;
    ELSEIF v_held IS NULL THEN
      UPDATE hold SET desk_id = v_desk, updated = v_ts
       WHERE id = v_id AND desk_id IS NULL;
      SET v_ok = (ROW_COUNT() = 1);
    ELSEIF p_old_kh IS NOT NULL THEN
      -- K25 hand-off: the presented key is spent and a new grant generation starts.
      SET v_saved = MILL_HOLD_KH(v_id);
      IF v_saved IS NOT NULL AND BINARY p_old_kh = BINARY v_saved THEN
        SET v_from = v_held;
        UPDATE hold SET desk_id = v_desk, updated = v_ts WHERE id = v_id;
        SET v_ok = 2;
      END IF;
    END IF;
  END;
  IF v_race = 1 THEN
    SET v_res = NULL;
    SELECT id INTO v_res FROM name WHERE type = 'res' AND name = TRIM(p_resource) FOR UPDATE;
    SET v_id = NULL;
    SELECT id, desk_id, updated INTO v_id, v_held, v_since
      FROM hold WHERE resource_id = v_res FOR UPDATE;
  END IF;
  IF v_ok = 2 THEN
    SET v_since = v_ts;
    SET v_held = v_desk;
    CALL mill_activity_put('hold', v_id, v_ts, v_desk, NULL, 'hold', NULL);
    CALL mill_watcher_put('hold', v_id, v_desk);
    CALL mill_transition_put('hold', v_id, 'held', 'held', 'hold_refresh', v_desk, 'holder',
      CONCAT('hold:', v_id, ':', v_desk), JSON_OBJECT('kh', p_kh, 'from', v_from));
  ELSEIF v_ok = 1 THEN
    SET v_since = v_ts;
    SET v_held = v_desk;
    CALL mill_activity_put('hold', v_id, v_ts, v_desk, 1, 'hold', NULL);
    CALL mill_watcher_put('hold', v_id, v_desk);
    CALL mill_transition_put('hold', v_id, IF(v_new = 1, 'no_row', 'free'), 'held',
      'hold_grant', v_desk, 'holder', CONCAT('hold:', v_id, ':', v_desk), JSON_OBJECT('kh', p_kh));
  ELSEIF v_id IS NOT NULL THEN
    CALL mill_transition_put('hold', v_id, 'any', 'refused', 'hold_refuse', v_desk,
      'waiter', CONCAT('hold:', v_id, ':', v_desk),
      JSON_OBJECT('op', 'take', 'asker', v_desk, 'holder', v_held));
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, v_res AS resource_id, v_held AS desk_id,
         IF(v_ok > 0, 1, 0) AS ok, IF(v_ok = 2, 1, 0) AS handoff, v_since AS since;
END //

-- Key-authorized release: any desk can present the capability. Locking the hold
-- serializes two drops and a drop racing a retake. The newest grant is the key
-- generation; an old key cannot release a newer grant, even for the same desk.
CREATE PROCEDURE mill_hold_drop(
  IN p_id BIGINT UNSIGNED,
  IN p_desk VARCHAR(64),
  IN p_kh CHAR(64)
)
BEGIN
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_holder BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_saved CHAR(64) DEFAULT NULL;
  DECLARE v_ts DATETIME(6);
  DECLARE v_ok TINYINT DEFAULT 0;
  DECLARE v_reason VARCHAR(64) DEFAULT 'wrong or spent release key';
  DECLARE v_move BIGINT UNSIGNED;
  DECLARE v_tok CHAR(64);
  DECLARE v_disc DATETIME(6);
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_saved = NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  SELECT id, token_hash, time_disconnect INTO v_move, v_tok, v_disc
    FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF v_tok IS NULL AND v_disc IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: desk has no live seat';
  END IF;
  SELECT desk_id INTO v_holder FROM hold WHERE id = p_id FOR UPDATE;
  IF v_holder IS NULL THEN
    SET v_reason = 'already free; release key is spent';
  ELSE
    SET v_saved = MILL_HOLD_KH(p_id);
    IF p_kh IS NOT NULL AND v_saved IS NOT NULL AND BINARY p_kh = BINARY v_saved THEN
      UPDATE hold SET desk_id = NULL, updated = v_ts WHERE id = p_id;
      CALL mill_activity_put('hold', p_id, v_ts, v_desk, NULL, 'drop', NULL);
      CALL mill_transition_put('hold', p_id, 'held', 'free', 'hold_drop', v_holder,
        'holder', CONCAT('hold:', p_id, ':', v_holder),
        IF(v_holder = v_desk, NULL, JSON_OBJECT('by', v_desk)));
      SET v_ok = 1;
      SET v_reason = '';
    END IF;
  END IF;
  IF v_ok = 0 THEN
    CALL mill_transition_put('hold', p_id, 'any', 'refused', 'hold_refuse', v_desk,
      'waiter', CONCAT('hold:', p_id, ':', v_desk),
      JSON_OBJECT('op', 'drop', 'asker', v_desk, 'holder', v_holder));
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, v_ok AS ok, IF(v_ok = 1, 'released', 'kept') AS op,
         v_reason AS reason, v_holder AS was_holder;
END //

-- Card 842: free every hold one desk owns (reset). The caller owns the transaction and has locked the
-- seat. Each freed hold gets its transition row in the same transaction (card 1207: transition is the hold's
-- history, no doing row; mill_hold_free_transition). Its activity row is stamped the way a drop stamps it
-- (roster kept). p_n = holds freed.
-- Card 1207: one transition row per hold p_desk holds now, for a release the book does itself (reset, desk
-- retire); the caller frees the holds right after, in its transaction. Python writes the transitions of a hold
-- or drop command (hold_activity.py); these releases have no command around them, so they are written here,
-- the way emit_drop / emit_force write them (desk_id = the holder; hold_force carries meta.by, the acting desk).
-- Edges H4 held->free hold_drop and H5 held->free hold_force (transition_edge).
CREATE PROCEDURE mill_hold_free_transition(
  IN p_desk BIGINT UNSIGNED,
  IN p_by   BIGINT UNSIGNED
)
BEGIN
  INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, role, join_key, meta)
  SELECT 'hold', h.id, 'held', 'free', IF(p_by <=> p_desk OR p_by IS NULL, 'hold_drop', 'hold_force'), p_desk,
         'holder', CONCAT('hold:', h.id, ':', p_desk),
         IF(p_by <=> p_desk OR p_by IS NULL, NULL, JSON_OBJECT('by', p_by))
    FROM hold h
   WHERE h.desk_id = p_desk
   ORDER BY h.id;
END //

CREATE PROCEDURE mill_hold_release_desk(
  IN p_desk BIGINT UNSIGNED,
  IN p_by   BIGINT UNSIGNED,
  IN p_ts   DATETIME(6),
  OUT p_n   INT
)
BEGIN
  DECLARE v_n INT DEFAULT 0;
  -- Lock the holds first (X), so the read under the INSERT below never upgrades a shared lock.
  -- The activity rows are read shared by that INSERT, then updated (card 1113 audit): left as is,
  -- because the only caller (mill_join_reset) holds the desk's seat exclusive first, so two
  -- releases of one desk queue on the seat.
  SELECT COUNT(*) INTO v_n FROM hold WHERE desk_id = p_desk FOR UPDATE;
  CALL mill_hold_free_transition(p_desk, p_by);
  UPDATE activity a JOIN hold h ON a.type = 'hold' AND a.id = h.id
     SET a.updated = p_ts, a.desk_id = p_by, a.act = 'drop'
   WHERE h.desk_id = p_desk;
  UPDATE hold SET desk_id = NULL, updated = p_ts WHERE desk_id = p_desk;
  SET p_n = ROW_COUNT();
END //


-- Card 931 / F223: release one hold owned by another desk. Auth (Admin, or high-trust stale)
-- is checked in Python before this call. The caller writes the hold_force transition (meta.by = p_by;
-- card 1207: no doing row); the holder's seat token is untouched. p_expect is the holder Python approved against; release
-- only when the row's desk_id still matches (check-then-act race guard). The age gate runs in
-- Python (hold_stale_days config).
CREATE PROCEDURE mill_hold_release_other(
  IN p_id     BIGINT UNSIGNED,
  IN p_by     VARCHAR(64),
  IN p_expect VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_by BIGINT UNSIGNED;
  DECLARE v_expect BIGINT UNSIGNED;
  DECLARE v_holder BIGINT UNSIGNED;
  DECLARE v_gone INT DEFAULT 0;
  DECLARE v_move BIGINT UNSIGNED;
  DECLARE v_roster BIGINT UNSIGNED;
  DECLARE v_tok CHAR(64);
  DECLARE v_disc DATETIME(6);
  DECLARE v_reason VARCHAR(64) DEFAULT 'kept';
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
  SET v_expect = MILL_NAME_GET('desk', p_expect);
  IF v_expect IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  -- Actor must have a live seat (same gate as mill_hold_delete).
  SELECT id, token_hash, time_disconnect INTO v_move, v_tok, v_disc FROM seat WHERE desk_id = v_by FOR UPDATE;
  IF v_tok IS NULL AND v_disc IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: desk has no live seat';
  END IF;
  SET v_holder = NULL;
  SELECT desk_id INTO v_holder FROM hold WHERE id = p_id FOR UPDATE;
  IF v_holder IS NULL THEN
    -- Freed between the Python read and this call: not held, so not 'kept'.
    SET v_gone = 0;
    SET v_reason = 'already free';
  ELSEIF v_holder <> v_expect THEN
    -- Holder changed since the Python check: refuse (do not drop the new holder).
    SET v_gone = 0;
    SET v_reason = 'holder changed';
  ELSE
    UPDATE hold
       SET desk_id = NULL, updated = v_ts
     WHERE id = p_id AND desk_id = v_expect;
    SET v_gone = ROW_COUNT();
    IF v_gone = 1 THEN
      CALL mill_activity_put('hold', p_id, v_ts, v_by, NULL, 'drop', NULL);
      SET v_roster = (SELECT roster_id FROM activity WHERE type = 'hold' AND id = p_id);
      SET v_reason = '';
    ELSE
      SET v_reason = 'kept';
    END IF;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id,
         IF(v_gone = 1, 'released', IF(v_reason = '' OR v_reason = 'kept', 'kept', v_reason)) AS op,
         IF(v_gone = 1, 1, 0) AS ok,
         v_holder AS was_holder, v_reason AS reason;
END //

CREATE PROCEDURE mill_hold_select(IN p_project VARCHAR(64))
BEGIN
  -- labels: JSON array of names in label order, from the label primary key (#274).
  -- Stable sort by id; holds list flat by default.
  SELECT h.type, h.id, h.created, h.updated, h.desk_id, h.resource_id,
         dn.name AS desk, dn.type AS desk_type,
         an.name AS roster, an.type AS roster_type,
         rn.name AS resource, rn.type AS resource_type,
         (SELECT CONCAT('[', GROUP_CONCAT(JSON_QUOTE(IFNULL((SELECT fdn.name FROM seat fs JOIN name fdn ON fdn.id = fs.desk_id AND fdn.deleted IS NULL WHERE fs.focus_label_id = ln.id LIMIT 1), ln.name)) ORDER BY l.ord, ln.name SEPARATOR ','), ']')
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
