-- Rollback: beta book (database @SRC@, only read) -> 0.7 book (the current database, made by migrate.ensure,
-- so it holds this pack's 0.7 tables, seeds and routines). Used in the rollback window after cutover: every write made
-- since cutover comes back. Lossy only where 0.7 cannot hold the fact: card and hold history, done_when and pass
-- evidence, votes and ballots (their letters stay), former members, roster of a discussion room.
-- Ids: desks keep theirs (beta desks never take 1 or 2). Rooms, tags and resources at or below the migration cut keep
-- theirs; newer ones move above every beta id. Nested sets are recomputed from the parent links:
-- lft = 2*preorder - depth - 1, rgt = lft + 2*subtree_size - 1.
DELETE FROM activity WHERE type = 'score';
-- the seeded system scores go; the beta book's scores replace them
DELETE FROM score;
SET @cut = IFNULL((SELECT n FROM @SRC@.mig_repair WHERE what = 'cut: highest 0.7 name id'), 0);
SET @base = 1 + GREATEST((SELECT IFNULL(MAX(id), 0) FROM @SRC@.desk), (SELECT IFNULL(MAX(id), 0) FROM @SRC@.room),
                         (SELECT IFNULL(MAX(id), 0) FROM @SRC@.tag), (SELECT IFNULL(MAX(id), 0) FROM @SRC@.resource), @cut);
SET @span = 1 + (SELECT IFNULL(MAX(id), 0) FROM @SRC@.card);
CREATE TABLE rb_room (id INT UNSIGNED PRIMARY KEY, nid BIGINT UNSIGNED NOT NULL, kind VARCHAR(8) NOT NULL, roster BIGINT UNSIGNED NOT NULL)
  SELECT id, IF(id <= GREATEST(@cut, 1) OR id = 1, id, @base + id) nid, kind, 0 roster FROM @SRC@.room;
UPDATE rb_room r JOIN @SRC@.room s ON s.id = r.id LEFT JOIN rb_room p ON p.id = s.roster_id
   SET r.roster = IF(r.kind = 'roster', r.nid, IFNULL(p.nid, 1));
CREATE TABLE rb_tag (id INT UNSIGNED PRIMARY KEY, nid BIGINT UNSIGNED NOT NULL) SELECT id, IF(id <= @cut, id, 2 * @base + id) nid FROM @SRC@.tag;
CREATE TABLE rb_res (id INT UNSIGNED PRIMARY KEY, nid BIGINT UNSIGNED NOT NULL) SELECT id, IF(id <= @cut, id, 3 * @base + id) nid FROM @SRC@.resource;

-- 1. names: rosters, desks, tags, discussion rooms (trees), resources, focus labels (named like their desk)
INSERT INTO name (id, type, name, deleted) SELECT r.nid, 'roster', s.name, s.retired_at FROM @SRC@.room s JOIN rb_room r ON r.id = s.id WHERE s.kind = 'roster'
  ON DUPLICATE KEY UPDATE name = VALUES(name), deleted = VALUES(deleted);
INSERT INTO name (id, type, name, deleted) SELECT id, 'desk', name, retired_at FROM @SRC@.desk;
INSERT INTO name (id, type, name) SELECT r.nid, 'tree', s.name FROM @SRC@.room s JOIN rb_room r ON r.id = s.id WHERE s.kind = 'room';
INSERT INTO name (id, type, name) SELECT r.nid, 'res', s.name FROM @SRC@.resource s JOIN rb_res r ON r.id = s.id;
INSERT INTO name (id, type, name) SELECT 4 * @base + d.id, 'label', d.name FROM @SRC@.desk d WHERE EXISTS (SELECT 1 FROM @SRC@.focus f WHERE f.desk_id = d.id);
-- a tag named like a desk with a focus list would take that label; it gets a suffix
INSERT INTO name (id, type, name) SELECT r.nid, 'label', IF(EXISTS (SELECT 1 FROM name n WHERE n.type = 'label' AND n.name = s.name), CONCAT(LEFT(s.name, 58), ' (tag)'), s.name)
  FROM @SRC@.tag s JOIN rb_tag r ON r.id = s.id;
-- members: current members of rosters and rooms; Admin is the role (and roster 2 when it was migrated as one)
INSERT IGNORE INTO member (name_id, desk_id, created) SELECT r.nid, m.desk_id, m.joined_at FROM @SRC@.room_member m JOIN rb_room r ON r.id = m.room_id WHERE m.left_at IS NULL;
INSERT IGNORE INTO member (name_id, desk_id, created) SELECT 2, desk_id, created FROM @SRC@.role_member WHERE role_id = 2;
UPDATE name n SET n = (SELECT COUNT(*) FROM member m WHERE m.name_id = n.id) WHERE type = 'roster';
INSERT INTO seat (desk_id, token_hash, delivery_mode, endpoint_url, endpoint_key, wake_on, lan_ip, time_connect, time_disconnect, updated)
  SELECT desk_id, token_hash, delivery_mode, endpoint_url, endpoint_key, wake_on, lan_ip, IFNULL(socket_at, last_seen), IF(socket_at IS NULL, last_seen, NULL), IFNULL(last_seen, NOW(6))
    FROM @SRC@.seat;

-- 2. payloads and their activity rows
INSERT INTO mail (id, created, desk_id, roster_id, body)
  SELECT l.id, l.created, l.sender_id, r.roster, l.body FROM @SRC@.letter l JOIN rb_room r ON r.id = l.room_id;
INSERT INTO activity (type, id, created, updated, deleted, desk_id, roster_id, n, bytes)
  SELECT 'mail', l.id, l.created, l.created, l.retired_at, l.sender_id, r.roster, 1, LENGTH(l.body) FROM @SRC@.letter l JOIN rb_room r ON r.id = l.room_id;
INSERT INTO mail_to (id, desk_id, opened, receipt, asked) SELECT letter_id, desk_id, read_at, receipt, asked FROM @SRC@.letter_to;
INSERT INTO todo (id, created, updated, updated_id, roster_id, creator_id, status, assigned_id, claimed_at, body)
  SELECT c.id, c.created, IFNULL(e.at, c.created), IFNULL(e.desk_id, c.creator_id), r.nid, c.creator_id, c.status, c.volunteer_id, c.claimed_at, c.body
    FROM @SRC@.card c JOIN rb_room r ON r.id = c.roster_id LEFT JOIN @SRC@.card_event e ON e.id = c.status_event_id;
INSERT INTO activity (type, id, created, updated, deleted, desk_id, roster_id, n, bytes)
  SELECT 'todo', c.id, c.created, IFNULL(e.at, c.created), c.retired_at, IFNULL(e.desk_id, c.creator_id), r.nid,
         LEAST(65535, (SELECT COUNT(*) FROM @SRC@.card_event x WHERE x.card_id = c.id)), LENGTH(c.body)
    FROM @SRC@.card c JOIN rb_room r ON r.id = c.roster_id LEFT JOIN @SRC@.card_event e ON e.id = c.status_event_id;
INSERT INTO hold (id, created, updated, desk_id, resource_id)
  SELECT x.nid, IFNULL(LEAST(MIN(e.at), IFNULL(MAX(h.taken_at), MIN(e.at))), MAX(h.taken_at)), IFNULL(MAX(h.taken_at), MAX(e.at)), MAX(h.desk_id), x.nid
    FROM rb_res x LEFT JOIN @SRC@.hold_event e ON e.resource_id = x.id LEFT JOIN @SRC@.hold h ON h.resource_id = x.id
   GROUP BY x.id, x.nid HAVING COUNT(e.id) > 0 OR COUNT(h.resource_id) > 0;
INSERT INTO activity (type, id, created, updated, desk_id, roster_id, n)
  SELECT 'hold', h.id, h.created, h.updated, IFNULL(h.desk_id, (SELECT MIN(id) FROM @SRC@.desk)), 1,
         LEAST(65535, (SELECT COUNT(*) FROM @SRC@.hold_event e JOIN rb_res x ON x.id = e.resource_id WHERE x.nid = h.id)) FROM hold h;
INSERT INTO doing (id, created, desk_id, roster_id, text, on_type, on_id, waiting_type, waiting_id, waiting_why@DOING_SUB_COL@)
  SELECT d.id, d.created, d.desk_id, 1, d.text,
         CASE WHEN d.on_card_id IS NOT NULL THEN 'todo' WHEN d.on_letter_id IS NOT NULL THEN 'mail' WHEN d.on_resource_id IS NOT NULL THEN 'hold' WHEN d.on_score_id IS NOT NULL THEN 'score' END,
         COALESCE(d.on_card_id, d.on_letter_id, (SELECT nid FROM rb_res WHERE id = d.on_resource_id), d.on_score_id),
         CASE WHEN d.wait_desk_id IS NOT NULL THEN 'desk' WHEN d.wait_card_id IS NOT NULL THEN 'todo' WHEN d.wait_letter_id IS NOT NULL THEN 'mail' WHEN d.wait_resource_id IS NOT NULL THEN 'hold' END,
         COALESCE(d.wait_desk_id, d.wait_card_id, d.wait_letter_id, (SELECT nid FROM rb_res WHERE id = d.wait_resource_id)), d.waiting_why@DOING_SUB_VAL@
    FROM @SRC@.doing d;
INSERT INTO activity (type, id, created, updated, desk_id, roster_id) SELECT 'doing', id, created, created, desk_id, 1 FROM @SRC@.doing;
-- a roster's own score (desk NULL) is owned by the roster again
INSERT INTO score (id, created, updated, desk_id, roster_id, kpi, value, target, note, better, unit)
  SELECT s.id, s.created, s.created, IFNULL(s.desk_id, r.nid), r.nid, s.kpi, '', IFNULL(CAST(s.target AS CHAR), ''), s.note, s.better, s.unit
    FROM @SRC@.score s JOIN rb_room r ON r.id = s.roster_id;
INSERT INTO activity (type, id, created, updated, deleted, desk_id, roster_id)
  SELECT 'score', s.id, s.created, s.created, s.retired_at, IFNULL(s.desk_id, r.nid), r.nid FROM @SRC@.score s JOIN rb_room r ON r.id = s.roster_id;
INSERT INTO score_point (score_id, id, created, desk_id, value, note) SELECT score_id, id, at, desk_id, value, note FROM @SRC@.score_point;
INSERT INTO score_evidence (score_id, timestamp, value, taken) SELECT score_id, at, value, taken FROM @SRC@.score_evidence;
INSERT INTO label (type, id, name_id, ord) SELECT 'todo', t.card_id, r.nid, 65535 FROM @SRC@.card_tag t JOIN rb_tag r ON r.id = t.tag_id;
INSERT INTO label (type, id, name_id, ord) SELECT 'mail', t.letter_id, r.nid, 65535 FROM @SRC@.letter_tag t JOIN rb_tag r ON r.id = t.tag_id;
INSERT INTO label (type, id, name_id, ord)
  SELECT 'todo', card_id, 4 * @base + desk_id, LEAST(65534, ROW_NUMBER() OVER (PARTITION BY desk_id ORDER BY rank_ord, card_id)) FROM @SRC@.focus;
INSERT INTO push_queue (id, desk_id, kind, payload, outcome, created)
  SELECT p.id, p.desk_id, 'mail',
         JSON_OBJECT('id', l.id, 'kind', 'mail', 'body', l.body, 'sender', s.name, 'created', DATE_FORMAT(l.created, '%Y-%m-%d %H:%i:%s.%f'),
                     'opened', NULL, 'receipt', t.receipt, 'mail_tos', (SELECT JSON_ARRAYAGG(d.name) FROM @SRC@.letter_to x JOIN @SRC@.desk d ON d.id = x.desk_id WHERE x.letter_id = l.id),
                     'affiliation_id', NULL),
         'missed', p.created
    FROM @SRC@.push p JOIN @SRC@.letter l ON l.id = p.letter_id JOIN @SRC@.desk s ON s.id = l.sender_id
    JOIN @SRC@.letter_to t ON t.letter_id = p.letter_id AND t.desk_id = p.desk_id;

-- 3. nested sets: discussion rooms (reply threads, by id), plans (by ord, id), then the came-from pairs.
--    A node's path is its ancestors' sibling ranks, 6 hex digits a level, so a string sort is preorder. MySQL sorts
--    strings on their first max_sort_length bytes (1024): that is 170 levels; a deeper path fails ck_rb_depth
--    instead of coming out of order (seen at M with 40-character levels past 25 deep).
CREATE TABLE rb_rank (type VARCHAR(8) NOT NULL, id BIGINT UNSIGNED NOT NULL, k CHAR(6) CHARACTER SET ascii NOT NULL, PRIMARY KEY (type, id));
INSERT INTO rb_rank
  SELECT 'mail', l.id, LPAD(HEX(ROW_NUMBER() OVER (PARTITION BY IF(l.reply_to_id IS NULL, -CAST(l.room_id AS SIGNED), CAST(l.reply_to_id AS SIGNED)) ORDER BY l.id)), 6, '0')
    FROM @SRC@.letter l JOIN rb_room r ON r.id = l.room_id AND r.kind = 'room';
INSERT INTO rb_rank
  SELECT 'todo', c.id, LPAD(HEX(ROW_NUMBER() OVER (PARTITION BY c.from_card_id ORDER BY c.ord, c.id)), 6, '0') FROM @SRC@.card c WHERE c.from_card_id IS NOT NULL;
CREATE TABLE rb_ns (tree BIGINT UNSIGNED NOT NULL, type VARCHAR(8) NOT NULL, id BIGINT UNSIGNED NOT NULL, path VARCHAR(1100) CHARACTER SET ascii NOT NULL, depth INT NOT NULL,
  PRIMARY KEY (tree, type, id), KEY ix_path (tree, path(255)), CONSTRAINT ck_rb_depth CHECK (LENGTH(path) <= 1020));
INSERT INTO rb_ns
  WITH RECURSIVE t (tree, id, path, depth) AS (
    SELECT r.nid, l.id, CAST(k.k AS CHAR(1100) CHARACTER SET ascii), 0
      FROM @SRC@.letter l JOIN rb_room r ON r.id = l.room_id AND r.kind = 'room' JOIN rb_rank k ON k.type = 'mail' AND k.id = l.id WHERE l.reply_to_id IS NULL
    UNION ALL SELECT t.tree, c.id, CONCAT(t.path, k.k), t.depth + 1 FROM t JOIN @SRC@.letter c ON c.reply_to_id = t.id JOIN rb_rank k ON k.type = 'mail' AND k.id = c.id)
  SELECT tree, 'mail', id, path, depth FROM t;
INSERT INTO rb_ns
  WITH RECURSIVE t (tree, id, path, depth) AS (
    SELECT 5 * @base + r.id, r.id, CAST('000001' AS CHAR(1100) CHARACTER SET ascii), 0 FROM @SRC@.card r
     WHERE r.from_card_id IS NULL AND EXISTS (SELECT 1 FROM @SRC@.card k WHERE k.from_card_id = r.id)
    UNION ALL SELECT t.tree, c.id, CONCAT(t.path, k.k), t.depth + 1 FROM t JOIN @SRC@.card c ON c.from_card_id = t.id JOIN rb_rank k ON k.type = 'todo' AND k.id = c.id)
  SELECT tree, 'todo', id, path, depth FROM t;
INSERT INTO name (id, type, name) SELECT DISTINCT tree, 'tree', CONCAT('plan-', tree - 5 * @base) FROM rb_ns WHERE type = 'todo';
INSERT INTO tree (name_id, type, id, lft, rgt)
  SELECT n.tree, n.type, n.id, 2 * n.pre - n.depth - 1, 2 * n.pre - n.depth - 1 + 2 * (SELECT COUNT(*) FROM rb_ns d WHERE d.tree = n.tree AND d.path LIKE CONCAT(n.path, '%')) - 1
    FROM (SELECT tree, type, id, path, depth, ROW_NUMBER() OVER (PARTITION BY tree ORDER BY path) pre FROM rb_ns) n;
INSERT INTO name (id, type, name) SELECT 5 * @base + @span + id, 'tree', CONCAT('from-letter-', id) FROM @SRC@.card WHERE from_letter_id IS NOT NULL;
INSERT INTO tree (name_id, type, id, lft, rgt) SELECT 5 * @base + @span + id, 'mail', from_letter_id, 1, 4 FROM @SRC@.card WHERE from_letter_id IS NOT NULL;
INSERT INTO tree (name_id, type, id, lft, rgt) SELECT 5 * @base + @span + id, 'todo', id, 2, 3 FROM @SRC@.card WHERE from_letter_id IS NOT NULL;
INSERT INTO name (id, type, name) SELECT 5 * @base + 2 * @span + id, 'tree', CONCAT('from-score-', id) FROM @SRC@.card WHERE from_score_id IS NOT NULL;
INSERT INTO tree (name_id, type, id, lft, rgt) SELECT 5 * @base + 2 * @span + id, 'score', from_score_id, 1, 4 FROM @SRC@.card WHERE from_score_id IS NOT NULL;
INSERT INTO tree (name_id, type, id, lft, rgt) SELECT 5 * @base + 2 * @span + id, 'todo', id, 2, 3 FROM @SRC@.card WHERE from_score_id IS NOT NULL;

-- 4. carried tables
INSERT INTO human (id, bearer_hash, directory_sub, created, updated) SELECT id, bearer_hash, directory_sub, created, updated FROM @SRC@.human;
INSERT INTO human_desk (human_id, desk_id, created) SELECT human_id, desk_id, created FROM @SRC@.human_desk;
INSERT IGNORE INTO human_member (human_id, name_id, created)
  SELECT h.human_id, IFNULL(r.nid, 2), h.created FROM @SRC@.human_member h LEFT JOIN rb_room r ON r.id = h.room_id;
INSERT INTO mill_invite (key_id, token_hash, label, created_by, created_at, ttl_seconds, expires_at, enabled_at, revoked_at)
  SELECT key_id, token_hash, label, created_by, created_at, ttl_seconds, expires_at, enabled_at, revoked_at FROM @SRC@.mill_invite;
INSERT INTO mill_invite_join (key_id, party, party_id, created) SELECT key_id, party, party_id, created FROM @SRC@.mill_invite_join;
DROP TABLE rb_ns, rb_rank, rb_room, rb_tag, rb_res;
