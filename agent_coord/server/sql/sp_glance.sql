-- Beta 0.8.0: the office glance (`mill glance`), computed live on each read (the owner, 2026-10-26).
-- No glance_cache table, no open_votes, no office-wide unread. Two result sets: the glance row,
-- then the newest 30 live activity rows. The client shapes both (beta_client.py; F176).

DROP PROCEDURE IF EXISTS mill_glance_refresh;
DROP PROCEDURE IF EXISTS uc_a6_glance_cached;
DROP PROCEDURE IF EXISTS uc_a6_glance;

DELIMITER //

CREATE PROCEDURE uc_a6_glance()
BEGIN
  DECLARE v_now DATETIME(6);
  DECLARE v_t0 DATETIME(6);
  DECLARE v_day DATETIME(6);
  DECLARE v_us INT UNSIGNED;
  SET v_now = MILL_NOW();
  SET v_t0 = SYSDATE(6);
  SET v_day = v_now - INTERVAL 1 DAY;
  SET v_us = LEAST(TIMESTAMPDIFF(MICROSECOND, v_t0, SYSDATE(6)), 4294967295);

  SELECT
    1 AS id,
    v_now AS at,
    v_us AS refresh_us,
    (SELECT COUNT(*) FROM seat j JOIN name d ON d.id = j.desk_id AND d.deleted IS NULL
      WHERE j.time_connect IS NOT NULL
        AND (j.time_disconnect IS NULL OR j.time_connect >= j.time_disconnect)) AS present,
    (SELECT COUNT(*) FROM hold WHERE desk_id IS NOT NULL) AS held,
    (SELECT COUNT(*) FROM todo t
       JOIN activity a ON a.type = 'todo' AND a.id = t.id AND a.deleted IS NULL
      WHERE t.status = 'open') AS open_n,
    (SELECT COUNT(*) FROM todo t
       JOIN activity a ON a.type = 'todo' AND a.id = t.id AND a.deleted IS NULL
      WHERE t.status = 'claimed') AS claimed_n,
    (SELECT COUNT(*) FROM todo t
       JOIN activity a ON a.type = 'todo' AND a.id = t.id AND a.deleted IS NULL
      WHERE t.status = 'parked') AS parked_n,
    (SELECT COUNT(*) FROM todo t
       JOIN activity a ON a.type = 'todo' AND a.id = t.id AND a.deleted IS NULL
      WHERE t.status = 'shipped') AS shipped_n,
    (SELECT COUNT(*) FROM todo t
       JOIN activity a ON a.type = 'todo' AND a.id = t.id AND a.deleted IS NULL
      WHERE t.status = 'done') AS done_n,
    (SELECT COUNT(*) FROM mail WHERE created >= v_day) AS letters_1d,
    -- 0.8.0: card moves live in doing (todo_event removed).
    (SELECT COUNT(*) FROM doing
      WHERE on_type = 'todo' AND act NOT IN ('focus', 'clear', 'finish')
        AND created >= v_day) AS card_moves_1d,
    (SELECT COUNT(*) FROM doing WHERE created >= v_day) AS doings_1d,
    (SELECT COUNT(*) FROM activity WHERE type = 'hold' AND updated >= v_day) AS holds_1d,
    (SELECT COUNT(*) FROM score_point WHERE created >= v_day) AS points_1d;

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
