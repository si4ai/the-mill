-- #818 PR B: --doing on an activity command writes one doing entry linked to
-- that command's item; `mill connected` reads what every desk is doing.
-- Rows live in table doing (append-only, see sp_join.sql mill_doing_insert).
-- 0.8.0: seat.doing_id names each desk's newest focus row (focus or clear; never a move row).
-- An entry ends on a real event, derived on read from rows that never change:
--   finished: the desk replies under the letter; the desk passes (ships) or
--             passes --done the card, or drops the hold: its own move row on that item
--             (act ship, done or drop; finish is a pre-0.8.0 row, the migration's);
--   cleared:  clock-out, reset or retire appends a clear row (mill_doing_clear);
--   newer:    the desk writes another --doing entry (a focus row).
-- 0.8.0 (C3): each read filters by act. A move row is never a newer or a cleared end: only focus rows
-- (act focus) are entries, an end at the next row reads focus rows only, an item's previous row reads move rows.
-- A mark, a note, someone else's pass, a card stepped back or a hold taken
-- again never ends one and never brings an ended one back. A score entry ends only as cleared or newer.

DROP FUNCTION IF EXISTS mill_doing_end;
DROP FUNCTION IF EXISTS mill_doing_cleared;
DROP PROCEDURE IF EXISTS mill_doing_put;
DROP PROCEDURE IF EXISTS mill_doing_finish;
DROP PROCEDURE IF EXISTS mill_doing_now;
DROP PROCEDURE IF EXISTS mill_doing_history;

DELIMITER //

-- When the entry was finished by its own event, or NULL. Derived, never stored.
CREATE FUNCTION mill_doing_end(
  p_desk    BIGINT UNSIGNED,
  p_id      BIGINT UNSIGNED,
  p_on_type VARCHAR(8),
  p_on_id   BIGINT UNSIGNED,
  p_created DATETIME(6)
) RETURNS DATETIME(6)
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  DECLARE v_at DATETIME(6);
  SET v_at = NULL;
  IF p_on_type = 'mail' THEN
    SELECT MIN(r.created) INTO v_at
      FROM tree t
      JOIN tree c ON c.name_id = t.name_id AND c.type = 'mail'
                 AND c.lft > t.lft AND c.rgt < t.rgt
      JOIN mail r ON r.id = c.id
     WHERE t.type = 'mail' AND t.id = p_on_id
       AND r.desk_id = p_desk AND r.created >= p_created;
  ELSEIF p_on_type IN ('todo', 'hold') THEN
    -- The pass, done or drop itself, not the item's live state: a later note,
    -- a step back or a re-take changes the card or hold, never this row.
    SELECT MIN(f.created) INTO v_at
      FROM doing f
     WHERE f.desk_id = p_desk AND f.act IN ('ship', 'done', 'drop', 'finish')
       AND f.on_type = p_on_type AND f.on_id = p_on_id
       AND (f.created > p_created OR (f.created = p_created AND f.id > p_id));
  END IF;
  RETURN v_at;
END //

-- When clock-out, reset or retire cleared the entry (an empty row with no
-- item after it), or NULL.
CREATE FUNCTION mill_doing_cleared(
  p_desk    BIGINT UNSIGNED,
  p_id      BIGINT UNSIGNED,
  p_created DATETIME(6)
) RETURNS DATETIME(6)
  NOT DETERMINISTIC
  READS SQL DATA
BEGIN
  DECLARE v_at DATETIME(6);
  SELECT MIN(e.created) INTO v_at
    FROM doing e
   WHERE e.desk_id = p_desk AND e.act = 'clear'
     AND (e.created > p_created OR (e.created = p_created AND e.id > p_id));
  RETURN v_at;
END //

-- One new entry for the desk, on the item the command just wrote. The roster
-- is that item's (its activity row). Watchers follow (mill_doing_insert).
-- #822 blocked-on (--waiting-on): p_w_type 'desk' with p_w_ref the desk name,
-- or 'mail', 'todo' or 'hold' with p_w_ref the id, plus the reason. Stored as
-- waiting_type, waiting_id, waiting_why on this one row; no edge or link table.
-- A missing or deleted target, or the desk itself, refuses the entry.
CREATE PROCEDURE mill_doing_put(
  IN p_desk      VARCHAR(64),
  IN p_text      VARCHAR(512),
  IN p_on_type   VARCHAR(8),
  IN p_on_id     BIGINT UNSIGNED,
  IN p_w_type    VARCHAR(8),
  IN p_w_ref     VARCHAR(64),
  IN p_w_why     VARCHAR(200)
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_roster BIGINT UNSIGNED;
  DECLARE v_wid BIGINT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF v_desk IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doing: desk has not joined';
  END IF;
  IF IFNULL(p_on_type, '') NOT IN ('mail', 'todo', 'hold', 'score') OR p_on_id IS NULL
     OR NOT EXISTS (SELECT 1 FROM activity WHERE type = p_on_type AND id = p_on_id AND deleted IS NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doing: the item is gone';
  END IF;
  SET v_wid = NULL;
  IF IFNULL(p_w_type, '') = 'desk' THEN
    SET v_wid = (SELECT id FROM name WHERE type = 'desk' AND name = p_w_ref AND deleted IS NULL);
    IF v_wid IS NULL THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doing: --waiting-on names no desk or item';
    END IF;
    IF v_wid = v_desk THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doing: a desk is not blocked on itself';
    END IF;
  ELSEIF IFNULL(p_w_type, '') IN ('mail', 'todo', 'hold') THEN
    SET v_wid = CAST(p_w_ref AS UNSIGNED);
    IF NOT EXISTS (SELECT 1 FROM activity WHERE type = p_w_type AND id = v_wid AND deleted IS NULL) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doing: --waiting-on names no desk or item';
    END IF;
  ELSEIF IFNULL(p_w_type, '') <> '' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doing: --waiting-on names no desk or item';
  END IF;
  SET v_roster = IFNULL((SELECT roster_id FROM activity WHERE type = p_on_type AND id = p_on_id), 1);
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_ts = MILL_NOW();
  -- F186 (spin D07): seat lock + live token. A retired desk (token cleared, time_disconnect set)
  -- must not write a focus after its retire.
  UPDATE seat SET updated = v_ts WHERE desk_id = v_desk AND token_hash IS NOT NULL;
  IF ROW_COUNT() = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'doing: desk has not joined';
  END IF;
  -- Card 955: closing a prior focus on a card adds its minutes to the cards score.
  BEGIN
    DECLARE v_prev BIGINT UNSIGNED DEFAULT NULL;
    DECLARE v_pon VARCHAR(8) DEFAULT NULL;
    DECLARE v_pid BIGINT UNSIGNED DEFAULT NULL;
    DECLARE v_pct DATETIME(6) DEFAULT NULL;
    DECLARE v_ptxt VARCHAR(512) DEFAULT NULL;
    DECLARE v_pact VARCHAR(16) DEFAULT NULL;
    DECLARE v_prid BIGINT UNSIGNED DEFAULT NULL;
    DECLARE v_mins INT DEFAULT NULL;
    DECLARE CONTINUE HANDLER FOR SQLEXCEPTION BEGIN END;
    SELECT g.id, g.on_type, g.on_id, g.created, g.text, g.act
      INTO v_prev, v_pon, v_pid, v_pct, v_ptxt, v_pact
      FROM seat s JOIN doing g ON g.id = s.doing_id
     WHERE s.desk_id = v_desk;
    IF v_prev IS NOT NULL AND v_pon = 'todo' AND v_pact = 'focus' AND IFNULL(v_ptxt, '') <> ''
       AND mill_doing_end(v_desk, v_prev, v_pon, v_pid, v_pct) IS NULL
       AND mill_doing_cleared(v_desk, v_prev, v_pct) IS NULL THEN
      SELECT roster_id INTO v_prid FROM todo WHERE id = v_pid;
      SET v_mins = TIMESTAMPDIFF(MINUTE, v_pct, v_ts);
      IF v_mins > 0 AND v_prid IS NOT NULL THEN
        CALL mill_card_score_event(v_prid, 'doing', NULL, NULL, NULL, v_mins, v_ts);
      END IF;
    END IF;
  END;
  CALL mill_doing_insert(v_desk, v_roster, p_text, v_ts, v_id);
  -- The row was inserted by this call; nothing older is touched.
  UPDATE doing SET on_type = p_on_type, on_id = p_on_id,
                   waiting_type = IF(v_wid IS NULL, NULL, p_w_type), waiting_id = v_wid,
                   waiting_why = IF(v_wid IS NULL, NULL, NULLIF(p_w_why, ''))
   WHERE id = v_id;
  CALL mill_activity_put('doing', v_id, v_ts, v_desk, v_roster, IF(p_text = '', 'clear', 'focus'), NULL);
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
  SELECT v_id AS id, v_ts AS created, v_desk AS desk_id, v_roster AS roster_id;
END //

-- A pass or done of a card, or the drop of a hold, without --doing by the desk
-- ends its current entry when that entry is on this item: an empty row on the
-- item marks the event. Nothing happens when the desk's newest row is anything else.
CREATE PROCEDURE mill_doing_finish(
  IN p_desk    VARCHAR(64),
  IN p_on_type VARCHAR(8),
  IN p_on_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_ts DATETIME(6);
  DECLARE v_desk BIGINT UNSIGNED;
  DECLARE v_cur BIGINT UNSIGNED;
  DECLARE v_text VARCHAR(512);
  DECLARE v_type VARCHAR(8);
  DECLARE v_on BIGINT UNSIGNED;
  DECLARE v_roster BIGINT UNSIGNED;
  DECLARE v_id BIGINT UNSIGNED;
  DECLARE CONTINUE HANDLER FOR NOT FOUND SET v_cur = NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;
  SET v_desk = MILL_NAME_GET('desk', p_desk);
  IF @mill_req_tx IS NULL THEN START TRANSACTION; END IF;
  SET v_cur = NULL;
  -- 0.8.0 (the owner, 2026-10-26): finish writes no row. The desk's own ship, done or drop move on its focus
  -- item (written by the card or hold write, mill_doing_move) ends the entry. The seat row lock serializes this
  -- read with the desk's other writes; the rule reads the row seat.doing_id names, not the desk's newest row.
  SELECT g.id, g.text, g.on_type, g.on_id, g.roster_id INTO v_cur, v_text, v_type, v_on, v_roster
    FROM seat dn JOIN doing g ON g.id = dn.doing_id WHERE dn.desk_id = v_desk FOR UPDATE;
  SET v_id = NULL, v_ts = NULL;
  IF @mill_req_tx IS NULL THEN COMMIT; END IF;
END //

-- What desks are doing now. Three row kinds, told apart by part:
--   desk:   one per listed desk: its newest entry, whether that has ended,
--           and its newest entry with text (the last thing it said). Only
--           entries written by --doing count (they carry on); rows kept from
--           before #818 (old join text, no on) are not shown as a doing.
--   letter: up to 3 per desk, newest first: letters the desk was asked on
--           (not copied, #818 D1) that it has not handled and has not
--           replied under (n = how many in all).
--   card:   up to 3 per desk: cards it has claimed that another desk watches,
--           newest claim first; age is since the claim (todo.claimed_at, #818 D2).
--   blocked: up to 3 per desk, newest first: other desks whose current entry
--           (not ended) is blocked on it (#822): on the desk, a card it holds
--           as volunteer, a hold it holds, or a letter it was asked on (not
--           copied, #818 D1). A read of the waiting_* fields on doing rows;
--           there is no edge or link table.
-- Listed: p_desk alone when named; else every desk on p_roster when named;
-- else every joined desk when p_all; else desks active in the last day.
CREATE PROCEDURE mill_doing_now(
  IN p_desk   VARCHAR(64),
  IN p_roster VARCHAR(64),
  IN p_all    TINYINT
)
BEGIN
  DECLARE v_now DATETIME(6);
  DECLARE v_one BIGINT UNSIGNED;
  DECLARE v_ros BIGINT UNSIGNED;
  SET v_now = MILL_NOW();
  SET v_one = NULL;
  SET v_ros = NULL;
  IF IFNULL(p_desk, '') <> '' THEN
    SET v_one = IFNULL(MILL_NAME_GET('desk', p_desk), 0);
  ELSEIF IFNULL(p_roster, '') <> '' THEN
    SET v_ros = IFNULL(MILL_NAME_GET('roster', p_roster), 0);
  END IF;
  DROP TEMPORARY TABLE IF EXISTS tmp_doing_desk;
  CREATE TEMPORARY TABLE tmp_doing_desk (desk_id BIGINT UNSIGNED NOT NULL PRIMARY KEY) ENGINE=MEMORY;
  INSERT INTO tmp_doing_desk (desk_id)
  SELECT s.desk_id
    FROM seat s
    JOIN name d ON d.id = s.desk_id AND d.type = 'desk' AND d.deleted IS NULL
   -- 0.8.0: a joined seat only (a named desk has a seat row from its mint; sp_join.sql).
   WHERE (s.token_hash IS NOT NULL OR s.time_disconnect IS NOT NULL)
     AND ((v_one IS NOT NULL AND s.desk_id = v_one)
      OR (v_ros IS NOT NULL AND EXISTS (SELECT 1 FROM member m WHERE m.desk_id = s.desk_id AND m.name_id = v_ros))
      OR (v_one IS NULL AND v_ros IS NULL AND (IFNULL(p_all, 0) = 1
          OR s.updated > v_now - INTERVAL 1 DAY
          OR EXISTS (SELECT 1 FROM activity a
                      WHERE a.desk_id = s.desk_id AND a.created > v_now - INTERVAL 1 DAY))));

  SELECT 'desk' AS part, d.name AS desk,
         cur.id, cur.text, cur.on_type, cur.on_id, cur.act, cur.waiting_type, cur.waiting_id, cur.waiting_why,
         (SELECT wn.name FROM name wn WHERE cur.waiting_type = 'desk' AND wn.id = cur.waiting_id) AS waiting_name,
         TIMESTAMPDIFF(SECOND, cur.created, v_now) AS age_s,
         -- the first of its own event and a clear
         CASE WHEN en.fin IS NULL THEN en.clr WHEN en.clr IS NULL THEN en.fin
              ELSE LEAST(en.fin, en.clr) END AS ended_at,
         -- how it ended, the same first-event rule as the history (no newer: it is the newest)
         CASE WHEN en.fin IS NULL AND en.clr IS NULL THEN NULL
              WHEN en.clr IS NULL OR (en.fin IS NOT NULL AND en.fin <= en.clr) THEN 'finished'
              ELSE 'cleared' END AS ended_by,
         -- the last thing it said: the same newest entry (main read it twice)
         cur.id AS last_id, cur.text AS last_text, cur.on_type AS last_on_type, cur.on_id AS last_on_id,
         TIMESTAMPDIFF(SECOND, cur.created, v_now) AS last_age_s,
         st.updated AS heartbeat, v_now AS now
    FROM tmp_doing_desk t
    JOIN name d ON d.id = t.desk_id
    JOIN seat st ON st.desk_id = t.desk_id
    -- 0.8.0: seat.doing_id is the desk's newest focus row (one primary-key read). A clear row has no text,
    -- so the last thing it said is read back from idx_desk_created (focus rows only).
    LEFT JOIN doing nw ON nw.id = st.doing_id
    LEFT JOIN LATERAL (
      SELECT g.id, g.created, g.text, g.on_type, g.on_id, g.act, g.waiting_type, g.waiting_id, g.waiting_why
        FROM doing g WHERE g.id = nw.id AND g.act = 'focus' AND g.on_type IS NOT NULL AND g.text <> ''
      UNION ALL
      (SELECT g.id, g.created, g.text, g.on_type, g.on_id, g.act, g.waiting_type, g.waiting_id, g.waiting_why
        FROM doing g WHERE NOT (nw.on_type IS NOT NULL AND nw.text <> '')
         AND g.desk_id = t.desk_id AND g.act = 'focus' AND g.on_type IS NOT NULL AND g.text <> ''
       ORDER BY g.created DESC, g.id DESC LIMIT 1)
    ) cur ON TRUE
    LEFT JOIN LATERAL (
      SELECT mill_doing_end(t.desk_id, cur.id, cur.on_type, cur.on_id, cur.created) AS fin,
             mill_doing_cleared(t.desk_id, cur.id, cur.created) AS clr
    ) en ON TRUE
   ORDER BY IFNULL(cur.created, '1970-01-01') DESC, d.name;

  SELECT 'letter' AS part, x.desk, x.id, x.sender, x.age_s, x.n, x.asked
    FROM (
      SELECT d.name AS desk, m.id, sd.name AS sender, mt.asked,
             TIMESTAMPDIFF(SECOND, m.created, v_now) AS age_s,
             COUNT(*) OVER (PARTITION BY mt.desk_id) AS n,
             ROW_NUMBER() OVER (PARTITION BY mt.desk_id ORDER BY m.created DESC, m.id DESC) AS rn
        FROM tmp_doing_desk t
        JOIN mail_to mt ON mt.desk_id = t.desk_id AND mt.type = 'mail' AND mt.opened IS NULL
                        AND mt.asked = 1
        JOIN mail m ON m.id = mt.id AND m.desk_id <> mt.desk_id
        JOIN name d ON d.id = mt.desk_id
        JOIN name sd ON sd.id = m.desk_id
        LEFT JOIN activity am ON am.type = 'mail' AND am.id = m.id
       WHERE am.deleted IS NULL
         AND NOT EXISTS (
           SELECT 1 FROM tree tl
             JOIN tree c ON c.name_id = tl.name_id AND c.type = 'mail'
                        AND c.lft > tl.lft AND c.rgt < tl.rgt
             JOIN mail r ON r.id = c.id AND r.desk_id = mt.desk_id
            WHERE tl.type = 'mail' AND tl.id = m.id)
    ) x
   WHERE x.rn <= 3
   ORDER BY x.desk, x.rn;

  SELECT 'card' AS part, x.desk, x.id, x.need, x.roster, x.watchers, x.age_s, x.n, x.claimed_at
    FROM (
      SELECT d.name AS desk, td.id,
             JSON_UNQUOTE(JSON_EXTRACT(td.body, '$.slug')) AS need,
             ro.name AS roster,
             (SELECT GROUP_CONCAT(wn.name ORDER BY wn.name SEPARATOR ',')
                FROM watcher w JOIN name wn ON wn.id = w.desk_id
               WHERE w.type = 'todo' AND w.id = td.id AND w.desk_id <> td.assigned_id) AS watchers,
             TIMESTAMPDIFF(SECOND, td.claimed_at, v_now) AS age_s,
             td.claimed_at,
             COUNT(*) OVER (PARTITION BY td.assigned_id) AS n,
             ROW_NUMBER() OVER (PARTITION BY td.assigned_id ORDER BY td.claimed_at DESC, td.id DESC) AS rn
        FROM tmp_doing_desk t
        JOIN todo td ON td.assigned_id = t.desk_id AND td.status = 'claimed'
        JOIN name d ON d.id = td.assigned_id
        JOIN name ro ON ro.id = td.roster_id
        LEFT JOIN activity at ON at.type = 'todo' AND at.id = td.id
       WHERE at.deleted IS NULL
         AND EXISTS (SELECT 1 FROM watcher w
                      WHERE w.type = 'todo' AND w.id = td.id AND w.desk_id <> td.assigned_id)
    ) x
   WHERE x.rn <= 3
   ORDER BY x.desk, x.rn;

  SELECT 'blocked' AS part, x.desk, x.waiter, x.waiting_type, x.waiting_id, x.waiting_why, x.age_s, x.n
    FROM (
      SELECT d.name AS desk, wn.name AS waiter, w.waiting_type, w.waiting_id, w.waiting_why,
             TIMESTAMPDIFF(SECOND, w.created, v_now) AS age_s,
             COUNT(*) OVER (PARTITION BY t.desk_id) AS n,
             ROW_NUMBER() OVER (PARTITION BY t.desk_id ORDER BY w.created DESC, w.id DESC) AS rn
        FROM (
          -- each seated desk's current entry, when it waits on something and has not ended
          SELECT s.desk_id AS waiter_id, cur.*
            FROM seat s
            LEFT JOIN doing nw ON nw.id = s.doing_id
            JOIN LATERAL (
              SELECT g.id, g.created, g.on_type, g.on_id, g.waiting_type, g.waiting_id, g.waiting_why
                FROM doing g WHERE g.id = nw.id AND g.act = 'focus' AND g.on_type IS NOT NULL AND g.text <> ''
              UNION ALL
              (SELECT g.id, g.created, g.on_type, g.on_id, g.waiting_type, g.waiting_id, g.waiting_why
                FROM doing g WHERE NOT (nw.on_type IS NOT NULL AND nw.text <> '')
                 AND g.desk_id = s.desk_id AND g.act = 'focus' AND g.on_type IS NOT NULL AND g.text <> ''
               ORDER BY g.created DESC, g.id DESC LIMIT 1)
            ) cur ON TRUE
           WHERE cur.waiting_type IS NOT NULL
             AND mill_doing_end(s.desk_id, cur.id, cur.on_type, cur.on_id, cur.created) IS NULL
             AND mill_doing_cleared(s.desk_id, cur.id, cur.created) IS NULL
        ) w
        JOIN tmp_doing_desk t ON t.desk_id <> w.waiter_id AND (
             (w.waiting_type = 'desk' AND w.waiting_id = t.desk_id)
          OR (w.waiting_type = 'todo' AND EXISTS (SELECT 1 FROM todo td WHERE td.id = w.waiting_id
                AND td.status = 'claimed' AND td.assigned_id = t.desk_id))
          OR (w.waiting_type = 'hold' AND EXISTS (SELECT 1 FROM hold h WHERE h.id = w.waiting_id
                AND h.desk_id = t.desk_id))
          OR (w.waiting_type = 'mail' AND EXISTS (SELECT 1 FROM mail_to mt WHERE mt.type = 'mail'
                AND mt.id = w.waiting_id AND mt.desk_id = t.desk_id AND mt.asked = 1)))
        JOIN name d ON d.id = t.desk_id
        JOIN name wn ON wn.id = w.waiter_id
    ) x
   WHERE x.rn <= 3
   ORDER BY x.desk, x.rn;

  DROP TEMPORARY TABLE IF EXISTS tmp_doing_desk;
END //

-- Past --doing entries (text and on), newest first, one page (p_page from 1).
-- Each row says when its event finished it, when it was cleared and when a
-- newer entry replaced it; the first of the three is how it ended.
-- total counts every matching entry (adoption count). p_on_type and p_on_id,
-- when set, keep the entries on that one item (a card trail); p_desk may be empty.
CREATE PROCEDURE mill_doing_history(
  IN p_desk    VARCHAR(64),
  IN p_since   DATETIME(6),
  IN p_page    INT,
  IN p_size    INT,
  IN p_on_type VARCHAR(16),
  IN p_on_id   BIGINT UNSIGNED
)
BEGIN
  DECLARE v_one BIGINT UNSIGNED;
  DECLARE v_off INT;
  SET v_one = NULL;
  IF IFNULL(p_desk, '') <> '' THEN
    SET v_one = IFNULL(MILL_NAME_GET('desk', p_desk), 0);
  END IF;
  SET v_off = (GREATEST(IFNULL(p_page, 1), 1) - 1) * GREATEST(IFNULL(p_size, 50), 1);
  -- 0.8.0 Wall (letter 3227): desk history stays focus entries; on=ITEM also
  -- returns that item's move rows (act + evidence) so the card trail is whole.
  SELECT g.id, d.name AS desk, g.created, g.text, g.on_type, g.on_id, g.act, g.evidence,
         g.waiting_type, g.waiting_id, g.waiting_why, ro.name AS roster,
         (SELECT wn.name FROM name wn WHERE g.waiting_type = 'desk' AND wn.id = g.waiting_id) AS waiting_name,
         mill_doing_end(g.desk_id, g.id, g.on_type, g.on_id, g.created) AS ended_at,
         mill_doing_cleared(g.desk_id, g.id, g.created) AS cleared_at,
         (SELECT MIN(nx.created) FROM doing nx
           WHERE nx.desk_id = g.desk_id AND nx.act = 'focus' AND nx.on_type IS NOT NULL AND nx.text <> ''
             AND (nx.created > g.created OR (nx.created = g.created AND nx.id > g.id))) AS replaced_at,
         COUNT(*) OVER () AS total
    FROM doing g
    JOIN name d ON d.id = g.desk_id
    JOIN name ro ON ro.id = g.roster_id
   WHERE g.on_type IS NOT NULL
     AND (
       (IFNULL(p_on_type, '') = '' AND g.act = 'focus' AND g.text <> '')
       OR (IFNULL(p_on_type, '') <> '' AND g.on_type = p_on_type AND g.on_id = p_on_id
           AND ((g.act = 'focus' AND g.text <> '')
                OR g.act NOT IN ('focus', 'clear')))
     )
     AND (v_one IS NULL OR g.desk_id = v_one)
     AND (p_since IS NULL OR g.created >= p_since)
   ORDER BY g.created DESC, g.id DESC
   LIMIT v_off, p_size;
END //

DELIMITER ;
