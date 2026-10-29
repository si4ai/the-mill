-- Nested set. Structure only. name_id is the plan (name.type = tree, bare name).
-- A node is one row and always has an activity payload (mail, todo, join, hold, score).
-- The first card is lft 1, rgt 2. Naming the plan does not insert a node.

DROP PROCEDURE IF EXISTS mill_tree_create;
DROP PROCEDURE IF EXISTS mill_tree_add;
DROP PROCEDURE IF EXISTS mill_tree_move;
DROP PROCEDURE IF EXISTS mill_tree_remove;
DROP PROCEDURE IF EXISTS mill_tree_detach_one;
DROP PROCEDURE IF EXISTS mill_tree_detach;
DROP PROCEDURE IF EXISTS mill_tree_prune;
DROP PROCEDURE IF EXISTS mill_tree_delete;
DROP PROCEDURE IF EXISTS mill_tree_select;
DROP PROCEDURE IF EXISTS mill_tree_subtree;
DROP PROCEDURE IF EXISTS mill_tree_ancestors;
DROP PROCEDURE IF EXISTS mill_tree_watchers;

DELIMITER //

CREATE PROCEDURE mill_tree_create(
  IN p_tree VARCHAR(64),
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE v_type VARCHAR(16);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_ts DATETIME(6);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_name = MILL_NAME_PUT('tree', p_tree);
  SELECT id FROM name WHERE id = v_name FOR UPDATE;
  IF EXISTS (SELECT 1 FROM tree WHERE name_id = v_name LIMIT 1) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree exists';
  END IF;
  SET v_type = NULLIF(TRIM(p_type), '');
  SET v_id = IFNULL(p_id, 0);
  IF v_type IS NULL OR v_id = 0 OR v_type NOT IN ('mail','todo','doing','hold','score') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree node requires a payload';
  END IF;
  CALL mill_activity_put(v_type, v_id, v_ts, 1, NULL, NULL, NULL);
  INSERT INTO tree (name_id, type, id, lft, rgt)
  VALUES (v_name, v_type, v_id, 1, 2);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_name AS name_id, v_type AS type, v_id AS id, 1 AS lft, 2 AS rgt, 'created' AS op;
END //

CREATE PROCEDURE mill_tree_add(
  IN p_tree         VARCHAR(64),
  IN p_parent_type  VARCHAR(16),
  IN p_parent_id    BIGINT UNSIGNED,
  IN p_type         VARCHAR(16),
  IN p_id           BIGINT UNSIGNED
)
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE v_r INT UNSIGNED;
  DECLARE v_n INT;
  DECLARE v_ts DATETIME(6);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_n = 0;
  SET v_name = NULL;
  IF p_tree IS NOT NULL AND TRIM(p_tree) <> '' THEN
    SET v_name = MILL_NAME_PUT('tree', p_tree);
  ELSE
    SELECT COUNT(DISTINCT name_id) INTO v_n
      FROM tree WHERE type = p_parent_type AND id = p_parent_id;
    IF v_n > 1 THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'which TREE_* (activity is on more than one plan)';
    END IF;
    IF v_n = 1 THEN
      SELECT name_id INTO v_name
        FROM tree WHERE type = p_parent_type AND id = p_parent_id LIMIT 1;
    END IF;
  END IF;
  IF v_name IS NULL THEN
    SET v_name = MILL_NAME_PUT('tree', LOWER(HEX(RANDOM_BYTES(5))));
    CALL mill_activity_put(p_parent_type, p_parent_id, v_ts, 1, NULL, NULL, NULL);
    INSERT INTO tree (name_id, type, id, lft, rgt)
    VALUES (v_name, p_parent_type, p_parent_id, 1, 2);
  END IF;
  SELECT id FROM name WHERE id = v_name FOR UPDATE;
  SELECT rgt INTO v_r FROM tree
   WHERE name_id = v_name AND type = p_parent_type AND id = p_parent_id
   FOR UPDATE;
  IF v_r IS NULL THEN
    IF EXISTS (SELECT 1 FROM tree WHERE name_id = v_name LIMIT 1) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree parent not found';
    END IF;
    CALL mill_activity_put(p_parent_type, p_parent_id, v_ts, 1, NULL, NULL, NULL);
    INSERT INTO tree (name_id, type, id, lft, rgt)
    VALUES (v_name, p_parent_type, p_parent_id, 1, 2);
    SELECT rgt INTO v_r FROM tree
     WHERE name_id = v_name AND type = p_parent_type AND id = p_parent_id;
  END IF;
  UPDATE tree SET rgt = rgt + 2 WHERE name_id = v_name AND rgt >= v_r ORDER BY rgt DESC;
  UPDATE tree SET lft = lft + 2 WHERE name_id = v_name AND lft > v_r ORDER BY lft DESC;
  INSERT INTO tree (name_id, type, id, lft, rgt)
  VALUES (v_name, p_type, p_id, v_r, v_r + 1);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_name AS name_id, p_type AS type, p_id AS id, v_r AS lft, (v_r + 1) AS rgt, 'added' AS op;
END //

CREATE PROCEDURE mill_tree_move(
  IN p_tree         VARCHAR(64),
  IN p_type         VARCHAR(16),
  IN p_id           BIGINT UNSIGNED,
  IN p_parent_type  VARCHAR(16),
  IN p_parent_id    BIGINT UNSIGNED
)
BEGIN
  -- lft/rgt are INT UNSIGNED: park via positive high-range shift, never negate.
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE v_n INT;
  DECLARE v_nl INT UNSIGNED;
  DECLARE v_nr INT UNSIGNED;
  DECLARE v_w INT UNSIGNED;
  DECLARE v_pr INT UNSIGNED;
  DECLARE v_shift INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_name = NULL;
  SET v_n = 0;
  IF p_tree IS NOT NULL AND TRIM(p_tree) <> '' THEN
    SET v_name = MILL_NAME_GET('tree', p_tree);
  ELSE
    SELECT COUNT(DISTINCT name_id) INTO v_n FROM tree WHERE type = p_type AND id = p_id;
    IF v_n = 0 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree node not found';
    END IF;
    IF v_n > 1 THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'which TREE_* (activity is on more than one plan)';
    END IF;
    SELECT name_id INTO v_name FROM tree WHERE type = p_type AND id = p_id LIMIT 1;
  END IF;
  SELECT id FROM name WHERE id = v_name FOR UPDATE;
  SELECT lft, rgt INTO v_nl, v_nr FROM tree
   WHERE name_id = v_name AND type = p_type AND id = p_id FOR UPDATE;
  SELECT rgt INTO v_pr FROM tree
   WHERE name_id = v_name AND type = p_parent_type AND id = p_parent_id FOR UPDATE;
  IF v_nl IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree node not found';
  END IF;
  IF v_pr IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree parent not found';
  END IF;
  IF v_pr >= v_nl AND v_pr <= v_nr THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree cannot move under its own branch';
  END IF;
  SET v_w = v_nr - v_nl + 1;
  SELECT IFNULL(MAX(rgt), 0) + 1 INTO v_shift FROM tree WHERE name_id = v_name;
  UPDATE tree SET lft = lft + v_shift, rgt = rgt + v_shift
   WHERE name_id = v_name AND lft BETWEEN v_nl AND v_nr;
  UPDATE tree SET rgt = rgt - v_w
   WHERE name_id = v_name AND rgt > v_nr AND lft < v_shift ORDER BY rgt ASC;
  UPDATE tree SET lft = lft - v_w
   WHERE name_id = v_name AND lft > v_nr AND lft < v_shift ORDER BY lft ASC;
  SELECT rgt INTO v_pr FROM tree
   WHERE name_id = v_name AND type = p_parent_type AND id = p_parent_id;
  UPDATE tree SET rgt = rgt + v_w
   WHERE name_id = v_name AND rgt >= v_pr AND lft < v_shift ORDER BY rgt DESC;
  UPDATE tree SET lft = lft + v_w
   WHERE name_id = v_name AND lft >= v_pr AND lft < v_shift ORDER BY lft DESC;
  UPDATE tree
     SET lft = v_pr + (lft - v_shift - v_nl),
         rgt = v_pr + (rgt - v_shift - v_nl)
   WHERE name_id = v_name AND lft >= v_shift;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_name AS name_id, p_type AS type, p_id AS id, 'moved' AS op;
END //

CREATE PROCEDURE mill_tree_remove(
  IN p_tree VARCHAR(64),
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE v_n INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_name = NULL;
  SET v_n = 0;
  IF p_tree IS NOT NULL AND TRIM(p_tree) <> '' THEN
    SET v_name = MILL_NAME_GET('tree', p_tree);
  ELSE
    SELECT COUNT(DISTINCT name_id) INTO v_n FROM tree WHERE type = p_type AND id = p_id;
    IF v_n = 0 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree node not found';
    END IF;
    IF v_n > 1 THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'which TREE_* (activity is on more than one plan)';
    END IF;
    SELECT name_id INTO v_name FROM tree WHERE type = p_type AND id = p_id LIMIT 1;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM tree WHERE name_id = v_name AND type = p_type AND id = p_id
  ) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree node not found';
  END IF;
  CALL mill_tree_detach_one(v_name, p_type, p_id);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_name AS name_id, p_type AS type, p_id AS id, 'removed' AS op;
END //

-- One node off one plan. Children move up to the node's parent. No transaction of its own:
-- mill_tree_remove and the delete SPs (mill_mail_delete, mill_todo_delete, mill_score_delete)
-- call it inside theirs. A node not on that plan is a no-op.
CREATE PROCEDURE mill_tree_detach_one(
  IN p_name BIGINT UNSIGNED,
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_l INT UNSIGNED;
  DECLARE v_r INT UNSIGNED;
  SELECT id FROM name WHERE id = p_name FOR UPDATE;
  SELECT lft, rgt INTO v_l, v_r FROM tree
   WHERE name_id = p_name AND type = p_type AND id = p_id
   FOR UPDATE;
  IF v_l IS NOT NULL THEN
    DELETE FROM tree WHERE name_id = p_name AND type = p_type AND id = p_id;
    UPDATE tree SET lft = lft - 1, rgt = rgt - 1
     WHERE name_id = p_name AND lft BETWEEN v_l AND v_r;
    UPDATE tree SET rgt = rgt - 2 WHERE name_id = p_name AND rgt > v_r ORDER BY rgt ASC;
    UPDATE tree SET lft = lft - 2 WHERE name_id = p_name AND lft > v_r ORDER BY lft ASC;
  END IF;
END //

-- The node off every plan it sits on (mill_tree_detach_one per plan). No transaction of its own.
CREATE PROCEDURE mill_tree_detach(
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  SET v_name = (SELECT MIN(name_id) FROM tree WHERE type = p_type AND id = p_id);
  WHILE v_name IS NOT NULL DO
    CALL mill_tree_detach_one(v_name, p_type, p_id);
    SET v_name = (SELECT MIN(name_id) FROM tree WHERE type = p_type AND id = p_id);
  END WHILE;
END //

CREATE PROCEDURE mill_tree_prune(
  IN p_tree VARCHAR(64),
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE v_l INT UNSIGNED;
  DECLARE v_r INT UNSIGNED;
  DECLARE v_w INT UNSIGNED;
  DECLARE v_n INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_name = NULL;
  SET v_n = 0;
  IF p_tree IS NOT NULL AND TRIM(p_tree) <> '' THEN
    SET v_name = MILL_NAME_GET('tree', p_tree);
  ELSE
    SELECT COUNT(DISTINCT name_id) INTO v_n FROM tree WHERE type = p_type AND id = p_id;
    IF v_n = 0 THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree node not found';
    END IF;
    IF v_n > 1 THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'which TREE_* (activity is on more than one plan)';
    END IF;
    SELECT name_id INTO v_name FROM tree WHERE type = p_type AND id = p_id LIMIT 1;
  END IF;
  SELECT id FROM name WHERE id = v_name FOR UPDATE;
  SELECT lft, rgt INTO v_l, v_r FROM tree
   WHERE name_id = v_name AND type = p_type AND id = p_id
   FOR UPDATE;
  IF v_l IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree node not found';
  END IF;
  SET v_w = v_r - v_l + 1;
  DELETE FROM tree WHERE name_id = v_name AND lft BETWEEN v_l AND v_r;
  UPDATE tree SET rgt = rgt - v_w WHERE name_id = v_name AND rgt > v_r ORDER BY rgt ASC;
  UPDATE tree SET lft = lft - v_w WHERE name_id = v_name AND lft > v_r ORDER BY lft ASC;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_name AS name_id, p_type AS type, p_id AS id, v_w AS width, 'pruned' AS op;
END //

CREATE PROCEDURE mill_tree_delete(IN p_tree VARCHAR(64))
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_name = MILL_NAME_GET('tree', p_tree);
  DELETE FROM tree WHERE name_id = v_name;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_name AS name_id, 'deleted' AS op;
END //

CREATE PROCEDURE mill_tree_select(IN p_tree VARCHAR(64))
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  SET v_name = MILL_NAME_GET('tree', p_tree);
  SELECT t.name_id, t.type, t.id, t.lft, t.rgt, n.name AS tree, n.type AS tree_type
    FROM tree t
    JOIN name n ON n.id = t.name_id
   WHERE t.name_id = v_name
   ORDER BY t.lft;
END //

CREATE PROCEDURE mill_tree_subtree(
  IN p_tree VARCHAR(64),
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  SET v_name = MILL_NAME_GET('tree', p_tree);
  SELECT c.name_id, c.type, c.id, c.lft, c.rgt
    FROM tree AS p
    JOIN tree AS c
      ON c.name_id = p.name_id
     AND c.lft BETWEEN p.lft AND p.rgt
   WHERE p.name_id = v_name AND p.type = p_type AND p.id = p_id
   ORDER BY c.lft;
END //

CREATE PROCEDURE mill_tree_ancestors(
  IN p_tree VARCHAR(64),
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_name BIGINT UNSIGNED;
  SET v_name = MILL_NAME_GET('tree', p_tree);
  SELECT a.name_id, a.type, a.id, a.lft, a.rgt
    FROM tree AS node
    JOIN tree AS a
      ON a.name_id = node.name_id
     AND a.lft <= node.lft
     AND a.rgt >= node.rgt
   WHERE node.name_id = v_name AND node.type = p_type AND node.id = p_id
   ORDER BY a.lft;
END //

CREATE PROCEDURE mill_tree_watchers(
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  -- Watchers on this node and its tree ancestors. A roster watcher expands to
  -- its members here, at wake time (#265).
  SELECT x.desk_id, x.desk, x.desk_type FROM (
    SELECT w.desk_id, w.type, w.id FROM watcher AS w
     WHERE w.type = p_type AND w.id = p_id
    UNION
    SELECT w.desk_id, w.type, w.id
      FROM tree AS node
      JOIN tree AS anc
        ON anc.name_id = node.name_id
       AND anc.lft <= node.lft
       AND anc.rgt >= node.rgt
      JOIN watcher AS w
        ON w.type = anc.type AND w.id = anc.id
     WHERE node.type = p_type AND node.id = p_id
  ) AS hit
  JOIN LATERAL (
    SELECT dn.id AS desk_id, dn.name AS desk, dn.type AS desk_type
      FROM name dn WHERE dn.id = hit.desk_id AND dn.type = 'desk'
    UNION
    SELECT md.id, md.name, md.type
      FROM name r
      JOIN member mb ON mb.name_id = r.id
      JOIN name md ON md.id = mb.desk_id AND md.type = 'desk' AND md.deleted IS NULL
     WHERE r.id = hit.desk_id AND r.type = 'roster'
  ) AS x
  GROUP BY x.desk_id, x.desk, x.desk_type;
END //

DELIMITER ;
