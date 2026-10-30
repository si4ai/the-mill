-- Queue. mill_push_take returns the desk's rows and deletes them.
-- A row older than 30 days is never handed out. mill_push_expire deletes those rows
-- for every desk. The wall runs it at start and then twice a day, not on every take.
-- Each desk that lost rows gets one kind=expired line (window and counts, no bodies).
-- That line does not age out. A later window adds to the same row.

DROP PROCEDURE IF EXISTS mill_push_put;
DROP PROCEDURE IF EXISTS mill_push_take;
DROP PROCEDURE IF EXISTS mill_push_expire;

DELIMITER //

CREATE PROCEDURE mill_push_put(
  IN p_desk    VARCHAR(64),
  IN p_kind    VARCHAR(16),
  IN p_payload JSON,
  IN p_outcome VARCHAR(16)
)
BEGIN
  DECLARE v_desk BIGINT UNSIGNED;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'push: desk is not seated';
  END IF;
  IF p_kind NOT IN ('hint', 'mail', 'receipt') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'push: kind';
  END IF;
  IF p_outcome NOT IN ('sent', 'missed', 'error') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'push: outcome';
  END IF;
  INSERT INTO push_queue (desk_id, kind, payload, outcome)
  VALUES (v_desk, p_kind, p_payload, p_outcome);
  SELECT LAST_INSERT_ID() AS id, p_desk AS desk, p_kind AS kind, p_outcome AS outcome;
END //

CREATE PROCEDURE mill_push_take(
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_max BIGINT UNSIGNED DEFAULT 0;
  DECLARE v_cut DATETIME(6);
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_cut = CURRENT_TIMESTAMP(6) - INTERVAL 30 DAY;

  -- The sweep is mill_push_expire. A row past 30 days stays queued for it.
  IF v_desk IS NULL THEN
    SELECT id, kind, payload, outcome, created FROM push_queue WHERE 1 = 0;
  ELSE
    SET v_max = (SELECT IFNULL(MAX(id), 0) FROM push_queue WHERE desk_id = v_desk);
    SELECT p.id, p.kind, p.payload, p.outcome, p.created
      FROM push_queue p
     WHERE p.desk_id = v_desk AND p.id <= v_max
       AND (p.kind = 'expired' OR p.created >= v_cut)
     ORDER BY p.id;
    DELETE FROM push_queue
     WHERE desk_id = v_desk AND id <= v_max
       AND (kind = 'expired' OR created >= v_cut);
  END IF;
END //

CREATE PROCEDURE mill_push_expire()
BEGIN
  DECLARE v_cut DATETIME(6);
  DECLARE v_gone INT DEFAULT 0;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  SET v_cut = CURRENT_TIMESTAMP(6) - INTERVAL 30 DAY;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;

  -- One expired line per desk. A later window adds counts and moves created forward.
  UPDATE push_queue AS e
  JOIN (
    SELECT id FROM (
      SELECT MIN(id) AS id
        FROM push_queue
       WHERE kind = 'expired'
       GROUP BY desk_id
    ) AS keep_one
  ) AS one ON one.id = e.id
  JOIN (
    SELECT desk_id, n_hint, n_mail, n_receipt, n_missed, n_error, w_start
      FROM (
        SELECT desk_id,
               CAST(SUM(kind = 'hint') AS UNSIGNED) AS n_hint,
               CAST(SUM(kind = 'mail') AS UNSIGNED) AS n_mail,
               CAST(SUM(kind = 'receipt') AS UNSIGNED) AS n_receipt,
               CAST(SUM(outcome = 'missed') AS UNSIGNED) AS n_missed,
               CAST(SUM(outcome = 'error') AS UNSIGNED) AS n_error,
               MIN(created) AS w_start
          FROM push_queue
         WHERE created < v_cut
           AND kind IN ('hint', 'mail', 'receipt')
         GROUP BY desk_id
      ) AS grouped
  ) AS s ON s.desk_id = e.desk_id
     SET e.created = CURRENT_TIMESTAMP(6),
         e.payload = JSON_OBJECT(
           'window_start', DATE_FORMAT(
             LEAST(
               IFNULL(
                 CAST(JSON_UNQUOTE(JSON_EXTRACT(e.payload, '$.window_start')) AS DATETIME(6)),
                 s.w_start
               ),
               s.w_start
             ),
             '%Y-%m-%d %H:%i:%s.%f'
           ),
           'window_end', DATE_FORMAT(v_cut, '%Y-%m-%d %H:%i:%s.%f'),
           'hint', IFNULL(CAST(JSON_EXTRACT(e.payload, '$.hint') AS UNSIGNED), 0) + s.n_hint,
           'mail', IFNULL(CAST(JSON_EXTRACT(e.payload, '$.mail') AS UNSIGNED), 0) + s.n_mail,
           'receipt', IFNULL(CAST(JSON_EXTRACT(e.payload, '$.receipt') AS UNSIGNED), 0) + s.n_receipt,
           'missed', IFNULL(CAST(JSON_EXTRACT(e.payload, '$.missed') AS UNSIGNED), 0) + s.n_missed,
           'error', IFNULL(CAST(JSON_EXTRACT(e.payload, '$.error') AS UNSIGNED), 0) + s.n_error
         )
   WHERE e.kind = 'expired';

  INSERT INTO push_queue (desk_id, kind, payload, outcome)
  SELECT s.desk_id,
         'expired',
         JSON_OBJECT(
           'window_start', DATE_FORMAT(s.w_start, '%Y-%m-%d %H:%i:%s.%f'),
           'window_end', DATE_FORMAT(v_cut, '%Y-%m-%d %H:%i:%s.%f'),
           'hint', s.n_hint,
           'mail', s.n_mail,
           'receipt', s.n_receipt,
           'missed', s.n_missed,
           'error', s.n_error
         ),
         'missed'
    FROM (
      SELECT desk_id,
             CAST(SUM(kind = 'hint') AS UNSIGNED) AS n_hint,
             CAST(SUM(kind = 'mail') AS UNSIGNED) AS n_mail,
             CAST(SUM(kind = 'receipt') AS UNSIGNED) AS n_receipt,
             CAST(SUM(outcome = 'missed') AS UNSIGNED) AS n_missed,
             CAST(SUM(outcome = 'error') AS UNSIGNED) AS n_error,
             MIN(created) AS w_start
        FROM push_queue
       WHERE created < v_cut
         AND kind IN ('hint', 'mail', 'receipt')
       GROUP BY desk_id
    ) AS s
   WHERE NOT EXISTS (
     SELECT 1 FROM push_queue AS already
      WHERE already.desk_id = s.desk_id AND already.kind = 'expired'
   );

  DELETE FROM push_queue
   WHERE created < v_cut
     AND kind IN ('hint', 'mail', 'receipt');
  SET v_gone = ROW_COUNT();
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_gone AS deleted, DATE_FORMAT(v_cut, '%Y-%m-%d %H:%i:%s.%f') AS cut;
END //

DELIMITER ;
