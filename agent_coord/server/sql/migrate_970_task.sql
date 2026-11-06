-- card 970: existing-book task acts; fresh books use tables.sql.

SET @mill_970_act := (
  SELECT COLUMN_TYPE FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'activity' AND COLUMN_NAME = 'act'
);
SET @mill_970_sql := IF(
  @mill_970_act IS NOT NULL AND @mill_970_act LIKE 'enum(%' AND @mill_970_act NOT LIKE '%''task''%',
  CONCAT('ALTER TABLE activity MODIFY act ', LEFT(@mill_970_act, CHAR_LENGTH(@mill_970_act) - 1), ',''task'') NOT NULL DEFAULT ''create'''),
  'SELECT 1'
);
PREPARE mill_970_stmt FROM @mill_970_sql;
EXECUTE mill_970_stmt;
DEALLOCATE PREPARE mill_970_stmt;

SET @mill_970_act := (
  SELECT COLUMN_TYPE FROM information_schema.COLUMNS
   WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'doing' AND COLUMN_NAME = 'act'
);
SET @mill_970_sql := IF(
  @mill_970_act IS NOT NULL AND @mill_970_act LIKE 'enum(%' AND @mill_970_act NOT LIKE '%''task''%',
  CONCAT('ALTER TABLE doing MODIFY act ', LEFT(@mill_970_act, CHAR_LENGTH(@mill_970_act) - 1), ',''task'') NOT NULL DEFAULT ''focus'''),
  'SELECT 1'
);
PREPARE mill_970_stmt FROM @mill_970_sql;
EXECUTE mill_970_stmt;
DEALLOCATE PREPARE mill_970_stmt;
