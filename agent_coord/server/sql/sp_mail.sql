DROP PROCEDURE IF EXISTS mill_mail_list;
DROP PROCEDURE IF EXISTS mill_mail_insert;
DROP PROCEDURE IF EXISTS mill_mail_update;
DROP PROCEDURE IF EXISTS mill_mail_delete;
DROP PROCEDURE IF EXISTS mill_mail_select;
DROP PROCEDURE IF EXISTS mill_mail_inbox;
DROP PROCEDURE IF EXISTS mill_mail_get;
DROP PROCEDURE IF EXISTS mill_mail_to_put;
DROP PROCEDURE IF EXISTS mill_mail_to_copied;
DROP PROCEDURE IF EXISTS mill_mail_to_node_put;
DROP PROCEDURE IF EXISTS mill_mail_to_node_delete;

DELIMITER //

CREATE PROCEDURE mill_mail_to_put(
  IN p_id      BIGINT UNSIGNED,
  IN p_group   VARCHAR(64),
  IN p_to_type VARCHAR(16),
  IN p_to      VARCHAR(64),
  IN p_receipt TINYINT
)
BEGIN
  -- p_group is the letter roster. It is not minted here:
  -- the letter row already carries roster_id (mill_mail_insert resolves it).
  DECLARE v_to BIGINT UNSIGNED;
  DECLARE v_type VARCHAR(16);
  SET v_to = MILL_NAME_PUT(p_to_type, p_to);
  SELECT type INTO v_type FROM name WHERE id = v_to;
  IF v_type = 'roster' THEN
    -- Card 963: skip retired desks still on the member table (M4 keeps those rows).
    INSERT IGNORE INTO mail_to (type, id, desk_id, receipt)
    SELECT 'mail', p_id, m.desk_id, IFNULL(p_receipt, 0)
      FROM member m
      JOIN name d ON d.id = m.desk_id AND d.deleted IS NULL
     WHERE m.name_id = v_to;
  ELSE
    INSERT IGNORE INTO mail_to (type, id, desk_id, receipt)
    VALUES ('mail', p_id, v_to, IFNULL(p_receipt, 0));
  END IF;
END //

-- #818 D1: the desks a reply reaches only as room members (reply-all, not
-- named) are copied on it; every other recipient stays asked (the default).
-- p_desks is a JSON array of desk names. Called by reply right after the
-- letter's recipients are written, before the wakes.
CREATE PROCEDURE mill_mail_to_copied(
  IN p_id    BIGINT UNSIGNED,
  IN p_desks JSON
)
BEGIN
  UPDATE mail_to mt
    JOIN name d ON d.id = mt.desk_id AND d.type = 'desk'
    JOIN JSON_TABLE(p_desks, '$[*]' COLUMNS (desk VARCHAR(64) PATH '$')) j ON j.desk = d.name
     SET mt.asked = 0
   WHERE mt.type = 'mail' AND mt.id = p_id;
END //

CREATE PROCEDURE mill_mail_to_node_put(
  IN p_id  BIGINT UNSIGNED,
  IN p_who BIGINT UNSIGNED
)
BEGIN
  -- mill add mail:ID WHO (#265). Node = this letter and every letter under it on
  -- its room tree (an off-tree letter is its own node). WHO (a desk, or a roster
  -- expanded to its members now) becomes a recipient on each. Backfill: the node
  -- row is unread, rows on older letters below it are marked opened. A letter's
  -- own sender is not added to it. Existing rows are left as they are.
  DECLARE v_type VARCHAR(16);
  DECLARE v_ts DATETIME(6);
  DECLARE v_added INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  SELECT type INTO v_type FROM name WHERE id = p_who AND deleted IS NULL;
  IF v_type IS NULL OR v_type NOT IN ('desk', 'roster') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'add: WHO is a live desk or roster';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM mail WHERE type = 'mail' AND id = p_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'add: no such mail';
  END IF;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  INSERT IGNORE INTO mail_to (type, id, desk_id, opened, receipt)
  WITH nodes AS (
      SELECT m.id, m.desk_id AS sender_id FROM mail m
       WHERE m.type = 'mail'
         AND (m.id = p_id OR m.id IN (
           SELECT c.id FROM tree t
             JOIN tree c ON c.name_id = t.name_id AND c.lft > t.lft AND c.rgt < t.rgt AND c.type = 'mail'
            WHERE t.type = 'mail' AND t.id = p_id))
    ), desks AS (
      SELECT d.id FROM name d WHERE d.id = p_who AND d.type = 'desk' AND d.deleted IS NULL
      UNION
      SELECT d.id FROM member mb JOIN name d ON d.id = mb.desk_id AND d.deleted IS NULL
       WHERE mb.name_id = p_who AND v_type = 'roster'
    )
  SELECT 'mail', n.id, d.id, IF(n.id = p_id, NULL, v_ts), 0
    FROM nodes n CROSS JOIN desks d
   WHERE n.sender_id <> d.id;
  SET v_added = ROW_COUNT();
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_added AS added,
         (WITH nodes AS (
      SELECT m.id, m.desk_id AS sender_id FROM mail m
       WHERE m.type = 'mail'
         AND (m.id = p_id OR m.id IN (
           SELECT c.id FROM tree t
             JOIN tree c ON c.name_id = t.name_id AND c.lft > t.lft AND c.rgt < t.rgt AND c.type = 'mail'
            WHERE t.type = 'mail' AND t.id = p_id))
    ), desks AS (
      SELECT d.id FROM name d WHERE d.id = p_who AND d.type = 'desk' AND d.deleted IS NULL
      UNION
      SELECT d.id FROM member mb JOIN name d ON d.id = mb.desk_id AND d.deleted IS NULL
       WHERE mb.name_id = p_who AND v_type = 'roster'
    ) SELECT COUNT(*) FROM nodes) AS letters,
         (WITH nodes AS (
      SELECT m.id, m.desk_id AS sender_id FROM mail m
       WHERE m.type = 'mail'
         AND (m.id = p_id OR m.id IN (
           SELECT c.id FROM tree t
             JOIN tree c ON c.name_id = t.name_id AND c.lft > t.lft AND c.rgt < t.rgt AND c.type = 'mail'
            WHERE t.type = 'mail' AND t.id = p_id))
    ), desks AS (
      SELECT d.id FROM name d WHERE d.id = p_who AND d.type = 'desk' AND d.deleted IS NULL
      UNION
      SELECT d.id FROM member mb JOIN name d ON d.id = mb.desk_id AND d.deleted IS NULL
       WHERE mb.name_id = p_who AND v_type = 'roster'
    ) SELECT COUNT(*) FROM desks) AS desks;
END //

CREATE PROCEDURE mill_mail_to_node_delete(
  IN p_id  BIGINT UNSIGNED,
  IN p_who BIGINT UNSIGNED
)
BEGIN
  -- mill remove mail:ID WHO (#265). Drops WHO's recipient rows on the node and
  -- every letter under it. Refuses, changing nothing, when a letter would be
  -- left with no recipient or WHO is not a recipient there. Sent letters stay.
  DECLARE v_type VARCHAR(16);
  DECLARE v_orphan BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_hits INT DEFAULT 0;
  DECLARE v_gone INT DEFAULT 0;
  DECLARE v_msg VARCHAR(255);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  SELECT type INTO v_type FROM name WHERE id = p_who AND deleted IS NULL;
  IF v_type IS NULL OR v_type NOT IN ('desk', 'roster') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'remove: WHO is a live desk or roster';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM mail WHERE type = 'mail' AND id = p_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'remove: no such mail';
  END IF;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  WITH nodes AS (
      SELECT m.id, m.desk_id AS sender_id FROM mail m
       WHERE m.type = 'mail'
         AND (m.id = p_id OR m.id IN (
           SELECT c.id FROM tree t
             JOIN tree c ON c.name_id = t.name_id AND c.lft > t.lft AND c.rgt < t.rgt AND c.type = 'mail'
            WHERE t.type = 'mail' AND t.id = p_id))
    ), desks AS (
      SELECT d.id FROM name d WHERE d.id = p_who AND d.type = 'desk' AND d.deleted IS NULL
      UNION
      SELECT d.id FROM member mb JOIN name d ON d.id = mb.desk_id AND d.deleted IS NULL
       WHERE mb.name_id = p_who AND v_type = 'roster'
    )
  SELECT COUNT(*) INTO v_hits
    FROM mail_to mt JOIN nodes n ON n.id = mt.id JOIN desks d ON d.id = mt.desk_id
   WHERE mt.type = 'mail';
  IF v_hits = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'remove: not a recipient on this letter or under it';
  END IF;
  WITH nodes AS (
      SELECT m.id, m.desk_id AS sender_id FROM mail m
       WHERE m.type = 'mail'
         AND (m.id = p_id OR m.id IN (
           SELECT c.id FROM tree t
             JOIN tree c ON c.name_id = t.name_id AND c.lft > t.lft AND c.rgt < t.rgt AND c.type = 'mail'
            WHERE t.type = 'mail' AND t.id = p_id))
    ), desks AS (
      SELECT d.id FROM name d WHERE d.id = p_who AND d.type = 'desk' AND d.deleted IS NULL
      UNION
      SELECT d.id FROM member mb JOIN name d ON d.id = mb.desk_id AND d.deleted IS NULL
       WHERE mb.name_id = p_who AND v_type = 'roster'
    )
  SELECT MIN(n.id) INTO v_orphan
    FROM nodes n
   WHERE NOT EXISTS (
           SELECT 1 FROM mail_to x
            WHERE x.type = 'mail' AND x.id = n.id
              AND x.desk_id NOT IN (SELECT id FROM desks))
     AND EXISTS (SELECT 1 FROM mail_to y WHERE y.type = 'mail' AND y.id = n.id);
  IF v_orphan IS NOT NULL THEN
    SET v_msg = CONCAT('remove: mail ', v_orphan, ' would have no recipient');
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  END IF;
  DELETE mt FROM mail_to mt
   WHERE mt.type = 'mail'
     AND mt.id IN (SELECT id FROM (WITH nodes AS (
      SELECT m.id, m.desk_id AS sender_id FROM mail m
       WHERE m.type = 'mail'
         AND (m.id = p_id OR m.id IN (
           SELECT c.id FROM tree t
             JOIN tree c ON c.name_id = t.name_id AND c.lft > t.lft AND c.rgt < t.rgt AND c.type = 'mail'
            WHERE t.type = 'mail' AND t.id = p_id))
    ), desks AS (
      SELECT d.id FROM name d WHERE d.id = p_who AND d.type = 'desk' AND d.deleted IS NULL
      UNION
      SELECT d.id FROM member mb JOIN name d ON d.id = mb.desk_id AND d.deleted IS NULL
       WHERE mb.name_id = p_who AND v_type = 'roster'
    ) SELECT id FROM nodes) AS nn)
     AND mt.desk_id IN (SELECT id FROM (WITH nodes AS (
      SELECT m.id, m.desk_id AS sender_id FROM mail m
       WHERE m.type = 'mail'
         AND (m.id = p_id OR m.id IN (
           SELECT c.id FROM tree t
             JOIN tree c ON c.name_id = t.name_id AND c.lft > t.lft AND c.rgt < t.rgt AND c.type = 'mail'
            WHERE t.type = 'mail' AND t.id = p_id))
    ), desks AS (
      SELECT d.id FROM name d WHERE d.id = p_who AND d.type = 'desk' AND d.deleted IS NULL
      UNION
      SELECT d.id FROM member mb JOIN name d ON d.id = mb.desk_id AND d.deleted IS NULL
       WHERE mb.name_id = p_who AND v_type = 'roster'
    ) SELECT id FROM desks) AS dd);
  SET v_gone = ROW_COUNT();
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_gone AS removed;
END //

CREATE PROCEDURE mill_mail_insert(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64),
  IN p_dst_type VARCHAR(16),
  IN p_dst     VARCHAR(64),
  IN p_body    VARCHAR(4096),
  IN p_receipt TINYINT
)
BEGIN
  -- Payload first (#216). The mail table assigns the id; LAST_INSERT_ID() is that id.
  -- Then the activity row (the timeline; mail has no FK to it). No lock, no catalog read.
  -- A failed write rolls both back (exit handler).
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_proj_type VARCHAR(16);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_to VARCHAR(64);
  DECLARE v_to_type VARCHAR(16);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  -- Roster: the sender roster name.
  SET v_proj = MILL_NAME_GET('roster', p_project);
  SET v_proj_type = 'roster';
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_proj IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such roster (MILL_NAME_GET)';
  END IF;
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  INSERT INTO mail (desk_id, roster_id, body) VALUES (v_desk, v_proj, p_body);
  SET v_id = LAST_INSERT_ID();
  CALL mill_activity_put('mail', v_id, v_ts, v_desk, v_proj, 'send', LENGTH(IFNULL(p_body, '')));
  SET v_to = IFNULL(p_dst, '');
  SET v_to_type = IFNULL(NULLIF(TRIM(p_dst_type), ''), 'desk');
  IF v_to = '' OR v_to = '*' OR v_to = p_project THEN
    SET v_to = p_project;
    SET v_to_type = v_proj_type;
  END IF;
  CALL mill_mail_to_put(v_id, p_project, v_to_type, v_to, IFNULL(p_receipt, 0));
  IF NOT EXISTS (SELECT 1 FROM mail_to WHERE type = 'mail' AND id = v_id LIMIT 1) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'mail: no recipients (empty mail_to; refuse orphan mail)';
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, v_desk AS desk_id, MILL_NAME_GET(v_to_type, v_to) AS dest_id;
END //

CREATE PROCEDURE mill_mail_update(
  IN p_id   BIGINT UNSIGNED,
  IN p_desk VARCHAR(64),
  IN p_dst  VARCHAR(64),
  IN p_body VARCHAR(4096)
)
BEGIN
  -- #656: only the letter's sender or an Admin desk may rewrite it; anyone else
  -- is refused and nothing changes.
  DECLARE v_ts DATETIME(6);
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_sender BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_sender = (SELECT desk_id FROM mail WHERE id = p_id);
  SET v_proj = (SELECT roster_id FROM mail WHERE id = p_id);
  IF v_sender IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'mail: no such letter';
  END IF;
  -- An unknown caller desk (NULL) is never the sender and never Admin.
  IF IFNULL(v_desk, 0) <> v_sender
     AND NOT EXISTS (SELECT 1 FROM member
                      WHERE name_id = 2  -- the reserved Admin roster (#722)
                        AND desk_id = IFNULL(v_desk, 0)) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'mail: only the sender or an Admin desk may change this letter';
  END IF;
  UPDATE mail SET body = IFNULL(p_body, body) WHERE id = p_id;
  CALL mill_activity_put('mail', p_id, v_ts, v_desk, v_proj, 'note', LENGTH(p_body));
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, v_ts AS updated;
END //

CREATE PROCEDURE mill_mail_delete(
  IN p_id   BIGINT UNSIGNED,
  IN p_desk VARCHAR(64)
)
BEGIN
  -- Soft-delete: off every tree plan (children move up), queued pushes dropped, letter
  -- deleted (mail_to cascades), activity.deleted stamped. No mill_activity_put; desk_id kept.
  -- #656: only the sender or an Admin desk; anyone else is refused, the row stays.
  DECLARE v_ts DATETIME(6);
  DECLARE v_gone INT DEFAULT 0;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_sender BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = IFNULL(MILL_NAME_GET('desk', p_desk), 0);
  SET v_sender = (SELECT desk_id FROM mail WHERE id = p_id);
  -- An unknown caller desk (0) is never the sender and never Admin.
  IF v_sender IS NOT NULL AND v_desk <> v_sender
     AND NOT EXISTS (SELECT 1 FROM member
                      WHERE name_id = 2  -- the reserved Admin roster (#722)
                        AND desk_id = v_desk) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'mail: only the sender or an Admin desk may change this letter';
  END IF;
  IF v_sender IS NOT NULL THEN
    CALL mill_tree_detach('mail', p_id);
  END IF;
  -- card 1022: mark matching wakes taken (no delete) and write transitions
  INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, role)
  SELECT 'wake', id, state, 'taken', 'wake_deliver', 0, 'office'
    FROM wake
   WHERE cause IN ('mail', 'receipt')
     AND state <> 'taken'
     AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.id')) AS UNSIGNED) = p_id;
  UPDATE wake
     SET state = 'taken'
   WHERE cause IN ('mail', 'receipt')
     AND state <> 'taken'
     AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload, '$.id')) AS UNSIGNED) = p_id;
  DELETE FROM mail WHERE id = p_id;  -- mail_to cascades; mail_no_delete_in_tree still guards
  SET v_gone = ROW_COUNT();
  IF v_gone = 1 THEN
    UPDATE activity SET deleted = v_ts, updated = v_ts
     WHERE type = 'mail' AND id = p_id;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, v_ts AS updated, 'deleted' AS op;
END //

CREATE PROCEDURE mill_mail_list(IN p_project VARCHAR(64))
BEGIN
  -- One row per letter (newest 500). Every dest rides along in dests (JSON_ARRAYAGG ... GROUP BY),
  -- so the caller does not read mail_to per letter. Letter roster is mail.roster_id only.
  DECLARE v_proj BIGINT UNSIGNED;
  IF p_project IS NULL OR p_project = '' THEN
    SELECT m.type, m.id, m.created, m.created AS updated, m.desk_id,
           m.roster_id AS sender_roster_id,
           m.roster_id AS roster_id, m.body,
           srcn.name AS desk, srcn.type AS desk_type, affn.name AS roster, affn.type AS roster_type,
           affn.name AS sender_roster, affn.type AS sender_roster_type,
           JSON_ARRAYAGG(JSON_OBJECT(
             'desk_id', t.desk_id, 'desk', dstn.name, 'desk_type', dstn.type, 'receipt', t.receipt
           )) AS dests
      FROM (SELECT id FROM mail ORDER BY id DESC LIMIT 500) s
      JOIN mail m ON m.id = s.id
      JOIN mail_to t ON t.type = 'mail' AND t.id = m.id
      LEFT JOIN name srcn ON srcn.id = m.desk_id
      LEFT JOIN name dstn ON dstn.id = t.desk_id
      LEFT JOIN name affn ON affn.id = m.roster_id
     GROUP BY m.type, m.id
     ORDER BY m.id DESC;
  ELSE
    SET v_proj = MILL_NAME_GET('roster', p_project);
    SELECT m.type, m.id, m.created, m.created AS updated, m.desk_id,
           m.roster_id AS sender_roster_id,
           m.roster_id AS roster_id, m.body,
           srcn.name AS desk, srcn.type AS desk_type, affn.name AS roster, affn.type AS roster_type,
           affn.name AS sender_roster, affn.type AS sender_roster_type,
           JSON_ARRAYAGG(JSON_OBJECT(
             'desk_id', t.desk_id, 'desk', dstn.name, 'desk_type', dstn.type, 'receipt', t.receipt
           )) AS dests
      FROM (SELECT id FROM mail WHERE v_proj IS NOT NULL AND roster_id = v_proj
             ORDER BY id DESC LIMIT 500) s
      JOIN mail m ON m.id = s.id
      JOIN mail_to t ON t.type = 'mail' AND t.id = m.id
      LEFT JOIN name srcn ON srcn.id = m.desk_id
      LEFT JOIN name dstn ON dstn.id = t.desk_id
      LEFT JOIN name affn ON affn.id = m.roster_id
     GROUP BY m.type, m.id
     ORDER BY m.id DESC;
  END IF;
END //

CREATE PROCEDURE mill_mail_get(IN p_id BIGINT UNSIGNED)
BEGIN
  -- Letter roster is mail.roster_id only (no fallback to activity).
  SELECT m.type, m.id, m.created, m.created AS updated, m.desk_id,
         m.roster_id AS sender_roster_id,
         m.roster_id AS roster_id, t.desk_id AS dst_id, m.body,
         t.receipt AS receipt,
         srcn.name AS desk, srcn.type AS desk_type, dstn.name AS dst, dstn.type AS dst_type, affn.name AS roster, affn.type AS roster_type,
         saffn.name AS sender_roster, saffn.type AS sender_roster_type
    FROM mail m
    JOIN mail_to t ON t.type = 'mail' AND t.id = m.id
    LEFT JOIN name srcn ON srcn.id = m.desk_id
    LEFT JOIN name dstn ON dstn.id = t.desk_id
    LEFT JOIN name affn ON affn.id = m.roster_id
    LEFT JOIN name saffn ON saffn.id = m.roster_id
   WHERE m.id = p_id;
END //

CREATE PROCEDURE mill_mail_select(
  IN p_desk VARCHAR(64)
)
BEGIN
  -- Desk inbox is every roster for this desk (#201).
  -- One argument: the desk. A roster mailbox is mill_mail_list.
  -- t.opened is this desk's flag (#220), so inbox does not read it again.
  DECLARE v_desk BIGINT UNSIGNED;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SELECT m.type, m.id, m.created, m.created AS updated, m.desk_id,
         m.roster_id AS sender_roster_id,
         m.roster_id AS roster_id, t.desk_id AS dst_id, m.body,
         t.receipt AS receipt, t.opened AS opened,
         srcn.name AS desk, srcn.type AS desk_type, dstn.name AS dst, dstn.type AS dst_type, affn.name AS roster, affn.type AS roster_type,
         saffn.name AS sender_roster, saffn.type AS sender_roster_type
    FROM mail m
    JOIN mail_to t ON t.type = 'mail' AND t.id = m.id
    LEFT JOIN name srcn ON srcn.id = m.desk_id
    LEFT JOIN name dstn ON dstn.id = t.desk_id
    LEFT JOIN name affn ON affn.id = m.roster_id
    LEFT JOIN name saffn ON saffn.id = m.roster_id
   WHERE t.desk_id = v_desk
   ORDER BY m.id DESC;
END //

-- Desk inbox page, cut in SQL. Unread (default): the newest p_limit unread
-- letters, newest first, so a new letter is never buried (F137). p_all: the
-- newest p_limit letters, newest first. Drives from mail_to idx_desk_unread
-- (desk_id, opened, id) in a derived table, so an unread page reads p_limit index
-- entries, not the whole mailbox. Same columns as mill_mail_select.
CREATE PROCEDURE mill_mail_inbox(
  IN p_desk  VARCHAR(64),
  IN p_all   TINYINT,
  IN p_limit INT
)
BEGIN
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_lim INT;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_lim = GREATEST(1, IFNULL(p_limit, 100));
  IF IFNULL(p_all, 0) = 0 THEN
    SELECT m.type, m.id, m.created, m.created AS updated, m.desk_id,
           m.roster_id AS sender_roster_id,
           m.roster_id AS roster_id, t.desk_id AS dst_id, m.body,
           t.receipt AS receipt, t.opened AS opened,
           srcn.name AS desk, srcn.type AS desk_type, dstn.name AS dst, dstn.type AS dst_type, affn.name AS roster, affn.type AS roster_type,
           affn.name AS sender_roster, affn.type AS sender_roster_type
      FROM (SELECT id, desk_id, receipt, opened FROM mail_to
             WHERE type = 'mail' AND desk_id = v_desk AND opened IS NULL
             ORDER BY id DESC LIMIT v_lim) t
      JOIN mail m ON m.type = 'mail' AND m.id = t.id
      LEFT JOIN name srcn ON srcn.id = m.desk_id
      LEFT JOIN name dstn ON dstn.id = t.desk_id
      LEFT JOIN name affn ON affn.id = m.roster_id
     ORDER BY t.id DESC;
  ELSE
    SELECT m.type, m.id, m.created, m.created AS updated, m.desk_id,
           m.roster_id AS sender_roster_id,
           m.roster_id AS roster_id, t.desk_id AS dst_id, m.body,
           t.receipt AS receipt, t.opened AS opened,
           srcn.name AS desk, srcn.type AS desk_type, dstn.name AS dst, dstn.type AS dst_type, affn.name AS roster, affn.type AS roster_type,
           affn.name AS sender_roster, affn.type AS sender_roster_type
      FROM (SELECT id, desk_id, receipt, opened FROM mail_to
             WHERE type = 'mail' AND desk_id = v_desk
             ORDER BY id DESC LIMIT v_lim) t
      JOIN mail m ON m.type = 'mail' AND m.id = t.id
      LEFT JOIN name srcn ON srcn.id = m.desk_id
      LEFT JOIN name dstn ON dstn.id = t.desk_id
      LEFT JOIN name affn ON affn.id = m.roster_id
     ORDER BY t.id DESC;
  END IF;
END //

DELIMITER ;
