DROP PROCEDURE IF EXISTS mill_todo_insert;
DROP PROCEDURE IF EXISTS mill_todo_insert_attached;
DROP PROCEDURE IF EXISTS mill_todo_update;
DROP PROCEDURE IF EXISTS mill_todo_delete;
DROP PROCEDURE IF EXISTS mill_todo_select;
DROP PROCEDURE IF EXISTS mill_todo_page;
DROP PROCEDURE IF EXISTS mill_todo_get;
DROP PROCEDURE IF EXISTS mill_todo_retire;
DROP PROCEDURE IF EXISTS mill_todo_reclaim;

DELIMITER //

CREATE PROCEDURE mill_todo_insert(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64),
  IN p_status  VARCHAR(16),
  IN p_body    VARCHAR(4096)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_proj = MILL_NAME_GET('roster', p_project);
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_proj IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such project (MILL_NAME_GET)';
  END IF;
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  -- Payload first (#216). The todo table assigns the id; LAST_INSERT_ID() is that id.
  -- Then the activity row (the timeline; todo has no FK to it). No lock, no catalog read.
  INSERT INTO todo (updated, updated_id, roster_id, creator_id, status, body)
  VALUES (v_ts, v_desk, v_proj, v_desk, IFNULL(NULLIF(p_status, ''), 'open'), IFNULL(p_body, ''));
  SET v_id = LAST_INSERT_ID();
  CALL mill_activity_put('todo', v_id, v_ts, v_desk, v_proj, MILL_WEIGHT('todo'), LENGTH(IFNULL(p_body, '')));
  CALL mill_watcher_roster('todo', v_id, v_proj, v_desk);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, p_status AS status;
END //

-- New card plus its tree place in one transaction (#146).
-- mill_tree_add commits on its own, so a failed attach used to leave the card.
-- Do not CALL it. The parent activity row is locked before the plan is chosen.
CREATE PROCEDURE mill_todo_insert_attached(
  IN p_project     VARCHAR(64),
  IN p_desk        VARCHAR(64),
  IN p_status      VARCHAR(16),
  IN p_body        VARCHAR(4096),
  IN p_parent_type VARCHAR(16),
  IN p_parent_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE v_r INT UNSIGNED;
  DECLARE v_n INT;
  DECLARE v_lock BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_proj = MILL_NAME_GET('roster', p_project);
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_proj IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such project (MILL_NAME_GET)';
  END IF;
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  -- Payload first (#216). The todo table assigns the id; LAST_INSERT_ID() is that id.
  -- Then the activity row (the timeline; todo has no FK to it). No lock, no catalog read.
  INSERT INTO todo (updated, updated_id, roster_id, creator_id, status, body)
  VALUES (v_ts, v_desk, v_proj, v_desk, IFNULL(NULLIF(p_status, ''), 'open'), IFNULL(p_body, ''));
  SET v_id = LAST_INSERT_ID();
  CALL mill_activity_put('todo', v_id, v_ts, v_desk, v_proj, MILL_WEIGHT('todo'), LENGTH(IFNULL(p_body, '')));
  CALL mill_watcher_roster('todo', v_id, v_proj, v_desk);
  SELECT id INTO v_lock FROM activity
   WHERE type = p_parent_type AND id = p_parent_id
   FOR UPDATE;
  SET v_n = 0;
  SET v_name = NULL;
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
  IF v_name IS NULL THEN
    SET v_name = MILL_NAME_PUT('tree', LOWER(HEX(RANDOM_BYTES(5))));
    CALL mill_activity_put(p_parent_type, p_parent_id, v_ts, 1, NULL, MILL_WEIGHT(p_parent_type), NULL);
    INSERT INTO tree (name_id, type, id, lft, rgt)
    VALUES (v_name, p_parent_type, p_parent_id, 1, 2);
  END IF;
  -- INTO, so this lock is not a client result set ahead of the card id.
  SELECT id INTO v_lock FROM name WHERE id = v_name FOR UPDATE;
  SELECT rgt INTO v_r FROM tree
   WHERE name_id = v_name AND type = p_parent_type AND id = p_parent_id
   FOR UPDATE;
  IF v_r IS NULL THEN
    IF EXISTS (SELECT 1 FROM tree WHERE name_id = v_name LIMIT 1) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tree parent not found';
    END IF;
    CALL mill_activity_put(p_parent_type, p_parent_id, v_ts, 1, NULL, MILL_WEIGHT(p_parent_type), NULL);
    INSERT INTO tree (name_id, type, id, lft, rgt)
    VALUES (v_name, p_parent_type, p_parent_id, 1, 2);
    SELECT rgt INTO v_r FROM tree
     WHERE name_id = v_name AND type = p_parent_type AND id = p_parent_id;
  END IF;
  UPDATE tree SET rgt = rgt + 2 WHERE name_id = v_name AND rgt >= v_r ORDER BY rgt DESC;
  UPDATE tree SET lft = lft + 2 WHERE name_id = v_name AND lft > v_r ORDER BY lft DESC;
  INSERT INTO tree (name_id, type, id, lft, rgt)
  VALUES (v_name, 'todo', v_id, v_r, v_r + 1);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, p_status AS status, v_name AS name_id, v_r AS lft;
END //

CREATE PROCEDURE mill_todo_update(
  IN p_id        BIGINT UNSIGNED,
  IN p_desk      VARCHAR(64),
  IN p_status    VARCHAR(16),
  IN p_volunteer VARCHAR(64),
  IN p_body      VARCHAR(4096)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_vol BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_vol = CASE
    WHEN p_volunteer IS NULL OR p_volunteer = '' THEN NULL
    WHEN p_volunteer = '-' THEN NULL
    ELSE MILL_NAME_GET('desk', p_volunteer)
  END;
  SELECT roster_id INTO v_proj FROM todo WHERE id = p_id;
  -- #818 D2: claimed_at is first, so it reads the old status and volunteer
  -- (MySQL assigns left to right). A claim, a new volunteer or a step back to
  -- claimed stamps it; leaving claimed clears it; anything else keeps it.
  UPDATE todo
     SET claimed_at = CASE
           WHEN IFNULL(NULLIF(p_status, ''), status) <> 'claimed' THEN NULL
           WHEN status <> 'claimed' OR claimed_at IS NULL THEN v_ts
           WHEN p_volunteer IS NOT NULL AND p_volunteer NOT IN ('', '-')
                AND NOT (v_vol <=> assigned_id) THEN v_ts
           ELSE claimed_at
         END,
         updated = v_ts,
         updated_id = v_desk,
         status = IFNULL(NULLIF(p_status, ''), status),
         assigned_id = CASE
           WHEN p_volunteer = '-' THEN NULL
           WHEN p_volunteer IS NULL OR p_volunteer = '' THEN assigned_id
           ELSE v_vol
         END,
         body = IFNULL(p_body, body)
   WHERE id = p_id;
  CALL mill_activity_put('todo', p_id, v_ts, v_desk, v_proj, MILL_WEIGHT('todo'), LENGTH(p_body));
  CALL mill_watcher_roster('todo', p_id, v_proj, v_desk);
  IF v_vol IS NOT NULL THEN
    CALL mill_watcher_put('todo', p_id, v_vol);
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, v_ts AS updated;
END //

CREATE PROCEDURE mill_todo_delete(
  IN p_id   BIGINT UNSIGNED,
  IN p_desk VARCHAR(64)
)
BEGIN
  -- Soft-delete: off every tree plan (children move up), watchers dropped, card deleted,
  -- activity.deleted stamped. Labels stay. No mill_activity_put; desk_id kept.
  -- #185: the stamp is not gated on DELETE ROW_COUNT. DELETE todo can drop the
  -- activity row (a trigger, or a cascade). Read the row first and put the stamp
  -- back after the card is gone. A card with no activity row still gets a
  -- tombstone from the caller desk and the card's roster. The first stamp is kept.
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_aff BIGINT UNSIGNED;
  DECLARE v_created DATETIME(6);
  DECLARE v_weight INT UNSIGNED;
  DECLARE v_n SMALLINT UNSIGNED;
  DECLARE v_bytes INT UNSIGNED;
  DECLARE v_has INT;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  IF EXISTS (SELECT 1 FROM todo WHERE id = p_id) THEN
    SET v_desk = NULL;
    SET v_has = 0;
    SELECT COUNT(*) INTO v_has FROM activity WHERE type = 'todo' AND id = p_id;
    IF v_has > 0 THEN
      SELECT desk_id, roster_id, created, weight, n, bytes
        INTO v_desk, v_aff, v_created, v_weight, v_n, v_bytes
        FROM activity WHERE type = 'todo' AND id = p_id;
    ELSE
      SELECT roster_id INTO v_aff FROM todo WHERE id = p_id;
      SET v_desk = MILL_NAME_GET('desk', p_desk);
      SET v_created = v_ts;
      SET v_weight = MILL_WEIGHT('todo');
      SET v_n = 1;
      SET v_bytes = NULL;
    END IF;
    CALL mill_tree_detach('todo', p_id);
    -- activity_del_watchers fires only on a hard activity delete, so drop watchers here.
    DELETE FROM watcher WHERE type = 'todo' AND id = p_id;
    DELETE FROM todo WHERE id = p_id;  -- todo_no_delete_in_tree still guards
    IF v_desk IS NOT NULL THEN
      INSERT INTO activity (
        type, id, created, updated, deleted, desk_id, roster_id, weight, n, bytes
      ) VALUES (
        'todo', p_id, IFNULL(v_created, v_ts), v_ts, v_ts, v_desk, v_aff,
        IFNULL(v_weight, 1), IFNULL(v_n, 1), v_bytes
      )
      ON DUPLICATE KEY UPDATE
        deleted = IFNULL(deleted, v_ts),
        updated = v_ts;
    END IF;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, 'deleted' AS op;
END //

-- #19: retire is a soft delete that keeps the card row, its status, plan,
-- labels and watchers. It stamps activity.deleted, so mill_todo_select and
-- mill_todo_page skip the card. Reclaim clears the stamp; the card comes back
-- with its old status. A card with no activity row gets one, stamped.
CREATE PROCEDURE mill_todo_retire(
  IN p_id   BIGINT UNSIGNED,
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_proj = NULL;
  SELECT roster_id INTO v_proj FROM todo WHERE id = p_id FOR UPDATE;
  IF v_proj IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'retire todo: no such card';
  END IF;
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'retire todo: no such desk';
  END IF;
  IF EXISTS (SELECT 1 FROM activity WHERE type = 'todo' AND id = p_id AND deleted IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'retire todo: card is already retired';
  END IF;
  INSERT INTO activity (type, id, created, updated, deleted, desk_id, roster_id, weight, n, bytes)
  VALUES ('todo', p_id, v_ts, v_ts, v_ts, v_desk, v_proj, MILL_WEIGHT('todo'), 1, NULL)
  ON DUPLICATE KEY UPDATE deleted = v_ts, updated = v_ts;
  UPDATE todo SET updated = v_ts, updated_id = v_desk WHERE id = p_id;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, 'retired' AS op;
END //

CREATE PROCEDURE mill_todo_reclaim(
  IN p_id   BIGINT UNSIGNED,
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'reclaim todo: no such desk';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM todo t
                   JOIN activity a ON a.type = 'todo' AND a.id = t.id AND a.deleted IS NOT NULL
                  WHERE t.id = p_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'reclaim todo: card is not retired';
  END IF;
  UPDATE activity SET deleted = NULL, updated = v_ts WHERE type = 'todo' AND id = p_id;
  UPDATE todo SET updated = v_ts, updated_id = v_desk WHERE id = p_id;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, 'reclaimed' AS op;
END //

CREATE PROCEDURE mill_todo_get(IN p_id BIGINT UNSIGNED)
BEGIN
  SELECT t.type, t.id, t.created, t.updated, t.updated_id, t.roster_id, t.creator_id,
         t.status, t.assigned_id, t.body,
         an.name AS roster, an.type AS roster_type, cn.name AS creator, cn.type AS creator_type, sn.name AS assigned, sn.type AS assigned_type, un.name AS updated_by, un.type AS updated_by_type,
         t.done_when, t.evidence
  FROM todo t
  LEFT JOIN name an ON an.id = t.roster_id
  LEFT JOIN name cn ON cn.id = t.creator_id
  LEFT JOIN name sn ON sn.id = t.assigned_id
  LEFT JOIN name un ON un.id = t.updated_id
  WHERE t.id = p_id;
END //

CREATE PROCEDURE mill_todo_select(
  IN p_project VARCHAR(64),
  IN p_status  VARCHAR(16)
)
BEGIN
  DECLARE v_proj BIGINT UNSIGNED;
  IF p_project IS NULL OR p_project = '' THEN
    SET v_proj = NULL;
  ELSE
    SET v_proj = MILL_NAME_GET('roster', p_project);
    IF v_proj IS NULL THEN
      SET v_proj = 0;
    END IF;
  END IF;
  -- List rows carry the card's plan (tree_id, tree) and its labels so the client can
  -- group them (#274). A card on several plans lists under its lowest plan id.
  -- labels is a JSON array of names in label order. tree reads tree.idx_activity;
  -- labels read the label primary key (type, id, name_id). Stable sort: plan, then id.
  SELECT t.type, t.id, t.created, t.updated, t.updated_id, t.roster_id, t.creator_id,
         t.status, t.assigned_id, t.body,
         an.name AS roster, an.type AS roster_type, cn.name AS creator, cn.type AS creator_type, sn.name AS assigned, sn.type AS assigned_type, un.name AS updated_by, un.type AS updated_by_type,
         tr.tree_id, trn.name AS tree,
         (SELECT CONCAT('[', GROUP_CONCAT(JSON_QUOTE(ln.name) ORDER BY l.ord, ln.name SEPARATOR ','), ']')
            FROM label l JOIN name ln ON ln.id = l.name_id
           WHERE l.type = 'todo' AND l.id = t.id) AS labels,
         t.done_when, t.evidence
  FROM todo t
  LEFT JOIN name an ON an.id = t.roster_id
  LEFT JOIN name cn ON cn.id = t.creator_id
  LEFT JOIN name sn ON sn.id = t.assigned_id
  LEFT JOIN name un ON un.id = t.updated_id
  LEFT JOIN LATERAL (
    SELECT MIN(x.name_id) AS tree_id FROM tree x WHERE x.type = 'todo' AND x.id = t.id
  ) tr ON TRUE
  LEFT JOIN name trn ON trn.id = tr.tree_id
  WHERE (v_proj IS NULL OR t.roster_id = v_proj)
    AND (p_status IS NULL OR p_status = '' OR t.status = p_status)
    AND NOT EXISTS (SELECT 1 FROM activity ra
                     WHERE ra.type = 'todo' AND ra.id = t.id AND ra.deleted IS NOT NULL)
  ORDER BY tr.tree_id IS NULL, tr.tree_id, t.id;
END //

-- mill_todo_select with the board filters in SQL: p_hide_done drops done cards,
-- p_id > 0 reads that one card. Same columns and order. mill todo reads this.
CREATE PROCEDURE mill_todo_page(
  IN p_project   VARCHAR(64),
  IN p_status    VARCHAR(16),
  IN p_hide_done TINYINT,
  IN p_id        BIGINT UNSIGNED
)
BEGIN
  DECLARE v_proj BIGINT UNSIGNED;
  IF p_project IS NULL OR p_project = '' THEN
    SET v_proj = NULL;
  ELSE
    SET v_proj = MILL_NAME_GET('roster', p_project);
    IF v_proj IS NULL THEN
      SET v_proj = 0;
    END IF;
  END IF;
  -- List rows carry the card's plan (tree_id, tree) and its labels so the client can
  -- group them (#274). A card on several plans lists under its lowest plan id.
  -- labels is a JSON array of names in label order. tree reads tree.idx_activity;
  -- labels read the label primary key (type, id, name_id). Stable sort: plan, then id.
  SELECT t.type, t.id, t.created, t.updated, t.updated_id, t.roster_id, t.creator_id,
         t.status, t.assigned_id, t.body,
         an.name AS roster, an.type AS roster_type, cn.name AS creator, cn.type AS creator_type, sn.name AS assigned, sn.type AS assigned_type, un.name AS updated_by, un.type AS updated_by_type,
         tr.tree_id, trn.name AS tree,
         (SELECT CONCAT('[', GROUP_CONCAT(JSON_QUOTE(ln.name) ORDER BY l.ord, ln.name SEPARATOR ','), ']')
            FROM label l JOIN name ln ON ln.id = l.name_id
           WHERE l.type = 'todo' AND l.id = t.id) AS labels,
         t.done_when, t.evidence
  FROM todo t
  LEFT JOIN name an ON an.id = t.roster_id
  LEFT JOIN name cn ON cn.id = t.creator_id
  LEFT JOIN name sn ON sn.id = t.assigned_id
  LEFT JOIN name un ON un.id = t.updated_id
  LEFT JOIN LATERAL (
    SELECT MIN(x.name_id) AS tree_id FROM tree x WHERE x.type = 'todo' AND x.id = t.id
  ) tr ON TRUE
  LEFT JOIN name trn ON trn.id = tr.tree_id
  WHERE (v_proj IS NULL OR t.roster_id = v_proj)
    AND (p_status IS NULL OR p_status = '' OR t.status = p_status)
    AND NOT EXISTS (SELECT 1 FROM activity ra
                     WHERE ra.type = 'todo' AND ra.id = t.id AND ra.deleted IS NOT NULL)
    AND (IFNULL(p_hide_done, 0) = 0 OR t.status <> 'done')
    AND (IFNULL(p_id, 0) = 0 OR t.id = p_id)
  ORDER BY tr.tree_id IS NULL, tr.tree_id, t.id;
END //

DELIMITER ;
