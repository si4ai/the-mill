DROP PROCEDURE IF EXISTS mill_member_put;
DROP PROCEDURE IF EXISTS mill_member_delete;
DROP PROCEDURE IF EXISTS mill_member_select;
DROP PROCEDURE IF EXISTS mill_member_admin_put;
DROP PROCEDURE IF EXISTS mill_member_admin_delete;

DELIMITER //

CREATE PROCEDURE mill_member_put(
  IN p_kind VARCHAR(16),
  IN p_slot VARCHAR(64),
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_del DATETIME(6);
  DECLARE v_d BIGINT UNSIGNED;
  SELECT id, deleted INTO v_id, v_del
    FROM name WHERE type = p_kind AND name = p_slot LIMIT 1;
  IF v_id IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'no such roster: mill send a mill-host desk to mill roster';
  END IF;
  IF v_del IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name retired: mill reclaim (mill host)';
  END IF;
  -- #675: the reserved Admin roster (id 2) is never reached by name. The name
  -- collation matches any case or accent, so only mill_member_admin_put adds it.
  IF v_id = 2 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'roster Admin: office host only (loopback)';
  END IF;
  SET v_d = MILL_NAME_GET('desk', p_desk);
  -- The member insert locks name(id). Hold that row first, then count the new member.
  SELECT id INTO v_id FROM name WHERE id = v_id FOR UPDATE;
  INSERT IGNORE INTO member (name_id, desk_id) VALUES (v_id, v_d);
  IF ROW_COUNT() = 1 THEN
    UPDATE name SET n = n + 1 WHERE id = v_id;
  END IF;
  SELECT v_id AS name_id, v_d AS desk_id, (SELECT n FROM name WHERE id = v_id) AS n;
END //

CREATE PROCEDURE mill_member_delete(
  IN p_kind VARCHAR(16),
  IN p_slot VARCHAR(64),
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_d BIGINT UNSIGNED;
  SELECT id INTO v_id FROM name WHERE type = p_kind AND name = p_slot LIMIT 1;
  SELECT id INTO v_d FROM name WHERE type = 'desk' AND name = p_desk LIMIT 1;
  IF v_id IS NULL OR v_d IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name not found';
  END IF;
  IF v_id = 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cannot leave Office';
  END IF;
  -- #675: off Admin only through mill_member_admin_delete (office host).
  IF v_id = 2 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'roster Admin: office host only (loopback)';
  END IF;
  DELETE FROM member WHERE name_id = v_id AND desk_id = v_d;
  IF ROW_COUNT() = 1 THEN
    UPDATE name SET n = IF(n > 0, n - 1, 0) WHERE id = v_id;
  END IF;
  SELECT p_desk AS desk, 'removed' AS op, (SELECT n FROM name WHERE id = v_id) AS n;
END //

-- #675: the office host Admin grant. The caller is the loopback member-add path
-- only (rpc._h_member with a wall-set host flag); the roster is fixed to id 2.
CREATE PROCEDURE mill_member_admin_put(
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_d BIGINT UNSIGNED;
  DECLARE v_lock BIGINT UNSIGNED;
  SET v_d = MILL_NAME_GET('desk', p_desk);
  IF v_d IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name not found';
  END IF;
  -- The member insert locks name(id). Hold Admin first, then count the new member.
  SELECT id INTO v_lock FROM name WHERE id = 2 FOR UPDATE;
  INSERT IGNORE INTO member (name_id, desk_id) VALUES (2, v_d);
  IF ROW_COUNT() = 1 THEN
    UPDATE name SET n = n + 1 WHERE id = 2;
  END IF;
  SELECT 2 AS name_id, v_d AS desk_id, (SELECT n FROM name WHERE id = 2) AS n;
END //

CREATE PROCEDURE mill_member_admin_delete(
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_d BIGINT UNSIGNED;
  SELECT id INTO v_d FROM name WHERE type = 'desk' AND name = p_desk LIMIT 1;
  IF v_d IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name not found';
  END IF;
  DELETE FROM member WHERE name_id = 2 AND desk_id = v_d;
  IF ROW_COUNT() = 1 THEN
    UPDATE name SET n = IF(n > 0, n - 1, 0) WHERE id = 2;
  END IF;
  SELECT p_desk AS desk, 'removed' AS op, (SELECT n FROM name WHERE id = 2) AS n;
END //

CREATE PROCEDURE mill_member_select(
  IN p_kind VARCHAR(16),
  IN p_slot VARCHAR(64),
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_d BIGINT UNSIGNED;
  IF p_desk IS NOT NULL AND p_desk <> '' THEN
    SELECT id INTO v_d FROM name WHERE type = 'desk' AND name = p_desk LIMIT 1;
    SELECT m.name_id, m.desk_id, m.created, sn.name AS slot, sn.type AS slot_type, dn.name AS desk, dn.type AS desk_type
    FROM member m
    LEFT JOIN name sn ON sn.id = m.name_id
    LEFT JOIN name dn ON dn.id = m.desk_id
    WHERE m.desk_id = v_d;
  ELSEIF p_slot IS NOT NULL AND p_slot <> '' THEN
    SELECT id INTO v_id FROM name WHERE type = p_kind AND name = p_slot LIMIT 1;
    SELECT m.name_id, m.desk_id, m.created, sn.name AS slot, sn.type AS slot_type, dn.name AS desk, dn.type AS desk_type
    FROM member m
    LEFT JOIN name sn ON sn.id = m.name_id
    LEFT JOIN name dn ON dn.id = m.desk_id
    WHERE m.name_id = v_id;
  ELSE
    SELECT m.name_id, m.desk_id, m.created, sn.name AS slot, sn.type AS slot_type, dn.name AS desk, dn.type AS desk_type
    FROM member m
    LEFT JOIN name sn ON sn.id = m.name_id
    LEFT JOIN name dn ON dn.id = m.desk_id;
  END IF;
END //

DELIMITER ;
