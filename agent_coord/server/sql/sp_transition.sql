-- card 1022: insert one transition row. Allowed (activity_type, from_state, to_state)
-- pairs live here and in agent_coord/server/transition.py (keep in sync; SPIN reads one list).
-- Unknown pair: refuse (SIGNAL). Emitters on later cards call this; this card ships the SP only.

DROP PROCEDURE IF EXISTS mill_transition_put;

DELIMITER //

CREATE PROCEDURE mill_transition_put(
  IN p_activity_type ENUM('mail','todo','doing','hold','score','wake'),
  IN p_activity_id   BIGINT UNSIGNED,
  IN p_from_state    VARCHAR(32),
  IN p_to_state      VARCHAR(32),
  IN p_reason        VARCHAR(32),
  IN p_desk_id       BIGINT UNSIGNED,
  IN p_role          ENUM('sender','recipient','actor','holder','waiter','office','other'),
  IN p_join_key      VARCHAR(96),
  IN p_meta          JSON
)
BEGIN
  DECLARE v_from VARCHAR(32) DEFAULT IFNULL(p_from_state, '');
  DECLARE v_to   VARCHAR(32) DEFAULT IFNULL(p_to_state, '');
  DECLARE v_ok   TINYINT DEFAULT 0;

  IF p_activity_id IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'mill_transition_put: activity_id required';
  END IF;
  IF p_to_state IS NULL OR p_to_state = '' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'mill_transition_put: to_state required';
  END IF;
  IF p_reason IS NULL OR p_reason = '' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'mill_transition_put: reason required';
  END IF;

  -- Allowed edges (card 1022 starter set; emitters widen this list with their cards).
  -- Keep identical to ALLOWED_EDGES in agent_coord/server/transition.py.
  IF (p_activity_type = 'wake' AND v_from = '' AND v_to = 'queued')
     OR (p_activity_type = 'wake' AND v_from = 'queued' AND v_to = 'delivered')
     OR (p_activity_type = 'wake' AND v_from = 'delivered' AND v_to = 'taken')
     OR (p_activity_type = 'wake' AND v_from = 'taken' AND v_to = 'done')
     OR (p_activity_type = 'wake' AND v_from = 'taken' AND v_to = 'wasted')
     OR (p_activity_type = 'mail' AND v_from = '' AND v_to = 'sent')
     OR (p_activity_type = 'mail' AND v_from = 'sent' AND v_to = 'read')
     OR (p_activity_type = 'todo' AND v_from = '' AND v_to = 'open')
     OR (p_activity_type = 'todo' AND v_from = 'open' AND v_to = 'claimed')
     OR (p_activity_type = 'todo' AND v_from = 'claimed' AND v_to = 'shipped')
     OR (p_activity_type = 'todo' AND v_from = 'shipped' AND v_to = 'done')
     OR (p_activity_type = 'hold' AND v_from = '' AND v_to = 'held')
     OR (p_activity_type = 'hold' AND v_from = 'held' AND v_to = 'free')
     OR (p_activity_type = 'doing' AND v_from = '' AND v_to = 'focus')
     OR (p_activity_type = 'doing' AND v_from = 'focus' AND v_to = 'clear')
     OR (p_activity_type = 'score' AND v_from = '' AND v_to = 'published')
  THEN
    SET v_ok = 1;
  END IF;

  IF v_ok = 0 THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'mill_transition_put: unknown (activity_type, from_state, to_state)';
  END IF;

  INSERT INTO transition (
    activity_type, activity_id, from_state, to_state, reason, desk_id, role, join_key, meta
  ) VALUES (
    p_activity_type, p_activity_id, v_from, v_to, p_reason,
    IFNULL(p_desk_id, 0), IFNULL(p_role, 'actor'), p_join_key, p_meta
  );
END //

DELIMITER ;
