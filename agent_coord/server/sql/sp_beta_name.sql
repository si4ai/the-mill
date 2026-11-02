-- 0.8.0 (card 868): the name family with trust, from docs/requirements/beta/beta_sp.sql. Applied last in
-- apply_order.txt, so its mill_desk_id replaces sp_cmd.sql's MILL_DESK_ID (same contract: NULL empty, 0 unknown).
-- Public (EXECUTE to the app user): cmd_*, sp_name_*, mill_*. Internal helpers are b_* (never granted).
-- sp_admin_set is granted to the host database user only (admin.md section 1: Admin grant is host loopback only).
-- Trust: every procedure reads b_trust() itself and applies docs/requirements/admin.md sections 1-3; no guard reads an
-- app argument or a caller-set user variable. The level lives in the server's config.toml (as on main); the server
-- re-creates b_trust() from it at startup and on `mill trust` (docs/requirements/schema-design.md section 9).
-- Ids are BIGINT UNSIGNED, as on main. There is no name history table: a lifecycle step changes the name row only.
-- No procedure starts, commits or rolls back; the caller owns the transaction; guards run before the
-- first write; the name row a decision depends on is read FOR UPDATE.
-- Refusals: SIGNAL SQLSTATE 45000 with main's texts where main has one (sp_name.sql, catalog.py, guard.py).

DELIMITER //

-- Install default. The server replaces this body with the config.toml level ('high' or 'limited') before it serves.
DROP FUNCTION IF EXISTS b_trust //
CREATE FUNCTION b_trust() RETURNS VARCHAR(8) DETERMINISTIC NO SQL
  RETURN 'high' //
-- Admin is roster id 2, never the string (F92).
DROP FUNCTION IF EXISTS b_is_admin //
CREATE FUNCTION b_is_admin(p_desk BIGINT UNSIGNED) RETURNS TINYINT READS SQL DATA
  RETURN p_desk IS NOT NULL AND EXISTS (SELECT 1 FROM member WHERE name_id = 2 AND desk_id = p_desk) //
-- A live, seated desk by name (the caller of a command).
DROP FUNCTION IF EXISTS b_desk //
CREATE FUNCTION b_desk(p_name VARCHAR(64)) RETURNS BIGINT UNSIGNED READS SQL DATA
BEGIN
  DECLARE v BIGINT UNSIGNED;
  SELECT n.id INTO v FROM name n JOIN seat s ON s.desk_id = n.id
   WHERE n.type = 'desk' AND n.name = TRIM(p_name) AND n.deleted IS NULL AND s.token_hash IS NOT NULL;
  IF v IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'desk: not a seated desk'; END IF;
  RETURN v;
END //
DROP FUNCTION IF EXISTS mill_desk_id //
-- Same contract as sp_cmd.sql MILL_DESK_ID: NULL for no name, 0 for a name the book does not hold.
CREATE FUNCTION mill_desk_id(p_name VARCHAR(64)) RETURNS BIGINT UNSIGNED READS SQL DATA
BEGIN
  IF p_name IS NULL OR TRIM(p_name) = '' THEN
    RETURN NULL;
  END IF;
  RETURN IFNULL((SELECT id FROM name WHERE type = 'desk' AND name = TRIM(p_name) AND deleted IS NULL), 0);
END //
-- A roster by name. Office is id 1 by name while no roster holds the name 'Office' (F92: Office follows id 1).
DROP FUNCTION IF EXISTS mill_roster_id //
CREATE FUNCTION mill_roster_id(p_name VARCHAR(64)) RETURNS BIGINT UNSIGNED READS SQL DATA
  RETURN IFNULL((SELECT id FROM name WHERE type = 'roster' AND name = TRIM(p_name) AND deleted IS NULL),
                IF(TRIM(p_name) COLLATE utf8mb4_0900_ai_ci = 'Office', 1, NULL)) //
-- The name a lifecycle verb acts on. F60: the type is typed by the caller, one of desk, roster, label.
DROP FUNCTION IF EXISTS b_name_type //
CREATE FUNCTION b_name_type(p_type VARCHAR(16)) RETURNS VARCHAR(8) DETERMINISTIC NO SQL
BEGIN
  IF LOWER(TRIM(p_type)) NOT IN ('desk','roster','label') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name: type is roster, label or desk';
  END IF;
  RETURN LOWER(TRIM(p_type));
END //
DROP PROCEDURE IF EXISTS b_name_event //
DROP PROCEDURE IF EXISTS b_name_check //
CREATE PROCEDURE b_name_check(IN p_name VARCHAR(64))
BEGIN
  IF p_name IS NULL OR CHAR_LENGTH(TRIM(p_name)) NOT BETWEEN 1 AND 64 OR TRIM(p_name) REGEXP '[[:cntrl:]]' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name: 1 to 64 characters';
  END IF;
END //

-- ---------- mint (admin.md section 2 and section 4) ----------
-- A roster or label: any seated desk under high trust, Admin only under limited trust. A plan (tree) or a
-- resource (res): any seated desk (section 3: tree, hold). A desk mints itself at connect (sp_name_mint_desk).
-- A live name of that type is returned as it is ('exists'); a retired one is refused (reuse = Admin reclaim).
DROP PROCEDURE IF EXISTS b_name_mint //
CREATE PROCEDURE b_name_mint(IN p_by BIGINT UNSIGNED, IN p_type VARCHAR(8), IN p_name VARCHAR(64), OUT o_id BIGINT UNSIGNED, OUT o_op VARCHAR(8))
BEGIN
  DECLARE v_del DATETIME(6);
  CALL b_name_check(p_name);
  IF p_type NOT IN ('roster','label','tree','res') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name: a desk mints itself at connect'; END IF;
  SET o_id = NULL;
  SELECT id, deleted INTO o_id, v_del FROM name WHERE type = p_type AND name = TRIM(p_name) FOR UPDATE;
  IF o_id IS NOT NULL AND v_del IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name retired: an Admin reclaims it (mill reclaim)'; END IF;
  IF o_id IS NOT NULL THEN SET o_op = 'exists';
  ELSE
    IF p_type = 'roster' AND TRIM(p_name) COLLATE utf8mb4_0900_ai_ci = 'Office' THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name in use: Office names roster id 1';
    END IF;
    IF p_type IN ('roster','label') AND b_trust() = 'limited' AND NOT b_is_admin(p_by) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'limited-trust: minting a roster or label is Admin (mill create roster NAME --yes)';
    END IF;
    INSERT INTO name (type, name) VALUES (p_type, TRIM(p_name)); SET o_id = LAST_INSERT_ID(); SET o_op = 'created';
  END IF;
END //
DROP PROCEDURE IF EXISTS sp_name_mint //
CREATE PROCEDURE sp_name_mint(IN p_by VARCHAR(64), IN p_type VARCHAR(16), IN p_name VARCHAR(64))
BEGIN
  DECLARE v_by BIGINT UNSIGNED DEFAULT b_desk(p_by); DECLARE v_id BIGINT UNSIGNED; DECLARE v_op VARCHAR(8);
  CALL b_name_mint(v_by, LOWER(TRIM(p_type)), p_name, v_id, v_op);
  SELECT v_id AS id, TRIM(p_name) AS name, LOWER(TRIM(p_type)) AS name_type, v_op AS op;
END //
-- connect: the desk mints itself with its seat token (the server has checked the invite). It is on Office.
DROP PROCEDURE IF EXISTS sp_name_mint_desk //
CREATE PROCEDURE sp_name_mint_desk(IN p_name VARCHAR(64), IN p_token_hash CHAR(64))
BEGIN
  DECLARE v BIGINT UNSIGNED; DECLARE v_del DATETIME(6);
  CALL b_name_check(p_name);
  IF p_token_hash IS NULL OR CHAR_LENGTH(p_token_hash) <> 64 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'connect: seat token hash required'; END IF;
  SELECT id, deleted INTO v, v_del FROM name WHERE type = 'desk' AND name = TRIM(p_name) FOR UPDATE;
  IF v_del IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name retired: an Admin reclaims it (mill reclaim)'; END IF;
  IF v IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name in use: that desk is minted'; END IF;
  INSERT INTO name (type, name) VALUES ('desk', TRIM(p_name)); SET v = LAST_INSERT_ID();
  INSERT INTO seat (desk_id, token_hash) VALUES (v, p_token_hash);
  INSERT INTO member (name_id, desk_id) VALUES (1, v);
  UPDATE name SET n = n + 1 WHERE id = 1;
  SELECT v AS id, TRIM(p_name) AS name, 'desk' AS name_type, 'created' AS op;
END //

-- ---------- rename (admin.md section 1; F60, F92) ----------
-- Admin at either trust. Exception: a desk renames itself when p_by_hash is its seat's token hash.
-- Admin (id 2) is never renamed (any spelling resolves to id 2 through the ai_ci collation and the guard reads the
-- id). Office (id 1) may be renamed by Admin; no other roster takes the name Office.
DROP PROCEDURE IF EXISTS sp_name_rename //
CREATE PROCEDURE sp_name_rename(IN p_by VARCHAR(64), IN p_by_hash CHAR(64), IN p_type VARCHAR(16), IN p_old VARCHAR(64), IN p_new VARCHAR(64))
BEGIN
  DECLARE v_by BIGINT UNSIGNED DEFAULT b_desk(p_by); DECLARE v_type VARCHAR(8) DEFAULT b_name_type(p_type);
  DECLARE v_id BIGINT UNSIGNED; DECLARE v_del DATETIME(6); DECLARE v_old VARCHAR(64); DECLARE v_self TINYINT DEFAULT 0;
  CALL b_name_check(p_new);
  SELECT id, deleted, name INTO v_id, v_del, v_old FROM name WHERE type = v_type AND name = TRIM(p_old) FOR UPDATE;
  IF v_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name not found'; END IF;
  IF v_type = 'desk' AND v_id = v_by AND p_by_hash IS NOT NULL
     AND EXISTS (SELECT 1 FROM seat WHERE desk_id = v_by AND token_hash = p_by_hash) THEN SET v_self = 1; END IF;
  IF NOT v_self AND NOT b_is_admin(v_by) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Admin only: rename (a desk renames only itself, with its own seat)';
  END IF;
  IF v_del IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name retired: mill reclaim first'; END IF;
  IF v_id = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cannot rename System'; END IF;
  IF v_id = 2 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cannot rename Admin'; END IF;
  IF v_type = 'roster' AND v_id <> 1 AND TRIM(p_new) COLLATE utf8mb4_0900_ai_ci = 'Office' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name in use: Office names roster id 1';
  END IF;
  IF EXISTS (SELECT 1 FROM name WHERE type = v_type AND name = TRIM(p_new) AND id <> v_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name in use';
  END IF;
  UPDATE name SET name = TRIM(p_new) WHERE id = v_id;
  SELECT v_id AS id, TRIM(p_new) AS name, v_type AS name_type, 'renamed' AS op;
END //

-- ---------- retire (admin.md sections 1 and 4; F65, F135; card 880) ----------
-- Admin at either trust. Exception (card 880): a desk retires itself when p_by_hash is its seat's token hash, as in
-- sp_name_rename. Soft: name.deleted. Office and Admin are never retired. A desk: its seat token and webhook are
-- cleared, its focus ends (a 'clear' row that seat.doing_id then names), and every hold it owns is freed, in this
-- call. Each freed hold gets a 'drop' row by the ACTING desk (the desk itself or Admin; never NULL), with the holder
-- as peer_id when another desk acted, and its activity row says 'drop' by that desk. Lock order: name, seat, hold.
DROP PROCEDURE IF EXISTS sp_name_retire //
CREATE PROCEDURE sp_name_retire(IN p_by VARCHAR(64), IN p_by_hash CHAR(64), IN p_type VARCHAR(16), IN p_name VARCHAR(64))
BEGIN
  DECLARE v_by BIGINT UNSIGNED DEFAULT b_desk(p_by); DECLARE v_type VARCHAR(8) DEFAULT b_name_type(p_type);
  DECLARE v_id BIGINT UNSIGNED; DECLARE v_del DATETIME(6); DECLARE v_nm VARCHAR(64); DECLARE v_released INT DEFAULT 0;
  DECLARE v_doing BIGINT UNSIGNED; DECLARE v_self TINYINT DEFAULT 0; DECLARE v_now DATETIME(6) DEFAULT NOW(6);
  DECLARE v_tok CHAR(64);
  -- Lock order: name, then seat. F186 (spin N01): the self-retire token check is under the seat lock
  -- with target = caller, so a reset that clears the token in between refuses.
  SELECT id, deleted, name INTO v_id, v_del, v_nm FROM name WHERE type = v_type AND name = TRIM(p_name) FOR UPDATE;
  IF v_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name not found'; END IF;
  IF v_id = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cannot delete System'; END IF;
  IF v_id = 1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cannot delete Office'; END IF;
  IF v_id = 2 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cannot delete Admin'; END IF;
  IF v_del IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name already retired'; END IF;
  IF v_type = 'desk' THEN
    SELECT doing_id, token_hash INTO v_doing, v_tok FROM seat WHERE desk_id = v_id FOR UPDATE;
    IF p_by_hash IS NOT NULL AND v_by = v_id AND v_tok IS NOT NULL AND v_tok = p_by_hash THEN
      SET v_self = 1;
    END IF;
  END IF;
  IF NOT v_self AND NOT b_is_admin(v_by) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Admin only: retire (a desk retires only itself, with its own seat)';
  END IF;
  UPDATE name SET deleted = v_now WHERE id = v_id;
  IF v_type = 'desk' THEN
    SELECT COUNT(*) INTO v_released FROM hold WHERE desk_id = v_id FOR UPDATE;
    INSERT INTO doing (created, desk_id, roster_id, act, on_type, on_id, peer_id)
      SELECT v_now, v_by, 1, 'drop', 'hold', h.id, NULLIF(v_id, v_by) FROM hold h WHERE h.desk_id = v_id ORDER BY h.id;
    UPDATE activity a JOIN hold h ON a.type = 'hold' AND a.id = h.id
       SET a.updated = v_now, a.desk_id = v_by, a.act = 'drop' WHERE h.desk_id = v_id;
    UPDATE hold SET desk_id = NULL WHERE desk_id = v_id;
    INSERT INTO doing (created, desk_id, roster_id, act, text) VALUES (v_now, v_id, 1, 'clear', ''); SET v_doing = LAST_INSERT_ID();
    INSERT INTO activity (type, id, created, updated, desk_id, roster_id, act) VALUES ('doing', v_doing, v_now, v_now, v_id, 1, 'clear');
    UPDATE seat SET token_hash = NULL, time_disconnect = v_now, doing_id = v_doing,
           delivery_mode = IF(delivery_mode = 'webhook', 'websocket', delivery_mode),
           endpoint_url = NULL, endpoint_key = NULL, wake_on = 'addressed'
     WHERE desk_id = v_id;
  END IF;
  SELECT v_id AS id, v_nm AS name, v_type AS name_type, 'deleted' AS op, v_released AS released;
END //

-- ---------- reclaim (admin.md sections 1 and 4) ----------
-- Admin at either trust; the same id comes back (UNIQUE (type, name) was held while retired). Refused while a
-- live seat is that desk or a member of that name. A reclaimed desk has no seat token until reset.
DROP PROCEDURE IF EXISTS sp_name_reclaim //
CREATE PROCEDURE sp_name_reclaim(IN p_by VARCHAR(64), IN p_type VARCHAR(16), IN p_name VARCHAR(64))
BEGIN
  DECLARE v_by BIGINT UNSIGNED DEFAULT b_desk(p_by); DECLARE v_type VARCHAR(8) DEFAULT b_name_type(p_type);
  DECLARE v_id BIGINT UNSIGNED; DECLARE v_del DATETIME(6); DECLARE v_nm VARCHAR(64);
  IF NOT b_is_admin(v_by) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Admin only: reclaim'; END IF;
  SELECT id, deleted, name INTO v_id, v_del, v_nm FROM name WHERE type = v_type AND name = TRIM(p_name) FOR UPDATE;
  IF v_id IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name not found'; END IF;
  IF v_id IN (0, 1, 2) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cannot reclaim a seed (System, Office, Admin)'; END IF;
  IF v_del IS NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name is live (not retired)'; END IF;
  IF EXISTS (SELECT 1 FROM seat WHERE token_hash IS NOT NULL AND token_hash <> ''
              AND (desk_id = v_id OR desk_id IN (SELECT desk_id FROM member WHERE name_id = v_id))) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name in use: mill reset first, then mill reclaim';
  END IF;
  UPDATE name SET deleted = NULL WHERE id = v_id;
  SELECT v_id AS id, v_nm AS name, v_type AS name_type, 'reclaimed' AS op,
         (SELECT COUNT(*) FROM member WHERE name_id = v_id OR desk_id = v_id) AS members;
END //

-- ---------- label rank renumber (owner rule: ordinals with periodic renumber) ----------
-- Spreads one label's ranked rows (ord 1..65534) evenly over 1..65534 in their current order; 0 (pinned) and
-- 65535 (unplaced) keep their meaning and are not touched. Run when an insert finds no gap.
DROP PROCEDURE IF EXISTS sp_label_renumber //
CREATE PROCEDURE sp_label_renumber(IN p_label BIGINT UNSIGNED)
BEGIN
  DECLARE v_n INT;
  SELECT COUNT(*) INTO v_n FROM label WHERE name_id = p_label AND ord BETWEEN 1 AND 65534;
  UPDATE label l JOIN (
    SELECT type, id, ROW_NUMBER() OVER (ORDER BY ord, created, type, id) AS rn
      FROM label WHERE name_id = p_label AND ord BETWEEN 1 AND 65534) r ON r.type = l.type AND r.id = l.id
     SET l.ord = 1 + FLOOR((r.rn - 1) * 65533 / GREATEST(v_n, 1))
   WHERE l.name_id = p_label;
  SELECT p_label AS label, v_n AS renumbered;
END //

-- ---------- trust (admin.md: show is any seated desk; set is Admin) ----------
-- No table holds trust. Show returns b_trust(). A set is guarded here (Admin, a known level) and answers the level to
-- apply; the server then writes config.toml and re-creates b_trust() (schema-design.md section 9).
DROP PROCEDURE IF EXISTS cmd_trust //
CREATE PROCEDURE cmd_trust(IN p_by VARCHAR(64), IN p_level VARCHAR(8))
BEGIN
  DECLARE v_by BIGINT UNSIGNED DEFAULT b_desk(p_by);
  IF p_level IS NOT NULL AND TRIM(p_level) <> '' THEN
    IF LOWER(TRIM(p_level)) NOT IN ('high','limited') THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'mill trust: high or limited'; END IF;
    IF NOT b_is_admin(v_by) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Admin only: set trust'; END IF;
    SELECT LOWER(TRIM(p_level)) AS trust, 'set' AS op;
  ELSE
    SELECT b_trust() AS trust, 'show' AS op;
  END IF;
END //

-- ---------- Admin grant (admin.md section 1: host loopback only) ----------
-- Granted to the host database user only. Remove needs an Admin p_by, and the last Admin stays.
DROP PROCEDURE IF EXISTS sp_admin_set //
CREATE PROCEDURE sp_admin_set(IN p_by VARCHAR(64), IN p_desk VARCHAR(64), IN p_on TINYINT)
BEGIN
  DECLARE v BIGINT UNSIGNED DEFAULT mill_desk_id(p_desk); DECLARE v_by BIGINT UNSIGNED DEFAULT mill_desk_id(p_by);
  IF IFNULL(v, 0) = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name not found'; END IF;
  SELECT id FROM name WHERE id = 2 FOR UPDATE;
  IF p_on THEN
    INSERT IGNORE INTO member (name_id, desk_id) VALUES (2, v);
    UPDATE name SET n = (SELECT COUNT(*) FROM member WHERE name_id = 2) WHERE id = 2;
  ELSE
    IF NOT b_is_admin(v_by) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Admin only: remove from Admin'; END IF;
    IF (SELECT COUNT(*) FROM member WHERE name_id = 2 AND desk_id <> v) = 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Admin: the last Admin stays'; END IF;
    DELETE FROM member WHERE name_id = 2 AND desk_id = v;
    UPDATE name SET n = (SELECT COUNT(*) FROM member WHERE name_id = 2) WHERE id = 2;
  END IF;
  SELECT p_desk AS desk, b_is_admin(v) AS admin;
END //

-- ---------- hard purge of a trashed roster|label|tree (card 879 / F218) ----------
-- mill delete stamps name.trashed (Python/sp_name_trash). mill restore clears it.
-- mill purge calls sp_name_purge: only trashed + unreferenced; sets @mill_allow_name_hard_delete
-- so name_no_delete allows the DELETE for roster|label|tree. Desks stay refused by the trigger.
-- Timeline: one doing+activity row with act delete|restore|purge (shared activity timeline).

DROP PROCEDURE IF EXISTS sp_name_trash //
CREATE PROCEDURE sp_name_trash(IN p_by VARCHAR(64), IN p_type VARCHAR(16), IN p_name VARCHAR(64))
BEGIN
  DECLARE v_by BIGINT UNSIGNED DEFAULT b_desk(p_by);
  DECLARE v_type VARCHAR(8); DECLARE v_id BIGINT UNSIGNED; DECLARE v_del DATETIME(6);
  DECLARE v_tr DATETIME(6); DECLARE v_nm VARCHAR(64); DECLARE v_now DATETIME(6) DEFAULT NOW(6);
  DECLARE v_doing BIGINT UNSIGNED; DECLARE v_members INT DEFAULT 0; DECLARE v_sole TINYINT DEFAULT 0;
  SET v_type = LOWER(TRIM(p_type));
  IF v_type NOT IN ('roster','label','tree') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'delete: type is roster, label or tree (desks keep mill retire)';
  END IF;
  SELECT id, deleted, trashed, name INTO v_id, v_del, v_tr, v_nm
    FROM name WHERE type = v_type AND name = TRIM(p_name) FOR UPDATE;
  IF v_id IS NULL OR v_del IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'delete: no live name (mill reclaim if retired)';
  END IF;
  IF v_id IN (1, 2) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'delete: Office and Admin never hard-delete; nothing changed';
  END IF;
  IF v_tr IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'delete: already trashed; mill restore or mill purge';
  END IF;
  -- Card 938: roster trash gated the same way as restore/purge (sole member or Admin).
  IF v_type = 'roster' THEN
    SELECT COUNT(*) INTO v_members FROM member WHERE name_id = v_id AND name_kind = 'roster';
    SELECT IFNULL(MAX(desk_id = v_by), 0) INTO v_sole
      FROM member WHERE name_id = v_id AND name_kind = 'roster';
    IF NOT b_is_admin(v_by) THEN
      IF v_members = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'delete: only Admin can trash a roster with no members';
      END IF;
      IF v_members <> 1 OR v_sole = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'delete: sole remaining member or Admin; nothing changed';
      END IF;
    END IF;
  END IF;
  UPDATE name SET trashed = v_now WHERE id = v_id;
  INSERT INTO doing (created, desk_id, roster_id, text, act)
    VALUES (v_now, v_by, 1, CONCAT(v_type, ':', v_nm), 'delete');
  SET v_doing = LAST_INSERT_ID();
  CALL mill_activity_put('doing', v_doing, v_now, v_by, 1, 'delete', NULL);
  SELECT v_id AS id, v_nm AS name, v_type AS name_type, 'deleted' AS op;
END //

DROP PROCEDURE IF EXISTS sp_name_restore //
CREATE PROCEDURE sp_name_restore(IN p_by VARCHAR(64), IN p_type VARCHAR(16), IN p_name VARCHAR(64))
BEGIN
  DECLARE v_by BIGINT UNSIGNED DEFAULT b_desk(p_by);
  DECLARE v_type VARCHAR(8); DECLARE v_id BIGINT UNSIGNED; DECLARE v_del DATETIME(6);
  DECLARE v_tr DATETIME(6); DECLARE v_nm VARCHAR(64); DECLARE v_now DATETIME(6) DEFAULT NOW(6);
  DECLARE v_doing BIGINT UNSIGNED; DECLARE v_members INT DEFAULT 0; DECLARE v_sole TINYINT DEFAULT 0;
  SET v_type = LOWER(TRIM(p_type));
  IF v_type NOT IN ('roster','label','tree') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'restore: type is roster, label or tree (desks keep mill retire)';
  END IF;
  SELECT id, deleted, trashed, name INTO v_id, v_del, v_tr, v_nm
    FROM name WHERE type = v_type AND name = TRIM(p_name) FOR UPDATE;
  IF v_id IS NULL OR v_del IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'restore: no name (mill delete first to trash)';
  END IF;
  IF v_tr IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'restore: not trashed; mill delete first';
  END IF;
  -- Card 931: restore gated the same way as delete (roster: sole member or Admin).
  IF v_type = 'roster' THEN
    SELECT COUNT(*) INTO v_members FROM member WHERE name_id = v_id AND name_kind = 'roster';
    SELECT IFNULL(MAX(desk_id = v_by), 0) INTO v_sole
      FROM member WHERE name_id = v_id AND name_kind = 'roster';
    IF NOT b_is_admin(v_by) THEN
      IF v_members = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'restore: only Admin can restore a roster with no members';
      END IF;
      IF v_members <> 1 OR v_sole = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'restore: sole remaining member or Admin; nothing changed';
      END IF;
    END IF;
  END IF;
  UPDATE name SET trashed = NULL WHERE id = v_id;
  INSERT INTO doing (created, desk_id, roster_id, text, act)
    VALUES (v_now, v_by, 1, CONCAT(v_type, ':', v_nm), 'restore');
  SET v_doing = LAST_INSERT_ID();
  CALL mill_activity_put('doing', v_doing, v_now, v_by, 1, 'restore', NULL);
  SELECT v_id AS id, v_nm AS name, v_type AS name_type, 'restored' AS op;
END //

DROP PROCEDURE IF EXISTS sp_name_purge //
CREATE PROCEDURE sp_name_purge(IN p_by VARCHAR(64), IN p_type VARCHAR(16), IN p_name VARCHAR(64))
BEGIN
  DECLARE v_by BIGINT UNSIGNED DEFAULT b_desk(p_by);
  DECLARE v_type VARCHAR(8); DECLARE v_id BIGINT UNSIGNED; DECLARE v_del DATETIME(6);
  DECLARE v_tr DATETIME(6); DECLARE v_nm VARCHAR(64); DECLARE v_now DATETIME(6) DEFAULT NOW(6);
  DECLARE v_doing BIGINT UNSIGNED; DECLARE v_n INT DEFAULT 0;
  DECLARE v_members INT DEFAULT 0; DECLARE v_sole TINYINT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    SET @mill_allow_name_hard_delete = NULL;
    RESIGNAL;
  END;
  SET v_type = LOWER(TRIM(p_type));
  IF v_type NOT IN ('roster','label','tree') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: type is roster, label or tree (desks keep mill retire)';
  END IF;
  SELECT id, deleted, trashed, name INTO v_id, v_del, v_tr, v_nm
    FROM name WHERE type = v_type AND name = TRIM(p_name) FOR UPDATE;
  IF v_id IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: no name (mill delete then purge)';
  END IF;
  IF v_id IN (1, 2) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'delete: Office and Admin never hard-delete; nothing changed';
  END IF;
  IF v_tr IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: trash with mill delete first';
  END IF;
  IF v_type = 'roster' THEN
    SELECT COUNT(*) INTO v_n FROM todo WHERE roster_id = v_id;
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: roster is referenced (cards); mill retire soft-deletes instead'; END IF;
    SELECT COUNT(*) INTO v_n FROM mail WHERE roster_id = v_id;
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: roster is referenced (letters); mill retire soft-deletes instead'; END IF;
    SELECT COUNT(*) INTO v_n FROM score WHERE roster_id = v_id;
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: roster is referenced (scores); mill retire soft-deletes instead'; END IF;
    SELECT COUNT(*) INTO v_n FROM doing WHERE roster_id = v_id;
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: roster is referenced (doing rows); mill retire soft-deletes instead'; END IF;
    SELECT COUNT(*) INTO v_n FROM activity WHERE roster_id = v_id;
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: roster is referenced (activity rows); mill retire soft-deletes instead'; END IF;
    SELECT COUNT(*) INTO v_n FROM human_member WHERE name_id = v_id AND name_kind = 'roster';
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: roster is referenced (human roles); mill retire soft-deletes instead'; END IF;
    SELECT COUNT(*) INTO v_members FROM member WHERE name_id = v_id AND name_kind = 'roster';
    SELECT IFNULL(MAX(desk_id = v_by), 0) INTO v_sole
      FROM member WHERE name_id = v_id AND name_kind = 'roster';
    IF v_members > 1 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: roster is referenced (members); mill retire soft-deletes instead';
    END IF;
    IF v_members = 1 AND v_sole = 0 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: roster is referenced (a member that is not you); mill retire soft-deletes instead';
    END IF;
    IF NOT b_is_admin(v_by) THEN
      IF v_members = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: only Admin can purge a roster with no members';
      END IF;
    END IF;
  ELSEIF v_type = 'label' THEN
    -- Card 931: purge of label/tree is Admin only (cli-desk.md; roster keeps sole-member path above).
    IF NOT b_is_admin(v_by) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: Admin only for a label';
    END IF;
    SELECT COUNT(*) INTO v_n FROM label WHERE name_id = v_id AND name_kind = 'label';
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: label is on items; mill retire soft-deletes instead'; END IF;
  ELSE
    IF NOT b_is_admin(v_by) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: Admin only for a tree';
    END IF;
    SELECT COUNT(*) INTO v_n FROM tree WHERE name_id = v_id AND name_kind = 'tree';
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: tree has nodes; remove them first, or mill retire soft-deletes'; END IF;
    SELECT COUNT(*) INTO v_n FROM tree_read WHERE tree_id = v_id;
    IF v_n > 0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'purge: tree has read cursors; clear them, or mill retire soft-deletes'; END IF;
  END IF;
  INSERT INTO doing (created, desk_id, roster_id, text, act)
    VALUES (v_now, v_by, 1, CONCAT(v_type, ':', v_nm), 'purge');
  SET v_doing = LAST_INSERT_ID();
  CALL mill_activity_put('doing', v_doing, v_now, v_by, 1, 'purge', NULL);
  SET @mill_allow_name_hard_delete = 1;
  IF v_type = 'roster' THEN
    DELETE FROM member WHERE name_id = v_id AND name_kind = 'roster';
  END IF;
  DELETE FROM name WHERE id = v_id AND type = v_type AND trashed IS NOT NULL;
  SET @mill_allow_name_hard_delete = NULL;
  SELECT v_id AS id, v_nm AS name, v_type AS name_type, 'purged' AS op;
END //


DELIMITER ;
