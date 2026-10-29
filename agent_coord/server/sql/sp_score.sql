DROP PROCEDURE IF EXISTS mill_score_upsert;
DROP PROCEDURE IF EXISTS mill_score_admin_upsert;
DROP PROCEDURE IF EXISTS mill_score_delete;
DROP PROCEDURE IF EXISTS mill_score_select;
DROP PROCEDURE IF EXISTS mill_score_point_add;
DROP PROCEDURE IF EXISTS mill_score_points;
DROP PROCEDURE IF EXISTS mill_score_define;
DROP PROCEDURE IF EXISTS mill_score_retire;
DROP PROCEDURE IF EXISTS mill_score_event;
DROP PROCEDURE IF EXISTS mill_wall_event;
DROP PROCEDURE IF EXISTS mill_score_evidence_purge;
DROP FUNCTION IF EXISTS MILL_SCORE_DOC_ADD;

DELIMITER //

CREATE PROCEDURE mill_score_upsert(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64),
  IN p_kpi     VARCHAR(64),
  IN p_value   VARCHAR(64),
  IN p_target  VARCHAR(64),
  IN p_note    VARCHAR(200)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_id = NULL;
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
  IF NOT EXISTS (SELECT 1 FROM seat WHERE desk_id = v_desk) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: that desk has no seat in this office';
  END IF;
  SELECT id INTO v_id FROM score
    WHERE roster_id = v_proj AND desk_id = v_desk AND kpi = p_kpi
    LIMIT 1;
  IF v_id IS NULL THEN
    INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note)
    VALUES (v_ts, v_desk, v_proj, IFNULL(p_kpi, ''), IFNULL(p_value, ''), IFNULL(p_target, ''), IFNULL(p_note, ''));
    SET v_id = LAST_INSERT_ID();
  ELSE
    UPDATE score
      SET updated = v_ts,
          value = IFNULL(p_value, value),
          target = IFNULL(p_target, target),
          note = IFNULL(p_note, note)
      WHERE id = v_id;
  END IF;
  CALL mill_activity_put('score', v_id, v_ts, v_desk, v_proj, 'score', NULL);
  -- F2: soft-deleted score on upsert revives. Clear activity.deleted here only
  -- (never in mill_activity_put; that would resurrect mail/todo on any touch).
  UPDATE activity SET deleted = NULL, updated = v_ts
   WHERE type = 'score' AND id = v_id AND deleted IS NOT NULL;
  CALL mill_watcher_roster('score', v_id, v_proj, v_desk);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, p_kpi AS kpi;
END //

-- Office host score, owned by the office itself (beta 0.8.0: desk_id NULL; main wrote
-- the Admin roster id here). score_tick writes mill-wall.* / mill-desk.* / book KPIs
-- here: roster_id = Office (id 1), desk_id NULL, the rows Glance reads. No watcher.
-- The kind-checked FK on score.roster_id holds Office as a roster, so no guard reads it.
CREATE PROCEDURE mill_score_admin_upsert(
  IN p_kpi    VARCHAR(64),
  IN p_value  VARCHAR(64),
  IN p_target VARCHAR(64),
  IN p_note   VARCHAR(200)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_id = NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  IF p_kpi IS NULL OR CHAR_LENGTH(p_kpi) = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'kpi required';
  END IF;
  SELECT id INTO v_id FROM score
    WHERE roster_id = 1 AND desk_id IS NULL AND kpi = p_kpi
    LIMIT 1;
  IF v_id IS NULL THEN
    INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note)
    VALUES (v_ts, NULL, 1, p_kpi, IFNULL(p_value, ''), IFNULL(p_target, ''), IFNULL(p_note, ''));
    SET v_id = LAST_INSERT_ID();
  ELSE
    UPDATE score
      SET updated = v_ts,
          value = IFNULL(p_value, value),
          target = IFNULL(p_target, target),
          note = IFNULL(p_note, note)
      WHERE id = v_id;
  END IF;
  CALL mill_activity_put('score', v_id, v_ts, NULL, 1, 'score', NULL);
  UPDATE activity SET deleted = NULL, updated = v_ts
   WHERE type = 'score' AND id = v_id AND deleted IS NOT NULL;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, p_kpi AS kpi;
END //

CREATE PROCEDURE mill_score_delete(
  IN p_id   BIGINT UNSIGNED,
  IN p_desk VARCHAR(64)
)
BEGIN
  -- p_desk is the caller desk (same shape as mill_todo_delete / mill_mail_delete).
  -- Soft-delete: the score row stays (score_evidence RESTRICT). Off every tree plan
  -- (children move up), watchers dropped, activity.deleted stamped.
  -- No mill_activity_put; desk_id kept.
  DECLARE v_ts DATETIME(6);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  IF EXISTS (SELECT 1 FROM score WHERE id = p_id) THEN
    CALL mill_tree_detach('score', p_id);
    DELETE FROM watcher WHERE type = 'score' AND id = p_id;
    UPDATE activity SET deleted = v_ts, updated = v_ts
     WHERE type = 'score' AND id = p_id AND deleted IS NULL;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_id AS id, 'deleted' AS op;
END //

CREATE PROCEDURE mill_score_select(IN p_project VARCHAR(64))
BEGIN
  DECLARE v_proj BIGINT UNSIGNED;
  SET v_proj = MILL_NAME_GET('roster', p_project);
  SELECT s.type, s.id, s.created, s.updated, s.desk_id, s.roster_id, s.kpi,
         s.value, s.target, s.note,
         dn.name AS desk, dn.type AS desk_type, an.name AS roster, an.type AS roster_type
  FROM score s
  LEFT JOIN name dn ON dn.id = s.desk_id
  LEFT JOIN name an ON an.id = s.roster_id
  WHERE v_proj IS NOT NULL AND s.roster_id = v_proj
  ORDER BY s.updated DESC;
END //

-- 0.7.5 (#288 step 1): record one numeric point. The definition is owned by the
-- roster (beta 0.8.0: desk_id NULL; main wrote the roster id here), so every
-- desk on the roster adds to one series. NULL target/better/unit keep the stored
-- value. Watchers as mill_score_upsert.
-- 0.7.6 (#308): p_at is the point's time: NULL is now, 'Nm', 'Nh' or 'Nd' is that
-- long ago, else a DATETIME in the book clock. A future time is refused. score.value
-- and note are the newest point by time, so a backfilled point never becomes latest.
CREATE PROCEDURE mill_score_point_add(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64),
  IN p_kpi     VARCHAR(64),
  IN p_value   DOUBLE,
  IN p_target  VARCHAR(64),
  IN p_note    VARCHAR(200),
  IN p_better  VARCHAR(4),
  IN p_unit    VARCHAR(16),
  IN p_at      VARCHAR(32)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_at DATETIME(6);
  DECLARE v_n BIGINT;
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_pt BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_id = NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF p_value IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: value must be a number';
  END IF;
  IF IFNULL(p_kpi, '') = '' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: name required';
  END IF;
  IF p_better IS NOT NULL AND p_better NOT IN ('up', 'down') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: --better must be up or down';
  END IF;
  SET v_ts = MILL_NOW();
  SET v_at = v_ts;
  IF IFNULL(p_at, '') <> '' THEN
    IF p_at REGEXP '^[0-9]{1,6}[mhd]$' THEN
      SET v_n = CAST(LEFT(p_at, CHAR_LENGTH(p_at) - 1) AS UNSIGNED);
      SET v_at = CASE RIGHT(p_at, 1)
        WHEN 'm' THEN v_ts - INTERVAL v_n MINUTE
        WHEN 'h' THEN v_ts - INTERVAL v_n HOUR
        ELSE v_ts - INTERVAL v_n DAY END;
    ELSEIF p_at REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}([ T][0-9]{2}:[0-9]{2}(:[0-9]{2})?)?$' THEN
      SET v_at = CAST(REPLACE(p_at, 'T', ' ') AS DATETIME(6));
    ELSE
      SET v_at = NULL;
    END IF;
    IF v_at IS NULL THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: --at must be YYYY-MM-DD[THH:MM[:SS]] or Nm, Nh, Nd ago';
    END IF;
    IF v_at > v_ts + INTERVAL 1 MINUTE THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: --at is in the future';
    END IF;
  END IF;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_proj = MILL_NAME_GET('roster', p_project);
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_proj IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such project (MILL_NAME_GET)';
  END IF;
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such desk (MILL_NAME_GET)';
  END IF;
  SELECT id INTO v_id FROM score
    WHERE roster_id = v_proj AND desk_id IS NULL AND kpi = p_kpi
    LIMIT 1 FOR UPDATE;
  IF v_id IS NULL THEN
    INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note, better, unit)
    VALUES (v_ts, NULL, v_proj, p_kpi, '', IFNULL(p_target, ''),
            '', IFNULL(p_better, 'up'), IFNULL(p_unit, ''));
    SET v_id = LAST_INSERT_ID();
  ELSE
    UPDATE score
      SET updated = v_ts,
          target = IFNULL(p_target, target),
          better = IFNULL(p_better, better),
          unit = IFNULL(p_unit, unit)
      WHERE id = v_id;
  END IF;
  INSERT INTO score_point (score_id, created, desk_id, value, note)
  VALUES (v_id, v_at, v_desk, p_value, IFNULL(p_note, ''));
  SET v_pt = LAST_INSERT_ID();
  UPDATE score s
    JOIN (SELECT sp.value, sp.note FROM score_point sp
           WHERE sp.score_id = v_id ORDER BY sp.created DESC, sp.id DESC LIMIT 1) n
      SET s.value = LEFT(CAST(n.value AS CHAR), 64), s.note = n.note
    WHERE s.id = v_id;
  CALL mill_activity_put('score', v_id, v_ts, v_desk, v_proj, 'score', NULL);
  UPDATE activity SET deleted = NULL, updated = v_ts
   WHERE type = 'score' AND id = v_id AND deleted IS NOT NULL;
  CALL mill_watcher_roster('score', v_id, v_proj, v_desk);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_pt AS point_id, v_ts AS updated, p_kpi AS kpi;
END //

-- 0.7.6 (#306): set or change a score's target, better or unit without a point.
-- Creates the roster-owned definition when the name is new. NULL keeps the
-- stored value; p_target '' clears the target.
CREATE PROCEDURE mill_score_define(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64),
  IN p_kpi     VARCHAR(64),
  IN p_target  VARCHAR(64),
  IN p_better  VARCHAR(4),
  IN p_unit    VARCHAR(16)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_id = NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF IFNULL(p_kpi, '') = '' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: name required';
  END IF;
  IF p_better IS NOT NULL AND p_better NOT IN ('up', 'down') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: --better must be up or down';
  END IF;
  IF p_target IS NULL AND p_better IS NULL AND p_unit IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: give VALUE, --target, --better or --unit';
  END IF;
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
  SELECT id INTO v_id FROM score
    WHERE roster_id = v_proj AND desk_id IS NULL AND kpi = p_kpi
    LIMIT 1 FOR UPDATE;
  IF v_id IS NULL THEN
    INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note, better, unit)
    VALUES (v_ts, NULL, v_proj, p_kpi, '', IFNULL(p_target, ''), '',
            IFNULL(p_better, 'up'), IFNULL(p_unit, ''));
    SET v_id = LAST_INSERT_ID();
  ELSE
    UPDATE score
      SET updated = v_ts,
          target = IFNULL(p_target, target),
          better = IFNULL(p_better, better),
          unit = IFNULL(p_unit, unit)
      WHERE id = v_id;
  END IF;
  CALL mill_activity_put('score', v_id, v_ts, v_desk, v_proj, 'score', NULL);
  UPDATE activity SET deleted = NULL, updated = v_ts
   WHERE type = 'score' AND id = v_id AND deleted IS NOT NULL;
  CALL mill_watcher_roster('score', v_id, v_proj, v_desk);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS updated, p_kpi AS kpi;
END //

-- 0.7.6 (#302): retire (soft-delete) the score a read of p_kpi returns. Points and
-- the row stay; the score leaves reads and lists. Allowed: Admin (p_admin = 1), the
-- desk that owns a desk-owned row, or a desk that recorded a point on it.
CREATE PROCEDURE mill_score_retire(
  IN p_project VARCHAR(64),
  IN p_desk    VARCHAR(64),
  IN p_kpi     VARCHAR(64),
  IN p_admin   TINYINT
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_owner BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_id = NULL;
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
  SELECT s.id, s.desk_id INTO v_id, v_owner FROM score s
    JOIN activity a ON a.type = 'score' AND a.id = s.id AND a.deleted IS NULL
   WHERE s.roster_id = v_proj AND s.kpi = p_kpi
     AND (s.desk_id IS NULL OR s.value <> ''
          OR EXISTS (SELECT 1 FROM score_point sp WHERE sp.score_id = s.id))
   ORDER BY (s.desk_id IS NULL) DESC, s.updated DESC
   LIMIT 1 FOR UPDATE;
  IF v_id IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: no such score on this roster';
  END IF;
  IF NOT (IFNULL(p_admin, 0) = 1 OR (v_desk IS NOT NULL AND IFNULL(v_owner = v_desk, 0))
          OR (v_desk IS NOT NULL AND EXISTS (SELECT 1 FROM score_point sp
                                              WHERE sp.score_id = v_id AND sp.desk_id = v_desk))) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'score: only a desk that recorded on it, or Admin, can retire it';
  END IF;
  CALL mill_tree_detach('score', v_id);
  DELETE FROM watcher WHERE type = 'score' AND id = v_id;
  UPDATE activity SET deleted = v_ts, updated = v_ts
   WHERE type = 'score' AND id = v_id AND deleted IS NULL;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, p_kpi AS kpi, 'retired' AS op;
END //

-- 0.7.5 (#288 step 1): read series. p_kpi names one score: its definition plus the
-- newest p_limit points by time (--at, else when recorded; idx_score_at). The
-- roster-owned definition (desk_id NULL, beta 0.8.0) wins, then the newest desk row. An
-- empty legacy desk row (no value, no points) is never returned (#305). p_kpi '' lists the
-- roster: every live score with its newest p_limit points. One row per point; a
-- score with no points is one row with point_id NULL. Soft-deleted scores are skipped.
-- owner is the desk of a desk row, else the roster's name (beta 0.8.0: a roster-owned row has no desk).
CREATE PROCEDURE mill_score_points(
  IN p_project VARCHAR(64),
  IN p_kpi     VARCHAR(64),
  IN p_limit   INT
)
BEGIN
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_n INT;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_id = NULL;
  SET v_n = LEAST(GREATEST(IFNULL(p_limit, 10), 1), 100);
  SET v_proj = MILL_NAME_GET('roster', p_project);
  IF v_proj IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'no such project (MILL_NAME_GET)';
  END IF;
  IF IFNULL(p_kpi, '') <> '' THEN
    SELECT s.id INTO v_id FROM score s
      LEFT JOIN activity a ON a.type = 'score' AND a.id = s.id
     WHERE s.roster_id = v_proj AND s.kpi = p_kpi AND a.deleted IS NULL
       AND (s.desk_id IS NULL OR s.value <> ''
            OR EXISTS (SELECT 1 FROM score_point sp WHERE sp.score_id = s.id))
     ORDER BY (s.desk_id IS NULL) DESC, s.updated DESC
     LIMIT 1;
    SELECT s.id, s.kpi, s.value AS latest, s.target, s.better, s.unit, s.updated,
           IFNULL(dn.name, rn.name) AS owner, p.id AS point_id, p.value AS v, p.created AS at,
           p.note, pn.name AS desk
      FROM score s
      LEFT JOIN name dn ON dn.id = s.desk_id
      LEFT JOIN name rn ON rn.id = s.roster_id
      LEFT JOIN (SELECT sp.score_id, sp.id, sp.value, sp.created, sp.note, sp.desk_id
                   FROM score_point sp
                  WHERE sp.score_id = v_id
                  ORDER BY sp.created DESC, sp.id DESC
                  LIMIT v_n) p ON p.score_id = s.id
      LEFT JOIN name pn ON pn.id = p.desk_id
     WHERE v_id IS NOT NULL AND s.id = v_id
     ORDER BY p.created DESC, p.id DESC;
  ELSE
    SELECT s.id, s.kpi, s.value AS latest, s.target, s.better, s.unit, s.updated,
           IFNULL(dn.name, rn.name) AS owner, p.id AS point_id, p.value AS v, p.created AS at,
           p.note, pn.name AS desk
      FROM score s
      LEFT JOIN activity a ON a.type = 'score' AND a.id = s.id
      LEFT JOIN name dn ON dn.id = s.desk_id
      LEFT JOIN name rn ON rn.id = s.roster_id
      LEFT JOIN (SELECT sp.score_id, sp.id, sp.value, sp.created, sp.note, sp.desk_id,
                        ROW_NUMBER() OVER (PARTITION BY sp.score_id ORDER BY sp.created DESC, sp.id DESC) AS rn
                   FROM score_point sp
                   JOIN score s2 ON s2.id = sp.score_id AND s2.roster_id = v_proj) p
             ON p.score_id = s.id AND p.rn <= v_n
      LEFT JOIN name pn ON pn.id = p.desk_id
     WHERE s.roster_id = v_proj AND a.deleted IS NULL
     ORDER BY s.kpi, s.id, p.created DESC, p.id DESC;
  END IF;
END //

-- Add one verb into a score history document. p_doc NULL starts a fresh document.
CREATE FUNCTION MILL_SCORE_DOC_ADD(
  p_doc  JSON,
  p_verb VARCHAR(64),
  p_ms   INT,
  p_mail INT,
  p_todo INT
) RETURNS JSON
  DETERMINISTIC
  NO SQL
BEGIN
  DECLARE v_doc JSON;
  DECLARE v_one JSON;
  DECLARE v_n BIGINT;
  DECLARE v_ms BIGINT;
  DECLARE v_total BIGINT;
  DECLARE v_mail BIGINT;
  DECLARE v_todo BIGINT;
  DECLARE v_bytes JSON;
  SET v_doc = IFNULL(p_doc, JSON_OBJECT());
  SET v_one = JSON_EXTRACT(v_doc, CONCAT('$."', p_verb, '"'));
  SET v_n = CAST(IFNULL(JSON_UNQUOTE(JSON_EXTRACT(v_one, '$.n')), '0') AS SIGNED) + 1;
  SET v_ms = CAST(IFNULL(JSON_UNQUOTE(JSON_EXTRACT(v_one, '$.ms')), '0') AS SIGNED) + IFNULL(p_ms, 0);
  SET v_total = CAST(IFNULL(JSON_UNQUOTE(JSON_EXTRACT(v_doc, '$.n')), '0') AS SIGNED) + 1;
  SET v_doc = JSON_MERGE_PATCH(
    v_doc,
    JSON_OBJECT('n', v_total, p_verb, JSON_OBJECT('n', v_n, 'ms', v_ms))
  );
  IF IFNULL(p_mail, 0) > 0 OR IFNULL(p_todo, 0) > 0 THEN
    SET v_bytes = IFNULL(JSON_EXTRACT(v_doc, '$.bytes'), JSON_OBJECT());
    IF IFNULL(p_mail, 0) > 0 THEN
      SET v_mail = CAST(IFNULL(JSON_UNQUOTE(JSON_EXTRACT(v_bytes, '$.mail')), '0') AS SIGNED) + p_mail;
      SET v_bytes = JSON_SET(v_bytes, '$.mail', v_mail);
    END IF;
    IF IFNULL(p_todo, 0) > 0 THEN
      SET v_todo = CAST(IFNULL(JSON_UNQUOTE(JSON_EXTRACT(v_bytes, '$.todo')), '0') AS SIGNED) + p_todo;
      SET v_bytes = JSON_SET(v_bytes, '$.todo', v_todo);
    END IF;
    SET v_doc = JSON_SET(v_doc, '$.bytes', v_bytes);
  END IF;
  RETURN v_doc;
END //

-- One system score per desk. Evidence is the hour document and the day document.
-- A result over 4096 bytes is rejected. The previous documents stay.
CREATE PROCEDURE mill_score_event(
  IN p_desk VARCHAR(64),
  IN p_verb VARCHAR(64),
  IN p_ms   INT,
  IN p_req  INT,
  IN p_resp INT,
  IN p_now  DATETIME(6)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_now DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_dup INT DEFAULT 0;
  DECLARE v_hour DATETIME(6);
  DECLARE v_day DATETIME(6);
  DECLARE v_hour_old JSON;
  DECLARE v_day_old JSON;
  DECLARE v_hour_new JSON;
  DECLARE v_day_new JSON;
  DECLARE v_taken DATE;
  DECLARE v_len INT;
  DECLARE v_msg VARCHAR(128);
  DECLARE v_mail INT;
  DECLARE v_todo INT;
  DECLARE v_bytes INT;
  DECLARE CONTINUE HANDLER FOR 1062 SET v_dup = 1;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_now = IFNULL(p_now, v_ts);
  SET v_proj = 1;  -- Office by id (#722); the kind-checked FK on score.roster_id holds it a roster
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NOT NULL AND p_verb IS NOT NULL AND CHAR_LENGTH(p_verb) > 0 THEN
    SET v_id = (
      SELECT id FROM score
       WHERE roster_id = v_proj AND desk_id = v_desk AND kpi = 'system'
       LIMIT 1
    );
    IF v_id IS NULL THEN
      INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note)
      VALUES (
        v_ts, v_desk, v_proj, 'system', '0', '',
        'verb count, host milliseconds, mail and todo bytes'
      );
      IF v_dup = 1 THEN
        SET v_dup = 0;
        SET v_id = (
          SELECT id FROM score
           WHERE roster_id = v_proj AND desk_id = v_desk AND kpi = 'system'
           LIMIT 1
        );
      ELSE
        SET v_id = LAST_INSERT_ID();
        CALL mill_activity_put('score', v_id, v_ts, v_desk, v_proj, NULL, NULL);
      END IF;
    END IF;
    SET v_bytes = IFNULL(p_req, 0) + IFNULL(p_resp, 0);
    SET v_mail = 0;
    SET v_todo = 0;
    IF p_verb IN ('send', 'reply', 'inbox', 'mail-thread') THEN
      SET v_mail = v_bytes;
    ELSEIF p_verb IN ('todo', 'open', 'note', 'pass', 'claim', 'assign') THEN
      SET v_todo = v_bytes;
    END IF;
    SET v_hour = STR_TO_DATE(
      CONCAT('1970-01-01 ', LPAD(HOUR(v_now), 2, '0'), ':00:00'),
      '%Y-%m-%d %H:%i:%s'
    );
    SET v_day = CAST(DATE(v_now) AS DATETIME);
    SET v_taken = (
      SELECT taken FROM score_evidence WHERE score_id = v_id AND `timestamp` = v_hour
    );
    SET v_hour_old = (
      SELECT value FROM score_evidence WHERE score_id = v_id AND `timestamp` = v_hour
    );
    IF v_hour_old IS NULL OR v_taken IS NULL OR v_taken <> DATE(v_now) THEN
      SET v_hour_new = MILL_SCORE_DOC_ADD(NULL, p_verb, p_ms, v_mail, v_todo);
    ELSE
      SET v_hour_new = MILL_SCORE_DOC_ADD(v_hour_old, p_verb, p_ms, v_mail, v_todo);
    END IF;
    SET v_day_old = (
      SELECT value FROM score_evidence WHERE score_id = v_id AND `timestamp` = v_day
    );
    SET v_day_new = MILL_SCORE_DOC_ADD(v_day_old, p_verb, p_ms, v_mail, v_todo);
    SET v_len = GREATEST(
      LENGTH(CAST(v_hour_new AS CHAR)),
      LENGTH(CAST(v_day_new AS CHAR))
    );
    IF v_len > 4096 THEN
      SET v_msg = LEFT(CONCAT('score history exceeds 4096 bytes: ', v_len), 128);
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    INSERT INTO score_evidence (score_id, `timestamp`, value, taken)
    VALUES (v_id, v_hour, v_hour_new, DATE(v_now)) AS new
    ON DUPLICATE KEY UPDATE value = new.value, taken = new.taken;
    INSERT INTO score_evidence (score_id, `timestamp`, value, taken)
    VALUES (v_id, v_day, v_day_new, DATE(v_now)) AS new
    ON DUPLICATE KEY UPDATE value = new.value, taken = new.taken;
    UPDATE score
       SET value = JSON_UNQUOTE(JSON_EXTRACT(v_day_new, '$.n')),
           updated = v_ts
     WHERE id = v_id;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
END //

-- One office score, kpi wall, hung on Office. Not a desk: desk_id NULL (beta 0.8.0).
-- Each wall /api route is a key: n calls and total host milliseconds.
CREATE PROCEDURE mill_wall_event(
  IN p_route VARCHAR(64),
  IN p_ms    INT,
  IN p_now   DATETIME(6)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_now DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_dup INT DEFAULT 0;
  DECLARE v_hour DATETIME(6);
  DECLARE v_day DATETIME(6);
  DECLARE v_hour_old JSON;
  DECLARE v_day_old JSON;
  DECLARE v_hour_new JSON;
  DECLARE v_day_new JSON;
  DECLARE v_taken DATE;
  DECLARE v_len INT;
  DECLARE v_msg VARCHAR(128);
  DECLARE CONTINUE HANDLER FOR 1062 SET v_dup = 1;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_now = IFNULL(p_now, v_ts);
  IF p_route IS NOT NULL AND CHAR_LENGTH(p_route) > 0 THEN
    SET v_id = (
      SELECT id FROM score
       WHERE roster_id = 1 AND desk_id IS NULL AND kpi = 'wall'
       LIMIT 1
    );
    IF v_id IS NULL THEN
      INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note)
      VALUES (v_ts, NULL, 1, 'wall', '0', '', 'wall route count and host milliseconds');
      IF v_dup = 1 THEN
        SET v_dup = 0;
        SET v_id = (
          SELECT id FROM score
           WHERE roster_id = 1 AND desk_id IS NULL AND kpi = 'wall'
           LIMIT 1
        );
      ELSE
        SET v_id = LAST_INSERT_ID();
        CALL mill_activity_put('score', v_id, v_ts, NULL, 1, NULL, NULL);
      END IF;
    END IF;
    SET v_hour = STR_TO_DATE(
      CONCAT('1970-01-01 ', LPAD(HOUR(v_now), 2, '0'), ':00:00'),
      '%Y-%m-%d %H:%i:%s'
    );
    SET v_day = CAST(DATE(v_now) AS DATETIME);
    SET v_taken = (
      SELECT taken FROM score_evidence WHERE score_id = v_id AND `timestamp` = v_hour
    );
    SET v_hour_old = (
      SELECT value FROM score_evidence WHERE score_id = v_id AND `timestamp` = v_hour
    );
    IF v_hour_old IS NULL OR v_taken IS NULL OR v_taken <> DATE(v_now) THEN
      SET v_hour_new = MILL_SCORE_DOC_ADD(NULL, p_route, p_ms, 0, 0);
    ELSE
      SET v_hour_new = MILL_SCORE_DOC_ADD(v_hour_old, p_route, p_ms, 0, 0);
    END IF;
    SET v_day_old = (
      SELECT value FROM score_evidence WHERE score_id = v_id AND `timestamp` = v_day
    );
    SET v_day_new = MILL_SCORE_DOC_ADD(v_day_old, p_route, p_ms, 0, 0);
    SET v_len = GREATEST(
      LENGTH(CAST(v_hour_new AS CHAR)),
      LENGTH(CAST(v_day_new AS CHAR))
    );
    IF v_len > 4096 THEN
      SET v_msg = LEFT(CONCAT('score history exceeds 4096 bytes: ', v_len), 128);
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
    END IF;
    INSERT INTO score_evidence (score_id, `timestamp`, value, taken)
    VALUES (v_id, v_hour, v_hour_new, DATE(v_now)) AS new
    ON DUPLICATE KEY UPDATE value = new.value, taken = new.taken;
    INSERT INTO score_evidence (score_id, `timestamp`, value, taken)
    VALUES (v_id, v_day, v_day_new, DATE(v_now)) AS new
    ON DUPLICATE KEY UPDATE value = new.value, taken = new.taken;
    UPDATE score
       SET value = JSON_UNQUOTE(JSON_EXTRACT(v_day_new, '$.n')),
           updated = v_ts
     WHERE id = v_id;
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
END //

-- Day documents older than 30 days, every score. Hour slots stay (1970-01-01).
-- Not a side effect of one score write (#204). The wall tick calls this.
CREATE PROCEDURE mill_score_evidence_purge(IN p_now DATETIME(6))
BEGIN
  DECLARE v_now DATETIME(6);
  SET v_now = IFNULL(p_now, MILL_NOW());
  DELETE FROM score_evidence
   WHERE `timestamp` >= '1970-01-02 00:00:00'
     AND `timestamp` < DATE_SUB(DATE(v_now), INTERVAL 30 DAY);
END //

DELIMITER ;
