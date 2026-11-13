DROP PROCEDURE IF EXISTS mill_label_put;
DROP PROCEDURE IF EXISTS mill_label_delete;
DROP PROCEDURE IF EXISTS mill_label_select;

DELIMITER //

CREATE PROCEDURE mill_label_put(
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED,
  IN p_label VARCHAR(64),
  IN p_ord  SMALLINT UNSIGNED
)
BEGIN
  DECLARE v_n BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_i INT DEFAULT 1;
  DECLARE v_try VARCHAR(64);
  -- A missed SELECT INTO is "no focus list yet", not an error. A plain INTO takes no shared lock (card 1113).
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_n = NULL;
  -- NULL ord keeps the stored value. A fresh row takes 65535 (#197).
  -- card 1153: updated is when ord was last set; a re-rank to a new ord moves it,
  -- the same ord again does not. It is assigned before ord, so it sees the old ord.
  -- card 1163: a desk name addresses that desk's focus list. The stored label string
  -- is the next free name-N, because the desk already holds the bare string.
  SET v_desk = (SELECT id FROM name
                 WHERE type = 'desk' AND name = TRIM(p_label)
                   AND deleted IS NULL AND trashed IS NULL
                 LIMIT 1);
  IF v_desk IS NOT NULL THEN
    SELECT s.focus_label_id INTO v_n
      FROM seat s
      JOIN name ln ON ln.id = s.focus_label_id AND ln.type = 'label'
       AND ln.deleted IS NULL AND ln.trashed IS NULL
     WHERE s.desk_id = v_desk
     LIMIT 1;
    WHILE v_n IS NULL DO
      SET v_try = CONCAT(TRIM(p_label), '-', v_i);
      IF CHAR_LENGTH(v_try) > 64 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name suffix exceeds 64 characters';
      END IF;
      SET v_n = (SELECT id FROM name WHERE name = v_try LIMIT 1);
      IF v_n IS NULL THEN
        INSERT INTO name (type, name) VALUES ('label', v_try);
        SET v_n = LAST_INSERT_ID();
        UPDATE seat SET focus_label_id = v_n WHERE desk_id = v_desk;
      ELSE
        SET v_n = NULL;
        SET v_i = v_i + 1;
      END IF;
    END WHILE;
  ELSE
    SET v_n = MILL_NAME_PUT('label', p_label);
  END IF;
  INSERT INTO label (type, id, name_id, ord)
  VALUES (p_type, p_id, v_n, COALESCE(p_ord, 65535))
  ON DUPLICATE KEY UPDATE
    updated = IF(COALESCE(p_ord, ord) <> ord, MILL_NOW(), updated),
    ord = COALESCE(p_ord, ord);
  SELECT type, id, name_id, ord
    FROM label
   WHERE type = p_type AND id = p_id AND name_id = v_n;
END //

CREATE PROCEDURE mill_label_delete(
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED,
  IN p_label VARCHAR(64)
)
BEGIN
  DECLARE v_n BIGINT UNSIGNED;
  DECLARE v_rows INT DEFAULT 0;
  -- Unknown name is a refusal. A known name that is not on this row is not removed (#202).
  -- A desk name removes that desk's focus list, not a label whose string is the desk.
  SET v_n = (SELECT id FROM name WHERE type = 'label' AND name = p_label AND deleted IS NULL LIMIT 1);
  IF v_n IS NULL THEN
    SET v_n = (SELECT s.focus_label_id FROM seat s
                JOIN name d ON d.id = s.desk_id AND d.type = 'desk' AND d.name = p_label
                 AND d.deleted IS NULL AND d.trashed IS NULL
                JOIN name ln ON ln.id = s.focus_label_id AND ln.type = 'label' AND ln.deleted IS NULL
               LIMIT 1);
  END IF;
  IF v_n IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'label: no such name';
  END IF;
  DELETE FROM label WHERE type = p_type AND id = p_id AND name_id = v_n;
  SET v_rows = ROW_COUNT();
  IF v_rows = 0 THEN
    SELECT p_type AS type, p_id AS id, 'not-removed' AS op;
  ELSE
    SELECT p_type AS type, p_id AS id, 'removed' AS op;
  END IF;
END //

CREATE PROCEDURE mill_label_select(
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  SELECT l.type, l.id, l.name_id, l.ord, n.name AS label, n.type AS label_type, l.created
    FROM label l
    JOIN name n ON n.id = l.name_id
   WHERE (p_type IS NULL OR p_type = '' OR l.type = p_type)
     AND (p_id IS NULL OR p_id = 0 OR l.id = p_id)
   ORDER BY l.ord, l.created, l.id;
END //

DELIMITER ;
