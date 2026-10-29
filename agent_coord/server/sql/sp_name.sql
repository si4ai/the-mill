DROP PROCEDURE IF EXISTS mill_name_delete;
DROP PROCEDURE IF EXISTS mill_name_rename;
DROP PROCEDURE IF EXISTS mill_name_reclaim;
DROP PROCEDURE IF EXISTS mill_name_host;
-- 0.8.0: retire, rename and reclaim are sp_name_retire / _rename / _reclaim (sp_beta_name.sql);
-- main's three procedures are dropped above and not created again. mill_name_host stays for the
-- host path (a get-or-mint by type, through MILL_NAME_PUT).

DELIMITER //

CREATE PROCEDURE mill_name_host(IN p_type VARCHAR(16), IN p_name VARCHAR(64))
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_del DATETIME(6);
  SET v_id = MILL_NAME_GET(p_type, p_name);
  IF v_id IS NOT NULL THEN
    SELECT v_id AS id, TRIM(p_name) AS name, p_type AS name_type, 'exists' AS op;
  ELSE
    SET v_id = MILL_NAME_PUT(p_type, p_name);
    SELECT v_id AS id, TRIM(p_name) AS name, p_type AS name_type, 'created' AS op;
  END IF;
END //

DELIMITER ;
