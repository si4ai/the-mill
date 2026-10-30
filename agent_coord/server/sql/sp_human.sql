-- Human wall bearer. The person holds the secret. The book stores the hash.
-- Apply with the other procedures. Do not run against a live book until the
-- wall check is the one this file defines.

DROP PROCEDURE IF EXISTS mill_human_open;
DROP PROCEDURE IF EXISTS mill_human_put;
DROP PROCEDURE IF EXISTS mill_human_roles;

DELIMITER //

CREATE PROCEDURE mill_human_open(IN p_hash CHAR(64))
BEGIN
  SELECT h.id, h.directory_sub
  FROM human h
  WHERE h.bearer_hash = p_hash
  LIMIT 1;
END //

CREATE PROCEDURE mill_human_put(
  IN p_hash CHAR(64),
  IN p_sub  VARCHAR(255)
)
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_sub VARCHAR(255);
  SET v_sub = NULLIF(LEFT(IFNULL(p_sub, ''), 255), '');
  IF p_hash IS NULL OR CHAR_LENGTH(p_hash) <> 64 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'human bearer hash required';
  END IF;
  IF v_sub IS NOT NULL THEN
    SELECT id INTO v_id FROM human WHERE directory_sub = v_sub LIMIT 1;
  END IF;
  IF v_id IS NULL THEN
    SELECT id INTO v_id FROM human WHERE bearer_hash = p_hash LIMIT 1;
  END IF;
  IF v_id IS NULL THEN
    INSERT INTO human (bearer_hash, directory_sub) VALUES (p_hash, v_sub);
    SET v_id = LAST_INSERT_ID();
  ELSE
    UPDATE human
      SET bearer_hash = p_hash,
          directory_sub = IFNULL(v_sub, directory_sub)
      WHERE id = v_id;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_sub AS directory_sub;
END //

CREATE PROCEDURE mill_human_roles(
  IN p_id   BIGINT UNSIGNED,
  IN p_role VARCHAR(64)
)
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  DELETE FROM human_member WHERE human_id = p_id;
  IF p_role IS NOT NULL AND p_role <> '' THEN
    SET v_name = MILL_NAME_GET('roster', p_role);
    IF v_name IS NOT NULL THEN
      INSERT IGNORE INTO human_member (human_id, name_id) VALUES (p_id, v_name);
    END IF;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, IFNULL(p_role, '') AS role;
END //

DELIMITER ;
