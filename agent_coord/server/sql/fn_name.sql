-- MILL_NAME_GET: SELECT only (reads must not mint).
-- MILL_NAME_PUT: INSERT on first use (intentional create paths only).
--   0.8.0: a new roster or label reads b_trust() (admin.md section 2): limited trust refuses it here,
--   Admin mints through sp_name_mint. A new desk gets its seat row (token NULL) with its name: every
--   desk column FKs to seat (desk_id), the desk kind table. Plans (tree) and resources (res) mint as on main.
-- Reads use MILL_NAME_GET. Creates use MILL_NAME_PUT.
-- A name is (type, bare string). id is the primary key. idx_type is UNIQUE (type, name).
-- Deleted names stay unique; retired names SIGNAL on get and put.

DROP FUNCTION IF EXISTS MILL_NAME;
DROP FUNCTION IF EXISTS MILL_NAME_GET;
DROP FUNCTION IF EXISTS MILL_NAME_PUT;
DROP FUNCTION IF EXISTS MILL_NEXT_ID;
DROP FUNCTION IF EXISTS MILL_SLUG;
DROP FUNCTION IF EXISTS MILL_DESLUG;
DROP FUNCTION IF EXISTS MILL_KIND;
DROP FUNCTION IF EXISTS MILL_NAME_TYPE;
DROP FUNCTION IF EXISTS MILL_NAME_BARE;
DROP FUNCTION IF EXISTS MILL_NAME_KEY;
DROP FUNCTION IF EXISTS NAME_TYPE;
DROP FUNCTION IF EXISTS NAME_BARE;
DROP FUNCTION IF EXISTS PROJECT_KEY;
DROP FUNCTION IF EXISTS DESK_KEY;
DROP FUNCTION IF EXISTS ROLE_KEY;
DROP FUNCTION IF EXISTS LABEL_KEY;
DROP FUNCTION IF EXISTS RES_KEY;
DROP FUNCTION IF EXISTS TREE_KEY;

DELIMITER //

CREATE FUNCTION MILL_NAME_GET(p_type VARCHAR(16), p_name VARCHAR(64)) RETURNS BIGINT UNSIGNED
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_del DATETIME(6);
  IF p_type IS NULL OR p_type NOT IN ('desk','roster','label','tree','res') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name type is desk, roster, label, tree, or res';
  END IF;
  IF p_name IS NULL OR TRIM(p_name) = '' THEN
    RETURN NULL;
  END IF;
  SELECT id, deleted INTO v_id, v_del
    FROM name
   WHERE type = p_type AND name = TRIM(p_name)
   LIMIT 1;
  IF v_id IS NULL THEN
    -- #722: Office names roster id 1, also after an Admin renamed it.
    IF p_type = 'roster' AND TRIM(p_name) COLLATE utf8mb4_0900_ai_ci = 'Office' THEN
      RETURN 1;
    END IF;
    RETURN NULL;
  END IF;
  IF v_del IS NOT NULL THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'name retired: mill reclaim NAME NAME --yes (mill host only)';
  END IF;
  RETURN v_id;
END //

CREATE FUNCTION MILL_NAME_PUT(p_type VARCHAR(16), p_name VARCHAR(64)) RETURNS BIGINT UNSIGNED
  NOT DETERMINISTIC
  MODIFIES SQL DATA
BEGIN
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_del DATETIME(6);
  DECLARE v_dup INT DEFAULT 0;
  DECLARE CONTINUE HANDLER FOR 1062 SET v_dup = 1;
  IF p_type IS NULL OR p_type NOT IN ('desk','roster','label','tree','res') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name type is desk, roster, label, tree, or res';
  END IF;
  IF p_name IS NULL OR TRIM(p_name) = '' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name is empty';
  END IF;
  SELECT id, deleted INTO v_id, v_del
    FROM name
   WHERE type = p_type AND name = TRIM(p_name)
   LIMIT 1;
  IF v_id IS NOT NULL THEN
    IF v_del IS NOT NULL THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'name retired: mill reclaim NAME NAME --yes (mill host only)';
    END IF;
    RETURN v_id;
  END IF;
  -- #722: Office names roster id 1 (renamed or not); never a second roster.
  IF p_type = 'roster' AND TRIM(p_name) COLLATE utf8mb4_0900_ai_ci = 'Office' THEN
    RETURN 1;
  END IF;
  IF p_type IN ('roster', 'label') AND b_trust() = 'limited' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'limited-trust: minting a roster or label is Admin (mill create roster NAME --yes)';
  END IF;
  INSERT INTO name (type, name) VALUES (p_type, TRIM(p_name));
  IF v_dup = 1 THEN
    SELECT id, deleted INTO v_id, v_del
      FROM name
     WHERE type = p_type AND name = TRIM(p_name)
     LIMIT 1;
    IF v_id IS NULL THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'name insert lost a race';
    END IF;
    IF v_del IS NOT NULL THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'name retired: mill reclaim NAME NAME --yes (mill host only)';
    END IF;
    RETURN v_id;
  END IF;
  SET v_id = LAST_INSERT_ID();
  IF p_type = 'desk' THEN
    INSERT INTO seat (desk_id) VALUES (v_id);
  END IF;
  RETURN v_id;
END //

DELIMITER ;
