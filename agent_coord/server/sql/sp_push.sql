-- card 1022: wake activity (= former push_queue). mill_push_take returns rows and
-- marks them taken (no delete). mill_push_expire rolls old untaken hint/mail/receipt
-- into one cause=expired marker per desk (archive/rollup; taken rows stay).

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
  DECLARE v_id   BIGINT UNSIGNED;
  DECLARE v_state VARCHAR(32);
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
  -- Initial delivery state (compat); lifecycle also uses queued/taken via transitions.
  SET v_state = p_outcome;

  IF GET_LOCK('mill_wake_alloc', 10) <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'push: wake id lock';
  END IF;
  SELECT IFNULL(MAX(id), 0) + 1 INTO v_id FROM activity WHERE type = 'wake';
  -- activity.desk_id = 0 (System); wake.desk_id = target desk
  INSERT INTO activity (type, id, desk_id, roster_id, act)
  VALUES ('wake', v_id, 0, 1, 'ring');
  INSERT INTO wake (id, type, desk_id, cause, state, payload)
  VALUES (v_id, 'wake', v_desk, p_kind, v_state, p_payload);
  DO RELEASE_LOCK('mill_wake_alloc');

  -- Seed transitions: none -> queued -> outcome state (when not already queued)
  INSERT IGNORE INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, role)
  VALUES ('wake', v_id, 'none', 'queued', 'wake_queue', 0, 'office');
  IF v_state <> 'queued' THEN
    INSERT IGNORE INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, role)
    VALUES ('wake', v_id, 'queued', v_state,
            CASE v_state
              WHEN 'sent' THEN 'wake_sent'
              WHEN 'missed' THEN 'wake_owed'
              ELSE 'wake_fail'
            END,
            0, 'office');
  END IF;

  SELECT v_id AS id, p_desk AS desk, p_kind AS kind, p_outcome AS outcome;
END //

CREATE PROCEDURE mill_push_take(
  IN p_desk VARCHAR(64)
)
BEGIN
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_max BIGINT UNSIGNED DEFAULT 0;
  DECLARE v_cut DATETIME(6);
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  SET v_cut = CURRENT_TIMESTAMP(6) - INTERVAL 7 DAY;

  -- Hand-back marks taken; rows stay for history/transitions.
  IF v_desk IS NULL THEN
    SELECT id, cause AS kind, payload, state AS outcome, created FROM wake WHERE 1 = 0;
  ELSE
    SET v_max = (
      SELECT IFNULL(MAX(id), 0) FROM wake
       WHERE desk_id = v_desk AND state <> 'taken'
    );
    SELECT p.id, p.cause AS kind, p.payload, p.state AS outcome, p.created
      FROM wake p
     WHERE p.desk_id = v_desk AND p.id <= v_max AND p.state <> 'taken'
       AND (p.cause = 'expired' OR p.created >= v_cut)
     ORDER BY p.id;

    INSERT INTO transition (activity_type, activity_id, from_state, to_state, reason, desk_id, role)
    SELECT 'wake', p.id, p.state, 'taken', 'wake_deliver', 0, 'office'
      FROM wake p
     WHERE p.desk_id = v_desk AND p.id <= v_max AND p.state <> 'taken'
       AND (p.cause = 'expired' OR p.created >= v_cut);

    UPDATE wake
       SET state = 'taken'
     WHERE desk_id = v_desk AND id <= v_max AND state <> 'taken'
       AND (cause = 'expired' OR created >= v_cut);
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
  SET v_cut = CURRENT_TIMESTAMP(6) - INTERVAL 7 DAY;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;

  -- One expired marker per desk. Later windows add counts.
  UPDATE wake AS e
  JOIN (
    SELECT id FROM (
      SELECT MIN(id) AS id
        FROM wake
       WHERE cause = 'expired'
       GROUP BY desk_id
    ) AS keep_one
  ) AS one ON one.id = e.id
  JOIN (
    SELECT desk_id, n_hint, n_mail, n_receipt, n_missed, n_error, w_start
      FROM (
        SELECT desk_id,
               CAST(SUM(cause = 'hint') AS UNSIGNED) AS n_hint,
               CAST(SUM(cause = 'mail') AS UNSIGNED) AS n_mail,
               CAST(SUM(cause = 'receipt') AS UNSIGNED) AS n_receipt,
               CAST(SUM(state = 'missed') AS UNSIGNED) AS n_missed,
               CAST(SUM(state = 'error') AS UNSIGNED) AS n_error,
               MIN(created) AS w_start
          FROM wake
         WHERE created < v_cut
           AND cause IN ('hint', 'mail', 'receipt')
           AND state <> 'taken'
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
   WHERE e.cause = 'expired';

  -- New expired markers need activity+wake rows
  BEGIN
    DECLARE done INT DEFAULT 0;
    DECLARE d BIGINT UNSIGNED;
    DECLARE n_hint INT UNSIGNED;
    DECLARE n_mail INT UNSIGNED;
    DECLARE n_receipt INT UNSIGNED;
    DECLARE n_missed INT UNSIGNED;
    DECLARE n_error INT UNSIGNED;
    DECLARE w_start DATETIME(6);
    DECLARE v_id BIGINT UNSIGNED;
    DECLARE cur CURSOR FOR
      SELECT s.desk_id, s.n_hint, s.n_mail, s.n_receipt, s.n_missed, s.n_error, s.w_start
        FROM (
          SELECT desk_id,
                 CAST(SUM(cause = 'hint') AS UNSIGNED) AS n_hint,
                 CAST(SUM(cause = 'mail') AS UNSIGNED) AS n_mail,
                 CAST(SUM(cause = 'receipt') AS UNSIGNED) AS n_receipt,
                 CAST(SUM(state = 'missed') AS UNSIGNED) AS n_missed,
                 CAST(SUM(state = 'error') AS UNSIGNED) AS n_error,
                 MIN(created) AS w_start
            FROM wake
           WHERE created < v_cut
             AND cause IN ('hint', 'mail', 'receipt')
             AND state <> 'taken'
           GROUP BY desk_id
        ) AS s
       WHERE NOT EXISTS (
         SELECT 1 FROM wake AS already
          WHERE already.desk_id = s.desk_id AND already.cause = 'expired'
       );
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = 1;
    OPEN cur;
    read_loop: LOOP
      FETCH cur INTO d, n_hint, n_mail, n_receipt, n_missed, n_error, w_start;
      IF done THEN LEAVE read_loop; END IF;
      IF GET_LOCK('mill_wake_alloc', 10) <> 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'push: wake id lock';
      END IF;
      SELECT IFNULL(MAX(id), 0) + 1 INTO v_id FROM activity WHERE type = 'wake';
      INSERT INTO activity (type, id, desk_id, roster_id, act)
      VALUES ('wake', v_id, 0, 1, 'ring');
      INSERT INTO wake (id, type, desk_id, cause, state, payload)
      VALUES (
        v_id, 'wake', d, 'expired', 'missed',
        JSON_OBJECT(
          'window_start', DATE_FORMAT(w_start, '%Y-%m-%d %H:%i:%s.%f'),
          'window_end', DATE_FORMAT(v_cut, '%Y-%m-%d %H:%i:%s.%f'),
          'hint', n_hint,
          'mail', n_mail,
          'receipt', n_receipt,
          'missed', n_missed,
          'error', n_error
        )
      );
      DO RELEASE_LOCK('mill_wake_alloc');
    END LOOP;
    CLOSE cur;
  END;

  -- Rollup: drop old untaken hint/mail/receipt bodies (taken rows stay)
  DELETE FROM wake
   WHERE created < v_cut
     AND cause IN ('hint', 'mail', 'receipt')
     AND state <> 'taken';
  SET v_gone = ROW_COUNT();
  -- orphaned activity rows for deleted wakes: leave for now (RESTRICT would block;
  -- delete wake first only when no FK from wake to activity... we have FK wake->activity,
  -- so DELETE wake is fine; activity rows remain as history.
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_gone AS deleted, DATE_FORMAT(v_cut, '%Y-%m-%d %H:%i:%s.%f') AS cut;
END //

DELIMITER ;
