-- 0.7 book (database @SRC@, only read) -> beta book (the current database, freshly made from beta_ddl.sql).
-- Copy-to-new-database: the 0.7 book stays untouched and is the rollback target. Ids are kept per entity (desk,
-- roster, room, resource, letter, card, ...), so no id map is needed. A row 0.7 holds that the beta book refuses is
-- repaired or dropped here and counted in mig_repair; nothing is coerced silently.
-- beta_migrate.py drops the history-breaking triggers for the copy (letter_sender_current, card_no_cycle) and
-- recreates them after; desk_on_office stays on and puts every desk on the Office roster.

-- 1. desks, seats, roles, resources
INSERT INTO desk (id, name, created, retired_at, live)
  SELECT id, name, updated, deleted, IF(deleted IS NULL, 1, NULL) FROM @SRC@.name WHERE type = 'desk' ORDER BY id;
INSERT INTO seat (desk_id, token_hash, delivery_mode, endpoint_url, endpoint_key, wake_on, lan_ip, socket_at, last_seen, seen_seq)
  SELECT s.desk_id, IF(d.live = 1, s.token_hash, NULL), s.delivery_mode, s.endpoint_url, s.endpoint_key, s.wake_on, s.lan_ip,
         IF(s.time_disconnect IS NULL AND d.live = 1, s.time_connect, NULL), IFNULL(s.time_disconnect, s.updated), 0
    FROM @SRC@.seat s JOIN desk d ON d.id = s.desk_id
   WHERE s.id = (SELECT MAX(x.id) FROM @SRC@.seat x WHERE x.desk_id = s.desk_id);
INSERT INTO mig_repair SELECT 'seat rows beyond the newest per desk (dropped)', (SELECT COUNT(*) FROM @SRC@.seat) - (SELECT COUNT(*) FROM seat);
INSERT INTO role_member (role_id, desk_id, created) SELECT 2, m.desk_id, m.created FROM @SRC@.member m JOIN desk d ON d.id = m.desk_id WHERE m.name_id = 2;
INSERT INTO resource (id, name) SELECT id, name FROM @SRC@.name WHERE type = 'res';

-- 2. rosters become rooms of kind roster (Office is room 1; Admin keeps role 2 and is also roster 2 so its letters stay)
UPDATE room r JOIN @SRC@.name n ON n.id = 1 SET r.name = n.name WHERE r.id = 1;
INSERT INTO room (id, kind, name, created, retired_at)
  SELECT id, 'roster', name, updated, deleted FROM @SRC@.name WHERE type = 'roster' AND id <> 1;
INSERT INTO room_member (room_id, desk_id, joined_at)
  SELECT m.name_id, m.desk_id, m.created FROM @SRC@.member m JOIN room r ON r.id = m.name_id AND r.kind = 'roster' JOIN desk d ON d.id = m.desk_id
   WHERE m.name_id <> 1;

-- 3. trees. A tree rooted at a letter is a discussion room; one rooted at a card or score is a plan. The parent of a
--    node is the tightest enclosing interval in its tree; a letter's reply_to is its nearest enclosing letter.
CREATE TABLE mig_tree (name_id BIGINT UNSIGNED PRIMARY KEY, root_type VARCHAR(8), root_id BIGINT UNSIGNED, roots INT)
  SELECT t.name_id,
         (SELECT r.type FROM @SRC@.tree r WHERE r.name_id = t.name_id ORDER BY r.lft LIMIT 1) root_type,
         (SELECT r.id FROM @SRC@.tree r WHERE r.name_id = t.name_id ORDER BY r.lft LIMIT 1) root_id,
         SUM(NOT EXISTS (SELECT 1 FROM @SRC@.tree p WHERE p.name_id = t.name_id AND p.lft < t.lft AND p.rgt > t.rgt)) roots
    FROM @SRC@.tree t GROUP BY t.name_id;
ANALYZE TABLE mig_tree;
INSERT INTO mig_repair SELECT 'tree with more than one root (extra roots left unparented)', COUNT(*) FROM mig_tree WHERE roots > 1;
CREATE TABLE mig_parent (name_id BIGINT UNSIGNED, type VARCHAR(8), id BIGINT UNSIGNED, lft INT UNSIGNED,
                         p_type VARCHAR(8) NULL, p_id BIGINT UNSIGNED NULL, p_mail BIGINT UNSIGNED NULL, PRIMARY KEY (name_id, type, id), KEY ix_item (type, id, name_id))
  SELECT t.name_id, t.type, t.id, t.lft,
         (SELECT p.type FROM @SRC@.tree p WHERE p.name_id = t.name_id AND p.lft < t.lft AND p.rgt > t.rgt ORDER BY p.lft DESC LIMIT 1) p_type,
         (SELECT p.id FROM @SRC@.tree p WHERE p.name_id = t.name_id AND p.lft < t.lft AND p.rgt > t.rgt ORDER BY p.lft DESC LIMIT 1) p_id,
         (SELECT p.id FROM @SRC@.tree p WHERE p.name_id = t.name_id AND p.type = 'mail' AND p.lft < t.lft AND p.rgt > t.rgt ORDER BY p.lft DESC LIMIT 1) p_mail
    FROM @SRC@.tree t;
-- new work tables have no index statistics until analyzed; without them the per-row lookups below scan
ANALYZE TABLE mig_parent;
-- a discussion room's roster is the roster most of its letters were tagged with (0.7 tagged each letter alone)
INSERT INTO room (id, kind, name, created, roster_id, roster_kind)
  SELECT n.id, 'room', n.name, n.updated, IF(r.id > 1, r.id, NULL), IF(r.id > 1, 'roster', NULL)
    FROM mig_tree k JOIN @SRC@.name n ON n.id = k.name_id
    LEFT JOIN room r ON r.kind = 'roster' AND r.id = (SELECT m.roster_id FROM mig_parent p JOIN @SRC@.mail m ON m.id = p.id
                                                       WHERE p.name_id = k.name_id AND p.type = 'mail' GROUP BY m.roster_id ORDER BY COUNT(*) DESC, m.roster_id LIMIT 1)
   WHERE k.root_type = 'mail';

-- 4. letters. Room: the discussion room it sits in, else its roster (a missing roster: the Office).
CREATE TABLE mig_letter (letter_id BIGINT UNSIGNED PRIMARY KEY, room_id INT UNSIGNED NOT NULL, reply_to_id BIGINT UNSIGNED NULL)
  SELECT m.id letter_id,
         COALESCE((SELECT MIN(p.name_id) FROM mig_parent p JOIN mig_tree k ON k.name_id = p.name_id AND k.root_type = 'mail' WHERE p.type = 'mail' AND p.id = m.id),
                  (SELECT r.id FROM room r WHERE r.id = m.roster_id AND r.kind = 'roster'), 1) room_id,
         (SELECT MIN(p.p_mail) FROM mig_parent p JOIN mig_tree k ON k.name_id = p.name_id AND k.root_type = 'mail'
           WHERE p.type = 'mail' AND p.id = m.id AND p.p_mail < m.id) reply_to_id
    FROM @SRC@.mail m;
ANALYZE TABLE mig_letter;
INSERT INTO mig_repair SELECT 'letter in a plan tree (kept in its roster, thread link dropped)', COUNT(DISTINCT p.id)
  FROM mig_parent p JOIN mig_tree k ON k.name_id = p.name_id AND k.root_type <> 'mail' WHERE p.type = 'mail';
INSERT INTO mig_repair SELECT 'letter whose roster tag differs from its room''s roster (room kept)', COUNT(*)
  FROM mig_letter g JOIN room r ON r.id = g.room_id AND r.kind = 'room' JOIN @SRC@.mail m ON m.id = g.letter_id
 WHERE m.roster_id <> IFNULL(r.roster_id, 1);
INSERT INTO mig_repair SELECT 'letter with an unknown roster (put in the Office)', COUNT(*)
  FROM @SRC@.mail m WHERE NOT EXISTS (SELECT 1 FROM room r WHERE r.id = m.roster_id AND r.kind = 'roster');
-- members: a discussion room's cast is everyone who wrote or was written to in it (0.7 kept no member rows for a tree).
INSERT INTO room_member (room_id, desk_id, joined_at)
  SELECT g.room_id, x.desk_id, MIN(x.at) FROM mig_letter g JOIN room r ON r.id = g.room_id AND r.kind = 'room'
    JOIN (SELECT m.id, m.desk_id, m.created at FROM @SRC@.mail m UNION ALL SELECT t.id, t.desk_id, m2.created FROM @SRC@.mail_to t JOIN @SRC@.mail m2 ON m2.id = t.id) x ON x.id = g.letter_id
    JOIN desk d ON d.id = x.desk_id GROUP BY g.room_id, x.desk_id;
-- a roster letter from or to a desk that is not on the roster (0.7 allowed it): kept as history, the desk becomes a former member
INSERT INTO mig_repair SELECT 'roster letter from or to a non-member (desk kept as a former member)', COUNT(*) FROM (
  SELECT DISTINCT g.room_id, x.desk_id FROM mig_letter g
    JOIN (SELECT m.id, m.desk_id FROM @SRC@.mail m UNION ALL SELECT t.id, t.desk_id FROM @SRC@.mail_to t) x ON x.id = g.letter_id JOIN desk d ON d.id = x.desk_id
   WHERE NOT EXISTS (SELECT 1 FROM room_member rm WHERE rm.room_id = g.room_id AND rm.desk_id = x.desk_id)) z;
INSERT INTO room_member (room_id, desk_id, joined_at, left_at)
  SELECT DISTINCT g.room_id, x.desk_id, NOW(6), NOW(6) FROM mig_letter g
    JOIN (SELECT m.id, m.desk_id FROM @SRC@.mail m UNION ALL SELECT t.id, t.desk_id FROM @SRC@.mail_to t) x ON x.id = g.letter_id JOIN desk d ON d.id = x.desk_id
   WHERE NOT EXISTS (SELECT 1 FROM room_member rm WHERE rm.room_id = g.room_id AND rm.desk_id = x.desk_id);
INSERT INTO letter (id, created, sender_id, room_id, reply_to_id, body, retired_at)
  SELECT m.id, m.created, m.desk_id, g.room_id, g.reply_to_id, m.body, a.deleted
    FROM @SRC@.mail m JOIN mig_letter g ON g.letter_id = m.id JOIN desk d ON d.id = m.desk_id
    LEFT JOIN @SRC@.activity a ON a.type = 'mail' AND a.id = m.id
   ORDER BY m.id;
INSERT INTO mig_repair SELECT 'letter from an unknown desk (dropped)', (SELECT COUNT(*) FROM @SRC@.mail) - (SELECT COUNT(*) FROM letter);
INSERT INTO letter_to (letter_id, desk_id, room_id, kind, asked, read_at, receipt)
  SELECT t.id, t.desk_id, l.room_id, IF(t.asked, 'named', 'copied'), t.asked <> 0, t.opened, t.receipt
    FROM @SRC@.mail_to t JOIN letter l ON l.id = t.id JOIN desk d ON d.id = t.desk_id;
-- tree_read was a second read cursor per (desk, room): what it covered is read now, in the one read state
INSERT INTO mig_repair SELECT 'unread recipient rows a tree_read cursor had covered (marked read)', COUNT(*)
  FROM letter_to t JOIN @SRC@.tree_read r ON r.desk_id = t.desk_id AND r.tree_id = t.room_id WHERE t.read_at IS NULL AND t.letter_id <= r.last_id;
UPDATE letter_to t JOIN @SRC@.tree_read r ON r.desk_id = t.desk_id AND r.tree_id = t.room_id
   SET t.read_at = r.updated WHERE t.read_at IS NULL AND t.letter_id <= r.last_id;

-- 5. scores (target was text in 0.7)
-- 0.7 let a roster own a score (system KPIs, roster KPIs): it stays the roster's own score, desk_id NULL
INSERT INTO mig_repair SELECT 'info: score owned by a roster (kept, desk_id NULL)', COUNT(*)
  FROM @SRC@.score s WHERE NOT EXISTS (SELECT 1 FROM desk d WHERE d.id = s.desk_id);
INSERT INTO score (id, desk_id, roster_id, kpi, target, better, unit, note, created, retired_at)
  SELECT s.id, (SELECT d.id FROM desk d WHERE d.id = s.desk_id),
         IF(r.id IS NULL, 1, s.roster_id), s.kpi, IF(s.target REGEXP '^-?[0-9]+(\\.[0-9]+)?$', CAST(s.target AS DOUBLE), NULL),
         s.better, s.unit, s.note, s.created, a.deleted
    FROM @SRC@.score s LEFT JOIN room r ON r.id = s.roster_id AND r.kind = 'roster'
    LEFT JOIN @SRC@.activity a ON a.type = 'score' AND a.id = s.id;
INSERT INTO mig_repair SELECT 'score target not numeric (set NULL)', COUNT(*) FROM @SRC@.score WHERE target <> '' AND NOT target REGEXP '^-?[0-9]+(\\.[0-9]+)?$';
INSERT INTO score_point (id, score_id, at, desk_id, value, note)
  SELECT p.id, p.score_id, p.created, p.desk_id, p.value, p.note FROM @SRC@.score_point p JOIN score s ON s.id = p.score_id JOIN desk d ON d.id = p.desk_id;
INSERT INTO score_evidence (score_id, at, value, taken) SELECT e.score_id, e.timestamp, e.value, e.taken FROM @SRC@.score_evidence e JOIN score s ON s.id = e.score_id;

-- 6. cards. 0.7 keeps no status history: each card gets one synthesized event for its current status.
INSERT INTO card (id, created, creator_id, roster_id, status, volunteer_id, claimed_at, retired_at, body)
  SELECT t.id, t.created, t.creator_id, IF(r.id IS NULL, 1, t.roster_id),
         IF(t.status IN ('claimed','shipped') AND t.assigned_id IS NULL, 'open', t.status),
         IF(t.status IN ('claimed','shipped','done'), t.assigned_id, NULL),
         IF(t.status = 'claimed' AND t.assigned_id IS NOT NULL, IFNULL(t.claimed_at, t.updated), NULL), a.deleted, t.body
    FROM @SRC@.todo t JOIN desk d ON d.id = t.creator_id LEFT JOIN room r ON r.id = t.roster_id AND r.kind = 'roster'
    LEFT JOIN @SRC@.activity a ON a.type = 'todo' AND a.id = t.id;
INSERT INTO mig_repair SELECT 'card claimed/shipped with no volunteer (reopened)', COUNT(*) FROM @SRC@.todo WHERE status IN ('claimed','shipped') AND assigned_id IS NULL;
INSERT INTO mig_repair SELECT 'card claimed_at on a card not claimed (cleared)', COUNT(*) FROM @SRC@.todo WHERE status <> 'claimed' AND claimed_at IS NOT NULL;
INSERT INTO mig_repair SELECT 'card with an unknown roster (put in the Office)', COUNT(*) FROM @SRC@.todo t WHERE NOT EXISTS (SELECT 1 FROM room r WHERE r.id = t.roster_id AND r.kind = 'roster');
-- came-from: the tightest enclosing node of the card in its first tree; siblings keep their order, gapped by 2^20
CREATE TABLE mig_card_parent (id BIGINT UNSIGNED PRIMARY KEY, name_id BIGINT UNSIGNED, lft INT UNSIGNED, p_type VARCHAR(8), p_id BIGINT UNSIGNED)
  SELECT p.id, p.name_id, p.lft, p.p_type, p.p_id FROM mig_parent p
   WHERE p.type = 'todo' AND p.p_type IS NOT NULL AND p.name_id = (SELECT MIN(x.name_id) FROM mig_parent x WHERE x.type = 'todo' AND x.id = p.id AND x.p_type IS NOT NULL);
ANALYZE TABLE mig_card_parent;
UPDATE card c JOIN mig_card_parent x ON x.id = c.id
   SET c.from_letter_id = IF(x.p_type = 'mail', (SELECT l.id FROM letter l WHERE l.id = x.p_id), NULL),
       c.from_card_id   = IF(x.p_type = 'todo' AND x.p_id <> c.id, (SELECT k.id FROM (SELECT id FROM card) k WHERE k.id = x.p_id), NULL),
       c.from_score_id  = IF(x.p_type = 'score', (SELECT s.id FROM score s WHERE s.id = x.p_id), NULL);
UPDATE card c JOIN (SELECT x.id, 1048576 * ROW_NUMBER() OVER (PARTITION BY x.name_id, x.p_type, x.p_id ORDER BY x.lft) o FROM mig_card_parent x) y ON y.id = c.id
   SET c.ord = y.o WHERE c.from_card_id IS NOT NULL OR c.from_letter_id IS NOT NULL OR c.from_score_id IS NOT NULL;
INSERT INTO mig_repair SELECT 'card in more than one tree (kept the first)', COUNT(*) FROM (
  SELECT id FROM mig_parent WHERE type = 'todo' GROUP BY id HAVING COUNT(DISTINCT name_id) > 1) z;
INSERT INTO mig_repair SELECT 'card whose tree parent is gone (left unparented)', COUNT(*) FROM card c JOIN mig_card_parent x ON x.id = c.id
 WHERE c.from_letter_id IS NULL AND c.from_card_id IS NULL AND c.from_score_id IS NULL;
INSERT INTO card_event (card_id, at, desk_id, from_status, to_status, volunteer_id, note)
  SELECT c.id, GREATEST(c.created, IFNULL(t.updated, c.created)), IFNULL((SELECT d.id FROM desk d WHERE d.id = t.updated_id), c.creator_id), NULL, c.status,
         IF(c.status IN ('claimed','shipped','done'), c.volunteer_id, NULL), 'migrated'
    FROM card c JOIN @SRC@.todo t ON t.id = c.id ORDER BY c.id;
UPDATE card c JOIN card_event e ON e.card_id = c.id SET c.status_event_id = e.id;
-- labels: one named like a desk is that desk's focus list (0.7 kept focus as a label); any other is a tag
INSERT INTO tag (id, name) SELECT n.id, n.name FROM @SRC@.name n WHERE n.type = 'label' AND NOT EXISTS (SELECT 1 FROM desk d WHERE d.name = n.name);
INSERT INTO card_tag (card_id, tag_id) SELECT l.id, l.name_id FROM @SRC@.label l JOIN tag g ON g.id = l.name_id JOIN card c ON c.id = l.id WHERE l.type = 'todo';
INSERT INTO letter_tag (letter_id, tag_id) SELECT l.id, l.name_id FROM @SRC@.label l JOIN tag g ON g.id = l.name_id JOIN letter m ON m.id = l.id WHERE l.type = 'mail';
INSERT INTO focus (desk_id, card_id, rank_ord)
  SELECT d.id, l.id, 1048576 * ROW_NUMBER() OVER (PARTITION BY d.id ORDER BY l.ord, l.id)
    FROM @SRC@.label l JOIN @SRC@.name n ON n.id = l.name_id JOIN desk d ON d.name = n.name JOIN card c ON c.id = l.id WHERE l.type = 'todo';
INSERT INTO mig_repair SELECT 'label on a doing, hold or score (dropped)', COUNT(*) FROM @SRC@.label WHERE type NOT IN ('todo','mail');

-- 7. holds: 0.7 keeps one row per resource ever held (desk NULL = free); beta keeps a row only while a live desk holds it
INSERT INTO mig_repair SELECT 'hold by a retired desk (released)', COUNT(*) FROM @SRC@.hold h JOIN desk d ON d.id = h.desk_id WHERE d.live IS NULL;
INSERT INTO hold (resource_id, desk_id, taken_at) SELECT h.resource_id, h.desk_id, h.updated FROM @SRC@.hold h JOIN desk d ON d.id = h.desk_id AND d.live = 1 JOIN resource r ON r.id = h.resource_id;
INSERT INTO hold_event (resource_id, desk_id, verb, at) SELECT resource_id, desk_id, 'take', taken_at FROM hold ORDER BY taken_at;

-- 8. doings: (type, id) pointers become typed columns; a dangling target is cleared and counted
INSERT INTO mig_repair SELECT 'doing pointing at a missing item (pointer cleared)', COUNT(*) FROM @SRC@.doing x
  WHERE (x.on_type = 'todo' AND NOT EXISTS (SELECT 1 FROM card c WHERE c.id = x.on_id)) OR (x.on_type = 'mail' AND NOT EXISTS (SELECT 1 FROM letter l WHERE l.id = x.on_id))
     OR (x.waiting_type = 'desk' AND NOT EXISTS (SELECT 1 FROM desk d WHERE d.id = x.waiting_id)) OR (x.waiting_type = 'todo' AND NOT EXISTS (SELECT 1 FROM card c WHERE c.id = x.waiting_id))
     OR (x.waiting_type = 'mail' AND NOT EXISTS (SELECT 1 FROM letter l WHERE l.id = x.waiting_id));
INSERT INTO doing (id, desk_id, created, text, on_card_id, on_letter_id, on_resource_id, on_score_id,
                   wait_desk_id, wait_card_id, wait_letter_id, wait_resource_id, waiting_why, directory_sub)
  SELECT x.id, x.desk_id, x.created, x.text,
         (SELECT id FROM card WHERE x.on_type = 'todo' AND id = x.on_id), (SELECT id FROM letter WHERE x.on_type = 'mail' AND id = x.on_id),
         (SELECT r.id FROM @SRC@.hold h JOIN resource r ON r.id = h.resource_id WHERE x.on_type = 'hold' AND h.id = x.on_id),
         (SELECT id FROM score WHERE x.on_type = 'score' AND id = x.on_id),
         w.wd, w.wc, w.wl, w.wr, IF(COALESCE(w.wd, w.wc, w.wl, w.wr) IS NULL, NULL, x.waiting_why), @DOING_SUB@
    FROM @SRC@.doing x JOIN desk d ON d.id = x.desk_id
    JOIN LATERAL (SELECT (SELECT id FROM desk WHERE x.waiting_type = 'desk' AND id = x.waiting_id) wd,
                         (SELECT id FROM card WHERE x.waiting_type = 'todo' AND id = x.waiting_id) wc,
                         (SELECT id FROM letter WHERE x.waiting_type = 'mail' AND id = x.waiting_id) wl,
                         (SELECT r.id FROM @SRC@.hold h JOIN resource r ON r.id = h.resource_id WHERE x.waiting_type = 'hold' AND h.id = x.waiting_id) wr) w
   ORDER BY x.id;
INSERT INTO doing_now (desk_id, doing_id, wait_desk_id)
  SELECT d.desk_id, d.id, d.wait_desk_id FROM doing d JOIN (SELECT desk_id, MAX(id) id FROM doing GROUP BY desk_id) m ON m.id = d.id;

-- 9. wake queue: an undelivered letter wake to a recipient row survives; card hints and expiry lines are not carried
INSERT IGNORE INTO push (id, desk_id, letter_id, named, created)
  SELECT q.id, q.desk_id, t.letter_id, t.kind, q.created FROM @SRC@.push_queue q
    JOIN letter_to t ON t.letter_id = CAST(JSON_UNQUOTE(JSON_EXTRACT(q.payload, '$.id')) AS UNSIGNED) AND t.desk_id = q.desk_id
    JOIN desk d ON d.id = q.desk_id AND d.live = 1
   WHERE q.kind = 'mail' AND q.outcome <> 'sent' ORDER BY q.id;
INSERT INTO mig_repair SELECT 'wake not carried (sent, a card hint, an expiry line, or not a recipient)', (SELECT COUNT(*) FROM @SRC@.push_queue) - (SELECT COUNT(*) FROM push);

-- 10. timeline, rebuilt in time order; every desk starts caught up
INSERT INTO activity (at, letter_id, card_event_id, doing_id, hold_event_id, score_point_id)
  SELECT at, l, ce, d, he, sp FROM (
    SELECT created at, id l, NULL ce, NULL d, NULL he, NULL sp FROM letter
    UNION ALL SELECT at, NULL, id, NULL, NULL, NULL FROM card_event
    UNION ALL SELECT created, NULL, NULL, id, NULL, NULL FROM doing
    UNION ALL SELECT at, NULL, NULL, NULL, id, NULL FROM hold_event
    UNION ALL SELECT at, NULL, NULL, NULL, NULL, id FROM score_point) u ORDER BY at;
UPDATE seat SET seen_seq = (SELECT IFNULL(MAX(seq), 0) FROM activity);

-- 11. carried: human sign-in, invites
INSERT INTO human (id, bearer_hash, directory_sub, created, updated) SELECT id, bearer_hash, directory_sub, created, updated FROM @SRC@.human;
INSERT INTO human_desk (human_id, desk_id, created) SELECT hd.human_id, hd.desk_id, hd.created FROM @SRC@.human_desk hd JOIN desk d ON d.id = hd.desk_id;
INSERT INTO human_member (human_id, role_id, room_id, created)
  SELECT hm.human_id, IF(hm.name_id = 2, 2, NULL), IF(hm.name_id = 2, NULL, hm.name_id), hm.created FROM @SRC@.human_member hm
   WHERE hm.name_id = 2 OR EXISTS (SELECT 1 FROM room r WHERE r.id = hm.name_id AND r.kind = 'roster');
INSERT INTO mig_repair SELECT 'human membership in a name that is not a roster (dropped)', (SELECT COUNT(*) FROM @SRC@.human_member) - (SELECT COUNT(*) FROM human_member);
INSERT INTO mill_invite (key_id, token_hash, label, created_by, created_at, ttl_seconds, expires_at, enabled_at, revoked_at)
  SELECT key_id, token_hash, label, created_by, created_at, IF(expires_at IS NULL, NULL, ttl_seconds), IF(ttl_seconds IS NULL, NULL, expires_at), enabled_at, revoked_at FROM @SRC@.mill_invite;
INSERT INTO mill_invite_join SELECT key_id, party, party_id, created FROM @SRC@.mill_invite_join;
INSERT INTO mig_repair SELECT 'watcher rows (replaced by wake rules)', COUNT(*) FROM @SRC@.watcher;
DROP TABLE mig_card_parent, mig_letter, mig_parent, mig_tree;
