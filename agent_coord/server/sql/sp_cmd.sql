-- #867 (0.7.18): the server calls procedures only for card moves and the last raw
-- writers. On today's tables, with the frozen L1 (card 868) names and arguments
-- where L1 has one; the rest are today-only and go away with the 0.8.0 schema.
--
-- Card guards run here, under the card's row lock, in the caller's transaction:
-- no START TRANSACTION / COMMIT (call() commits, request_tx owns a --doing run).
-- A refusal SIGNALs 'card:<code>[:<arg>]' (MESSAGE_TEXT holds 128 characters);
-- the server writes the desk's line for the code (rpc._card_refusal).
-- Desk args are ids: the server passes MILL_DESK_ID(name) inside the same CALL.

DROP FUNCTION IF EXISTS MILL_DESK_ID;
DROP FUNCTION IF EXISTS MILL_CARD_ADMIN;
DROP FUNCTION IF EXISTS MILL_CARD_MOVES;
DROP FUNCTION IF EXISTS mill_sp_version;
DROP PROCEDURE IF EXISTS mill_card_write;
DROP PROCEDURE IF EXISTS cmd_claim;
DROP PROCEDURE IF EXISTS cmd_unclaim;
DROP PROCEDURE IF EXISTS cmd_pass;
DROP PROCEDURE IF EXISTS cmd_card_accept;
DROP PROCEDURE IF EXISTS cmd_push_put_back;
DROP PROCEDURE IF EXISTS cmd_push_mark;
DROP PROCEDURE IF EXISTS cmd_push_sent;
DROP PROCEDURE IF EXISTS mill_read_cursor;
DROP PROCEDURE IF EXISTS cmd_read_upto;
DROP PROCEDURE IF EXISTS mill_todo_select_rosters;
DROP PROCEDURE IF EXISTS mill_todo_select_retired;
DROP PROCEDURE IF EXISTS cmd_invite_create;
DROP PROCEDURE IF EXISTS cmd_invite_enable;
DROP PROCEDURE IF EXISTS cmd_invite_ttl;
DROP PROCEDURE IF EXISTS cmd_invite_revoke;
DROP PROCEDURE IF EXISTS cmd_invite_join_record;
DROP PROCEDURE IF EXISTS mill_hello;

DELIMITER //

-- A desk name to its id. NULL for no name (no who-may check), 0 for a name the
-- book does not hold (matches no volunteer, asker or Admin).
CREATE FUNCTION MILL_DESK_ID(p_name VARCHAR(64)) RETURNS BIGINT UNSIGNED
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  IF p_name IS NULL OR TRIM(p_name) = '' THEN
    RETURN NULL;
  END IF;
  RETURN IFNULL(MILL_NAME_GET('desk', p_name), 0);
END //

-- Admin is roster id 2, never its name (#722).
CREATE FUNCTION MILL_CARD_ADMIN(p_desk BIGINT UNSIGNED) RETURNS TINYINT
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  RETURN EXISTS (SELECT 1 FROM member WHERE name_id = 2 AND desk_id = p_desk);
END //

-- claim and unclaim move an open or claimed card. Else the refusal code
-- (moves:<command>:<status>[:noparent]); a parked card off every plan says so.
CREATE FUNCTION MILL_CARD_MOVES(p_cmd VARCHAR(8), p_st VARCHAR(8), p_card BIGINT UNSIGNED) RETURNS VARCHAR(128)
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  IF p_st IN ('open', 'claimed') THEN
    RETURN NULL;
  END IF;
  RETURN CONCAT('card:moves:', p_cmd, ':', p_st,
    IF(p_st = 'parked' AND NOT EXISTS (
         SELECT 1 FROM tree node
           JOIN tree anc ON anc.name_id = node.name_id AND anc.lft < node.lft AND anc.rgt > node.rgt
          WHERE node.type = 'todo' AND node.id = p_card), ':noparent', ''));
END //

-- The book's routines answer this pack's SQL stamp: 'sp-' and its first 12 hex (MILL_SQL_STAMP, #614).
-- (0.8.0 has no sp_deploy table: the owner, 2026-10-26.)
CREATE FUNCTION mill_sp_version() RETURNS CHAR(15) CHARSET ascii
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  DECLARE v CHAR(64) DEFAULT NULL;
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION SET v = NULL;
  SET v = MILL_SQL_STAMP();
  RETURN IF(v IS NULL, NULL, CONCAT('sp-', LEFT(v, 12)));
END //

-- mill_todo_write inside the caller's transaction: @mill_req_tx is set for the
-- call and put back after it, also when it fails. p_evidence rides on the
-- status change's move row in doing (0.8.0).
CREATE PROCEDURE mill_card_write(
  IN p_card     BIGINT UNSIGNED,
  IN p_desk     BIGINT UNSIGNED,
  IN p_status   VARCHAR(16),
  IN p_vol      VARCHAR(64),
  IN p_body     VARCHAR(4096),
  IN p_evidence VARCHAR(2000)
)
BEGIN
  DECLARE v_saved INT DEFAULT @mill_req_tx;
  DECLARE v_name VARCHAR(64);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    SET @mill_req_tx = v_saved;
    RESIGNAL;
  END;
  SELECT name INTO v_name FROM name WHERE id = p_desk;
  SET @mill_req_tx = 1;
  CALL mill_todo_write(p_card, v_name, p_status, IF(p_vol = '=', v_name, p_vol), p_body, p_evidence);
  SET @mill_req_tx = v_saved;
END //

-- L1: cmd_claim(p_desk, p_card). #325 kept (owner decision, v3 pending): p_take_over
-- takes a card another desk holds; p_prior is the volunteer the caller's take-over
-- line names ('' for none) and p_body the composed body (eta, msg, that line) or
-- NULL. The volunteer is read under the row lock: a take-over whose p_prior is not
-- the volunteer now is refused (card:stale_prior), so the line never names a
-- stale prior. Result: card, status, prior_volunteer.
CREATE PROCEDURE cmd_claim(
  IN p_desk      BIGINT UNSIGNED,
  IN p_card      BIGINT UNSIGNED,
  IN p_take_over TINYINT,
  IN p_prior     VARCHAR(64),
  IN p_body      VARCHAR(4096)
)
BEGIN
  DECLARE v_st VARCHAR(8);
  DECLARE v_vol BIGINT UNSIGNED;
  DECLARE v_vname VARCHAR(64);
  DECLARE v_held VARCHAR(64);
  DECLARE v_msg VARCHAR(128);
  DECLARE v_seat BIGINT UNSIGNED;
  -- Lock order (F183): seat then card.
  SELECT id INTO v_seat FROM seat WHERE desk_id = p_desk FOR UPDATE;
  SELECT t.status, t.assigned_id, n.name INTO v_st, v_vol, v_vname
    FROM todo t LEFT JOIN name n ON n.id = t.assigned_id
   WHERE t.id = p_card FOR UPDATE;
  IF v_st IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'claim: no such card';
  END IF;
  IF EXISTS (SELECT 1 FROM activity WHERE type = 'todo' AND id = p_card AND deleted IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card:deleted';
  END IF;
  -- Another desk's volunteer, or '' (none, or this desk).
  SET v_held = IF(v_vol IS NOT NULL AND NOT (v_vol <=> p_desk), v_vname, '');
  SET v_msg = MILL_CARD_MOVES('claim', v_st, p_card);
  IF v_msg IS NULL AND v_held <> '' AND NOT IFNULL(p_take_over, 0) THEN
    SET v_msg = CONCAT('card:claimed_by:', v_held);
  END IF;
  IF v_msg IS NULL AND IFNULL(p_take_over, 0) AND NOT (v_held <=> IFNULL(p_prior, '')) THEN
    SET v_msg = 'card:stale_prior';
  END IF;
  IF v_msg IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  END IF;
  CALL mill_card_write(p_card, p_desk, 'claimed', '=', p_body, NULL);
  -- Card 955: roster cards score (guarded; score failure never refuses claim).
  BEGIN
    DECLARE v_rid BIGINT UNSIGNED DEFAULT NULL;
    DECLARE CONTINUE HANDLER FOR SQLEXCEPTION BEGIN END;
    SELECT roster_id INTO v_rid FROM todo WHERE id = p_card;
    CALL mill_card_score_event(v_rid, 'claimed', NULL, NULL, NULL, NULL, NULL);
  END;
  SELECT p_card AS card, 'claimed' AS status, NULLIF(v_held, '') AS prior_volunteer;
END //

-- L1: cmd_unclaim(p_desk, p_card). The volunteer releases; the card is open again.
CREATE PROCEDURE cmd_unclaim(
  IN p_desk BIGINT UNSIGNED,
  IN p_card BIGINT UNSIGNED
)
BEGIN
  DECLARE v_st VARCHAR(8);
  DECLARE v_vol BIGINT UNSIGNED;
  DECLARE v_msg VARCHAR(128);
  DECLARE v_seat BIGINT UNSIGNED;
  SELECT id INTO v_seat FROM seat WHERE desk_id = p_desk FOR UPDATE;
  SELECT status, assigned_id INTO v_st, v_vol FROM todo WHERE id = p_card FOR UPDATE;
  IF v_st IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'unclaim: no such card';
  END IF;
  IF EXISTS (SELECT 1 FROM activity WHERE type = 'todo' AND id = p_card AND deleted IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card:deleted';
  END IF;
  SET v_msg = MILL_CARD_MOVES('unclaim', v_st, p_card);
  IF v_msg IS NULL AND v_vol IS NOT NULL AND p_desk IS NOT NULL AND v_vol <> p_desk THEN
    SET v_msg = 'card:who_may_unclaim';
  END IF;
  IF v_msg IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  END IF;
  CALL mill_card_write(p_card, p_desk, 'open', '-', NULL, NULL);
  SELECT p_card AS card, 'open' AS status;
END //

-- L1: cmd_pass(p_desk, p_card, p_step, p_evidence) -> card, status, was.
-- ship: claimed -> shipped, the volunteer. done: shipped -> done, the asker or Admin
-- (the volunteer when the asker does not resolve). back: done -> shipped, shipped ->
-- claimed (open with no volunteer), the asker or the volunteer. Evidence (0.8.0: on the
-- step's move row text in doing): ship keeps what it is given, done keeps it or the ship's when
-- none is given, any step back has none. Result evidence: the card's newest move row's, if a ship or done.
CREATE PROCEDURE cmd_pass(
  IN p_desk     BIGINT UNSIGNED,
  IN p_card     BIGINT UNSIGNED,
  IN p_step     VARCHAR(4),
  IN p_evidence VARCHAR(2000)
)
BEGIN
  DECLARE v_st VARCHAR(8);
  DECLARE v_vol, v_ask BIGINT UNSIGNED;
  DECLARE v_askname VARCHAR(64);
  DECLARE v_next VARCHAR(8);
  DECLARE v_msg VARCHAR(128);
  DECLARE v_ev VARCHAR(2000) DEFAULT NULLIF(TRIM(p_evidence), '');
  DECLARE v_seat BIGINT UNSIGNED;
  SELECT id INTO v_seat FROM seat WHERE desk_id = p_desk FOR UPDATE;
  SELECT t.status, t.assigned_id, an.id, an.name INTO v_st, v_vol, v_ask, v_askname
    FROM todo t LEFT JOIN name an ON an.id = t.creator_id
   WHERE t.id = p_card FOR UPDATE;
  IF v_st IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'pass: no such card';
  END IF;
  IF EXISTS (SELECT 1 FROM activity WHERE type = 'todo' AND id = p_card AND deleted IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card:deleted';
  END IF;
  IF p_step = 'ship' THEN
    IF v_st = 'shipped' THEN SET v_msg = 'card:already_shipped';
    ELSEIF v_st = 'done' THEN SET v_msg = 'card:already_done';
    ELSEIF v_st NOT IN ('open', 'claimed') THEN SET v_msg = CONCAT('card:not_shippable:', v_st);
    ELSEIF v_st = 'open' AND v_vol IS NULL THEN SET v_msg = 'card:claim_first';
    ELSEIF v_vol IS NOT NULL AND p_desk IS NOT NULL AND v_vol <> p_desk THEN SET v_msg = 'card:who_may_ship';
    ELSEIF v_vol IS NULL AND v_ask IS NOT NULL AND p_desk IS NOT NULL AND v_ask <> p_desk THEN SET v_msg = 'card:who_may_ship';
    ELSE SET v_next = 'shipped';
    END IF;
  ELSEIF p_step = 'done' THEN
    IF v_st <> 'shipped' THEN SET v_msg = CONCAT('card:done_not_shipped:', v_st);
    ELSEIF p_desk IS NOT NULL
       AND NOT (v_ask <=> p_desk OR (v_ask IS NULL AND v_vol <=> p_desk))
       AND NOT MILL_CARD_ADMIN(p_desk) THEN
      SET v_msg = LEFT(CONCAT('card:who_may_done:', IFNULL(v_askname, '')), 128);
    ELSE SET v_next = 'done';
    END IF;
  ELSEIF p_step = 'back' THEN
    IF v_st NOT IN ('shipped', 'done') THEN SET v_msg = CONCAT('card:back_status:', v_st);
    ELSEIF p_desk IS NOT NULL AND NOT (v_ask <=> p_desk) AND NOT (v_vol <=> p_desk) THEN
      SET v_msg = CONCAT('card:who_may_back:', IF(v_ask IS NULL, '', '1'));
    ELSE SET v_next = IF(v_st = 'done', 'shipped', IF(v_vol IS NOT NULL, 'claimed', 'open'));
    END IF;
  ELSE
    SET v_msg = 'pass: step is ship, done or back';
  END IF;
  IF v_msg IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  END IF;
  IF p_step = 'done' AND v_ev IS NULL THEN
    SET v_ev = (SELECT d.evidence FROM doing d
           WHERE d.on_type = 'todo' AND d.on_id = p_card AND d.act = 'ship'
           ORDER BY d.id DESC LIMIT 1);
  END IF;
  -- Card 955: capture claim/eta before mill_card_write clears claimed_at.
  BEGIN
    DECLARE v_rid BIGINT UNSIGNED DEFAULT NULL;
    DECLARE v_claimed DATETIME(6) DEFAULT NULL;
    DECLARE v_body VARCHAR(4096) DEFAULT NULL;
    DECLARE v_now DATETIME(6) DEFAULT MILL_NOW();
    DECLARE v_lead INT DEFAULT NULL;
    DECLARE v_eta_min INT DEFAULT NULL;
    DECLARE v_actual INT DEFAULT NULL;
    DECLARE v_eta_raw VARCHAR(64) DEFAULT NULL;
    DECLARE v_eta_at DATETIME(6) DEFAULT NULL;
    DECLARE v_doing INT DEFAULT NULL;
    DECLARE v_kind VARCHAR(16) DEFAULT NULL;
    SELECT roster_id, claimed_at, body INTO v_rid, v_claimed, v_body
      FROM todo WHERE id = p_card;
    IF p_step = 'ship' THEN
      SET v_kind = 'passed';
      IF v_claimed IS NOT NULL THEN
        SET v_lead = TIMESTAMPDIFF(MINUTE, v_claimed, v_now);
        SET v_actual = v_lead;
        SET v_eta_raw = JSON_UNQUOTE(JSON_EXTRACT(CAST(IFNULL(NULLIF(v_body, ''), '{}') AS JSON), '$.eta_at'));
        IF v_eta_raw IS NOT NULL AND v_eta_raw NOT IN ('null', '') THEN
          SET v_eta_at = CAST(REPLACE(LEFT(v_eta_raw, 32), 'T', ' ') AS DATETIME(6));
          IF v_eta_at IS NOT NULL THEN
            SET v_eta_min = TIMESTAMPDIFF(MINUTE, v_claimed, v_eta_at);
          END IF;
        END IF;
      END IF;
      SELECT IFNULL(SUM(TIMESTAMPDIFF(MINUTE, g.created, v_now)), 0) INTO v_doing
        FROM doing g
       WHERE g.on_type = 'todo' AND g.on_id = p_card AND g.act = 'focus'
         AND IFNULL(g.text, '') <> ''
         AND mill_doing_end(g.desk_id, g.id, g.on_type, g.on_id, g.created) IS NULL
         AND mill_doing_cleared(g.desk_id, g.id, g.created) IS NULL;
      IF IFNULL(v_doing, 0) = 0 THEN SET v_doing = NULL; END IF;
    ELSEIF p_step = 'done' THEN
      SET v_kind = 'shipped';
    END IF;
    SET @mill_card_score_rid = v_rid;
    SET @mill_card_score_kind = v_kind;
    SET @mill_card_score_lead = v_lead;
    SET @mill_card_score_eta = v_eta_min;
    SET @mill_card_score_actual = v_actual;
    SET @mill_card_score_doing = v_doing;
    SET @mill_card_score_now = v_now;
  END;
  CALL mill_card_write(p_card, p_desk, v_next, '', NULL, IF(p_step = 'back', NULL, v_ev));
  -- Card 955: score after the write; guarded so a score failure never refuses pass.
  BEGIN
    DECLARE CONTINUE HANDLER FOR SQLEXCEPTION BEGIN END;
    IF @mill_card_score_kind IS NOT NULL THEN
      CALL mill_card_score_event(
        @mill_card_score_rid, @mill_card_score_kind,
        @mill_card_score_lead, @mill_card_score_eta,
        @mill_card_score_actual, @mill_card_score_doing,
        @mill_card_score_now
      );
    END IF;
    SET @mill_card_score_rid = NULL, @mill_card_score_kind = NULL,
        @mill_card_score_lead = NULL, @mill_card_score_eta = NULL,
        @mill_card_score_actual = NULL, @mill_card_score_doing = NULL,
        @mill_card_score_now = NULL;
  END;
  SELECT p_card AS card, v_next AS status, v_st AS was,
         (SELECT IF(d.act IN ('ship', 'done'), d.evidence, NULL) FROM doing d
           WHERE d.on_type = 'todo' AND d.on_id = p_card AND d.act NOT IN ('focus', 'clear', 'finish')
           ORDER BY d.id DESC LIMIT 1) AS evidence;
END //

-- L1: cmd_card_accept(p_desk, p_card, p_done_when) -> card, done_when. The asker or
-- Admin sets the acceptance line; blank clears it; a done card refuses.
CREATE PROCEDURE cmd_card_accept(
  IN p_desk      BIGINT UNSIGNED,
  IN p_card      BIGINT UNSIGNED,
  IN p_done_when VARCHAR(1000)
)
BEGIN
  DECLARE v_st VARCHAR(8);
  DECLARE v_ask BIGINT UNSIGNED;
  DECLARE v_text VARCHAR(1000) DEFAULT NULLIF(TRIM(p_done_when), '');
  SELECT status, creator_id INTO v_st, v_ask FROM todo WHERE id = p_card FOR UPDATE;
  IF v_st IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'done-when: no such card';
  END IF;
  IF v_st = 'done' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card:done_when_done';
  END IF;
  IF p_desk IS NOT NULL AND NOT (v_ask <=> p_desk) AND NOT MILL_CARD_ADMIN(p_desk) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card:who_may_done_when';
  END IF;
  UPDATE todo SET done_when = v_text WHERE id = p_card;
  SELECT p_card AS card, v_text AS done_when;
END //

-- Today only (L1 has cmd_push_missed(p_push)): a sent row waits again with the
-- frame's idem key stamped into its payload (the stored row has none).
CREATE PROCEDURE cmd_push_put_back(
  IN p_push    BIGINT UNSIGNED,
  IN p_payload JSON
)
BEGIN
  UPDATE push_queue SET outcome = 'missed', payload = p_payload WHERE id = p_push AND outcome = 'sent';
  SELECT ROW_COUNT() AS marked;
END //

-- Today only: a missed row becomes p_outcome (sent, hint, expired).
CREATE PROCEDURE cmd_push_mark(
  IN p_push    BIGINT UNSIGNED,
  IN p_outcome VARCHAR(8)
)
BEGIN
  UPDATE push_queue SET outcome = p_outcome WHERE id = p_push AND outcome = 'missed';
  SELECT ROW_COUNT() AS marked;
END //

-- L1: cmd_push_sent(p_desk, p_ids JSON). Deletes only this desk's rows (#831).
CREATE PROCEDURE cmd_push_sent(
  IN p_desk BIGINT UNSIGNED,
  IN p_ids  JSON
)
BEGIN
  DELETE p FROM push_queue p
    JOIN JSON_TABLE(p_ids, '$[*]' COLUMNS (id BIGINT UNSIGNED PATH '$')) j ON j.id = p.id
   WHERE p.desk_id = p_desk;
  SELECT ROW_COUNT() AS sent;
END //

-- Today only (0.8.0 reads letter_to.read_at): a desk's read cursor on one tree.
CREATE PROCEDURE mill_read_cursor(
  IN p_desk BIGINT UNSIGNED,
  IN p_tree BIGINT UNSIGNED
)
BEGIN
  SELECT IFNULL((SELECT last_id FROM tree_read WHERE desk_id = p_desk AND tree_id = p_tree), 0) AS last_id;
END //

-- Today only: move the cursor forward, never back.
CREATE PROCEDURE cmd_read_upto(
  IN p_desk BIGINT UNSIGNED,
  IN p_tree BIGINT UNSIGNED,
  IN p_last BIGINT UNSIGNED
)
BEGIN
  INSERT INTO tree_read (desk_id, tree_id, last_id) VALUES (p_desk, p_tree, p_last) AS new
    ON DUPLICATE KEY UPDATE last_id = GREATEST(tree_read.last_id, new.last_id);
END //

-- Today only: cards on these rosters (JSON id list), newest first; retired cards off.
CREATE PROCEDURE mill_todo_select_rosters(
  IN p_ids    JSON,
  IN p_status VARCHAR(16)
)
BEGIN
  SELECT t.type, t.id, t.created, t.updated, t.updated_id, t.roster_id, t.creator_id,
         t.status, t.assigned_id, t.body,
         an.name AS roster, an.type AS roster_type, cn.name AS creator, cn.type AS creator_type,
         sn.name AS assigned, sn.type AS assigned_type, un.name AS updated_by, un.type AS updated_by_type,
         t.done_when,
         (SELECT IF(d.act IN ('ship', 'done'), d.evidence, NULL) FROM doing d
           WHERE d.on_type = 'todo' AND d.on_id = t.id AND d.act NOT IN ('focus', 'clear', 'finish')
           ORDER BY d.id DESC LIMIT 1) AS evidence
    FROM todo t
    JOIN JSON_TABLE(p_ids, '$[*]' COLUMNS (id BIGINT UNSIGNED PATH '$')) j ON j.id = t.roster_id
    LEFT JOIN name an ON an.id = t.roster_id
    LEFT JOIN name cn ON cn.id = t.creator_id
    LEFT JOIN name sn ON sn.id = t.assigned_id
    LEFT JOIN name un ON un.id = t.updated_id
   WHERE (IFNULL(p_status, '') = '' OR t.status = p_status)
     AND NOT EXISTS (SELECT 1 FROM activity ra
                      WHERE ra.type = 'todo' AND ra.id = t.id AND ra.deleted IS NOT NULL)
   ORDER BY t.updated DESC;
END //

-- Today only: one roster's retired cards (mill reclaim lists them).
CREATE PROCEDURE mill_todo_select_retired(IN p_roster BIGINT UNSIGNED)
BEGIN
  SELECT t.id, t.status, t.body, t.creator_id, t.assigned_id, cn.name AS creator, sn.name AS assigned
    FROM todo t
    JOIN activity a ON a.type = 'todo' AND a.id = t.id AND a.deleted IS NOT NULL
    LEFT JOIN name cn ON cn.id = t.creator_id
    LEFT JOIN name sn ON sn.id = t.assigned_id
   WHERE t.roster_id = p_roster
   ORDER BY t.id;
END //

-- L1: cmd_invite_create(p_key, p_hash, p_label, p_by, p_ttl). Invite times are UTC
-- (the door compares them with its UTC clock). NULL ttl never expires. Result: n.
CREATE PROCEDURE cmd_invite_create(
  IN p_key   VARCHAR(16),
  IN p_hash  CHAR(64),
  IN p_label VARCHAR(64),
  IN p_by    VARCHAR(64),
  IN p_ttl   INT
)
BEGIN
  INSERT INTO mill_invite (key_id, token_hash, label, created_by, ttl_seconds, expires_at, enabled_at)
  VALUES (p_key, p_hash, p_label, p_by, p_ttl,
          IF(p_ttl IS NULL, NULL, UTC_TIMESTAMP(6) + INTERVAL p_ttl SECOND), NULL);
  SELECT ROW_COUNT() AS n;
END //

-- L1: cmd_invite_enable(p_key). n = 0 when revoked or already enabled.
CREATE PROCEDURE cmd_invite_enable(IN p_key VARCHAR(16))
BEGIN
  UPDATE mill_invite SET enabled_at = UTC_TIMESTAMP(6)
   WHERE key_id = p_key AND revoked_at IS NULL AND enabled_at IS NULL;
  SELECT ROW_COUNT() AS n;
END //

-- L1: cmd_invite_ttl(p_key, p_ttl). NULL ttl never expires. n = 0 when revoked.
CREATE PROCEDURE cmd_invite_ttl(
  IN p_key VARCHAR(16),
  IN p_ttl INT
)
BEGIN
  UPDATE mill_invite
     SET ttl_seconds = p_ttl,
         expires_at = IF(p_ttl IS NULL, NULL, UTC_TIMESTAMP(6) + INTERVAL p_ttl SECOND)
   WHERE key_id = p_key AND revoked_at IS NULL;
  SELECT ROW_COUNT() AS n;
END //

-- L1: cmd_invite_revoke(p_key). n = 0 when already revoked.
CREATE PROCEDURE cmd_invite_revoke(IN p_key VARCHAR(16))
BEGIN
  UPDATE mill_invite SET revoked_at = UTC_TIMESTAMP(6) WHERE key_id = p_key AND revoked_at IS NULL;
  SELECT ROW_COUNT() AS n;
END //

-- Today only (L1's cmd_invite_join takes the token hash; the admin join action
-- names the key): attribute a join to a key, once.
CREATE PROCEDURE cmd_invite_join_record(
  IN p_key      VARCHAR(16),
  IN p_party    VARCHAR(16),
  IN p_party_id VARCHAR(64)
)
BEGIN
  INSERT IGNORE INTO mill_invite_join (key_id, party, party_id) VALUES (p_key, p_party, p_party_id);
  SELECT ROW_COUNT() AS n;
END //

-- L1: mill_hello(p_client, p_mode) -> status, office, client, message. The client's
-- SP stamp against the office's (mill_sp_version). 'ok' on a match; else 'warn'
-- with the line, or SIGNAL when p_mode is 'refuse'.
CREATE PROCEDURE mill_hello(
  IN p_client VARCHAR(15),
  IN p_mode   VARCHAR(6)
)
BEGIN
  DECLARE v_office CHAR(15) DEFAULT mill_sp_version();
  DECLARE v_msg VARCHAR(128);
  IF v_office IS NOT NULL AND p_client IS NOT NULL AND v_office = p_client THEN
    SELECT 'ok' AS status, v_office AS office, p_client AS client, '' AS message;
  ELSE
    SET v_msg = CONCAT('sp stamp: office ', IFNULL(v_office, 'none'), ', client ', IFNULL(p_client, 'none'),
                       '; run ', 'mill install sql --apply');
    IF p_mode = 'refuse' THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    SELECT 'warn' AS status, v_office AS office, p_client AS client, v_msg AS message;
  END IF;
END //

DELIMITER ;
