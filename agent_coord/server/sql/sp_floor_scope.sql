-- One SELECT for one wall scope and one displayed part.
-- p_kind: role | lan. p_id: a role name, or a join.lan_ip. p_part: agents|mail|todos|holds|scores|events.
-- Desks in scope are loaded once into session temp mill_floor_desk. Each part reads that set once.

DROP PROCEDURE IF EXISTS mill_floor_scope_load;

DELIMITER //
CREATE PROCEDURE mill_floor_scope_load(
  IN p_kind VARCHAR(16),
  IN p_id   VARCHAR(64)
)
BEGIN
  DECLARE v_role BIGINT UNSIGNED DEFAULT NULL;
  -- The caller creates mill_floor_desk so the rows stay visible after this procedure returns.
  IF p_kind = 'role' THEN
    SET v_role = (
      SELECT id FROM name WHERE type = 'roster' AND name = p_id AND deleted IS NULL LIMIT 1
    );
  END IF;
  DELETE FROM mill_floor_desk;
  INSERT IGNORE INTO mill_floor_desk (desk_id)
  SELECT h.desk_id
    FROM seat h
   WHERE p_kind = 'lan' AND h.lan_ip = p_id
  UNION ALL
  SELECT h.desk_id
    FROM seat h
    JOIN member mr ON mr.name_id = v_role AND mr.desk_id = h.desk_id
   WHERE p_kind = 'role' AND v_role IS NOT NULL;
END //
DELIMITER ;

DROP PROCEDURE IF EXISTS mill_floor_part;

DELIMITER //
CREATE PROCEDURE mill_floor_part(
  IN p_kind VARCHAR(16),
  IN p_id   VARCHAR(64),
  IN p_part VARCHAR(16)
)
BEGIN
  CREATE TEMPORARY TABLE IF NOT EXISTS mill_floor_desk (
    desk_id BIGINT UNSIGNED NOT NULL PRIMARY KEY
  );
  CALL mill_floor_scope_load(p_kind, p_id);
  -- Each part JOINs mill_floor_desk (PK desk_id) once; MySQL allows one reference
  -- to a temporary table per statement.
  IF p_part = 'agents' THEN
    SELECT
      IFNULL(dsk.name, '') AS owner, IFNULL(dsk.type, '') AS owner_type,
      IFNULL((SELECT g.text FROM doing g WHERE g.desk_id = h.desk_id
              ORDER BY g.created DESC, g.id DESC LIMIT 1), '') AS doing,
      IF(h.time_connect IS NOT NULL AND (h.time_disconnect IS NULL OR h.time_connect >= h.time_disconnect), 1, 0) AS alive,
      IFNULL(h.lan_ip, '') AS lan_ip,
      '' AS roster_id,
      '' AS role,
      '' AS waiting_on,
      '' AS root,
      DATE_FORMAT(h.updated, '%Y-%m-%dT%H:%i:%s') AS heartbeat
    FROM seat h
    JOIN name dsk ON dsk.id = h.desk_id AND dsk.deleted IS NULL AND dsk.type = 'desk'
    LEFT JOIN mill_floor_desk fd ON fd.desk_id = h.desk_id
    WHERE h.token_hash IS NOT NULL AND h.token_hash <> ''
      AND (
        (p_kind = 'lan' AND h.lan_ip = p_id AND (
            (h.time_connect IS NOT NULL AND (h.time_disconnect IS NULL OR h.time_connect >= h.time_disconnect))
            OR (h.time_disconnect IS NOT NULL
                AND h.time_disconnect >= MILL_NOW() - INTERVAL 1 DAY
                AND (h.time_connect IS NULL OR h.time_disconnect > h.time_connect))
        ))
        OR (p_kind = 'role' AND fd.desk_id IS NOT NULL)
      )
    ORDER BY dsk.name;
  ELSEIF p_part = 'mail' THEN
    -- Letters in scope (sender or any dest desk), newest 500 letters. One row per letter;
    -- every dest of that letter rides along in dests (JSON_ARRAYAGG), so no per-letter dest read.
    CREATE TEMPORARY TABLE IF NOT EXISTS mill_floor_mail (
      id BIGINT UNSIGNED NOT NULL PRIMARY KEY
    );
    DELETE FROM mill_floor_mail;
    INSERT IGNORE INTO mill_floor_mail (id)
    SELECT m.id FROM mill_floor_desk d JOIN mail m ON m.desk_id = d.desk_id;
    INSERT IGNORE INTO mill_floor_mail (id)
    SELECT t.id FROM mill_floor_desk d JOIN mail_to t ON t.desk_id = d.desk_id AND t.type = 'mail';
    SELECT m.id AS id,
      IFNULL(ANY_VALUE(affn.name), '') AS roster_id, IFNULL(ANY_VALUE(affn.type), '') AS roster_id_type,
      IFNULL(ANY_VALUE(srcn.name), '') AS src, IFNULL(ANY_VALUE(srcn.type), '') AS src_type,
      IFNULL(ANY_VALUE(m.body), '') AS body,
      'note' AS kind,
      DATE_FORMAT(ANY_VALUE(m.created), '%Y-%m-%dT%H:%i:%s') AS at,
      MAX(IFNULL(t.receipt, 0)) AS human_required,
      JSON_ARRAYAGG(JSON_OBJECT(
        'desk_id', t.desk_id, 'desk', dstn.name, 'desk_type', dstn.type, 'receipt', t.receipt
      )) AS dests
    FROM (SELECT id FROM mill_floor_mail ORDER BY id DESC LIMIT 500) s
    JOIN mail m ON m.id = s.id
    JOIN mail_to t ON t.type = 'mail' AND t.id = m.id
    LEFT JOIN name srcn ON srcn.id = m.desk_id
    LEFT JOIN name dstn ON dstn.id = t.desk_id
    LEFT JOIN name affn ON affn.id = m.roster_id
    GROUP BY m.id
    ORDER BY m.id DESC;
  ELSEIF p_part = 'todos' THEN
    SELECT t.id AS id,
      CAST(t.id AS CHAR) AS need_id,  -- need_id = card id
      IFNULL(t.status, 'open') AS status,
      IFNULL(JSON_UNQUOTE(JSON_EXTRACT(t.body, '$.doing')), '') AS doing,
      IF(LEFT(t.body, 1) = '{', IFNULL(JSON_UNQUOTE(JSON_EXTRACT(t.body, '$.detail')), ''), IFNULL(t.body, '')) AS detail,
      IFNULL(JSON_UNQUOTE(JSON_EXTRACT(t.body, '$.progress')), '') AS progress,
      IFNULL(sn.name, '') AS assigned, IFNULL(sn.type, '') AS assigned_type,
      IFNULL(cn.name, '') AS creator, IFNULL(cn.type, '') AS creator_type,
      IFNULL(an.name, '') AS roster_id, IFNULL(an.type, '') AS roster_id_type
    FROM (
      SELECT DISTINCT tt.id
        FROM mill_floor_desk d
        JOIN todo tt ON tt.assigned_id = d.desk_id OR tt.creator_id = d.desk_id
    ) s
    JOIN todo t ON t.id = s.id
    LEFT JOIN name sn ON sn.id = t.assigned_id
    LEFT JOIN name cn ON cn.id = t.creator_id
    LEFT JOIN name an ON an.id = t.roster_id
    ORDER BY t.updated DESC
    LIMIT 200;
  ELSEIF p_part = 'holds' THEN
    SELECT
      IFNULL(rn.name, '') AS resource, IFNULL(rn.type, '') AS resource_type,
      IFNULL(dn.name, '') AS owner, IFNULL(dn.type, '') AS owner_type,
      IFNULL(an.name, '') AS roster_id, IFNULL(an.type, '') AS roster_id_type,
      0 AS holder_dead
    FROM hold h
    LEFT JOIN activity act ON act.type = 'hold' AND act.id = h.id
    LEFT JOIN name dn ON dn.id = h.desk_id
    LEFT JOIN name an ON an.id = act.roster_id
    LEFT JOIN name rn ON rn.id = h.resource_id
    JOIN mill_floor_desk fd ON fd.desk_id = h.desk_id
    ORDER BY h.updated DESC
    LIMIT 200;
  ELSEIF p_part = 'scores' THEN
    SELECT
      IFNULL(dn.name, '') AS owner, IFNULL(dn.type, '') AS owner_type,
      IFNULL(s.kpi, '') AS kpi,
      IFNULL(s.value, '') AS value,
      IFNULL(s.target, '') AS target,
      IFNULL(s.note, '') AS note,
      IFNULL(an.name, '') AS roster_id, IFNULL(an.type, '') AS roster_id_type
    FROM score s
    LEFT JOIN name dn ON dn.id = s.desk_id
    LEFT JOIN name an ON an.id = s.roster_id
    JOIN mill_floor_desk fd ON fd.desk_id = s.desk_id
    ORDER BY s.updated DESC
    LIMIT 200;
  ELSEIF p_part = 'events' THEN
    SELECT a.id AS id,
      a.type AS kind,
      a.type AS type,
      DATE_FORMAT(a.updated, '%Y-%m-%dT%H:%i:%s') AS at,
      IFNULL(dn.name, '') AS owner, IFNULL(dn.type, '') AS owner_type,
      IFNULL(an.name, '') AS roster_id, IFNULL(an.type, '') AS roster_id_type,
      a.weight AS weight,
      a.n AS n
    FROM activity a
    LEFT JOIN name dn ON dn.id = a.desk_id
    LEFT JOIN name an ON an.id = a.roster_id
    JOIN mill_floor_desk fd ON fd.desk_id = a.desk_id
    ORDER BY a.updated DESC
    LIMIT 120;
  END IF;
END //
DELIMITER ;


-- Cheap per-part fingerprint. Same scope predicates as mill_floor_part.
-- p_kind: role | lan | project. p_id: role name, lan_ip, or project name. p_part: agents|mail|todos|holds|scores|events|trees.
-- Trees on lan/role: fixed empty material until trees join the SP. Project trees use light structure stats.

DROP PROCEDURE IF EXISTS mill_floor_fp;

DELIMITER //
CREATE PROCEDURE mill_floor_fp(
  IN p_kind VARCHAR(16),
  IN p_id   VARCHAR(64),
  IN p_part VARCHAR(16)
)
BEGIN
  DECLARE v_proj BIGINT UNSIGNED DEFAULT NULL;

  IF p_kind <> 'project' THEN
    CREATE TEMPORARY TABLE IF NOT EXISTS mill_floor_desk (
      desk_id BIGINT UNSIGNED NOT NULL PRIMARY KEY
    );
    CALL mill_floor_scope_load(p_kind, p_id);
  END IF;

  IF p_kind = 'project' THEN
    IF IFNULL(p_id, '') <> '' THEN
      SET v_proj = MILL_NAME_GET('roster', p_id);
    END IF;
    IF p_part = 'mail' THEN
      SELECT 'mail' AS part, MILL_FP(CONCAT_WS(':',
        COUNT(DISTINCT m.id),
        IFNULL(MAX(m.id), 0),
        IFNULL(DATE_FORMAT(MAX(m.created), '%Y%m%d%H%i%s%f'), '0'),
        IFNULL(DATE_FORMAT(MAX(t.opened), '%Y%m%d%H%i%s%f'), '0'),
        IFNULL(MAX(t.receipt), 0)
      )) AS fp
      FROM mail m
      JOIN mail_to t ON t.type = 'mail' AND t.id = m.id
      WHERE v_proj IS NOT NULL
        AND m.roster_id = v_proj;
    ELSEIF p_part = 'trees' THEN
      SELECT 'trees' AS part, MILL_FP(CONCAT_WS(':',
        COUNT(*),
        IFNULL(SUM(t.lft) + SUM(t.rgt), 0),
        IFNULL(MAX(t.id), 0)
      )) AS fp
      FROM tree t
      JOIN activity a ON a.type = t.type AND a.id = t.id
      WHERE v_proj IS NOT NULL AND a.roster_id = v_proj;
    ELSEIF p_part = 'todos' THEN
      SELECT 'todos' AS part, MILL_FP(CONCAT_WS(':',
        COUNT(*),
        IFNULL(MAX(t.id), 0),
        IFNULL(DATE_FORMAT(MAX(t.updated), '%Y%m%d%H%i%s%f'), '0')
      )) AS fp
      FROM todo t
      WHERE v_proj IS NOT NULL AND t.roster_id = v_proj;
    ELSEIF p_part = 'agents' THEN
      SELECT 'agents' AS part, MILL_FP(CONCAT_WS(':',
        COUNT(*),
        IFNULL(MAX(h.id), 0),
        IFNULL(DATE_FORMAT(MAX(h.updated), '%Y%m%d%H%i%s%f'), '0')
      )) AS fp
      FROM seat h
      WHERE h.token_hash IS NOT NULL AND h.token_hash <> ''
        AND v_proj IS NOT NULL
        AND EXISTS (
          SELECT 1 FROM member mr
          WHERE mr.desk_id = h.desk_id AND mr.name_id = v_proj
        );
    ELSEIF p_part = 'scores' THEN
      SELECT 'scores' AS part, MILL_FP(CONCAT_WS(':',
        COUNT(*),
        IFNULL(MAX(s.id), 0),
        IFNULL(DATE_FORMAT(MAX(s.updated), '%Y%m%d%H%i%s%f'), '0')
      )) AS fp
      FROM score s
      WHERE v_proj IS NOT NULL AND s.roster_id = v_proj;
    ELSEIF p_part = 'holds' THEN
      SELECT 'holds' AS part, MILL_FP(CONCAT_WS(':',
        COUNT(*),
        IFNULL(MAX(h.id), 0),
        IFNULL(DATE_FORMAT(MAX(h.updated), '%Y%m%d%H%i%s%f'), '0')
      )) AS fp
      FROM hold h
      WHERE v_proj IS NOT NULL AND h.desk_id IS NOT NULL;
    ELSEIF p_part = 'events' THEN
      SELECT 'events' AS part, MILL_FP(CONCAT_WS(':',
        COUNT(*),
        IFNULL(MAX(a.id), 0),
        IFNULL(DATE_FORMAT(MAX(a.updated), '%Y%m%d%H%i%s%f'), '0')
      )) AS fp
      FROM activity a
      WHERE v_proj IS NOT NULL AND a.roster_id = v_proj;
    ELSE
      SELECT IFNULL(p_part, '') AS part, MILL_FP('') AS fp;
    END IF;
  ELSEIF p_part = 'trees' THEN
    SELECT 'trees' AS part, MILL_FP('trees:0') AS fp;
  ELSEIF p_part = 'agents' THEN
    SELECT 'agents' AS part, MILL_FP(CONCAT_WS(':',
      COUNT(*),
      IFNULL(MAX(h.id), 0),
      IFNULL(DATE_FORMAT(MAX(h.updated), '%Y%m%d%H%i%s%f'), '0')
    )) AS fp
    FROM seat h
    JOIN name dsk ON dsk.id = h.desk_id AND dsk.deleted IS NULL AND dsk.type = 'desk'
    WHERE h.token_hash IS NOT NULL AND h.token_hash <> ''
      AND (
        (p_kind = 'lan' AND h.lan_ip = p_id AND (
            (h.time_connect IS NOT NULL AND (h.time_disconnect IS NULL OR h.time_connect >= h.time_disconnect))
            OR (h.time_disconnect IS NOT NULL
                AND h.time_disconnect >= MILL_NOW() - INTERVAL 1 DAY
                AND (h.time_connect IS NULL OR h.time_disconnect > h.time_connect))
        ))
        OR (p_kind = 'role' AND h.desk_id IN (SELECT desk_id FROM mill_floor_desk))
      );
  ELSEIF p_part = 'mail' THEN
    SELECT 'mail' AS part, MILL_FP(CONCAT_WS(':',
      COUNT(DISTINCT m.id),
      IFNULL(MAX(m.id), 0),
      IFNULL(DATE_FORMAT(MAX(m.created), '%Y%m%d%H%i%s%f'), '0'),
      IFNULL(DATE_FORMAT(MAX(t.opened), '%Y%m%d%H%i%s%f'), '0'),
      IFNULL(MAX(t.receipt), 0)
    )) AS fp
    FROM mail m
    JOIN mail_to t ON t.type = 'mail' AND t.id = m.id
    WHERE EXISTS (
      SELECT 1 FROM mill_floor_desk d
      WHERE d.desk_id = m.desk_id OR d.desk_id = t.desk_id);
  ELSEIF p_part = 'todos' THEN
    SELECT 'todos' AS part, MILL_FP(CONCAT_WS(':',
      COUNT(*),
      IFNULL(MAX(t.id), 0),
      IFNULL(DATE_FORMAT(MAX(t.updated), '%Y%m%d%H%i%s%f'), '0')
    )) AS fp
    FROM todo t
    WHERE EXISTS (
      SELECT 1 FROM mill_floor_desk d
      WHERE d.desk_id = t.assigned_id OR d.desk_id = t.creator_id);
  ELSEIF p_part = 'holds' THEN
    SELECT 'holds' AS part, MILL_FP(CONCAT_WS(':',
      COUNT(*),
      IFNULL(MAX(h.id), 0),
      IFNULL(DATE_FORMAT(MAX(h.updated), '%Y%m%d%H%i%s%f'), '0')
    )) AS fp
    FROM hold h
    WHERE h.desk_id IN (SELECT desk_id FROM mill_floor_desk);
  ELSEIF p_part = 'scores' THEN
    SELECT 'scores' AS part, MILL_FP(CONCAT_WS(':',
      COUNT(*),
      IFNULL(MAX(s.id), 0),
      IFNULL(DATE_FORMAT(MAX(s.updated), '%Y%m%d%H%i%s%f'), '0')
    )) AS fp
    FROM score s
    WHERE s.desk_id IN (SELECT desk_id FROM mill_floor_desk);
  ELSEIF p_part = 'events' THEN
    SELECT 'events' AS part, MILL_FP(CONCAT_WS(':',
      COUNT(*),
      IFNULL(MAX(a.id), 0),
      IFNULL(DATE_FORMAT(MAX(a.updated), '%Y%m%d%H%i%s%f'), '0')
    )) AS fp
    FROM activity a
    WHERE a.desk_id IN (SELECT desk_id FROM mill_floor_desk);
  ELSE
    SELECT IFNULL(p_part, '') AS part, MILL_FP('') AS fp;
  END IF;
END //
DELIMITER ;
