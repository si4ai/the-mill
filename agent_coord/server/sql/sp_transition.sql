-- card 1022: insert one transition row. Allowed edges live in transition_edge
-- (seeded to match agent_coord/server/transition_enums.py ALLOWED_TRANSITIONS).
-- Unknown pair: refuse (SIGNAL). Emitters on later cards call this; this card ships the SP only.
-- from_state/to_state/reason are VARCHAR text in rows; callers should pass Enum .value from Python.

DROP PROCEDURE IF EXISTS mill_transition_put;

DELIMITER //

CREATE PROCEDURE mill_transition_put(
  IN p_activity_type ENUM('mail','todo','doing','hold','score','wake'),
  IN p_activity_id   BIGINT UNSIGNED,
  IN p_from_state    VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin,
  IN p_to_state      VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin,
  IN p_reason        VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin,
  IN p_desk_id       BIGINT UNSIGNED,
  IN p_role          ENUM('sender','recipient','actor','holder','waiter','office','other'),
  IN p_join_key      VARCHAR(96),
  IN p_meta          JSON
)
BEGIN
  DECLARE v_from VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin;
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

  SET v_from = IF(p_from_state IS NULL OR p_from_state = '', 'none', p_from_state);

  SELECT 1 INTO v_ok FROM transition_edge
   WHERE activity_type = p_activity_type
     AND from_state = v_from
     AND to_state = p_to_state
     AND reason = p_reason
   LIMIT 1;
  IF v_ok = 0 OR v_ok IS NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'mill_transition_put: unknown (activity_type, from_state, to_state, reason)';
  END IF;

  INSERT INTO transition (
    activity_type, activity_id, from_state, to_state, reason, desk_id, role, join_key, meta
  ) VALUES (
    p_activity_type, p_activity_id, v_from, p_to_state, p_reason,
    IFNULL(p_desk_id, 0), IFNULL(p_role, 'actor'), p_join_key, p_meta
  );
END //

DELIMITER ;
