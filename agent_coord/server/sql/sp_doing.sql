-- Card 1207 (the owner, 2026-11-13): a doing row is one tw.exe (TaskWrapper) run, written only by mill_doing_task.
-- The row is the start; later states and the end are transition rows (activity_type doing, join_key task:...).
-- A desk's current doings are its rows with no terminal transition (finished, failed, stale, cleared); a desk may
-- run many. There are no focus, clear or finish rows, no --doing or --waiting-on, and no seat pointer.
-- A task's card is the card in its tw_start transition meta (MILL_DOING_CARD); the card link is an open question.

DROP FUNCTION IF EXISTS mill_doing_end;
DROP FUNCTION IF EXISTS mill_doing_cleared;
DROP FUNCTION IF EXISTS MILL_DOING_CARD;
DROP FUNCTION IF EXISTS MILL_DOING_LIVE;
DROP PROCEDURE IF EXISTS mill_doing_put;
DROP PROCEDURE IF EXISTS mill_doing_task;
DROP PROCEDURE IF EXISTS mill_doing_finish;
DROP PROCEDURE IF EXISTS mill_doing_clear_live;
DROP PROCEDURE IF EXISTS mill_doing_now;
DROP PROCEDURE IF EXISTS mill_doing_history;

DELIMITER //

-- 1 while the doing row has no terminal transition (the same rule as records.doing.live_tasks).
CREATE FUNCTION MILL_DOING_LIVE(p_id BIGINT UNSIGNED) RETURNS TINYINT
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  RETURN NOT EXISTS (SELECT 1 FROM transition e
                      WHERE e.activity_type = 'doing' AND e.activity_id = p_id
                        AND e.to_state IN ('finished', 'failed', 'stale', 'cleared'));
END //

-- The card a tw run is for: its tw_start transition's meta.card (tw --card), or NULL.
CREATE FUNCTION MILL_DOING_CARD(p_id BIGINT UNSIGNED) RETURNS BIGINT UNSIGNED
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  RETURN (SELECT CAST(JSON_UNQUOTE(JSON_EXTRACT(s.meta, '$.card')) AS UNSIGNED)
            FROM transition s
           WHERE s.activity_type = 'doing' AND s.activity_id = p_id AND s.reason = 'tw_start'
             AND JSON_EXTRACT(s.meta, '$.card') IS NOT NULL
           ORDER BY s.id LIMIT 1);
END //

-- card 970: the task birth. The caller holds a request transaction through the first transition insert.
-- p_card only picks the row's roster (the card's); the card itself rides in the tw_start meta.
CREATE PROCEDURE mill_doing_task(
  IN p_desk VARCHAR(64),
  IN p_join_key VARCHAR(96),
  IN p_card BIGINT UNSIGNED,
  IN p_start TINYINT
)
BEGIN
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_seat BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_id BIGINT UNSIGNED DEFAULT NULL;
  DECLARE v_state VARCHAR(32) DEFAULT 'idle';
  DECLARE v_created DATETIME(6);
  DECLARE v_roster BIGINT UNSIGNED DEFAULT 1;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SELECT id INTO v_seat FROM seat WHERE desk_id = v_desk AND token_hash IS NOT NULL FOR UPDATE;
  IF v_seat IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'tw.event: desk has not joined';
  END IF;
  SELECT t.activity_id, t.to_state, g.created
    INTO v_id, v_state, v_created
    FROM transition t JOIN doing g ON g.id = t.activity_id AND g.desk_id = t.desk_id
   WHERE t.activity_type = 'doing' AND t.desk_id = v_desk AND t.join_key = p_join_key
   ORDER BY t.id DESC LIMIT 1 FOR UPDATE;
  IF v_id IS NULL AND p_start = 1 THEN
    SET v_created = MILL_NOW();
    SET v_roster = IFNULL((SELECT roster_id FROM todo WHERE id = p_card), 1);
    INSERT INTO doing (created, desk_id, roster_id, text) VALUES (v_created, v_desk, v_roster, '');
    SET v_id = LAST_INSERT_ID();
    CALL mill_activity_put('doing', v_id, v_created, v_desk, v_roster, 'task', NULL);
  END IF;
  SELECT v_id AS id, v_desk AS desk_id, v_state AS state, v_created AS created;
END //

-- Clock-out, reset and retire end the desk's live doings: one Tsk7 row each (any -> cleared, reason clear),
-- desk_id the desk, meta {cause, by}. A later tw hop on a cleared run is a no-op (terminal).
CREATE PROCEDURE mill_doing_clear_live(
  IN p_desk  BIGINT UNSIGNED,
  IN p_by    BIGINT UNSIGNED,
  IN p_cause VARCHAR(16)
)
BEGIN
  INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, role, join_key, meta)
  SELECT 'doing', g.id, 'any', 'cleared', 'clear', g.desk_id, 'actor',
         (SELECT l.join_key FROM transition l
           WHERE l.activity_type = 'doing' AND l.activity_id = g.id AND l.join_key LIKE 'task:%'
           ORDER BY l.id DESC LIMIT 1),
         JSON_OBJECT('cause', p_cause, 'by', IFNULL(p_by, g.desk_id))
    FROM doing g
    JOIN activity a ON a.type = 'doing' AND a.id = g.id
   WHERE g.desk_id = p_desk AND MILL_DOING_LIVE(g.id)
   ORDER BY g.id;
END //

-- What desks are doing now: one row per listed desk (part desk), its heartbeat and how many doings it is
-- running (live tw runs; records.doing.live_doings reads the runs themselves). Card 1207 (wall-ui, 2026-11-13):
-- the blocked part (--waiting-on) and the waiting-on-it letters and cards are gone.
-- Listed: p_desk alone when named; else every desk on p_roster when named;
-- else every joined desk when p_all; else desks active in the last day.
CREATE PROCEDURE mill_doing_now(
  IN p_desk   VARCHAR(64),
  IN p_roster VARCHAR(64),
  IN p_all    TINYINT
)
BEGIN
  DECLARE v_now DATETIME(6);
  DECLARE v_one BIGINT UNSIGNED;
  DECLARE v_ros BIGINT UNSIGNED;
  DECLARE v_ids JSON;
  SET v_now = MILL_NOW();
  SET v_one = NULL;
  SET v_ros = NULL;
  IF IFNULL(p_desk, '') <> '' THEN
    SET v_one = IFNULL(MILL_NAME_GET('desk', p_desk), 0);
  ELSEIF IFNULL(p_roster, '') <> '' THEN
    SET v_ros = IFNULL(MILL_NAME_GET('roster', p_roster), 0);
  END IF;
  DROP TEMPORARY TABLE IF EXISTS tmp_doing_desk;
  CREATE TEMPORARY TABLE tmp_doing_desk (desk_id BIGINT UNSIGNED NOT NULL PRIMARY KEY) ENGINE=MEMORY;
  -- Card 1113: the desk list by a plain read into a value. INSERT ... SELECT from seat and name is
  -- a locking read: a status read held shared locks on every listed seat and name row.
  SELECT JSON_ARRAYAGG(s.desk_id) INTO v_ids
    FROM seat s
    JOIN name d ON d.id = s.desk_id AND d.type = 'desk' AND d.deleted IS NULL
   WHERE (s.token_hash IS NOT NULL OR s.time_disconnect IS NOT NULL)
     AND ((v_one IS NOT NULL AND s.desk_id = v_one)
      OR (v_ros IS NOT NULL AND EXISTS (SELECT 1 FROM member m WHERE m.desk_id = s.desk_id AND m.name_id = v_ros))
      OR (v_one IS NULL AND v_ros IS NULL AND (IFNULL(p_all, 0) = 1
          OR s.updated > v_now - INTERVAL 1 DAY
          OR EXISTS (SELECT 1 FROM activity a
                      WHERE a.desk_id = s.desk_id AND a.created > v_now - INTERVAL 1 DAY))));
  INSERT INTO tmp_doing_desk (desk_id)
  SELECT j.id FROM JSON_TABLE(IFNULL(v_ids, JSON_ARRAY()), '$[*]' COLUMNS (id BIGINT UNSIGNED PATH '$')) j;

  SELECT 'desk' AS part, d.name AS desk, lv.n AS doing_n,
         TIMESTAMPDIFF(SECOND, lv.newest, v_now) AS age_s,
         st.updated AS heartbeat, v_now AS now
    FROM tmp_doing_desk t
    JOIN name d ON d.id = t.desk_id
    JOIN seat st ON st.desk_id = t.desk_id
    LEFT JOIN LATERAL (
      SELECT COUNT(*) AS n, MAX(g.created) AS newest
        FROM doing g WHERE g.desk_id = t.desk_id AND MILL_DOING_LIVE(g.id)
    ) lv ON TRUE
   ORDER BY IFNULL(lv.newest, '1970-01-01') DESC, d.name;

  DROP TEMPORARY TABLE IF EXISTS tmp_doing_desk;
END //

-- Past doings (tw runs), newest first, one page (p_page from 1): each with its card (MILL_DOING_CARD), when it
-- ended and how (its terminal transition: finished, failed, stale or cleared). total counts every match.
-- p_on_type/p_on_id keep one item: a card's tw runs plus that item's moves (its transition rows, src transition;
-- act mapped from the reason; the card's todo.meta.evidence on its newest ship or done). p_desk may be empty.
CREATE PROCEDURE mill_doing_history(
  IN p_desk    VARCHAR(64),
  IN p_since   DATETIME(6),
  IN p_page    INT,
  IN p_size    INT,
  IN p_on_type VARCHAR(16),
  IN p_on_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_one BIGINT UNSIGNED;
  DECLARE v_off INT;
  SET v_one = NULL;
  IF IFNULL(p_desk, '') <> '' THEN
    SET v_one = IFNULL(MILL_NAME_GET('desk', p_desk), 0);
  END IF;
  SET v_off = (GREATEST(IFNULL(p_page, 1), 1) - 1) * GREATEST(IFNULL(p_size, 50), 1);
  SELECT x.id, x.desk, x.created, x.text, x.on_type, x.on_id, x.act, x.evidence, x.roster,
         x.ended_at, x.ended_by, x.src,
         COUNT(*) OVER () AS total
    FROM (
      SELECT g.id, d.name AS desk, g.created, g.text,
             IF(g.card IS NULL, NULL, 'todo') AS on_type, g.card AS on_id, 'task' AS act,
             CAST(NULL AS CHAR) AS evidence, ro.name AS roster,
             en.at AS ended_at, en.to_state AS ended_by, 'doing' AS src
        FROM (SELECT g0.*, MILL_DOING_CARD(g0.id) AS card FROM doing g0
               WHERE (v_one IS NULL OR g0.desk_id = v_one)
                 AND (p_since IS NULL OR g0.created >= p_since)) g
        JOIN name d ON d.id = g.desk_id
        JOIN name ro ON ro.id = g.roster_id
        LEFT JOIN LATERAL (
          SELECT e.at, e.to_state FROM transition e
           WHERE e.activity_type = 'doing' AND e.activity_id = g.id
             AND e.to_state IN ('finished', 'failed', 'stale', 'cleared')
           ORDER BY e.id LIMIT 1
        ) en ON TRUE
       WHERE IFNULL(p_on_type, '') = '' OR (p_on_type = 'todo' AND g.card = p_on_id)
      UNION ALL
      SELECT t.id, d.name AS desk, t.at AS created, '' AS text, t.activity_type AS on_type, t.activity_id AS on_id,
             CASE t.reason
               WHEN 'create' THEN 'create' WHEN 'create_parked' THEN 'park' WHEN 'unpark' THEN 'unpark'
               WHEN 'claim' THEN 'claim' WHEN 'take_over' THEN 'claim' WHEN 'assign' THEN 'assign'
               WHEN 'unclaim' THEN 'unclaim' WHEN 'pass_ship' THEN 'ship' WHEN 'pass_done' THEN 'done'
               WHEN 'pass_back' THEN 'back' WHEN 'retire' THEN 'retire' WHEN 'reclaim' THEN 'reclaim'
               WHEN 'rename' THEN 'rename' WHEN 'hold_grant' THEN 'hold' ELSE 'drop' END AS act,
             IF(t.activity_type = 'todo' AND t.reason IN ('pass_ship', 'pass_done')
                AND t.id = (SELECT MAX(l.id) FROM transition l
                             WHERE l.activity_type = 'todo' AND l.activity_id = t.activity_id
                               AND l.reason IN ('pass_ship', 'pass_done')),
                (SELECT MILL_TODO_EVIDENCE(c.meta) FROM todo c WHERE c.id = t.activity_id), NULL) AS evidence,
             IFNULL((SELECT r.name FROM todo c JOIN name r ON r.id = c.roster_id
                      WHERE t.activity_type = 'todo' AND c.id = t.activity_id), 'Office') AS roster,
             NULL AS ended_at, NULL AS ended_by, 'transition' AS src
        FROM transition t
        JOIN name d ON d.id = t.desk_id
       WHERE IFNULL(p_on_type, '') <> ''
         AND t.activity_type = p_on_type AND t.activity_id = p_on_id
         AND t.reason IN ('create', 'create_parked', 'unpark', 'claim', 'take_over', 'assign', 'unclaim',
                          'pass_ship', 'pass_done', 'pass_back', 'retire', 'reclaim', 'rename',
                          'hold_grant', 'hold_drop', 'hold_force')
         AND (v_one IS NULL OR t.desk_id = v_one)
         AND (p_since IS NULL OR t.at >= p_since)
    ) x
   ORDER BY x.created DESC, x.src, x.id DESC
   LIMIT v_off, p_size;
END //

DELIMITER ;
