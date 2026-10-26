-- Beta 0.8.0: the office glance (`mill glance`). One cached row in glance_cache, refreshed
-- when it is older than 30 seconds (relaxed tier), plus the newest 30 activity rows.
-- No office-wide unread (owner rule). The client shapes both sets (beta_client.py).

DROP PROCEDURE IF EXISTS mill_glance_refresh;
DROP PROCEDURE IF EXISTS uc_a6_glance_cached;

DELIMITER //

-- A row younger than p_max_s stays. Callers at the same moment both write the row; the last write stays.
-- A fresh row is left as it is. Two callers at once both write the row; the last one stays.
CREATE PROCEDURE mill_glance_refresh(IN p_max_s INT)
BEGIN
  DECLARE v_now DATETIME(6);
  DECLARE v_t0 DATETIME(6);
  DECLARE v_day DATETIME(6);
  DECLARE v_max INT;
  SET v_now = MILL_NOW();
  SET v_max = GREATEST(IFNULL(p_max_s, 30), 0);
  IF NOT EXISTS (SELECT 1 FROM glance_cache
                  WHERE id = 1 AND at >= v_now - INTERVAL v_max SECOND) THEN
    SET v_t0 = SYSDATE(6);
    SET v_day = v_now - INTERVAL 1 DAY;
    REPLACE INTO glance_cache (id, at, refresh_us, present, held, open_n, claimed_n, parked_n,
                              shipped_n, done_n, letters_1d, card_moves_1d, doings_1d,
                              holds_1d, points_1d, open_votes)
    SELECT 1, v_now, 0,
           (SELECT COUNT(*) FROM seat j JOIN name d ON d.id = j.desk_id AND d.deleted IS NULL
             WHERE j.time_connect IS NOT NULL
               AND (j.time_disconnect IS NULL OR j.time_connect >= j.time_disconnect)),
           (SELECT COUNT(*) FROM hold WHERE desk_id IS NOT NULL),
           IFNULL(SUM(t.status = 'open'), 0),
           IFNULL(SUM(t.status = 'claimed'), 0),
           IFNULL(SUM(t.status = 'parked'), 0),
           IFNULL(SUM(t.status = 'shipped'), 0),
           IFNULL(SUM(t.status = 'done'), 0),
           (SELECT COUNT(*) FROM mail WHERE created >= v_day),
           (SELECT COUNT(*) FROM todo_event WHERE created >= v_day),
           (SELECT COUNT(*) FROM doing WHERE created >= v_day),
           (SELECT COUNT(*) FROM activity WHERE type = 'hold' AND updated >= v_day),
           (SELECT COUNT(*) FROM score_point WHERE created >= v_day),
           (SELECT COUNT(*) FROM vote WHERE closed IS NULL)
      FROM todo t
      LEFT JOIN activity a ON a.type = 'todo' AND a.id = t.id
     WHERE a.deleted IS NULL;
    UPDATE glance_cache
       SET refresh_us = LEAST(TIMESTAMPDIFF(MICROSECOND, v_t0, SYSDATE(6)), 4294967295)
     WHERE id = 1;
  END IF;
END //

-- Two result sets: the glance row, then the newest 30 live activity rows
-- (seq 1 = newest; kind letter, card, doing, hold or score; desk NULL = the office).
-- Each kind reads its newest 30 ids from the activity primary key, so the read stays
-- small at any history size; the 30 newest by time are taken from those.
CREATE PROCEDURE uc_a6_glance_cached()
BEGIN
  CALL mill_glance_refresh(30);
  SELECT id, at, refresh_us, present, held, open_n, claimed_n, parked_n, shipped_n, done_n,
         letters_1d, card_moves_1d, doings_1d, holds_1d, points_1d, open_votes
    FROM glance_cache WHERE id = 1;
  SELECT ROW_NUMBER() OVER (ORDER BY r.updated DESC, r.type, r.id DESC) AS seq,
         r.updated AS at,
         CASE r.type WHEN 'mail' THEN 'letter' WHEN 'todo' THEN 'card' ELSE r.type END AS kind,
         r.id AS ref,
         dn.name AS desk
    FROM (
      (SELECT type, id, updated, desk_id FROM activity
        WHERE type = 'mail' AND deleted IS NULL ORDER BY id DESC LIMIT 30)
      UNION ALL
      (SELECT type, id, updated, desk_id FROM activity
        WHERE type = 'todo' AND deleted IS NULL ORDER BY id DESC LIMIT 30)
      UNION ALL
      (SELECT type, id, updated, desk_id FROM activity
        WHERE type = 'doing' AND deleted IS NULL ORDER BY id DESC LIMIT 30)
      UNION ALL
      (SELECT type, id, updated, desk_id FROM activity
        WHERE type = 'hold' AND deleted IS NULL ORDER BY id DESC LIMIT 30)
      UNION ALL
      (SELECT type, id, updated, desk_id FROM activity
        WHERE type = 'score' AND deleted IS NULL ORDER BY id DESC LIMIT 30)
    ) r
    LEFT JOIN name dn ON dn.id = r.desk_id
   ORDER BY r.updated DESC, r.type, r.id DESC
   LIMIT 30;
END //

DELIMITER ;
