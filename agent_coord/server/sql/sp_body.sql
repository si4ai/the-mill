-- Card 1133: the body of a mail or card, its edit stamp and its history (activity_history).
-- A card's text is todo.body; the rest of what the server keeps on a card (slug, progress, eta_at, started_at,
-- aliases) is todo.meta. Card state (status, volunteer, claimed_at) stays in its own columns.
-- MILL_TODO_DOC rebuilds the one JSON document the server reads today, so readers keep their shape while
-- writers store the split. MILL_BODY_TEXT and MILL_BODY_META split such a document for a writer.
-- mill_body_replace is the one way to change the text of either kind and keep the old text.

DROP FUNCTION IF EXISTS MILL_TODO_DOC;
DROP FUNCTION IF EXISTS MILL_BODY_TEXT;
DROP FUNCTION IF EXISTS MILL_BODY_META;
DROP PROCEDURE IF EXISTS mill_body_replace;
DROP PROCEDURE IF EXISTS mill_body_history;

DELIMITER //

-- The card document: meta with the text as its detail. meta NULL is a row the 1133 migration has not split
-- yet, whose body is still the whole document.
CREATE FUNCTION MILL_TODO_DOC(p_body VARCHAR(4096), p_meta JSON)
  RETURNS TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci
  DETERMINISTIC
  NO SQL
BEGIN
  IF p_meta IS NULL THEN
    RETURN p_body;
  END IF;
  RETURN CAST(JSON_SET(p_meta, '$.detail', IFNULL(p_body, '')) AS CHAR CHARACTER SET utf8mb4);
END //

-- The text of a card document: its detail string, unescaped. A body that is not a JSON object is all text.
CREATE FUNCTION MILL_BODY_TEXT(p_doc VARCHAR(4096))
  RETURNS VARCHAR(4096) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci
  DETERMINISTIC
  NO SQL
BEGIN
  IF p_doc IS NULL THEN
    RETURN NULL;
  END IF;
  IF NOT JSON_VALID(p_doc) THEN
    RETURN p_doc;
  END IF;
  IF JSON_TYPE(CAST(p_doc AS JSON)) <> 'OBJECT' THEN
    RETURN p_doc;
  END IF;
  RETURN CASE IFNULL(JSON_TYPE(JSON_EXTRACT(p_doc, '$.detail')), 'NULL')
    WHEN 'NULL' THEN ''
    WHEN 'STRING' THEN JSON_UNQUOTE(JSON_EXTRACT(p_doc, '$.detail'))
    ELSE CAST(JSON_EXTRACT(p_doc, '$.detail') AS CHAR CHARACTER SET utf8mb4)
  END;
END //

-- The meta of a card document: every key but detail. A body that is not a JSON object has empty meta.
CREATE FUNCTION MILL_BODY_META(p_doc VARCHAR(4096))
  RETURNS JSON
  DETERMINISTIC
  NO SQL
BEGIN
  IF p_doc IS NULL THEN
    RETURN NULL;
  END IF;
  IF NOT JSON_VALID(p_doc) THEN
    RETURN JSON_OBJECT();
  END IF;
  IF JSON_TYPE(CAST(p_doc AS JSON)) <> 'OBJECT' THEN
    RETURN JSON_OBJECT();
  END IF;
  RETURN JSON_REMOVE(CAST(p_doc AS JSON), '$.detail');
END //

-- Replace the text of a letter or a card (the replace-body command, card 1125). One transaction under the item lock:
-- the old text goes to activity_history (full text, never a diff), the row takes the new text and both stamps,
-- and the item's activity row says act replace. p_expected is the body stamp the caller read (body_updated, or
-- created when the text was never edited); any other value refuses body:stale and writes nothing, so two desks
-- editing from the same text cannot lose one edit (UNIQUE type, activity_id, old_updated backs this up).
-- Rights: a letter's sender or an Admin desk; a card's asker or an Admin desk. A letter's opened and receipt
-- marks (mail_to) are not touched. Refusals, nothing written: body:type, body:no_desk, body:no_text,
-- body:no_such_item, body:deleted, body:rights, body:stale, body:unchanged (the new text is the same as the
-- current text, so the replace did nothing; its message says so in plain words).
CREATE PROCEDURE mill_body_replace(
  IN p_type     VARCHAR(8),
  IN p_id       BIGINT UNSIGNED,
  IN p_desk     VARCHAR(64),
  IN p_body     VARCHAR(4096),
  IN p_expected DATETIME(6)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_lock BIGINT UNSIGNED;
  DECLARE v_owner BIGINT UNSIGNED;
  DECLARE v_proj BIGINT UNSIGNED;
  DECLARE v_old VARCHAR(4096) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
  DECLARE v_old_ts DATETIME(6);
  DECLARE v_old_by BIGINT UNSIGNED;
  DECLARE v_hist BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  IF p_type IS NULL OR p_type NOT IN ('mail', 'todo') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'body:type';
  END IF;
  IF p_body IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'body:no_text';
  END IF;
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'body:no_desk';
  END IF;
  -- Lock order (F183, card 1113): the editing desk's seat, then the item, both exclusive, as every writer.
  SELECT id INTO v_lock FROM seat WHERE desk_id = v_desk FOR UPDATE;
  IF p_type = 'mail' THEN
    SELECT desk_id, roster_id, body, IFNULL(body_updated, created), IFNULL(body_updater_id, desk_id)
      INTO v_owner, v_proj, v_old, v_old_ts, v_old_by
      FROM mail WHERE id = p_id FOR UPDATE;
  ELSE
    SELECT creator_id, roster_id, IF(meta IS NULL, MILL_BODY_TEXT(body), body),
           IFNULL(body_updated, created), IFNULL(body_updater_id, creator_id)
      INTO v_owner, v_proj, v_old, v_old_ts, v_old_by
      FROM todo WHERE id = p_id FOR UPDATE;
  END IF;
  IF v_owner IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'body:no_such_item';
  END IF;
  IF EXISTS (SELECT 1 FROM activity WHERE type = p_type AND id = p_id AND deleted IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'body:deleted';
  END IF;
  IF v_desk <> v_owner
     AND NOT EXISTS (SELECT 1 FROM member
                      WHERE name_id = 2  -- the reserved Admin roster (#722)
                        AND desk_id = v_desk) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'body:rights';
  END IF;
  IF NOT (p_expected <=> v_old_ts) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'body:stale';
  END IF;
  IF CAST(p_body AS BINARY) = CAST(v_old AS BINARY) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'body:unchanged: replace did nothing: the new text is the same as the current text';
  END IF;
  INSERT INTO activity_history (type, activity_id, old_body, old_updated, old_updater_id, replaced_at, replaced_by)
  VALUES (p_type, p_id, v_old, v_old_ts, v_old_by, v_ts, v_desk);
  SET v_hist = LAST_INSERT_ID();
  IF p_type = 'mail' THEN
    UPDATE mail SET body = p_body, body_updated = v_ts, body_updater_id = v_desk WHERE id = p_id;
  ELSE
    -- meta first (left to right): a row the migration has not split takes its meta from the old document.
    UPDATE todo
       SET meta = IFNULL(meta, MILL_BODY_META(body)),
           body = p_body,
           body_updated = v_ts,
           body_updater_id = v_desk,
           updated = v_ts,
           updated_id = v_desk
     WHERE id = p_id;
  END IF;
  CALL mill_activity_put(p_type, p_id, v_ts, v_desk, v_proj, 'replace', LENGTH(p_body));
  IF p_type = 'todo' THEN
    CALL mill_watcher_roster('todo', p_id, v_proj, v_desk);
  END IF;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT p_type AS type, p_id AS id, v_hist AS history_id, v_ts AS body_updated, v_desk AS body_updater_id,
         v_old_ts AS old_updated, 'replaced' AS op;
END //

-- The old texts of one letter or card, newest first by default: each row is the text that stood from old_updated
-- (written by old_updater) until replaced_at (replaced by replaced_by). The current text is the item's.
-- p_order 'newest' or NULL lists the latest old text first; 'oldest' lists the first text first. Any other value
-- refuses body:order.
CREATE PROCEDURE mill_body_history(
  IN p_type  VARCHAR(8),
  IN p_id    BIGINT UNSIGNED,
  IN p_order VARCHAR(8)
)
BEGIN
  IF p_order IS NOT NULL AND p_order NOT IN ('newest', 'oldest') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'body:order: order is newest or oldest';
  END IF;
  IF IFNULL(p_order, 'newest') = 'oldest' THEN
    SELECT h.id, h.type, h.activity_id, h.old_body, h.old_updated, h.old_updater_id, ou.name AS old_updater,
           h.replaced_at, h.replaced_by AS replaced_by_id, rb.name AS replaced_by
      FROM activity_history h
      LEFT JOIN name ou ON ou.id = h.old_updater_id
      LEFT JOIN name rb ON rb.id = h.replaced_by
     WHERE h.type = p_type AND h.activity_id = p_id
     ORDER BY h.old_updated, h.id;
  ELSE
    SELECT h.id, h.type, h.activity_id, h.old_body, h.old_updated, h.old_updater_id, ou.name AS old_updater,
           h.replaced_at, h.replaced_by AS replaced_by_id, rb.name AS replaced_by
      FROM activity_history h
      LEFT JOIN name ou ON ou.id = h.old_updater_id
      LEFT JOIN name rb ON rb.id = h.replaced_by
     WHERE h.type = p_type AND h.activity_id = p_id
     ORDER BY h.old_updated DESC, h.id DESC;
  END IF;
END //

DELIMITER ;
