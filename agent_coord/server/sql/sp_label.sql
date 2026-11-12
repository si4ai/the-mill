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
  -- NULL ord keeps the stored value. A fresh row takes 65535 (#197).
  -- card 1153: updated is when ord was last set; a re-rank to a new ord moves it,
  -- the same ord again does not. It is assigned before ord, so it sees the old ord.
  SET v_n = MILL_NAME_PUT('label', p_label);
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
  SELECT id INTO v_n FROM name WHERE type = 'label' AND name = p_label AND deleted IS NULL LIMIT 1;
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
