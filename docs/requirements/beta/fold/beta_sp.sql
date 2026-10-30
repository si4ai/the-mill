-- the-mill beta routines. One command = one CALL: guards and writes in one transaction, a small result.
-- Public (granted to the app user): cmd_*, uc_*, mill_span, mill_hello, mill_sp_version. Internal: mill_i_*, sp_*.
-- A refusal is SQLSTATE 45000 with a plain message; the caller shows it as is. No routine reads a user variable.
-- Lock order: desk -> room -> card (parent before child, then by id) -> hold -> letter_to -> push.
-- Signatures and result shapes are frozen in the beta notes (FROZEN_SIGNATURES); change them only with L2 and L3.
DELIMITER //

-- ---------------------------------------------------------------- internals
DROP FUNCTION IF EXISTS mill_i_is_admin //
CREATE FUNCTION mill_i_is_admin(p_desk INT UNSIGNED) RETURNS TINYINT READS SQL DATA
  RETURN EXISTS (SELECT 1 FROM role_member WHERE role_id = 2 AND desk_id = p_desk) //

DROP FUNCTION IF EXISTS mill_i_is_member //
CREATE FUNCTION mill_i_is_member(p_room INT UNSIGNED, p_desk INT UNSIGNED) RETURNS TINYINT READS SQL DATA
  RETURN EXISTS (SELECT 1 FROM room_member WHERE room_id = p_room AND desk_id = p_desk AND left_at IS NULL) //

-- wake rows for one letter: every named recipient with a seat, and copied ones whose seat wakes on all
DROP PROCEDURE IF EXISTS mill_i_wake //
CREATE PROCEDURE mill_i_wake(IN p_letter BIGINT UNSIGNED)
BEGIN
  INSERT IGNORE INTO push (desk_id, letter_id, named)
    SELECT t.desk_id, t.letter_id, t.kind FROM letter_to t JOIN seat s ON s.desk_id = t.desk_id JOIN desk d ON d.id = t.desk_id
     WHERE t.letter_id = p_letter AND d.live = 1 AND (t.kind = 'named' OR s.wake_on = 'all');
END //

DROP PROCEDURE IF EXISTS mill_i_card_move //
CREATE PROCEDURE mill_i_card_move(IN p_card BIGINT UNSIGNED, IN p_desk INT UNSIGNED, IN p_from VARCHAR(8), IN p_to VARCHAR(8),
                                  IN p_vol INT UNSIGNED, IN p_evidence VARCHAR(2000))
BEGIN
  DECLARE v_ev BIGINT UNSIGNED;
  INSERT INTO card_event (card_id, desk_id, from_status, to_status, volunteer_id, evidence)
    VALUES (p_card, p_desk, p_from, p_to, IF(p_to IN ('claimed','shipped','done'), p_vol, NULL), NULLIF(TRIM(p_evidence), ''));
  SET v_ev = LAST_INSERT_ID();
  UPDATE card SET status = p_to, status_event_id = v_ev, volunteer_id = IF(p_to IN ('claimed','shipped','done'), p_vol, NULL),
         claimed_at = CASE WHEN p_to <> 'claimed' THEN NULL WHEN p_from = 'claimed' AND volunteer_id <=> p_vol THEN claimed_at ELSE NOW(6) END
   WHERE id = p_card;
  INSERT INTO activity (card_event_id) VALUES (v_ev);
  -- the volunteer and the asker hear about it (one wake per event and desk)
  INSERT IGNORE INTO push (desk_id, card_event_id)
    SELECT x.d, v_ev FROM (SELECT c.creator_id d FROM card c WHERE c.id = p_card UNION SELECT p_vol) x
      JOIN seat s ON s.desk_id = x.d JOIN desk k ON k.id = x.d WHERE x.d IS NOT NULL AND x.d <> p_desk AND k.live = 1;
END //

-- ---------------------------------------------------------------- version stamp
DROP PROCEDURE IF EXISTS mill_hello //
CREATE PROCEDURE mill_hello(IN p_client VARCHAR(15), IN p_mode VARCHAR(6))
BEGIN
  DECLARE v_msg VARCHAR(128);
  IF p_client <=> mill_sp_version() THEN
    SELECT 'ok' AS status, mill_sp_version() AS office;
  ELSEIF p_mode = 'refuse' THEN
    SET v_msg = CONCAT('sp version mismatch: office ', mill_sp_version(), ', client ', IFNULL(p_client, 'none'));
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  ELSE
    SELECT CONCAT('warn: office ', mill_sp_version(), ', client ', IFNULL(p_client, 'none')) AS status, mill_sp_version() AS office;
  END IF;
END //

-- ---------------------------------------------------------------- desks and presence
DROP PROCEDURE IF EXISTS cmd_desk_create //
CREATE PROCEDURE cmd_desk_create(IN p_name VARCHAR(64), IN p_token_hash CHAR(64))
BEGIN
  DECLARE v_id INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_name, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'desk: name required'; END IF;
  START TRANSACTION;
  INSERT INTO desk (name) VALUES (TRIM(p_name)); SET v_id = LAST_INSERT_ID();   -- desk_on_office puts it on the Office roster
  INSERT INTO seat (desk_id, token_hash) VALUES (v_id, p_token_hash);
  COMMIT;
  SELECT v_id AS desk;
END //

DROP PROCEDURE IF EXISTS uc_desk_by_token //
CREATE PROCEDURE uc_desk_by_token(IN p_token_hash CHAR(64))
BEGIN
  SELECT d.id AS desk, d.name, d.live IS NOT NULL AS live, mill_i_is_admin(d.id) AS admin
    FROM seat s JOIN desk d ON d.id = s.desk_id WHERE s.token_hash = p_token_hash AND p_token_hash IS NOT NULL;
END //

DROP PROCEDURE IF EXISTS uc_desk_by_name //
CREATE PROCEDURE uc_desk_by_name(IN p_name VARCHAR(64))
BEGIN
  SELECT id AS desk, name, live IS NOT NULL AS live, mill_i_is_admin(id) AS admin FROM desk WHERE name = p_name;
END //

-- retire a desk: release its holds, end its doing, drop its queue and token, then flip live (the hold FK refuses the
-- flip while a hold remains). The desk itself or Admin.
DROP PROCEDURE IF EXISTS cmd_retire //
CREATE PROCEDURE cmd_retire(IN p_by INT UNSIGNED, IN p_desk INT UNSIGNED)
BEGIN
  DECLARE v_live TINYINT; DECLARE v_doing BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF p_by <> p_desk AND NOT mill_i_is_admin(p_by) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: retire is the desk itself or Admin'; END IF;
  START TRANSACTION;
  SELECT live INTO v_live FROM desk WHERE id = p_desk FOR UPDATE;
  IF v_live IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'retire: no such live desk'; END IF;
  INSERT INTO hold_event (resource_id, desk_id, card_id, verb) SELECT resource_id, desk_id, card_id, 'release' FROM hold WHERE desk_id = p_desk;
  INSERT INTO activity (hold_event_id) SELECT id FROM hold_event WHERE desk_id = p_desk AND verb = 'release' AND id > IFNULL((SELECT MAX(hold_event_id) FROM activity), 0);
  DELETE FROM hold WHERE desk_id = p_desk;
  INSERT INTO doing (desk_id, text) VALUES (p_desk, ''); SET v_doing = LAST_INSERT_ID();
  INSERT INTO doing_now (desk_id, doing_id, wait_desk_id) VALUES (p_desk, v_doing, NULL)
    ON DUPLICATE KEY UPDATE doing_id = v_doing, wait_desk_id = NULL;
  INSERT INTO activity (doing_id) VALUES (v_doing);
  DELETE FROM push WHERE desk_id = p_desk;
  UPDATE seat SET token_hash = NULL, socket_at = NULL WHERE desk_id = p_desk;
  UPDATE desk SET live = NULL, retired_at = NOW(6) WHERE id = p_desk;
  COMMIT;
  SELECT p_desk AS retired;
END //

-- connect: present now, and the queue handed back. Rows stay until cmd_push_sent says the frame went out.
DROP PROCEDURE IF EXISTS cmd_connect //
CREATE PROCEDURE cmd_connect(IN p_desk INT UNSIGNED)
BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  UPDATE seat SET socket_at = NOW(6), last_seen = NOW(6) WHERE desk_id = p_desk;
  IF ROW_COUNT() = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'connect: desk has no seat'; END IF;
  CALL mill_i_push_age(p_desk);
  COMMIT;
  SELECT p.id AS push, p.letter_id AS letter, p.card_event_id AS card_event, p.named, p.created
    FROM push p WHERE p.desk_id = p_desk ORDER BY p.id LIMIT 500;
  SELECT n AS expired, since, last FROM push_expired WHERE desk_id = p_desk;
END //

DROP PROCEDURE IF EXISTS cmd_disconnect //
CREATE PROCEDURE cmd_disconnect(IN p_desk INT UNSIGNED)
BEGIN
  UPDATE seat SET socket_at = NULL, last_seen = NOW(6) WHERE desk_id = p_desk;
  SELECT ROW_COUNT() AS disconnected;
END //

-- heartbeat: lazy, writes at most once a minute per desk (the hot row stays cold)
DROP PROCEDURE IF EXISTS cmd_touch //
CREATE PROCEDURE cmd_touch(IN p_desk INT UNSIGNED)
BEGIN
  UPDATE seat SET last_seen = NOW(6) WHERE desk_id = p_desk AND (last_seen IS NULL OR last_seen < NOW(6) - INTERVAL 60 SECOND);
  SELECT ROW_COUNT() AS touched;
END //

DROP PROCEDURE IF EXISTS uc_here //
CREATE PROCEDURE uc_here()
BEGIN
  SELECT d.id AS desk, d.name, s.socket_at FROM seat s JOIN desk d ON d.id = s.desk_id WHERE s.socket_at IS NOT NULL ORDER BY d.name LIMIT 500;
  SELECT d.id AS desk, d.name, s.last_seen FROM seat s JOIN desk d ON d.id = s.desk_id
   WHERE s.socket_at IS NULL AND d.live = 1 AND s.last_seen IS NOT NULL ORDER BY s.last_seen DESC LIMIT 10;
END //

-- ---------------------------------------------------------------- wake queue (7 days)
DROP PROCEDURE IF EXISTS mill_i_push_age //
CREATE PROCEDURE mill_i_push_age(IN p_desk INT UNSIGNED)
BEGIN
  DECLARE v_cut DATETIME(6) DEFAULT NOW(6) - INTERVAL 7 DAY;
  INSERT INTO push_expired (desk_id, n, since, last)
    SELECT desk_id, COUNT(*), MIN(created), MAX(created) FROM push WHERE (p_desk IS NULL OR desk_id = p_desk) AND created < v_cut GROUP BY desk_id
    ON DUPLICATE KEY UPDATE n = push_expired.n + VALUES(n), last = GREATEST(push_expired.last, VALUES(last));
  DELETE FROM push WHERE (p_desk IS NULL OR desk_id = p_desk) AND created < v_cut;
END //

DROP PROCEDURE IF EXISTS sp_push_purge //
CREATE PROCEDURE sp_push_purge()
BEGIN
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  DELETE p FROM push p JOIN desk d ON d.id = p.desk_id WHERE d.live IS NULL;
  CALL mill_i_push_age(NULL);
  COMMIT;
END //

DROP PROCEDURE IF EXISTS cmd_push_sent //
CREATE PROCEDURE cmd_push_sent(IN p_desk INT UNSIGNED, IN p_ids JSON)
BEGIN   -- only the receiving desk's own rows
  DELETE p FROM push p JOIN JSON_TABLE(p_ids, '$[*]' COLUMNS (id BIGINT UNSIGNED PATH '$')) j ON j.id = p.id WHERE p.desk_id = p_desk;
  SELECT ROW_COUNT() AS sent;
END //

DROP PROCEDURE IF EXISTS cmd_push_missed //
CREATE PROCEDURE cmd_push_missed(IN p_desk INT UNSIGNED, IN p_push BIGINT UNSIGNED)
BEGIN
  UPDATE push SET attempts = LEAST(attempts + 1, 255) WHERE id = p_push AND desk_id = p_desk;
  SELECT ROW_COUNT() AS marked;
END //

-- ---------------------------------------------------------------- rosters and rooms
-- A roster is a room of kind roster. The creator is a member like any other; there is no lead.
DROP PROCEDURE IF EXISTS cmd_roster_create //
CREATE PROCEDURE cmd_roster_create(IN p_desk INT UNSIGNED, IN p_name VARCHAR(64), IN p_members JSON)
BEGIN
  DECLARE v_r INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_name, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'roster: name required'; END IF;
  START TRANSACTION;
  INSERT INTO room (kind, name) VALUES ('roster', TRIM(p_name)); SET v_r = LAST_INSERT_ID();
  INSERT INTO room_member (room_id, desk_id)
    SELECT v_r, j.id FROM JSON_TABLE(JSON_ARRAY_APPEND(IFNULL(p_members, JSON_ARRAY()), '$', p_desk), '$[*]' COLUMNS (id INT UNSIGNED PATH '$')) j
      JOIN desk d ON d.id = j.id AND d.live = 1 GROUP BY j.id;
  COMMIT;
  SELECT v_r AS roster, (SELECT COUNT(*) FROM room_member WHERE room_id = v_r) AS members;
END //

-- a plain discussion room, optionally inside a roster
DROP PROCEDURE IF EXISTS cmd_room_create //
CREATE PROCEDURE cmd_room_create(IN p_desk INT UNSIGNED, IN p_name VARCHAR(64), IN p_roster INT UNSIGNED, IN p_members JSON)
BEGIN
  DECLARE v_r INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_name, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'room: name required'; END IF;
  START TRANSACTION;
  INSERT INTO room (kind, name, roster_id, roster_kind) VALUES ('room', TRIM(p_name), p_roster, IF(p_roster IS NULL, NULL, 'roster'));
  SET v_r = LAST_INSERT_ID();
  INSERT INTO room_member (room_id, desk_id)
    SELECT v_r, j.id FROM JSON_TABLE(JSON_ARRAY_APPEND(IFNULL(p_members, JSON_ARRAY()), '$', p_desk), '$[*]' COLUMNS (id INT UNSIGNED PATH '$')) j
      JOIN desk d ON d.id = j.id AND d.live = 1 GROUP BY j.id;
  COMMIT;
  SELECT v_r AS room, (SELECT COUNT(*) FROM room_member WHERE room_id = v_r) AS members;
END //

-- add (p_join = 1) or remove (0) a member. A current member or Admin may; nobody leaves the Office roster.
DROP PROCEDURE IF EXISTS cmd_member //
CREATE PROCEDURE cmd_member(IN p_by INT UNSIGNED, IN p_room INT UNSIGNED, IN p_desk INT UNSIGNED, IN p_join TINYINT)
BEGIN
  DECLARE v_kind VARCHAR(8);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT kind INTO v_kind FROM room WHERE id = p_room AND retired_at IS NULL FOR UPDATE;
  IF v_kind IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'member: no such room'; END IF;
  IF p_room = 1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'member: every desk is on the Office roster'; END IF;
  IF NOT mill_i_is_member(p_room, p_by) AND NOT mill_i_is_admin(p_by) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: membership changes are by a member or Admin';
  END IF;
  IF p_join THEN
    INSERT INTO room_member (room_id, desk_id) SELECT p_room, id FROM desk WHERE id = p_desk AND live = 1
      ON DUPLICATE KEY UPDATE left_at = NULL;
    IF ROW_COUNT() = 0 AND NOT mill_i_is_member(p_room, p_desk) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'member: no such live desk'; END IF;
  ELSE
    UPDATE room_member SET left_at = NOW(6) WHERE room_id = p_room AND desk_id = p_desk AND left_at IS NULL;
  END IF;
  COMMIT;
  SELECT p_room AS room, p_desk AS desk, mill_i_is_member(p_room, p_desk) AS member;
END //

DROP PROCEDURE IF EXISTS uc_rooms //
CREATE PROCEDURE uc_rooms(IN p_desk INT UNSIGNED)
BEGIN
  SELECT r.id AS room, r.kind, r.name, r.roster_id AS roster,
         (SELECT COUNT(*) FROM room_member x WHERE x.room_id = r.id AND x.left_at IS NULL) AS members,
         (SELECT COUNT(*) FROM letter_to t WHERE t.desk_id = p_desk AND t.room_id = r.id AND t.read_at IS NULL) AS unread
    FROM room_member m JOIN room r ON r.id = m.room_id
   WHERE m.desk_id = p_desk AND m.left_at IS NULL AND r.retired_at IS NULL ORDER BY r.id = 1 DESC, r.kind, r.name LIMIT 500;
END //

-- ---------------------------------------------------------------- letters
-- send into a room. p_to NULL = every current member but the sender (a roster or the whole Office);
-- p_to = JSON array of desk ids = only those (each must be a current member; in the Office that is every desk).
DROP PROCEDURE IF EXISTS cmd_send //
CREATE PROCEDURE cmd_send(IN p_from INT UNSIGNED, IN p_room INT UNSIGNED, IN p_to JSON, IN p_body VARCHAR(4096), IN p_ask TINYINT)
BEGIN
  DECLARE v_id BIGINT UNSIGNED; DECLARE v_n INT; DECLARE v_want INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_body, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'send: empty letter'; END IF;
  IF NOT mill_i_is_member(IFNULL(p_room, 1), p_from) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'send: sender is not a current member of this room'; END IF;
  START TRANSACTION;
  INSERT INTO letter (sender_id, room_id, body) VALUES (p_from, IFNULL(p_room, 1), p_body); SET v_id = LAST_INSERT_ID();
  IF p_to IS NULL THEN
    INSERT INTO letter_to (letter_id, desk_id, room_id, kind, asked)
      SELECT v_id, m.desk_id, m.room_id, 'named', IFNULL(p_ask, 0) FROM room_member m JOIN desk d ON d.id = m.desk_id
       WHERE m.room_id = IFNULL(p_room, 1) AND m.left_at IS NULL AND m.desk_id <> p_from AND d.live = 1;
  ELSE
    SELECT COUNT(DISTINCT j.id) INTO v_want FROM JSON_TABLE(p_to, '$[*]' COLUMNS (id INT UNSIGNED PATH '$')) j WHERE j.id <> p_from;
    INSERT INTO letter_to (letter_id, desk_id, room_id, kind, asked)
      SELECT v_id, m.desk_id, m.room_id, 'named', IFNULL(p_ask, 0)
        FROM (SELECT DISTINCT id FROM JSON_TABLE(p_to, '$[*]' COLUMNS (id INT UNSIGNED PATH '$')) j0) j
        JOIN room_member m ON m.room_id = IFNULL(p_room, 1) AND m.desk_id = j.id AND m.left_at IS NULL
        JOIN desk d ON d.id = m.desk_id AND d.live = 1
       WHERE j.id <> p_from;
    IF ROW_COUNT() <> v_want THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'send: a recipient is not a live current member of this room'; END IF;
  END IF;
  SELECT COUNT(*) INTO v_n FROM letter_to WHERE letter_id = v_id;
  IF v_n = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'send: no recipient'; END IF;
  CALL mill_i_wake(v_id);
  INSERT INTO activity (letter_id) VALUES (v_id);
  COMMIT;
  SELECT v_id AS letter, v_n AS recipients;
END //

-- reply in the parent's room. Every current member is a recipient: the parent's sender and p_named desks are named
-- (asked), the rest are copied. In the Office the reply goes to the parent's sender and p_named only.
DROP PROCEDURE IF EXISTS cmd_reply //
CREATE PROCEDURE cmd_reply(IN p_from INT UNSIGNED, IN p_parent BIGINT UNSIGNED, IN p_body VARCHAR(4096), IN p_named JSON)
BEGIN
  DECLARE v_id BIGINT UNSIGNED; DECLARE v_room INT UNSIGNED; DECLARE v_psender INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_body, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'reply: empty letter'; END IF;
  SELECT room_id, sender_id INTO v_room, v_psender FROM letter WHERE id = p_parent AND retired_at IS NULL;
  IF v_room IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'reply: no such letter'; END IF;
  IF NOT mill_i_is_member(v_room, p_from) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'reply: sender is not a current member of this room'; END IF;
  START TRANSACTION;
  INSERT INTO letter (sender_id, room_id, reply_to_id, body) VALUES (p_from, v_room, p_parent, p_body); SET v_id = LAST_INSERT_ID();
  INSERT INTO letter_to (letter_id, desk_id, room_id, kind, asked)
    SELECT v_id, m.desk_id, v_room, IF(m.desk_id = v_psender OR n.id IS NOT NULL, 'named', 'copied'), (m.desk_id = v_psender OR n.id IS NOT NULL)
      FROM room_member m JOIN desk d ON d.id = m.desk_id AND d.live = 1
      LEFT JOIN (SELECT DISTINCT id FROM JSON_TABLE(IFNULL(p_named, JSON_ARRAY()), '$[*]' COLUMNS (id INT UNSIGNED PATH '$')) j0) n ON n.id = m.desk_id
     WHERE m.room_id = v_room AND m.left_at IS NULL AND m.desk_id <> p_from
       AND (v_room <> 1 OR m.desk_id = v_psender OR n.id IS NOT NULL);
  CALL mill_i_wake(v_id);
  INSERT INTO activity (letter_id) VALUES (v_id);
  COMMIT;
  SELECT v_id AS letter, (SELECT COUNT(*) FROM letter_to WHERE letter_id = v_id) AS recipients;
END //

DROP PROCEDURE IF EXISTS cmd_mark //
CREATE PROCEDURE cmd_mark(IN p_desk INT UNSIGNED, IN p_letter BIGINT UNSIGNED)
BEGIN
  UPDATE letter_to SET read_at = NOW(6) WHERE letter_id = p_letter AND desk_id = p_desk AND read_at IS NULL;
  SELECT ROW_COUNT() AS marked;
END //

-- mark a room read up to a letter (what 0.7 kept as a second cursor in tree_read): one read state
DROP PROCEDURE IF EXISTS cmd_mark_room //
CREATE PROCEDURE cmd_mark_room(IN p_desk INT UNSIGNED, IN p_room INT UNSIGNED, IN p_upto BIGINT UNSIGNED)
BEGIN
  UPDATE letter_to SET read_at = NOW(6) WHERE desk_id = p_desk AND room_id = p_room AND letter_id <= p_upto AND read_at IS NULL;
  SELECT ROW_COUNT() AS marked;
END //

DROP PROCEDURE IF EXISTS uc_unread //
CREATE PROCEDURE uc_unread(IN p_desk INT UNSIGNED)
BEGIN
  SELECT t.letter_id AS letter, s.name AS sender, t.room_id AS room, t.kind, t.asked, l.created, LEFT(l.body, 200) AS body
    FROM letter_to t JOIN letter l ON l.id = t.letter_id JOIN desk s ON s.id = l.sender_id
   WHERE t.desk_id = p_desk AND t.read_at IS NULL ORDER BY t.letter_id DESC LIMIT 50;
END //

-- the thread around a letter (its room's newest 30; in the Office, its reply chain) and mark what was shown read
DROP PROCEDURE IF EXISTS uc_thread //
CREATE PROCEDURE uc_thread(IN p_desk INT UNSIGNED, IN p_letter BIGINT UNSIGNED)
BEGIN
  DECLARE v_room INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  SELECT room_id INTO v_room FROM letter WHERE id = p_letter;
  IF v_room IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'thread: no such letter'; END IF;
  DROP TEMPORARY TABLE IF EXISTS mill_t_shown;
  IF v_room = 1 THEN
    CREATE TEMPORARY TABLE mill_t_shown (id BIGINT UNSIGNED PRIMARY KEY) ENGINE=MEMORY
      WITH RECURSIVE up (id, p, n) AS (SELECT id, reply_to_id, 0 FROM letter WHERE id = p_letter
                                       UNION ALL SELECT l.id, l.reply_to_id, n + 1 FROM letter l JOIN up ON l.id = up.p WHERE n < 30)
      SELECT id FROM up;
  ELSE
    CREATE TEMPORARY TABLE mill_t_shown (id BIGINT UNSIGNED PRIMARY KEY) ENGINE=MEMORY
      SELECT id FROM letter WHERE room_id = v_room ORDER BY id DESC LIMIT 30;
  END IF;
  START TRANSACTION;
  UPDATE letter_to t JOIN mill_t_shown s ON s.id = t.letter_id SET t.read_at = NOW(6) WHERE t.desk_id = p_desk AND t.read_at IS NULL;
  COMMIT;
  SELECT l.id AS letter, k.name AS sender, l.reply_to_id AS reply_to, l.created, l.body
    FROM mill_t_shown s JOIN letter l ON l.id = s.id JOIN desk k ON k.id = l.sender_id ORDER BY l.id;
  DROP TEMPORARY TABLE IF EXISTS mill_t_shown;
END //

-- ---------------------------------------------------------------- cards
DROP PROCEDURE IF EXISTS cmd_card //
CREATE PROCEDURE cmd_card(IN p_desk INT UNSIGNED, IN p_roster INT UNSIGNED, IN p_body VARCHAR(4096), IN p_done_when VARCHAR(1000),
                          IN p_from_letter BIGINT UNSIGNED, IN p_from_card BIGINT UNSIGNED, IN p_from_score INT UNSIGNED, IN p_parked TINYINT)
BEGIN
  DECLARE v_id BIGINT UNSIGNED; DECLARE v_ord BIGINT DEFAULT 0; DECLARE v_lock BIGINT UNSIGNED; DECLARE v_kind VARCHAR(8);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_body, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card: body required'; END IF;
  SELECT kind INTO v_kind FROM room WHERE id = IFNULL(p_roster, 1) AND retired_at IS NULL;
  IF v_kind IS NULL OR v_kind <> 'roster' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card: no such roster'; END IF;
  START TRANSACTION;
  IF p_from_card IS NOT NULL THEN
    SELECT id INTO v_lock FROM card WHERE id = p_from_card FOR UPDATE;     -- the parent row serializes its children's order
    IF v_lock IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card: no such parent card'; END IF;
    SELECT IFNULL(MAX(ord) + 1048576, 0) INTO v_ord FROM card WHERE from_card_id = p_from_card;
  END IF;
  INSERT INTO card (creator_id, roster_id, body, done_when, from_letter_id, from_card_id, from_score_id, ord)
    VALUES (p_desk, IFNULL(p_roster, 1), p_body, NULLIF(TRIM(p_done_when), ''), p_from_letter, p_from_card, p_from_score, v_ord);
  SET v_id = LAST_INSERT_ID();
  CALL mill_i_card_move(v_id, p_desk, NULL, IF(p_parked, 'parked', 'open'), NULL, NULL);
  COMMIT;
  SELECT v_id AS card, IF(p_parked, 'parked', 'open') AS status, v_ord AS ord;
END //

-- the asker (or Admin) sets the acceptance line while the card is not done
DROP PROCEDURE IF EXISTS cmd_card_accept //
CREATE PROCEDURE cmd_card_accept(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED, IN p_done_when VARCHAR(1000))
BEGIN
  DECLARE v_ask INT UNSIGNED; DECLARE v_st VARCHAR(8);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT creator_id, status INTO v_ask, v_st FROM card WHERE id = p_card AND retired_at IS NULL FOR UPDATE;
  IF v_ask IS NULL OR v_st = 'done' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'accept: card is done or gone'; END IF;
  IF p_desk <> v_ask AND NOT mill_i_is_admin(p_desk) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: done-when is the asker or Admin'; END IF;
  UPDATE card SET done_when = NULLIF(TRIM(p_done_when), '') WHERE id = p_card;
  COMMIT;
  SELECT id AS card, done_when FROM card WHERE id = p_card;
END //

-- claim: an open card, or one you already hold (no change). Parked, shipped, done or someone else's: refused.
DROP PROCEDURE IF EXISTS cmd_claim //
CREATE PROCEDURE cmd_claim(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED)
BEGIN
  DECLARE v_st VARCHAR(8); DECLARE v_vol INT UNSIGNED; DECLARE v_msg VARCHAR(200);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT status, volunteer_id INTO v_st, v_vol FROM card WHERE id = p_card AND retired_at IS NULL FOR UPDATE;
  IF v_st IS NULL THEN SET v_msg = 'claim: no such card';
  ELSEIF v_st = 'claimed' AND v_vol = p_desk THEN SET v_msg = NULL;
  ELSEIF v_st = 'claimed' THEN SET v_msg = CONCAT('claim: card is claimed by ', (SELECT name FROM desk WHERE id = v_vol), '; ask them to unclaim');
  ELSEIF v_st <> 'open' THEN SET v_msg = CONCAT('claim: card is ', v_st, '; only an open card is claimed');
  END IF;
  IF v_msg IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg; END IF;
  IF v_st = 'open' THEN CALL mill_i_card_move(p_card, p_desk, 'open', 'claimed', p_desk, NULL); END IF;
  COMMIT;
  SELECT p_card AS card, 'claimed' AS status, v_st AS was;
END //

DROP PROCEDURE IF EXISTS cmd_unclaim //
CREATE PROCEDURE cmd_unclaim(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED)
BEGIN
  DECLARE v_st VARCHAR(8); DECLARE v_vol INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT status, volunteer_id INTO v_st, v_vol FROM card WHERE id = p_card AND retired_at IS NULL FOR UPDATE;
  IF v_st IS NULL OR v_st <> 'claimed' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'unclaim: card is not claimed'; END IF;
  IF v_vol <> p_desk THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: unclaim is the volunteer'; END IF;
  CALL mill_i_card_move(p_card, p_desk, 'claimed', 'open', NULL, NULL);
  COMMIT;
  SELECT p_card AS card, 'open' AS status;
END //

-- pass: ship (claimed -> shipped, the volunteer), done (shipped -> done, the asker, the volunteer or Admin),
-- back (done -> shipped, shipped -> claimed; the asker or the volunteer). Evidence rides ship and done.
DROP PROCEDURE IF EXISTS cmd_pass //
CREATE PROCEDURE cmd_pass(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED, IN p_step VARCHAR(4), IN p_evidence VARCHAR(2000))
BEGIN
  DECLARE v_st VARCHAR(8); DECLARE v_vol, v_ask INT UNSIGNED; DECLARE v_next VARCHAR(8); DECLARE v_msg VARCHAR(200);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT status, volunteer_id, creator_id INTO v_st, v_vol, v_ask FROM card WHERE id = p_card AND retired_at IS NULL FOR UPDATE;
  IF v_st IS NULL THEN SET v_msg = 'pass: no such card';
  ELSEIF p_step = 'ship' THEN
    IF v_st = 'shipped' THEN SET v_msg = 'pass: already shipped; the asker accepts it with --done';
    ELSEIF v_st = 'done' THEN SET v_msg = 'pass: already done; --back steps it back to shipped';
    ELSEIF v_st <> 'claimed' THEN SET v_msg = 'claim first: only a claimed card ships';
    ELSEIF v_vol <> p_desk THEN SET v_msg = 'who-may: pass claimed->shipped is the volunteer';
    ELSE SET v_next = 'shipped'; END IF;
  ELSEIF p_step = 'done' THEN
    IF v_st <> 'shipped' THEN SET v_msg = CONCAT('pass --done: card is ', v_st, ', not shipped; nothing changed');
    -- the volunteer does not accept its own work; only when the asker is retired may it (card 789, #655), and Admin always (#19)
    ELSEIF NOT (p_desk = v_ask OR mill_i_is_admin(p_desk)
                OR (p_desk <=> v_vol AND NOT EXISTS (SELECT 1 FROM desk WHERE id = v_ask AND live = 1))) THEN
      SET v_msg = IF(EXISTS (SELECT 1 FROM desk WHERE id = v_ask AND live = 1), 'who-may: pass shipped->done is the asker or Admin',
                     'who-may: pass shipped->done is the asker; the asker is retired, so only the volunteer or Admin may');
    ELSE SET v_next = 'done'; END IF;
  ELSEIF p_step = 'back' THEN
    IF v_st NOT IN ('shipped','done') THEN SET v_msg = 'pass --back: only shipped or done steps back (unclaim releases a claim)';
    ELSEIF p_desk <> v_ask AND NOT (p_desk <=> v_vol) THEN SET v_msg = 'who-may: pass --back is the asker or the volunteer';
    ELSE SET v_next = IF(v_st = 'done', 'shipped', 'claimed'), p_evidence = NULL; END IF;
  ELSE SET v_msg = 'pass: step is ship, done or back';
  END IF;
  IF v_msg IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg; END IF;
  CALL mill_i_card_move(p_card, p_desk, v_st, v_next, v_vol, p_evidence);
  COMMIT;
  SELECT p_card AS card, v_next AS status, v_st AS was;
END //

-- park (open -> parked) or unpark (parked -> open)
DROP PROCEDURE IF EXISTS cmd_park //
CREATE PROCEDURE cmd_park(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED, IN p_park TINYINT)
BEGIN
  DECLARE v_st VARCHAR(8);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT status INTO v_st FROM card WHERE id = p_card AND retired_at IS NULL FOR UPDATE;
  IF p_park AND (v_st IS NULL OR v_st <> 'open') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'park: only an open card parks'; END IF;
  IF NOT p_park AND (v_st IS NULL OR v_st <> 'parked') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'unpark: card is not parked'; END IF;
  CALL mill_i_card_move(p_card, p_desk, v_st, IF(p_park, 'parked', 'open'), NULL, NULL);
  COMMIT;
  SELECT p_card AS card, IF(p_park, 'parked', 'open') AS status;
END //

-- retire a card (the asker or Admin); it keeps its history
DROP PROCEDURE IF EXISTS cmd_card_retire //
CREATE PROCEDURE cmd_card_retire(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED)
BEGIN
  DECLARE v_ask INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT creator_id INTO v_ask FROM card WHERE id = p_card AND retired_at IS NULL FOR UPDATE;
  IF v_ask IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'retire: no such card'; END IF;
  IF p_desk <> v_ask AND NOT mill_i_is_admin(p_desk) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: retire is the asker or Admin'; END IF;
  UPDATE card SET retired_at = NOW(6) WHERE id = p_card;
  COMMIT;
  SELECT p_card AS card, 'retired' AS status;
END //

-- ---------------------------------------------------------------- order: signed gapped ordinals, step 2^20
-- first (p_after = 0): MIN - step; last (p_after NULL): MAX + step; after a sibling: the midpoint. Only a middle insert
-- into an exhausted gap renumbers, and then only that parent's children (or that desk's focus list).
DROP PROCEDURE IF EXISTS mill_i_renumber_children //
CREATE PROCEDURE mill_i_renumber_children(IN p_parent BIGINT UNSIGNED)
BEGIN
  UPDATE card c JOIN (SELECT id, 1048576 * ROW_NUMBER() OVER (ORDER BY ord, id) r FROM card WHERE from_card_id = p_parent) x
         ON x.id = c.id SET c.ord = x.r;
END //

DROP PROCEDURE IF EXISTS cmd_move //
CREATE PROCEDURE cmd_move(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED, IN p_parent BIGINT UNSIGNED, IN p_after BIGINT UNSIGNED)
BEGIN
  DECLARE v_lo, v_hi, v_ord BIGINT; DECLARE v_n INT; DECLARE v_try INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF p_parent = p_card THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'move: a card cannot be its own parent'; END IF;
  START TRANSACTION;
  SELECT COUNT(*) INTO v_n FROM (SELECT id FROM card WHERE id IN (p_parent, p_card) AND retired_at IS NULL ORDER BY id FOR UPDATE) k;
  IF v_n <> IF(p_parent IS NULL, 1, 2) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'move: no such card or parent'; END IF;
  IF NOT (mill_i_is_admin(p_desk) OR EXISTS (SELECT 1 FROM card c JOIN room_member m ON m.room_id = c.roster_id AND m.desk_id = p_desk AND m.left_at IS NULL
                                             WHERE c.id = p_card)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: move is a member of the card''s roster or Admin';
  END IF;
  IF p_parent IS NULL THEN
    SET v_ord = 0;
  ELSEIF p_after IS NULL THEN
    SELECT IFNULL(MAX(ord) + 1048576, 0) INTO v_ord FROM card WHERE from_card_id = p_parent AND id <> p_card;
  ELSEIF p_after = 0 THEN
    SELECT IFNULL(MIN(ord) - 1048576, 0) INTO v_ord FROM card WHERE from_card_id = p_parent AND id <> p_card;
  ELSE
    again: LOOP
      SELECT ord INTO v_lo FROM card WHERE id = p_after AND from_card_id = p_parent;
      IF v_lo IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'move: --after is not a child of that parent'; END IF;
      SET v_hi = (SELECT MIN(ord) FROM card WHERE from_card_id = p_parent AND ord > v_lo AND id <> p_card);
      IF v_hi IS NULL THEN SET v_ord = v_lo + 1048576; LEAVE again; END IF;
      IF v_hi - v_lo >= 2 THEN SET v_ord = v_lo + (v_hi - v_lo) DIV 2; LEAVE again; END IF;
      IF v_try > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'move: no room after renumber'; END IF;
      CALL mill_i_renumber_children(p_parent); SET v_try = 1, v_lo = NULL;
    END LOOP;
  END IF;
  UPDATE card SET from_card_id = p_parent, from_letter_id = NULL, from_score_id = NULL, ord = v_ord WHERE id = p_card;
  COMMIT;
  SELECT p_card AS card, p_parent AS parent, v_ord AS ord, v_try AS renumbered;
END //

DROP PROCEDURE IF EXISTS cmd_rank //
CREATE PROCEDURE cmd_rank(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED, IN p_after BIGINT UNSIGNED)
BEGIN
  DECLARE v_lo, v_hi, v_ord BIGINT; DECLARE v_lock INT UNSIGNED; DECLARE v_try INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT id INTO v_lock FROM desk WHERE id = p_desk FOR UPDATE;            -- the list's mutex (not the hot seat row)
  IF p_after IS NULL THEN
    SELECT IFNULL(MAX(rank_ord) + 1048576, 0) INTO v_ord FROM focus WHERE desk_id = p_desk AND card_id <> p_card;
  ELSEIF p_after = 0 THEN
    SELECT IFNULL(MIN(rank_ord) - 1048576, 0) INTO v_ord FROM focus WHERE desk_id = p_desk AND card_id <> p_card;
  ELSE
    again: LOOP
      SELECT rank_ord INTO v_lo FROM focus WHERE desk_id = p_desk AND card_id = p_after;
      IF v_lo IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'rank: --after is not in your focus'; END IF;
      SET v_hi = (SELECT MIN(rank_ord) FROM focus WHERE desk_id = p_desk AND rank_ord > v_lo AND card_id <> p_card);
      IF v_hi IS NULL THEN SET v_ord = v_lo + 1048576; LEAVE again; END IF;
      IF v_hi - v_lo >= 2 THEN SET v_ord = v_lo + (v_hi - v_lo) DIV 2; LEAVE again; END IF;
      IF v_try > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'rank: no room after renumber'; END IF;
      UPDATE focus f JOIN (SELECT card_id, 1048576 * ROW_NUMBER() OVER (ORDER BY rank_ord, card_id) r FROM focus WHERE desk_id = p_desk) x
             ON x.card_id = f.card_id SET f.rank_ord = x.r WHERE f.desk_id = p_desk;
      SET v_try = 1, v_lo = NULL;
    END LOOP;
  END IF;
  INSERT INTO focus (desk_id, card_id, rank_ord) VALUES (p_desk, p_card, v_ord) ON DUPLICATE KEY UPDATE rank_ord = v_ord;
  COMMIT;
  SELECT p_card AS card, v_ord AS rank_ord;
END //

DROP PROCEDURE IF EXISTS cmd_tag //
CREATE PROCEDURE cmd_tag(IN p_desk INT UNSIGNED, IN p_card BIGINT UNSIGNED, IN p_tag VARCHAR(64))
BEGIN
  DECLARE v_tag INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_tag, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tag: name required'; END IF;
  START TRANSACTION;
  INSERT IGNORE INTO tag (name) VALUES (TRIM(p_tag));
  SELECT id INTO v_tag FROM tag WHERE name = TRIM(p_tag);
  INSERT IGNORE INTO card_tag (card_id, tag_id) VALUES (p_card, v_tag);
  COMMIT;
  SELECT p_card AS card, v_tag AS tag;
END //

-- ---------------------------------------------------------------- holds and doings
-- take a resource (created on first use). INSERT IGNORE on the key: no read-then-insert, no gap lock.
DROP PROCEDURE IF EXISTS cmd_hold //
CREATE PROCEDURE cmd_hold(IN p_desk INT UNSIGNED, IN p_resource VARCHAR(128), IN p_card BIGINT UNSIGNED)
BEGIN
  DECLARE v_res, v_holder INT UNSIGNED; DECLARE v_new INT; DECLARE v_msg VARCHAR(200);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_resource, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: resource required'; END IF;
  START TRANSACTION;
  INSERT IGNORE INTO resource (name) VALUES (TRIM(p_resource));
  SELECT id INTO v_res FROM resource WHERE name = TRIM(p_resource);
  INSERT IGNORE INTO hold (resource_id, desk_id, card_id) VALUES (v_res, p_desk, p_card);
  SET v_new = ROW_COUNT();
  SELECT desk_id INTO v_holder FROM hold WHERE resource_id = v_res;
  IF v_holder IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'hold: only a live desk holds'; END IF;
  IF v_holder <> p_desk THEN
    SET v_msg = CONCAT('hold: ', TRIM(p_resource), ' is held by ', (SELECT name FROM desk WHERE id = v_holder));
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  END IF;
  IF v_new = 1 THEN
    INSERT INTO hold_event (resource_id, desk_id, card_id, verb) VALUES (v_res, p_desk, p_card, 'take');
    INSERT INTO activity (hold_event_id) VALUES (LAST_INSERT_ID());
  END IF;
  COMMIT;
  SELECT v_res AS resource, v_new AS taken;
END //

DROP PROCEDURE IF EXISTS cmd_drop //
CREATE PROCEDURE cmd_drop(IN p_desk INT UNSIGNED, IN p_resource VARCHAR(128))
BEGIN
  DECLARE v_res INT UNSIGNED; DECLARE v_card BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT r.id, h.card_id INTO v_res, v_card FROM resource r JOIN hold h ON h.resource_id = r.id AND h.desk_id = p_desk
   WHERE r.name = TRIM(p_resource) FOR UPDATE;
  IF v_res IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'drop: not your hold'; END IF;
  DELETE FROM hold WHERE resource_id = v_res AND desk_id = p_desk;
  INSERT INTO hold_event (resource_id, desk_id, card_id, verb) VALUES (v_res, p_desk, v_card, 'drop');
  INSERT INTO activity (hold_event_id) VALUES (LAST_INSERT_ID());
  COMMIT;
  SELECT v_res AS resource, 1 AS dropped;
END //

DROP PROCEDURE IF EXISTS uc_holds //
CREATE PROCEDURE uc_holds()
BEGIN
  SELECT r.name AS resource, d.name AS holder, h.taken_at, h.card_id AS card, LEFT(c.body, 60) AS why
    FROM hold h JOIN resource r ON r.id = h.resource_id JOIN desk d ON d.id = h.desk_id LEFT JOIN card c ON c.id = h.card_id
   ORDER BY h.taken_at LIMIT 500;
END //

DROP PROCEDURE IF EXISTS cmd_doing //
CREATE PROCEDURE cmd_doing(IN p_desk INT UNSIGNED, IN p_text VARCHAR(512), IN p_on_card BIGINT UNSIGNED, IN p_on_letter BIGINT UNSIGNED,
                           IN p_wait_desk INT UNSIGNED, IN p_wait_card BIGINT UNSIGNED, IN p_why VARCHAR(200))
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  INSERT INTO doing (desk_id, text, on_card_id, on_letter_id, wait_desk_id, wait_card_id, waiting_why)
    VALUES (p_desk, IFNULL(p_text, ''), p_on_card, p_on_letter, p_wait_desk, p_wait_card, NULLIF(TRIM(p_why), ''));
  SET v_id = LAST_INSERT_ID();
  INSERT INTO doing_now (desk_id, doing_id, wait_desk_id) VALUES (p_desk, v_id, p_wait_desk)
    ON DUPLICATE KEY UPDATE doing_id = v_id, wait_desk_id = p_wait_desk;
  INSERT INTO activity (doing_id) VALUES (v_id);
  COMMIT;
  SELECT v_id AS doing;
END //

-- ---------------------------------------------------------------- consensus
-- open: a decision letter to every current member of a roster, and the vote it carries. Any member may open one.
DROP PROCEDURE IF EXISTS cmd_vote_open //
CREATE PROCEDURE cmd_vote_open(IN p_desk INT UNSIGNED, IN p_roster INT UNSIGNED, IN p_body VARCHAR(4096), IN p_choices VARCHAR(9), IN p_minutes INT UNSIGNED)
BEGIN
  DECLARE v_letter, v_vote BIGINT UNSIGNED; DECLARE v_kind VARCHAR(8); DECLARE v_deadline DATETIME(6);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF p_choices NOT IN ('yes_no','keep_drop') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: choices are yes_no or keep_drop'; END IF;
  IF p_minutes IS NULL OR p_minutes < 1 OR p_minutes > 43200 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: deadline is 1 to 43200 minutes away'; END IF;
  IF TRIM(IFNULL(p_body, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: the decision letter needs a body'; END IF;
  SELECT kind INTO v_kind FROM room WHERE id = p_roster AND retired_at IS NULL;
  IF v_kind IS NULL OR v_kind <> 'roster' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: a vote goes to a roster'; END IF;
  IF NOT mill_i_is_member(p_roster, p_desk) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: only a current member opens a vote'; END IF;
  SET v_deadline = NOW(6) + INTERVAL p_minutes MINUTE;
  START TRANSACTION;
  INSERT INTO letter (sender_id, room_id, body) VALUES (p_desk, p_roster, p_body); SET v_letter = LAST_INSERT_ID();
  INSERT INTO letter_to (letter_id, desk_id, room_id, kind, asked)
    SELECT v_letter, m.desk_id, p_roster, 'named', 1 FROM room_member m JOIN desk d ON d.id = m.desk_id AND d.live = 1
     WHERE m.room_id = p_roster AND m.left_at IS NULL AND m.desk_id <> p_desk;
  INSERT INTO vote (letter_id, room_id, opened_by, choices, deadline) VALUES (v_letter, p_roster, p_desk, p_choices, v_deadline);
  SET v_vote = LAST_INSERT_ID();
  CALL mill_i_wake(v_letter);
  INSERT INTO activity (letter_id) VALUES (v_letter);
  INSERT INTO activity (vote_id) VALUES (v_vote);
  COMMIT;
  SELECT v_vote AS vote, v_letter AS letter, v_deadline AS deadline;
END //

-- close one vote: count the ballots of current live members. Decided = a strict majority of the votes cast, with a
-- quorum of more than half the members; else tie or no_quorum, and needs_human = 1 (the glance shows it).
DROP PROCEDURE IF EXISTS mill_i_vote_close //
CREATE PROCEDURE mill_i_vote_close(IN p_vote BIGINT UNSIGNED)
BEGIN
  DECLARE v_room INT UNSIGNED; DECLARE v_choices VARCHAR(9); DECLARE v_voters, v_ballots, v_for, v_against INT; DECLARE v_out VARCHAR(9);
  SELECT room_id, choices INTO v_room, v_choices FROM vote WHERE id = p_vote AND closed_at IS NULL FOR UPDATE;
  IF v_room IS NOT NULL THEN
    SELECT COUNT(*) INTO v_voters FROM room_member m JOIN desk d ON d.id = m.desk_id AND d.live = 1 WHERE m.room_id = v_room AND m.left_at IS NULL;
    SELECT COUNT(*), IFNULL(SUM(b.choice IN ('yes','keep')), 0), IFNULL(SUM(b.choice IN ('no','drop')), 0) INTO v_ballots, v_for, v_against
      FROM ballot b JOIN room_member m ON m.room_id = b.room_id AND m.desk_id = b.desk_id AND m.left_at IS NULL
      JOIN desk d ON d.id = b.desk_id AND d.live = 1 WHERE b.vote_id = p_vote;
    SET v_out = CASE WHEN v_ballots * 2 <= v_voters THEN 'no_quorum' WHEN v_for = v_against THEN 'tie'
                     WHEN v_for > v_against THEN IF(v_choices = 'yes_no', 'yes', 'keep') ELSE IF(v_choices = 'yes_no', 'no', 'drop') END;
    UPDATE vote SET closed_at = NOW(6), outcome = v_out, voters = v_voters, ballots = v_ballots, for_n = v_for, against_n = v_against,
           needs_human = (v_out IN ('tie','no_quorum')) WHERE id = p_vote;
  END IF;
END //

DROP PROCEDURE IF EXISTS sp_vote_close_due //
CREATE PROCEDURE sp_vote_close_due()
BEGIN
  DECLARE v_id BIGINT UNSIGNED; DECLARE v_done INT DEFAULT 0;
  DECLARE c CURSOR FOR SELECT id FROM vote WHERE closed_at IS NULL AND deadline <= NOW(6) ORDER BY id LIMIT 200;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_done = 1;
  OPEN c;
  each_vote: LOOP
    FETCH c INTO v_id;
    IF v_done THEN LEAVE each_vote; END IF;
    START TRANSACTION; CALL mill_i_vote_close(v_id); COMMIT;
  END LOOP;
  CLOSE c;
END //

-- cast or change a ballot until the deadline. When every current member has voted the vote closes at once.
DROP PROCEDURE IF EXISTS cmd_vote_cast //
CREATE PROCEDURE cmd_vote_cast(IN p_desk INT UNSIGNED, IN p_vote BIGINT UNSIGNED, IN p_choice VARCHAR(4))
BEGIN
  DECLARE v_room INT UNSIGNED; DECLARE v_choices VARCHAR(9); DECLARE v_deadline DATETIME(6); DECLARE v_closed DATETIME(6);
  DECLARE v_voters, v_ballots INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT room_id, choices, deadline, closed_at INTO v_room, v_choices, v_deadline, v_closed FROM vote WHERE id = p_vote FOR UPDATE;
  IF v_room IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: no such vote'; END IF;
  IF v_closed IS NOT NULL OR v_deadline <= NOW(6) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: closed (the deadline passed)'; END IF;
  IF NOT mill_i_is_member(v_room, p_desk) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: only a current member of the roster votes'; END IF;
  INSERT INTO ballot (vote_id, desk_id, room_id, choices, choice) VALUES (p_vote, p_desk, v_room, v_choices, p_choice)
    ON DUPLICATE KEY UPDATE choice = VALUES(choice), at = NOW(6);       -- ck_ballot_choice refuses a choice of the other kind
  SELECT COUNT(*) INTO v_voters FROM room_member m JOIN desk d ON d.id = m.desk_id AND d.live = 1 WHERE m.room_id = v_room AND m.left_at IS NULL;
  SELECT COUNT(*) INTO v_ballots FROM ballot b JOIN room_member m ON m.room_id = b.room_id AND m.desk_id = b.desk_id AND m.left_at IS NULL WHERE b.vote_id = p_vote;
  IF v_ballots >= v_voters THEN CALL mill_i_vote_close(p_vote); END IF;
  UPDATE letter_to SET read_at = IFNULL(read_at, NOW(6)) WHERE letter_id = (SELECT letter_id FROM vote WHERE id = p_vote) AND desk_id = p_desk;
  COMMIT;
  SELECT p_vote AS vote, p_choice AS choice, v_ballots AS ballots, v_voters AS voters, (SELECT outcome FROM vote WHERE id = p_vote) AS outcome;
END //

DROP PROCEDURE IF EXISTS uc_vote //
CREATE PROCEDURE uc_vote(IN p_vote BIGINT UNSIGNED)
BEGIN
  CALL sp_vote_close_due();
  SELECT v.id AS vote, v.letter_id AS letter, v.room_id AS roster, r.name AS roster_name, v.choices, v.opened_at, v.deadline, v.closed_at,
         v.outcome, v.voters, v.ballots, v.for_n, v.against_n, v.needs_human, LEFT(l.body, 200) AS decision
    FROM vote v JOIN room r ON r.id = v.room_id JOIN letter l ON l.id = v.letter_id WHERE v.id = p_vote;
  SELECT d.name AS desk, b.choice, b.at FROM ballot b JOIN desk d ON d.id = b.desk_id WHERE b.vote_id = p_vote ORDER BY d.name;
  SELECT d.name AS not_voted FROM vote v JOIN room_member m ON m.room_id = v.room_id AND m.left_at IS NULL JOIN desk d ON d.id = m.desk_id AND d.live = 1
   WHERE v.id = p_vote AND NOT EXISTS (SELECT 1 FROM ballot b WHERE b.vote_id = v.id AND b.desk_id = m.desk_id) ORDER BY d.name;
END //

-- ---------------------------------------------------------------- awareness
DROP PROCEDURE IF EXISTS sp_glance_refresh //
CREATE PROCEDURE sp_glance_refresh()
BEGIN
  DECLARE t0 DATETIME(6) DEFAULT NOW(6);
  REPLACE INTO glance_cache
  SELECT 1, t0, 0,
         (SELECT COUNT(*) FROM seat WHERE socket_at IS NOT NULL), (SELECT COUNT(*) FROM hold),
         IFNULL(SUM(status = 'open'), 0), IFNULL(SUM(status = 'claimed'), 0), IFNULL(SUM(status = 'parked'), 0), IFNULL(SUM(status = 'shipped'), 0), IFNULL(SUM(status = 'done'), 0),
         MAX(a.l), MAX(a.ce), MAX(a.d), MAX(a.he), MAX(a.sp),
         (SELECT COUNT(*) FROM vote WHERE closed_at IS NULL), (SELECT COUNT(*) FROM vote WHERE needs_human = 1 AND closed_at > NOW(6) - INTERVAL 7 DAY)
    FROM card c,
         (SELECT IFNULL(SUM(letter_id IS NOT NULL), 0) l, IFNULL(SUM(card_event_id IS NOT NULL), 0) ce, IFNULL(SUM(doing_id IS NOT NULL), 0) d,
                 IFNULL(SUM(hold_event_id IS NOT NULL), 0) he, IFNULL(SUM(score_point_id IS NOT NULL), 0) sp FROM activity WHERE at > NOW(6) - INTERVAL 1 DAY) a
   WHERE c.retired_at IS NULL;
  UPDATE glance_cache SET refresh_us = LEAST(TIMESTAMPDIFF(MICROSECOND, t0, NOW(6)), 4294967295) WHERE id = 1;
END //

-- the office glance: counts at most ~30 s old (refreshed inline when older than 90 s, so it works without the event
-- scheduler), the newest 30 changes live, open votes, and closed votes that need a human.
DROP PROCEDURE IF EXISTS uc_glance //
CREATE PROCEDURE uc_glance()
BEGIN
  CALL sp_vote_close_due();
  IF NOT EXISTS (SELECT 1 FROM glance_cache WHERE id = 1 AND at > NOW(6) - INTERVAL 90 SECOND) THEN CALL sp_glance_refresh(); END IF;
  SELECT * FROM glance_cache WHERE id = 1;
  SELECT a.seq, a.at, CASE WHEN a.letter_id THEN 'letter' WHEN a.card_event_id THEN 'card' WHEN a.doing_id THEN 'doing'
         WHEN a.hold_event_id THEN 'hold' WHEN a.vote_id THEN 'vote' ELSE 'score' END AS kind,
         COALESCE(a.letter_id, ce.card_id, a.doing_id, he.resource_id, sp.score_id, a.vote_id) AS ref, k.name AS desk
    FROM activity a LEFT JOIN letter l ON l.id = a.letter_id LEFT JOIN card_event ce ON ce.id = a.card_event_id
    LEFT JOIN doing d ON d.id = a.doing_id LEFT JOIN hold_event he ON he.id = a.hold_event_id LEFT JOIN score_point sp ON sp.id = a.score_point_id
    LEFT JOIN vote v ON v.id = a.vote_id
    JOIN desk k ON k.id = COALESCE(l.sender_id, ce.desk_id, d.desk_id, he.desk_id, sp.desk_id, v.opened_by)
   ORDER BY a.seq DESC LIMIT 30;
  SELECT v.id AS vote, r.name AS roster, v.choices, v.deadline, v.closed_at, v.outcome, v.voters, v.ballots, v.for_n, v.against_n, v.needs_human,
         LEFT(l.body, 120) AS decision
    FROM vote v JOIN room r ON r.id = v.room_id JOIN letter l ON l.id = v.letter_id
   WHERE v.closed_at IS NULL OR (v.needs_human = 1 AND v.closed_at > NOW(6) - INTERVAL 7 DAY) OR v.closed_at > NOW(6) - INTERVAL 1 DAY
   ORDER BY v.closed_at IS NULL DESC, v.needs_human DESC, v.id DESC LIMIT 50;
END //

-- one roster: members (present, current doing), its cards by status, its rooms, its votes
DROP PROCEDURE IF EXISTS uc_roster_glance //
CREATE PROCEDURE uc_roster_glance(IN p_roster INT UNSIGNED)
BEGIN
  CALL sp_vote_close_due();
  SELECT d.id AS desk, d.name, s.socket_at IS NOT NULL AS present, x.text AS doing
    FROM room_member m JOIN desk d ON d.id = m.desk_id AND d.live = 1 LEFT JOIN seat s ON s.desk_id = d.id
    LEFT JOIN doing_now n ON n.desk_id = d.id LEFT JOIN doing x ON x.id = n.doing_id
   WHERE m.room_id = p_roster AND m.left_at IS NULL ORDER BY d.name LIMIT 500;
  SELECT status, COUNT(*) AS n FROM card WHERE roster_id = p_roster AND retired_at IS NULL GROUP BY status;
  SELECT id AS room, name FROM room WHERE roster_id = p_roster AND retired_at IS NULL ORDER BY name LIMIT 100;
  SELECT v.id AS vote, v.choices, v.deadline, v.closed_at, v.outcome, v.voters, v.ballots, v.needs_human, LEFT(l.body, 120) AS decision
    FROM vote v JOIN letter l ON l.id = v.letter_id WHERE v.room_id = p_roster ORDER BY v.closed_at IS NULL DESC, v.id DESC LIMIT 20;
END //

-- what changed since this desk last looked (moves its cursor)
DROP PROCEDURE IF EXISTS uc_since //
CREATE PROCEDURE uc_since(IN p_desk INT UNSIGNED)
BEGIN
  DECLARE v BIGINT UNSIGNED;
  SELECT seen_seq INTO v FROM seat WHERE desk_id = p_desk;
  SELECT IFNULL(SUM(letter_id IS NOT NULL), 0) AS letters, IFNULL(SUM(card_event_id IS NOT NULL), 0) AS card_moves,
         IFNULL(SUM(doing_id IS NOT NULL), 0) AS doings, IFNULL(SUM(hold_event_id IS NOT NULL), 0) AS holds,
         IFNULL(SUM(score_point_id IS NOT NULL), 0) AS points, IFNULL(SUM(vote_id IS NOT NULL), 0) AS votes
    FROM activity WHERE seq > IFNULL(v, 0);
  SELECT a.seq, a.at, CASE WHEN a.letter_id THEN 'letter' WHEN a.card_event_id THEN 'card' WHEN a.doing_id THEN 'doing'
         WHEN a.hold_event_id THEN 'hold' WHEN a.vote_id THEN 'vote' ELSE 'score' END AS kind,
         COALESCE(a.letter_id, ce.card_id, a.doing_id, he.resource_id, sp.score_id, a.vote_id) AS ref, k.name AS desk
    FROM activity a LEFT JOIN letter l ON l.id = a.letter_id LEFT JOIN card_event ce ON ce.id = a.card_event_id
    LEFT JOIN doing d ON d.id = a.doing_id LEFT JOIN hold_event he ON he.id = a.hold_event_id LEFT JOIN score_point sp ON sp.id = a.score_point_id
    LEFT JOIN vote vt ON vt.id = a.vote_id
    JOIN desk k ON k.id = COALESCE(l.sender_id, ce.desk_id, d.desk_id, he.desk_id, sp.desk_id, vt.opened_by)
   WHERE a.seq > IFNULL(v, 0) ORDER BY a.seq DESC LIMIT 50;
  UPDATE seat SET seen_seq = IFNULL((SELECT MAX(seq) FROM activity), 0) WHERE desk_id = p_desk;
END //

-- one desk: its current doing and who waits on it; what it holds, claims and ranks; its unread
DROP PROCEDURE IF EXISTS uc_desk //
CREATE PROCEDURE uc_desk(IN p_desk INT UNSIGNED)
BEGIN
  SELECT x.text, x.created, x.on_card_id AS on_card, x.on_letter_id AS on_letter, w.name AS waiting_on, x.waiting_why
    FROM doing_now n JOIN doing x ON x.id = n.doing_id LEFT JOIN desk w ON w.id = x.wait_desk_id WHERE n.desk_id = p_desk;
  SELECT k.name AS waits_on_me FROM doing_now n JOIN desk k ON k.id = n.desk_id WHERE n.wait_desk_id = p_desk;
  SELECT id AS card, status, LEFT(body, 80) AS body, done_when FROM card WHERE volunteer_id = p_desk AND status IN ('claimed','shipped') AND retired_at IS NULL ORDER BY id DESC LIMIT 50;
  SELECT f.card_id AS card, c.status FROM focus f JOIN card c ON c.id = f.card_id WHERE f.desk_id = p_desk ORDER BY f.rank_ord, f.card_id LIMIT 50;
  SELECT COUNT(*) AS unread, IFNULL(SUM(asked), 0) AS asked FROM letter_to WHERE desk_id = p_desk AND read_at IS NULL;
END //

DROP PROCEDURE IF EXISTS uc_card //
CREATE PROCEDURE uc_card(IN p_card BIGINT UNSIGNED)
BEGIN
  SELECT c.id AS card, c.roster_id AS roster, r.name AS roster_name, c.status, a.name AS asker, v.name AS volunteer, c.claimed_at,
         c.body, c.done_when, c.from_letter_id AS from_letter, c.from_card_id AS from_card, c.from_score_id AS from_score, c.ord, c.retired_at
    FROM card c JOIN room r ON r.id = c.roster_id JOIN desk a ON a.id = c.creator_id LEFT JOIN desk v ON v.id = c.volunteer_id WHERE c.id = p_card;
  SELECT e.id AS event, e.at, d.name AS desk, e.from_status, e.to_status, e.evidence FROM card_event e JOIN desk d ON d.id = e.desk_id
   WHERE e.card_id = p_card ORDER BY e.id DESC LIMIT 50;
END //

-- ---------------------------------------------------------------- memory
-- the whole tree under a root (a letter, card or score): replies, cards made from letters, sub-cards, cards from a score.
-- First result: the nodes (at most 20000). Second result: one row, nodes and truncated (1 when the tree is larger).
DROP PROCEDURE IF EXISTS mill_span //
CREATE PROCEDURE mill_span(IN p_type VARCHAR(8), IN p_id BIGINT UNSIGNED, IN p_depth INT)
BEGIN
  DECLARE v_n INT;
  IF p_type NOT IN ('letter','card','score') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'span: root type is letter, card or score'; END IF;
  DROP TEMPORARY TABLE IF EXISTS mill_t_span;
  CREATE TEMPORARY TABLE mill_t_span (typ VARCHAR(8) NOT NULL, id BIGINT UNSIGNED NOT NULL, ptyp VARCHAR(8) NULL, pid BIGINT UNSIGNED NULL,
                                      depth INT NOT NULL, ord BIGINT NOT NULL, PRIMARY KEY (typ, id)) ENGINE=MEMORY
  WITH RECURSIVE t (typ, id, ptyp, pid, depth, ord) AS (
    SELECT CAST(p_type AS CHAR(8)), p_id, CAST(NULL AS CHAR(8)), CAST(NULL AS UNSIGNED), 0, CAST(0 AS SIGNED)
    UNION ALL
    SELECT x.typ, x.id, x.ptyp, x.pid, x.depth, x.ord FROM t JOIN LATERAL (
        SELECT 'letter' typ, l.id, 'letter' ptyp, t.id pid, t.depth + 1 depth, CAST(l.id AS SIGNED) ord FROM letter l WHERE t.typ = 'letter' AND l.reply_to_id = t.id
        UNION ALL SELECT 'card', c.id, 'letter', t.id, t.depth + 1, c.ord FROM card c WHERE t.typ = 'letter' AND c.from_letter_id = t.id
        UNION ALL SELECT 'card', c.id, 'card', t.id, t.depth + 1, c.ord FROM card c WHERE t.typ = 'card' AND c.from_card_id = t.id
        UNION ALL SELECT 'card', c.id, 'score', t.id, t.depth + 1, c.ord FROM card c WHERE t.typ = 'score' AND c.from_score_id = t.id
      ) x WHERE t.depth < LEAST(IFNULL(p_depth, 50), 200)
    LIMIT 20001)
  SELECT typ, id, ptyp, pid, MIN(depth) AS depth, MIN(ord) AS ord FROM t GROUP BY typ, id, ptyp, pid;
  SELECT COUNT(*) INTO v_n FROM mill_t_span;
  SELECT typ, id, ptyp, pid, depth, ord FROM mill_t_span ORDER BY depth, ptyp, pid, ord, id LIMIT 20000;
  SELECT LEAST(v_n, 20000) AS nodes, v_n > 20000 AS truncated, 20000 AS cap;
  DROP TEMPORARY TABLE IF EXISTS mill_t_span;
END //

DROP PROCEDURE IF EXISTS uc_trail //
CREATE PROCEDURE uc_trail(IN p_card BIGINT UNSIGNED)
BEGIN
  WITH RECURSIVE up (id, fc, fl, fs, n) AS (
    SELECT id, from_card_id, from_letter_id, from_score_id, 0 FROM card WHERE id = p_card
    UNION ALL SELECT c.id, c.from_card_id, c.from_letter_id, c.from_score_id, n + 1 FROM card c JOIN up ON c.id = up.fc WHERE n < 50)
  SELECT id AS card, fc AS from_card, fl AS from_letter, fs AS from_score, n AS up FROM up ORDER BY n;
  SELECT id AS card, ord, status FROM card WHERE from_card_id = p_card ORDER BY ord, id LIMIT 200;
  SELECT r.name AS resource, d.name AS holder FROM hold h JOIN resource r ON r.id = h.resource_id JOIN desk d ON d.id = h.desk_id WHERE h.card_id = p_card;
  SELECT k.name AS desk, LEFT(x.text, 80) AS doing FROM doing x JOIN desk k ON k.id = x.desk_id WHERE x.on_card_id = p_card ORDER BY x.id DESC LIMIT 10;
END //

-- ---------------------------------------------------------------- scores
DROP PROCEDURE IF EXISTS cmd_score //
CREATE PROCEDURE cmd_score(IN p_desk INT UNSIGNED, IN p_roster INT UNSIGNED, IN p_kpi VARCHAR(64), IN p_target DOUBLE,
                           IN p_better VARCHAR(4), IN p_unit VARCHAR(16), IN p_note VARCHAR(200))
BEGIN
  DECLARE v_id INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF TRIM(IFNULL(p_kpi, '')) = '' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: kpi is required'; END IF;
  IF NOT (mill_i_is_member(IFNULL(p_roster, 1), p_desk) OR mill_i_is_admin(p_desk)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: a score is made by a member of its roster';
  END IF;
  START TRANSACTION;
  INSERT INTO score (desk_id, roster_id, kpi, target, better, unit, note)
    VALUES (p_desk, IFNULL(p_roster, 1), TRIM(p_kpi), p_target, IFNULL(p_better, 'up'), IFNULL(p_unit, ''), IFNULL(p_note, ''));
  SET v_id = LAST_INSERT_ID();
  COMMIT;
  SELECT v_id AS score;
END //

DROP PROCEDURE IF EXISTS cmd_score_retire //
CREATE PROCEDURE cmd_score_retire(IN p_desk INT UNSIGNED, IN p_score INT UNSIGNED)
BEGIN
  DECLARE v_owner INT UNSIGNED;
  DECLARE v_n INT DEFAULT 0;
  SELECT desk_id, 1 INTO v_owner, v_n FROM score WHERE id = p_score AND retired_at IS NULL;
  IF v_n = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: no such live score'; END IF;
  IF NOT (v_owner <=> p_desk OR mill_i_is_admin(p_desk)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: retire a score is its owner or Admin';
  END IF;
  UPDATE score SET retired_at = NOW(6) WHERE id = p_score;
  SELECT p_score AS score, 'retired' AS status;
END //

DROP PROCEDURE IF EXISTS cmd_score_point //
CREATE PROCEDURE cmd_score_point(IN p_desk INT UNSIGNED, IN p_score INT UNSIGNED, IN p_value DOUBLE, IN p_note VARCHAR(200))
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_roster INT UNSIGNED;
  DECLARE v_n INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  IF CHAR_LENGTH(IFNULL(p_note, '')) > 200 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: --note is over 200 characters'; END IF;
  IF p_value IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: a point needs a value'; END IF;
  SELECT roster_id, 1 INTO v_roster, v_n FROM score WHERE id = p_score AND retired_at IS NULL;
  IF v_n = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: no such live score'; END IF;
  IF NOT (mill_i_is_member(v_roster, p_desk) OR mill_i_is_admin(p_desk)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'who-may: a point is added by a member of the score''s roster';
  END IF;
  START TRANSACTION;
  INSERT INTO score_point (score_id, desk_id, value, note) VALUES (p_score, p_desk, p_value, IFNULL(p_note, ''));
  SET v_id = LAST_INSERT_ID();
  INSERT INTO activity (score_point_id) VALUES (v_id);
  COMMIT;
  SELECT v_id AS point;
END //

-- ---------------------------------------------------------------- invites (0.7 wrote these with raw SQL in door.py)
DROP PROCEDURE IF EXISTS cmd_invite_create //
CREATE PROCEDURE cmd_invite_create(IN p_key VARCHAR(16), IN p_hash CHAR(64), IN p_label VARCHAR(64), IN p_by VARCHAR(64), IN p_ttl INT)
BEGIN
  INSERT INTO mill_invite (key_id, token_hash, label, created_by, ttl_seconds, expires_at)
  VALUES (p_key, p_hash, IFNULL(p_label, ''), IFNULL(p_by, ''), p_ttl, IF(p_ttl IS NULL, NULL, NOW(6) + INTERVAL p_ttl SECOND));
  SELECT p_key AS key_id;
END //

DROP PROCEDURE IF EXISTS cmd_invite_enable //
CREATE PROCEDURE cmd_invite_enable(IN p_key VARCHAR(16))
BEGIN
  UPDATE mill_invite SET enabled_at = NOW(6) WHERE key_id = p_key AND revoked_at IS NULL AND enabled_at IS NULL;
  IF ROW_COUNT() = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'invite: not found, revoked or already enabled'; END IF;
  SELECT p_key AS key_id, 'enabled' AS state;
END //

DROP PROCEDURE IF EXISTS cmd_invite_ttl //
CREATE PROCEDURE cmd_invite_ttl(IN p_key VARCHAR(16), IN p_ttl INT)
BEGIN
  UPDATE mill_invite SET ttl_seconds = p_ttl, expires_at = IF(p_ttl IS NULL, NULL, NOW(6) + INTERVAL p_ttl SECOND)
   WHERE key_id = p_key AND revoked_at IS NULL;
  IF ROW_COUNT() = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'invite: not found or revoked'; END IF;
  SELECT p_key AS key_id, p_ttl AS ttl_seconds;
END //

DROP PROCEDURE IF EXISTS cmd_invite_revoke //
CREATE PROCEDURE cmd_invite_revoke(IN p_key VARCHAR(16))
BEGIN
  UPDATE mill_invite SET revoked_at = NOW(6) WHERE key_id = p_key AND revoked_at IS NULL;
  SELECT p_key AS key_id, ROW_COUNT() AS revoked;
END //

-- redeem: enabled, not revoked, not expired, checked under the row lock. Only the token hash reaches SQL.
DROP PROCEDURE IF EXISTS cmd_invite_join //
CREATE PROCEDURE cmd_invite_join(IN p_hash CHAR(64), IN p_party VARCHAR(16), IN p_party_id VARCHAR(64))
BEGIN
  DECLARE v_key VARCHAR(16);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN ROLLBACK; RESIGNAL; END;
  START TRANSACTION;
  SELECT key_id INTO v_key FROM mill_invite WHERE token_hash = p_hash AND enabled_at IS NOT NULL AND revoked_at IS NULL
     AND (expires_at IS NULL OR expires_at > NOW(6)) FOR UPDATE;
  IF v_key IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'invite: not valid'; END IF;
  INSERT IGNORE INTO mill_invite_join (key_id, party, party_id) VALUES (v_key, p_party, p_party_id);
  COMMIT;
  SELECT v_key AS key_id;
END //

DELIMITER ;

-- relaxed-tier writers (need event_scheduler = ON; the read routines refresh inline when it is off)
DROP EVENT IF EXISTS ev_glance_refresh;
CREATE EVENT ev_glance_refresh ON SCHEDULE EVERY 30 SECOND DO CALL sp_glance_refresh();
DROP EVENT IF EXISTS ev_vote_close;
CREATE EVENT ev_vote_close ON SCHEDULE EVERY 1 MINUTE DO CALL sp_vote_close_due();
DROP EVENT IF EXISTS ev_push_purge;
CREATE EVENT ev_push_purge ON SCHEDULE EVERY 1 HOUR DO CALL sp_push_purge();
