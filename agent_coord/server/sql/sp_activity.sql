-- Activity is the record of mail, todo, join, hold, and score.
-- mill_activity_put upserts that row: first write n=1, later writes n=n+1.
-- p_id = payload id (mail.id, todo.id, ...). No AUTO_INCREMENT on activity.
-- p_bytes = last payload UTF-8 byte length (mail/todo body); NULL if none.
-- p_project NULL keeps the row's roster: a tree parent touch passes NULL (card 841).
-- p_desk NULL (beta 0.8.0) is the office: a new row has no desk, and a touch of an
-- existing row keeps its desk (a parent touch is not the parent's new author).
-- Outer SP owns the transaction.

DROP PROCEDURE IF EXISTS mill_activity_put;
DROP PROCEDURE IF EXISTS mill_span;
DROP PROCEDURE IF EXISTS mill_between;
DROP PROCEDURE IF EXISTS mill_watcher_put;
DROP PROCEDURE IF EXISTS mill_watcher_roster;
DROP PROCEDURE IF EXISTS mill_watcher_delete;
DROP PROCEDURE IF EXISTS mill_name_poke;
DROP PROCEDURE IF EXISTS mill_watcher_select;
DROP PROCEDURE IF EXISTS mill_watcher_set_hint;
DROP PROCEDURE IF EXISTS mill_activity_select;
DROP PROCEDURE IF EXISTS mill_activity_get;
DROP PROCEDURE IF EXISTS mill_activity_bucket;

DELIMITER //

CREATE PROCEDURE mill_activity_put(
  IN p_type    ENUM('mail','todo','doing','hold','score'),
  IN p_id      BIGINT UNSIGNED,
  IN p_ts      DATETIME(6),
  IN p_desk    BIGINT UNSIGNED,
  IN p_project BIGINT UNSIGNED,
  IN p_weight  INT,
  IN p_bytes   INT UNSIGNED
)
BEGIN
  IF p_id IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'mill_activity_put: id required';
  END IF;
  INSERT INTO activity (type, id, updated, desk_id, roster_id, weight, n, bytes)
  VALUES (p_type, p_id, p_ts, p_desk, IFNULL(p_project, 1), IFNULL(p_weight, MILL_WEIGHT(p_type)), 1, p_bytes)
  ON DUPLICATE KEY UPDATE
    updated = p_ts,
    desk_id = IFNULL(p_desk, desk_id),
    roster_id = IFNULL(p_project, roster_id),
    weight = IFNULL(p_weight, weight),
    n = n + 1,
    bytes = IFNULL(p_bytes, bytes);
END //

CREATE PROCEDURE mill_watcher_put(
  IN p_type ENUM('todo','doing','hold','score'),
  IN p_id   BIGINT UNSIGNED,
  IN p_desk BIGINT UNSIGNED
)
BEGIN
  -- Beta 0.8.0: no IGNORE, so a non-desk (a roster id) is the FK refusal, not a silent no-op.
  INSERT INTO watcher (type, id, desk_id) VALUES (p_type, p_id, p_desk) AS new
  ON DUPLICATE KEY UPDATE desk_id = new.desk_id;
END //

CREATE PROCEDURE mill_watcher_roster(
  IN p_type ENUM('todo','doing','hold','score'),
  IN p_id   BIGINT UNSIGNED,
  IN p_aff  BIGINT UNSIGNED,
  IN p_desk BIGINT UNSIGNED
)
BEGIN
  -- p_aff is the roster. Members are not watchers.
  CALL mill_watcher_put(p_type, p_id, p_desk);
END //

CREATE PROCEDURE mill_watcher_delete(
  IN p_type ENUM('todo','doing','hold','score'),
  IN p_id   BIGINT UNSIGNED,
  IN p_desk BIGINT UNSIGNED
)
BEGIN
  DELETE FROM watcher WHERE type = p_type AND id = p_id AND desk_id = p_desk;
END //

CREATE PROCEDURE mill_watcher_select(
  IN p_type ENUM('todo','doing','hold','score'),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  -- Beta 0.8.0: a watcher is a desk (watcher.desk_id FKs to seat). Main's roster
  -- watcher rows (#265) are expanded to their member desks by the 0.8.0 migration.
  SELECT w.desk_id, n.name AS desk, n.type AS desk_type, w.hint, h.delivery_mode, h.endpoint_url
    FROM watcher w
    JOIN name n ON n.id = w.desk_id AND n.type = 'desk'
    LEFT JOIN seat h ON h.desk_id = w.desk_id
   WHERE w.type = p_type AND w.id = p_id;
END //

CREATE PROCEDURE mill_watcher_set_hint(
  IN p_type ENUM('todo','doing','hold','score'),
  IN p_id   BIGINT UNSIGNED,
  IN p_desk BIGINT UNSIGNED,
  IN p_hint VARCHAR(4096)
)
BEGIN
  INSERT INTO watcher (type, id, desk_id, hint)
  VALUES (p_type, p_id, p_desk, NULLIF(p_hint, ''))
  ON DUPLICATE KEY UPDATE hint = NULLIF(p_hint, '');
  SELECT w.desk_id, n.name AS desk, n.type AS desk_type, w.hint
    FROM watcher w
    JOIN name n ON n.id = w.desk_id
   WHERE w.type = p_type AND w.id = p_id AND w.desk_id = p_desk;
END //

-- state: 'deleted' when activity.deleted is set (any type), 'sent' for a live
-- letter, else NULL. mail is joined only for mail rows.
CREATE PROCEDURE mill_activity_select(
  IN p_desk  BIGINT UNSIGNED,
  IN p_limit INT
)
BEGIN
  SELECT a.type, a.id, a.created, a.updated, a.desk_id, a.roster_id, a.weight, a.n, a.bytes,
         ANY_VALUE(dn.name) AS desk, ANY_VALUE(dn.type) AS desk_type, ANY_VALUE(an.name) AS roster, ANY_VALUE(an.type) AS roster_type,
         CASE
           WHEN a.deleted IS NOT NULL THEN 'deleted'
           WHEN a.type = 'mail' AND m.id IS NOT NULL THEN 'sent'
           ELSE NULL
         END AS state
  FROM activity a
  LEFT JOIN name dn ON dn.id = a.desk_id
  LEFT JOIN name an ON an.id = a.roster_id
  LEFT JOIN mail m ON a.type = 'mail' AND m.id = a.id
  WHERE p_desk IS NULL OR p_desk = 0 OR a.desk_id = p_desk
  ORDER BY a.updated DESC
  LIMIT p_limit;
END //

-- One activity row by its primary key (type, id), with the same state as
-- mill_activity_select. The watcher hint reads this, not the newest 40 rows.
CREATE PROCEDURE mill_activity_get(
  IN p_type VARCHAR(16),
  IN p_id   BIGINT UNSIGNED
)
BEGIN
  SELECT a.type, a.id, a.created, a.updated,
         CASE
           WHEN a.deleted IS NOT NULL THEN 'deleted'
           WHEN a.type = 'mail' AND m.id IS NOT NULL THEN 'sent'
           ELSE NULL
         END AS state
    FROM activity a
    LEFT JOIN mail m ON a.type = 'mail' AND m.id = a.id
   WHERE a.type = p_type AND a.id = p_id;
END //

CREATE PROCEDURE mill_activity_bucket(
  IN p_project VARCHAR(64),
  IN p_desk    BIGINT UNSIGNED,
  IN p_type    VARCHAR(16),
  IN p_since   DATETIME(6),
  IN p_bucket  VARCHAR(8)
)
BEGIN
  DECLARE v_proj BIGINT UNSIGNED;
  SET v_proj = MILL_NAME_GET('roster', p_project);
  SELECT
    CASE LOWER(IFNULL(p_bucket, 'hour'))
      WHEN 'min' THEN
        CAST(DATE_FORMAT(a.updated, '%Y-%m-%d %H:%i:00') AS DATETIME(6))
      WHEN '5min' THEN
        CAST(DATE_FORMAT(
          DATE_SUB(a.updated, INTERVAL (MINUTE(a.updated) % 5) MINUTE),
          '%Y-%m-%d %H:%i:00'
        ) AS DATETIME(6))
      WHEN 'day' THEN
        CAST(DATE_FORMAT(a.updated, '%Y-%m-%d 00:00:00') AS DATETIME(6))
      ELSE
        CAST(DATE_FORMAT(a.updated, '%Y-%m-%d %H:00:00') AS DATETIME(6))
    END AS updated,
    a.type,
    a.desk_id,
    a.roster_id,
    SUM(a.n) AS n,
    ANY_VALUE(dn.name) AS desk, ANY_VALUE(dn.type) AS desk_type,
    ANY_VALUE(an.name) AS roster, ANY_VALUE(an.type) AS roster_type
  FROM activity a
  LEFT JOIN name dn ON dn.id = a.desk_id
  LEFT JOIN name an ON an.id = a.roster_id
  WHERE a.roster_id = v_proj
    AND (p_desk IS NULL OR p_desk = 0 OR a.desk_id = p_desk)
    AND (p_type IS NULL OR p_type = '' OR a.type = p_type)
    AND (p_since IS NULL OR a.updated >= p_since)
  GROUP BY 1, a.type, a.desk_id, a.roster_id, dn.name, an.name
  ORDER BY 1, a.type;
END //

-- Span chooses the table. min reads activity. hour and day read score_evidence.
-- One project, role, or station. member is unique on (name_id, desk_id),
-- and join.desk_id is unique, so each desk is read once.
CREATE PROCEDURE mill_span(
  IN p_kind  VARCHAR(16),
  IN p_id    VARCHAR(64),
  IN p_grain VARCHAR(16)
)
BEGIN
  DECLARE v_kind VARCHAR(16);
  DECLARE v_grain VARCHAR(16);
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE CONTINUE HANDLER FOR NOT FOUND BEGIN END;

  SET v_kind = LOWER(IFNULL(p_kind, ''));
  SET v_grain = LOWER(IFNULL(p_grain, ''));
  IF v_kind NOT IN ('project', 'role', 'lan') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'span scope is project, role, or lan';
  END IF;
  IF v_grain NOT IN ('min', 'hour', 'day') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'span is min, hour, or day';
  END IF;

  SET v_name = NULL;
  IF v_kind = 'project' THEN
    SELECT id INTO v_name FROM name WHERE type = 'roster' AND name = p_id AND deleted IS NULL LIMIT 1;
  ELSEIF v_kind = 'role' THEN
    SELECT id INTO v_name FROM name WHERE type = 'roster' AND name = p_id AND deleted IS NULL LIMIT 1;
  END IF;

  IF v_grain = 'min' AND v_kind = 'project' THEN
    CALL mill_activity_bucket(p_id, 0, '', DATE_SUB(MILL_NOW(), INTERVAL 15 MINUTE), 'min');
  ELSEIF v_grain = 'min' AND v_kind = 'role' THEN
    SELECT
      CAST(DATE_FORMAT(a.updated, '%Y-%m-%d %H:%i:00') AS DATETIME(6)) AS updated,
      a.type, a.desk_id, a.roster_id, SUM(a.n) AS n,
      ANY_VALUE(dn.name) AS desk, ANY_VALUE(dn.type) AS desk_type, ANY_VALUE(an.name) AS roster, ANY_VALUE(an.type) AS roster_type
    FROM member m
    JOIN activity a
      ON a.desk_id = m.desk_id
     AND a.updated >= DATE_SUB(MILL_NOW(), INTERVAL 15 MINUTE)
    LEFT JOIN name dn ON dn.id = a.desk_id
    LEFT JOIN name an ON an.id = a.roster_id
    WHERE m.name_id = v_name
    GROUP BY 1, a.type, a.desk_id, a.roster_id, dn.name, an.name
    ORDER BY 1, a.type;
  ELSEIF v_grain = 'min' AND v_kind = 'lan' THEN
    SELECT
      CAST(DATE_FORMAT(a.updated, '%Y-%m-%d %H:%i:00') AS DATETIME(6)) AS updated,
      a.type, a.desk_id, a.roster_id, SUM(a.n) AS n,
      ANY_VALUE(dn.name) AS desk, ANY_VALUE(dn.type) AS desk_type, ANY_VALUE(an.name) AS roster, ANY_VALUE(an.type) AS roster_type
    FROM seat j
    JOIN activity a
      ON a.desk_id = j.desk_id
     AND a.updated >= DATE_SUB(MILL_NOW(), INTERVAL 15 MINUTE)
    LEFT JOIN name dn ON dn.id = a.desk_id
    LEFT JOIN name an ON an.id = a.roster_id
    WHERE j.lan_ip = p_id
    GROUP BY 1, a.type, a.desk_id, a.roster_id, dn.name, an.name
    ORDER BY 1, a.type;
  ELSEIF v_grain = 'hour' AND v_kind IN ('project', 'role') THEN
    SELECT s.desk_id, dn.name AS desk, dn.type AS desk_type, e.`timestamp` AS `timestamp`, e.taken, e.value
    FROM member m
    JOIN score s
      ON s.roster_id = 1
     AND s.desk_id = m.desk_id
     AND s.kpi = 'system'
    JOIN score_evidence e
      ON e.score_id = s.id
     AND e.`timestamp` >= '1970-01-01 00:00:00'
     AND e.`timestamp` < '1970-01-02 00:00:00'
    LEFT JOIN name dn ON dn.id = s.desk_id
    WHERE m.name_id = v_name
    ORDER BY s.desk_id, e.`timestamp`;
  ELSEIF v_grain = 'hour' AND v_kind = 'lan' THEN
    SELECT s.desk_id, dn.name AS desk, dn.type AS desk_type, e.`timestamp` AS `timestamp`, e.taken, e.value
    FROM seat j
    JOIN score s
      ON s.roster_id = 1
     AND s.desk_id = j.desk_id
     AND s.kpi = 'system'
    JOIN score_evidence e
      ON e.score_id = s.id
     AND e.`timestamp` >= '1970-01-01 00:00:00'
     AND e.`timestamp` < '1970-01-02 00:00:00'
    LEFT JOIN name dn ON dn.id = s.desk_id
    WHERE j.lan_ip = p_id
    ORDER BY s.desk_id, e.`timestamp`;
  ELSEIF v_grain = 'day' AND v_kind IN ('project', 'role') THEN
    SELECT s.desk_id, dn.name AS desk, dn.type AS desk_type, e.`timestamp` AS `timestamp`, e.taken, e.value
    FROM member m
    JOIN score s
      ON s.roster_id = 1
     AND s.desk_id = m.desk_id
     AND s.kpi = 'system'
    JOIN score_evidence e
      ON e.score_id = s.id
     AND e.`timestamp` >= '1970-01-02 00:00:00'
     AND e.`timestamp` >= DATE_SUB(DATE(MILL_NOW()), INTERVAL 30 DAY)
    LEFT JOIN name dn ON dn.id = s.desk_id
    WHERE m.name_id = v_name
    ORDER BY s.desk_id, e.`timestamp`;
  ELSE
    SELECT s.desk_id, dn.name AS desk, dn.type AS desk_type, e.`timestamp` AS `timestamp`, e.taken, e.value
    FROM seat j
    JOIN score s
      ON s.roster_id = 1
     AND s.desk_id = j.desk_id
     AND s.kpi = 'system'
    JOIN score_evidence e
      ON e.score_id = s.id
     AND e.`timestamp` >= '1970-01-02 00:00:00'
     AND e.`timestamp` >= DATE_SUB(DATE(MILL_NOW()), INTERVAL 30 DAY)
    LEFT JOIN name dn ON dn.id = s.desk_id
    WHERE j.lan_ip = p_id
    ORDER BY s.desk_id, e.`timestamp`;
  END IF;
END //

-- Latest activity per desk in one project, role, or station.
-- The scope picks the desks (member, or join.lan_ip). Each desk is read once.
-- p_n is how many activity rows per desk, by updated. 0 or above 50 means 50.
-- A letter repeats once per recipient. A card's other desk is the assignee,
-- or the creator when the row already sits on the assignee. Join, score,
-- and hold have no other desk.
-- state: 'deleted' when activity.deleted is set (any type), 'sent' for a live
-- letter, else NULL. mail is joined only for mail rows.
CREATE PROCEDURE mill_between(
  IN p_kind VARCHAR(16),
  IN p_id   VARCHAR(64),
  IN p_n    INT
)
BEGIN
  DECLARE v_kind VARCHAR(16);
  DECLARE v_name BIGINT UNSIGNED;
  DECLARE v_n INT;
  DECLARE CONTINUE HANDLER FOR NOT FOUND BEGIN END;

  SET v_kind = LOWER(IFNULL(p_kind, ''));
  IF v_kind NOT IN ('project', 'role', 'lan') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'between scope is project, role, or lan';
  END IF;
  SET v_n = IFNULL(p_n, 50);
  IF v_n < 1 OR v_n > 50 THEN
    SET v_n = 50;
  END IF;

  SET v_name = NULL;
  IF v_kind = 'project' THEN
    SELECT id INTO v_name FROM name WHERE type = 'roster' AND name = p_id AND deleted IS NULL LIMIT 1;
  ELSEIF v_kind = 'role' THEN
    SELECT id INTO v_name FROM name WHERE type = 'roster' AND name = p_id AND deleted IS NULL LIMIT 1;
  END IF;

  SELECT
    recent.updated,
    recent.type,
    recent.id,
    recent.n,
    recent.desk_id,
    dn.name AS desk, dn.type AS desk_type,
    recent.roster_id,
    an.name AS roster, an.type AS roster_type,
    CASE recent.type
      WHEN 'mail' THEN mt.desk_id
      WHEN 'todo' THEN CASE
        WHEN td.assigned_id IS NOT NULL AND td.assigned_id <> recent.desk_id THEN td.assigned_id
        WHEN td.creator_id IS NOT NULL AND td.creator_id <> recent.desk_id THEN td.creator_id
        ELSE NULL
      END
      ELSE NULL
    END AS other_desk_id,
    oname.name AS other_desk, oname.type AS other_desk_type,
    CASE
      WHEN recent.deleted IS NOT NULL THEN 'deleted'
      WHEN recent.type = 'mail' AND ml.id IS NOT NULL THEN 'sent'
      ELSE NULL
    END AS state
  FROM (
    SELECT m.desk_id
      FROM member m
     WHERE v_kind IN ('project', 'role')
       AND m.name_id = v_name
    UNION ALL
    SELECT j.desk_id
      FROM seat j
     WHERE v_kind = 'lan'
       AND j.lan_ip = p_id
  ) d
  JOIN LATERAL (
    SELECT a.type, a.id, a.updated, a.deleted, a.desk_id, a.roster_id, a.n
      FROM activity a
     WHERE a.desk_id = d.desk_id
     ORDER BY a.updated DESC, a.type, a.id
     LIMIT v_n
  ) recent ON TRUE
  LEFT JOIN name dn ON dn.id = recent.desk_id
  LEFT JOIN name an ON an.id = recent.roster_id
  LEFT JOIN mail ml
    ON recent.type = 'mail'
   AND ml.id = recent.id
  LEFT JOIN mail_to mt
    ON recent.type = 'mail'
   AND mt.type = 'mail'
   AND mt.id = recent.id
   AND mt.desk_id <> recent.desk_id
  LEFT JOIN todo td
    ON recent.type = 'todo'
   AND td.type = 'todo'
   AND td.id = recent.id
  LEFT JOIN name oname ON oname.id = CASE recent.type
    WHEN 'mail' THEN mt.desk_id
    WHEN 'todo' THEN CASE
      WHEN td.assigned_id IS NOT NULL AND td.assigned_id <> recent.desk_id THEN td.assigned_id
      WHEN td.creator_id IS NOT NULL AND td.creator_id <> recent.desk_id THEN td.creator_id
      ELSE NULL
    END
    ELSE NULL
  END
  ORDER BY recent.desk_id, recent.updated DESC, recent.type, recent.id, other_desk_id;
END //

DELIMITER ;
