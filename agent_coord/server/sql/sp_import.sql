-- card 1200: copy this book's desk bearer salts onto an uploaded book.
-- match is the desk's unique name. the upload database is otherwise left as loaded.
-- call it from the book that holds the salts: CALL mill_import_bearer_salts('upload_db');

DROP PROCEDURE IF EXISTS mill_import_bearer_salts;

DELIMITER //

CREATE PROCEDURE mill_import_bearer_salts(IN p_upload VARCHAR(64))
BEGIN
  IF p_upload IS NULL OR p_upload NOT REGEXP '^[A-Za-z0-9_]+$' THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'upload database name is not a plain identifier';
  END IF;
  SET @mill_import_sql = CONCAT(
    'UPDATE `', p_upload, '`.seat s ',
    'JOIN `', p_upload, '`.name n ON n.id = s.desk_id AND n.type = ''desk'' ',
    'JOIN `', DATABASE(), '`.name ln ON ln.type = ''desk'' AND ln.name = n.name ',
    'JOIN `', DATABASE(), '`.seat ls ON ls.desk_id = ln.id ',
    'SET s.token_hash = ls.token_hash ',
    'WHERE ls.token_hash IS NOT NULL'
  );
  PREPARE mill_import_stmt FROM @mill_import_sql;
  EXECUTE mill_import_stmt;
  DEALLOCATE PREPARE mill_import_stmt;
END //

DELIMITER ;
