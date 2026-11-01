-- Weight for one activity type. Change it here, not in every procedure.

DROP FUNCTION IF EXISTS MILL_WEIGHT;

DELIMITER //
CREATE FUNCTION MILL_WEIGHT(p_type ENUM('mail','todo','doing','hold','score','wake')) RETURNS INT
  DETERMINISTIC
  NO SQL
BEGIN
  RETURN CASE p_type
    WHEN 'mail' THEN 3
    WHEN 'todo' THEN 2
    WHEN 'hold' THEN 2
    WHEN 'score' THEN 1
    WHEN 'doing' THEN 1
    WHEN 'wake' THEN 1
    ELSE 1
  END;
END //
DELIMITER ;
