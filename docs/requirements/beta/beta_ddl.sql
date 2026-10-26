-- 29 tables. Wipe then apply.
-- BETA (0.8, card 868): main's tables.sql with the departures listed in BETA-CHANGES.md; 29 tables:
-- main's 22 plus todo_event, doing_now, vote, vote_option, vote_cast, glance_cache, sp_deploy.
-- BETA order: name, then seat (the desk kind table), then main's order.
-- name, member, activity, label, tree, watcher,
-- mail, mail_to, tree_read, todo, seat, doing, hold, score, score_point, score_evidence,
-- human, human_desk, human_member, mill_invite, mill_invite_join, push_queue.
-- Platform follows the payloads. label and tree reference activity, so they sit under it.
-- charset: utf8mb4 names/prose; ascii_bin hashes and invite keys.
-- name stores a bare string. type is desk, roster, label, tree, or res. A roster is an unordered list of desks; members are equal.
-- id 1 = Office. id 2 = Admin. Never retire.
-- activity PK (type, id). Payload type uses this same ENUM list. Ids are per type (each payload table's AUTO_INCREMENT).
-- activity is the timeline, not a parent: no payload (mail, todo, doing, hold, score) has an FK to it.
-- A writer inserts the payload, takes LAST_INSERT_ID(), then writes the activity row in the same transaction.
-- label and tree keep their FKs to activity: they point at a timeline row that already exists.
-- Every mill FK to name is RESTRICT, and name_no_delete refuses a hard DELETE (retire stamps name.deleted).
-- name.n = desk count for a roster.
-- member is N-N only. name_id is a roster, pinned by name_kind (kind-checked FK). Not an activity type.

--
-- BETA. Three rules place every relation (owner rules; reads far outnumber writes). All three are main's:
--   [row]   a field on the row that owns the fact; a reference to one of several kinds is the composite
--           (type ENUM, id), as on main's activity, label, tree and doing.on_*/waiting_*.
--   [tree]  nested set (Celko lft/rgt, as on main): plans and mail rooms/threads, one lft/rgt line per tree name.
--   [label] label rank (as on main): ord 0 pinned, 65535 unplaced; a desk's focus list is a label.
--
-- BETA. Names, for integrity (owner rule). name exists only so a name cannot confuse or mislead an agent or a human;
-- it is the ONE place names are managed: a name is an isolated column, not a first-class object. UNIQUE (type, name)
-- as on main (no duplicates). There is no name history (owner decision 2026-10-24).
-- BETA. Kind tables (owner rule 2026-10-25): a name kind gets its own table only if the thing has its own data.
-- seat (desk_id, kind id = name.id) is the desk kind: it holds the desk's token, wake and connect data, so every desk
-- column FKs to seat (desk_id) and a desk column cannot hold a roster id. A roster, label, tree or res has no data of
-- its own (a roster's detail is name.n, as on main), so it has no kind table; its columns carry a <x>_kind column
-- pinned by DEFAULT and CHECK and reference name (id, type), so they cannot hold a name of another kind.
-- Indexes (owner rule): PRIMARY and UNIQUE keys are indexed by definition; every other index is declared here and
-- named idx_*, so MySQL creates no index for an FK. seat rows are written only by the minting procedure.
-- Name lifecycle (docs/requirements/admin.md sections 1, 2, 4; rows F60, F65, F92, F135), in beta_sp.sql sp_name_*:
--   mint     a desk mints itself at connect; a roster, role or label (first-use label too) is minted by any seated
--            desk under high trust and only by Admin under limited trust; a plan (tree) or resource by any desk.
--   rename   a plain UPDATE of name.name; related records follow through the id. Admin at either trust; a desk
--            may rename itself when its seat hash matches. No hold on a renamed-away name, for any type (names
--            are agents', not humans'): the old string is free for a new mint at once.
--   seeds    Office (id 1) and Admin (id 2) are never retired or reclaimed; Admin is never renamed in any case- or
--            accent-insensitive spelling; Office may be renamed by Admin, everything follows id 1, and no other
--            roster is renamed onto Office. Guards read ids 1 and 2, never the strings.
--   retire   deletion is hard to do: Admin only, soft (name.deleted); name_no_delete refuses DELETE (as on main).
--            UNIQUE (type, name) stays held while retired, so reuse is an Admin reclaim that restores the same id,
--            refused while a live seat is that desk or a member of that name. Retiring a desk clears its seat token
--            and webhook and frees its holds in the same call (F65, F135).
--
-- BETA. Trust (owner rule). The office trust setting (high | limited) stays in the server's config.toml, as on main;
-- no table holds it. At server startup, before any request, the server reads config.toml and re-creates
-- b_trust() (DETERMINISTIC, returns 'high' or 'limited'); `mill trust high|limited` writes config.toml and then
-- re-creates it the same way. A hand edit of config.toml takes effect at the next restart. Full rules:
-- docs/requirements/schema-design.md, "Office settings live in config.toml".
-- Every cmd_* and sp_* calls b_trust() itself (no procedure takes trust as an argument) and applies
-- docs/requirements/admin.md sections 1-3 (always Admin; trust-gated; any desk) inside the procedure: the app user
-- holds EXECUTE only, so the procedure is the only place a guard can stand. Granting Admin is the host path only:
-- its procedure is granted to the host database user, not to the app user.
--
-- BETA. Ids and id references are BIGINT UNSIGNED, as on main (owner decision 2026-10-24: the INT narrowing is
-- withdrawn). Isolation READ COMMITTED.

CREATE TABLE IF NOT EXISTS name (
  id          BIGINT UNSIGNED   NOT NULL AUTO_INCREMENT,
  type        ENUM('desk','roster','label','tree','res') NOT NULL,
  updated     DATETIME(6)       NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  name        VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  deleted     DATETIME(6)       NULL,
  n           INT UNSIGNED      NOT NULL DEFAULT 0,
  PRIMARY KEY (id),
  UNIQUE KEY idx_type (type, name),
  UNIQUE KEY idx_id_type (id, type)   -- BETA: target of the kind-checked name FKs; UNIQUE only because MySQL 8.4 requires it (id is already the PK)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

INSERT IGNORE INTO name (id, type, name) VALUES
  (1, 'roster', 'Office'),
  (2, 'roster', 'Admin');

-- BETA (kind tables): seat is the desk kind. seat.desk_id = name.id (UNIQUE idx_desk); every desk column FKs to
-- seat (desk_id), not to name. Placed before the tables that reference it (main has it after todo).
-- #818: one desk's standing setup (token, wake, connect stamps). Not an activity:
-- no type column, no activity row. One row per desk. Agent text says desk/join/connect.
CREATE TABLE IF NOT EXISTS seat (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  desk_id         BIGINT UNSIGNED NOT NULL,
  created         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  token_hash      CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  delivery_mode   ENUM('websocket','webhook','polling') NOT NULL DEFAULT 'polling',
  endpoint_url    VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  -- #618: the desk's own webhook key. Only mill_join_wake_target reads it (POST time).
  endpoint_key    VARCHAR(512) CHARACTER SET ascii COLLATE ascii_bin NULL,
  -- #628: which items POST: all, or addressed only (room-only items wait for the next connect).
  -- Card 836: addressed is the default, so a room copy wakes no one.
  wake_on         ENUM('all','addressed') NOT NULL DEFAULT 'addressed',
  lan_ip          VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NULL,
  time_connect    DATETIME(6) NULL,
  time_disconnect DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY idx_desk (desk_id),
  KEY idx_lan_updated (lan_ip, updated),
  KEY idx_token_hash (token_hash),
  -- RESTRICT (#96): a seat is history. Reset/disconnect stamp the row; a name delete must not wipe it.
  CONSTRAINT fk_seat_desk FOREIGN KEY (desk_id) REFERENCES name (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- N-N roster membership. name_id is a roster. Self add/remove.
-- Office: never leave. Admin: the host desk is on it.
CREATE TABLE IF NOT EXISTS member (
  name_id     BIGINT UNSIGNED NOT NULL,
  name_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (name_kind = 'roster'),   -- BETA: pins the name kind for fk_member_name
  desk_id     BIGINT UNSIGNED NOT NULL,
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (name_id, name_kind, desk_id),
  KEY idx_desk (desk_id, name_id),
  CONSTRAINT fk_member_name FOREIGN KEY (name_id, name_kind) REFERENCES name (id, type) ON DELETE RESTRICT,
  CONSTRAINT fk_member_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Activity, then the rows that share its (type, id).
CREATE TABLE IF NOT EXISTS activity (
  type        ENUM('mail','todo','doing','hold','score') NOT NULL,
  id          BIGINT UNSIGNED       NOT NULL,
  created     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated     DATETIME(6)  NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  deleted     DATETIME(6)       NULL,
  desk_id          BIGINT UNSIGNED       NULL,   -- BETA: NULL = the office itself (main wrote roster id 2, Admin, here)
  roster_id   BIGINT UNSIGNED       NOT NULL DEFAULT 1,
  roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (roster_kind = 'roster'),   -- BETA: pins the name kind for fk_activity_roster
  weight           INT UNSIGNED NOT NULL DEFAULT 1,
  n                SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  bytes            INT UNSIGNED NULL,
  PRIMARY KEY (type, id),
  KEY idx_type (type, roster_id, updated),
  KEY idx_desk (desk_id, type, updated),
  KEY idx_desk_updated (desk_id, updated),
  KEY idx_roster (roster_id, roster_kind, type, updated),
  -- roster_id is required. 1 = Office. A missing roster is Office, so every row is counted.
  -- A name row is not deleted. Retire stamps name.deleted, and this id keeps pointing at it.
  CONSTRAINT fk_activity_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_activity_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES name (id, type) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Tags on any activity. name_id is a label. Not member (desk <-> roster).
-- ord: 0 pinned, 65535 unplaced. RANK is reserved (#196).
-- BETA (owner rule): ordinals with periodic renumber. sp_label_renumber spreads one label's ranks 1..65534 again
-- when a gap runs out; 0 and 65535 keep their meaning. (Main said 'Gaps stay. Never renumber.')
CREATE TABLE IF NOT EXISTS label (
  type        ENUM('mail','todo','doing','hold','score') NOT NULL,
  id          BIGINT UNSIGNED NOT NULL,
  name_id     BIGINT UNSIGNED NOT NULL,
  name_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'label' CHECK (name_kind = 'label'),   -- BETA: pins the name kind for fk_label_name
  ord         SMALLINT UNSIGNED NOT NULL DEFAULT 65535,
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (type, id, name_id),
  KEY idx_label_ord (name_id, name_kind, ord, created),
  CONSTRAINT fk_label_activity FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE CASCADE,
  CONSTRAINT fk_label_name FOREIGN KEY (name_id, name_kind) REFERENCES name (id, type) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Nested set (Celko). Structure. name_id is the plan (name.type = tree).
-- One plan = one lft/rgt line. A node payload is (type, id), an activity row.
-- The same payload may sit in many plans. The first card is lft 1.
CREATE TABLE IF NOT EXISTS tree (
  name_id  BIGINT UNSIGNED NOT NULL,
  name_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'tree' CHECK (name_kind = 'tree'),   -- BETA: pins the name kind for fk_tree_name
  type     ENUM('mail','todo','doing','hold','score') NOT NULL,
  id       BIGINT UNSIGNED NOT NULL,
  lft      INT UNSIGNED NOT NULL,
  rgt      INT UNSIGNED NOT NULL,
  PRIMARY KEY (name_id, name_kind, type, id),
  UNIQUE KEY idx_lft (name_id, lft),
  UNIQUE KEY idx_rgt (name_id, rgt),
  KEY idx_type_lft (type, lft),
  KEY idx_activity (type, id),
  CONSTRAINT fk_tree_name FOREIGN KEY (name_id, name_kind) REFERENCES name (id, type) ON DELETE RESTRICT,
  CONSTRAINT fk_tree_activity FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- Who to poke (desk_id = subscriber name.id). Mail is not a watcher type.
-- A name row is not a watcher target.
CREATE TABLE IF NOT EXISTS watcher (
  type        ENUM('todo','doing','hold','score') NOT NULL,
  id          BIGINT UNSIGNED NOT NULL,
  desk_id     BIGINT UNSIGNED NOT NULL,
  hint        VARCHAR(4096) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  updated     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (type, id, desk_id),
  KEY idx_desk (desk_id),
  CONSTRAINT fk_watcher_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;


-- Letter only. Dest/state live on mail_to. No updated, no group_id.
CREATE TABLE IF NOT EXISTS mail (
  type            ENUM('mail','todo','doing','hold','score') NOT NULL DEFAULT 'mail',
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  desk_id         BIGINT UNSIGNED NOT NULL,
  -- Card roster required. No DEFAULT: a missed insert must fail.
  roster_id  BIGINT UNSIGNED NOT NULL,
  roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (roster_kind = 'roster'),   -- BETA: pins the name kind for fk_mail_roster
  body            VARCHAR(4096) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (type, id),
  UNIQUE KEY idx_id (id),
  KEY idx_desk (desk_id, created),
  KEY idx_mail_roster (roster_id, roster_kind),
  CONSTRAINT fk_mail_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_mail_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES name (id, type) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Who has the letter. Desk, opened, receipt. Roster lives on the letter.
CREATE TABLE IF NOT EXISTS mail_to (
  type            ENUM('mail','todo','doing','hold','score') NOT NULL DEFAULT 'mail',
  id              BIGINT UNSIGNED NOT NULL,
  desk_id         BIGINT UNSIGNED NOT NULL,
  opened          DATETIME(6) NULL,
  receipt         TINYINT(1) NOT NULL DEFAULT 0,
  -- #818 D1: 1 = asked (named on the letter), 0 = copied (reached only as a
  -- room member on reply-all). Waiting on a desk counts asked rows only.
  asked           TINYINT(1) NOT NULL DEFAULT 1,
  created         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (type, id, desk_id),
  KEY idx_desk (desk_id, created),
  -- Unread page for one desk, newest first (mill_mail_inbox).
  KEY idx_desk_unread (desk_id, opened, id),
  CONSTRAINT fk_mail_to_mail FOREIGN KEY (type, id) REFERENCES mail (type, id) ON DELETE CASCADE,
  CONSTRAINT fk_mail_to_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Per-desk read cursor on one tree (#155). tree_id is tree.name_id (the tree's
-- name row), so any tree can carry it: a mail room today, todo branches later.
-- last_id is the newest activity id this desk has read on that tree.
CREATE TABLE IF NOT EXISTS tree_read (
  desk_id  BIGINT UNSIGNED NOT NULL,
  tree_id  BIGINT UNSIGNED NOT NULL,
  tree_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'tree' CHECK (tree_kind = 'tree'),   -- BETA: pins the name kind for fk_tree_read_tree
  last_id  BIGINT UNSIGNED NOT NULL,
  updated  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (desk_id, tree_id),
  KEY idx_tree (tree_id, tree_kind),
  CONSTRAINT fk_tree_read_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_tree_read_tree FOREIGN KEY (tree_id, tree_kind) REFERENCES name (id, type) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS todo (
  type            ENUM('mail','todo','doing','hold','score') NOT NULL DEFAULT 'todo',
  id              BIGINT UNSIGNED        NOT NULL AUTO_INCREMENT,
  created         DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated         DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  updated_id      BIGINT UNSIGNED        NOT NULL,
  -- Card roster required. No DEFAULT: a missed insert must fail.
  roster_id  BIGINT UNSIGNED        NOT NULL,
  roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (roster_kind = 'roster'),   -- BETA: pins the name kind for fk_todo_roster
  creator_id      BIGINT UNSIGNED        NOT NULL,
  status          ENUM('parked','open','claimed','shipped','done') NOT NULL DEFAULT 'open',
  assigned_id     BIGINT UNSIGNED        NULL,
  -- #818 D2: when the card became claimed or its volunteer changed (claim,
  -- --take-over, assign, pass --back to claimed). NULL when not claimed.
  claimed_at      DATETIME(6)   NULL,
  body            VARCHAR(4096) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  -- BETA (owner rule): the acceptance line, set by the asker or Admin until the card is done (cmd_card_accept).
  done_when       VARCHAR(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  PRIMARY KEY (type, id),
  UNIQUE KEY idx_id (id),
  KEY idx_status (status, updated),
  KEY idx_roster (roster_id, roster_kind, status, updated),
  KEY idx_updated (updated_id),
  KEY idx_creator (creator_id),
  KEY idx_assigned (assigned_id),
  CONSTRAINT fk_todo_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES name (id, type) ON DELETE RESTRICT,
  CONSTRAINT fk_todo_updated FOREIGN KEY (updated_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_todo_creator FOREIGN KEY (creator_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_todo_assigned FOREIGN KEY (assigned_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- BETA (owner rule: pass with evidence; lab H5, RESULTS.md line 114): one status change of a todo, with its
-- evidence on ship and done. todo.status stays the current value; this is its history.
CREATE TABLE IF NOT EXISTS todo_event (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  todo_id     BIGINT UNSIGNED NOT NULL,
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  desk_id     BIGINT UNSIGNED NOT NULL,
  from_status ENUM('parked','open','claimed','shipped','done') NULL,
  to_status   ENUM('parked','open','claimed','shipped','done') NOT NULL,
  assigned_id BIGINT UNSIGNED NULL,
  evidence    VARCHAR(2000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  PRIMARY KEY (id),
  KEY idx_todo (todo_id, id),
  KEY idx_desk (desk_id),
  KEY idx_assigned (assigned_id),
  CONSTRAINT ck_todo_event_evidence CHECK (evidence IS NULL OR to_status IN ('shipped','done')),
  CONSTRAINT fk_todo_event_todo FOREIGN KEY (todo_id) REFERENCES todo (id) ON DELETE RESTRICT,
  CONSTRAINT fk_todo_event_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_todo_event_assigned FOREIGN KEY (assigned_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- #818: what a desk is doing. Append-only: one row per entry, never overwritten.
-- The desk's current doing is its newest row. on_* is the activity the entry
-- is about (any type but doing); waiting_* is what it is blocked on (#822:
-- a desk, letter, card or hold, plus the reason) as fields on this one row.
-- No edge or link table: who is blocked on a desk is a read (mill_doing_now).
CREATE TABLE IF NOT EXISTS doing (
  type          ENUM('mail','todo','doing','hold','score') NOT NULL DEFAULT 'doing',
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  desk_id       BIGINT UNSIGNED NOT NULL,
  roster_id     BIGINT UNSIGNED NOT NULL DEFAULT 1,
  roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (roster_kind = 'roster'),   -- BETA: pins the name kind for fk_doing_roster
  text          VARCHAR(512) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  on_type       ENUM('mail','todo','hold','score') NULL,
  on_id         BIGINT UNSIGNED NULL,
  waiting_type  ENUM('mail','todo','hold','desk') NULL,
  waiting_id    BIGINT UNSIGNED NULL,
  waiting_why   VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  PRIMARY KEY (type, id),
  UNIQUE KEY idx_id (id),
  KEY idx_desk_created (desk_id, created),
  KEY idx_on (on_type, on_id),
  KEY idx_roster (roster_id, roster_kind),
  UNIQUE KEY idx_id_desk (id, desk_id),   -- BETA: target of doing_now's composite FK
  CONSTRAINT fk_doing_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_doing_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES name (id, type) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- BETA (lab: A2 desk doing 4.6 -> 0.1 ms at M, RESULTS.md lines 20 and 56): the desk's current doing, kept by the
-- same procedure that appends the doing row. The composite FK keeps it on the desk's own row.
CREATE TABLE IF NOT EXISTS doing_now (
  desk_id     BIGINT UNSIGNED NOT NULL,
  doing_id    BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (desk_id),
  KEY idx_doing (doing_id, desk_id),
  CONSTRAINT fk_doing_now_doing FOREIGN KEY (doing_id, desk_id) REFERENCES doing (id, desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- One lock per resource. desk_id NULL means free. Release nulls desk_id; the row stays.
CREATE TABLE IF NOT EXISTS hold (
  type        ENUM('mail','todo','doing','hold','score') NOT NULL DEFAULT 'hold',
  id          BIGINT UNSIGNED          NOT NULL AUTO_INCREMENT,
  created     DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated     DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  desk_id          BIGINT UNSIGNED          NULL,
  resource_id      BIGINT UNSIGNED          NOT NULL,
  resource_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'res' CHECK (resource_kind = 'res'),   -- BETA: pins the name kind for fk_hold_res
  PRIMARY KEY (type, id),
  UNIQUE KEY idx_id (id),
  UNIQUE KEY idx_hold (resource_id, resource_kind),
  KEY idx_desk (desk_id),
  CONSTRAINT fk_hold_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_hold_res  FOREIGN KEY (resource_id, resource_kind) REFERENCES name (id, type) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS score (
  type        ENUM('mail','todo','doing','hold','score') NOT NULL DEFAULT 'score',
  id          BIGINT UNSIGNED        NOT NULL AUTO_INCREMENT,
  created     DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated     DATETIME(6)   NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  desk_id          BIGINT UNSIGNED        NULL,   -- BETA: NULL = an office-wide score (main wrote roster id 2, Admin, here)
  -- Card roster required. No DEFAULT: a missed insert must fail.
  roster_id   BIGINT UNSIGNED        NOT NULL,
  roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (roster_kind = 'roster'),   -- BETA: pins the name kind for fk_score_roster
  kpi              VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  value            VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  target           VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  note             VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  -- 0.7.5 series: which way is better, and the unit shown with each point.
  better      ENUM('up','down') NOT NULL DEFAULT 'up',
  unit        VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  PRIMARY KEY (type, id),
  UNIQUE KEY idx_id (id),
  desk_key    BIGINT UNSIGNED AS (IFNULL(desk_id, 0)) STORED,   -- BETA: one office-wide row per kpi (NULL is not unique)
  UNIQUE KEY idx_score_who (roster_id, roster_kind, desk_key, kpi),
  KEY idx_desk (desk_id),
  CONSTRAINT fk_score_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES name (id, type) ON DELETE RESTRICT,
  CONSTRAINT fk_score_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- 0.7.5: one numeric point of a score series (#288 step 1). The score row is the
-- definition; points are its child series keyed by score.id. The newest N is a
-- backward read of the primary key, no sort. desk_id is the desk that recorded it.
CREATE TABLE IF NOT EXISTS score_point (
  score_id    BIGINT UNSIGNED NOT NULL,
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created     DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  desk_id     BIGINT UNSIGNED NOT NULL,
  value       DOUBLE          NOT NULL,
  note        VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  PRIMARY KEY (score_id, id),
  UNIQUE KEY idx_id (id),
  KEY idx_desk (desk_id),
  KEY idx_score_at (score_id, created, id),
  CONSTRAINT fk_score_point_score FOREIGN KEY (score_id) REFERENCES score (id) ON DELETE RESTRICT,
  CONSTRAINT fk_score_point_desk  FOREIGN KEY (desk_id) REFERENCES seat (desk_id)  ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- History of one score. Hour rows reuse 1970-01-01 00:00 through 23:00; taken is the real day.
-- The same hour on a new day replaces that document. Day rows are the real midnight, including February 29.
-- value is one JSON document, at most 4096 bytes. A larger write is rejected.
-- Day rows older than 30 days are removed. The 1970 hour rows stay.
-- RESTRICT (#95): mill_score_delete keeps the score card, so evidence stays attached.
-- A direct DELETE score fails while evidence rows exist.
CREATE TABLE IF NOT EXISTS score_evidence (
  score_id   BIGINT UNSIGNED NOT NULL,
  timestamp  DATETIME(6)     NOT NULL,
  value      JSON            NOT NULL,
  taken      DATE            NULL,
  PRIMARY KEY (score_id, timestamp),
  CONSTRAINT fk_score_evidence_score FOREIGN KEY (score_id) REFERENCES score (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Waste readings filled from the debug logs. kpi is the label string, not a name row. Target 0.
-- desk_id NULL (BETA: the office; main used 2, Admin). roster_id = Office. activity row matches score.id.
-- System SCORE is one row per desk (kpi system). Its evidence document holds verb counts, milliseconds, and mail and todo bytes.
INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note)
SELECT CURRENT_TIMESTAMP(6), NULL, 1, 'mill-wall.ticks', '', '0',
       'server complexity: api.mill.heartbeat per desk-hour while sitting; target 0'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM score WHERE roster_id = 1 AND desk_id IS NULL AND kpi = 'mill-wall.ticks');
INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note)
SELECT CURRENT_TIMESTAMP(6), NULL, 1, 'mill-desk.idle_verbs', '', '0',
       'prompt complexity: mill inbox/todo per desk-hour with no HINT; target 0'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM score WHERE roster_id = 1 AND desk_id IS NULL AND kpi = 'mill-desk.idle_verbs');
INSERT INTO score (updated, desk_id, roster_id, kpi, value, target, note)
SELECT CURRENT_TIMESTAMP(6), NULL, 1, 'mill-desk.hint_drop', '', '0',
       'sit FIFO overflow: mill-perf op=ws.recv drop=1 in window; target 0'
  FROM DUAL
 WHERE NOT EXISTS (SELECT 1 FROM score WHERE roster_id = 1 AND desk_id IS NULL AND kpi = 'mill-desk.hint_drop');
INSERT IGNORE INTO activity (type, id, created, updated, desk_id, roster_id, weight, n, bytes)
SELECT 'score', s.id, s.created, s.updated, s.desk_id, s.roster_id, 1, 1, NULL
FROM score s
WHERE s.kpi IN ('mill-wall.ticks', 'mill-desk.idle_verbs', 'mill-desk.hint_drop');

-- BETA (owner decision: a roster decides by vote, open / cast / close). One question a roster votes on; the
-- question is a mail on that roster. closed/outcome are set together by the close procedure.
CREATE TABLE IF NOT EXISTS vote (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  desk_id     BIGINT UNSIGNED NOT NULL,
  roster_id   BIGINT UNSIGNED NOT NULL,
  roster_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (roster_kind = 'roster'),   -- BETA: pins the name kind for fk_vote_roster
  mail_id     BIGINT UNSIGNED NOT NULL,
  question    VARCHAR(400) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  deadline    DATETIME(6) NOT NULL,
  closed      DATETIME(6) NULL,
  outcome     ENUM('decided','deadlock','no_show') NULL,
  result_opt  TINYINT UNSIGNED NULL,
  members_n   SMALLINT UNSIGNED NULL,
  escalated   DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY idx_mail (mail_id),
  KEY idx_roster_open (roster_id, roster_kind, closed, deadline),
  KEY idx_desk (desk_id),
  KEY idx_result (id, result_opt),
  KEY idx_due (closed, deadline),
  CONSTRAINT ck_vote_deadline CHECK (deadline > created),
  CONSTRAINT ck_vote_closed CHECK ((closed IS NULL) = (outcome IS NULL) AND (closed IS NULL) = (members_n IS NULL)),
  CONSTRAINT ck_vote_result CHECK ((outcome = 'decided') <=> (result_opt IS NOT NULL) OR (outcome IS NULL AND result_opt IS NULL)),
  CONSTRAINT ck_vote_escalated CHECK (escalated IS NULL OR outcome IN ('deadlock','no_show')),
  CONSTRAINT fk_vote_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_vote_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES name (id, type) ON DELETE RESTRICT,
  CONSTRAINT fk_vote_mail FOREIGN KEY (mail_id) REFERENCES mail (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- BETA: one option of a vote (label is option text, not a name row).
CREATE TABLE IF NOT EXISTS vote_option (
  vote_id     BIGINT UNSIGNED NOT NULL,
  opt         TINYINT UNSIGNED NOT NULL,
  label       VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  PRIMARY KEY (vote_id, opt),
  UNIQUE KEY idx_label (vote_id, label),
  CONSTRAINT ck_vote_option_opt CHECK (opt BETWEEN 1 AND 16),
  CONSTRAINT fk_vote_option_vote FOREIGN KEY (vote_id) REFERENCES vote (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
ALTER TABLE vote ADD CONSTRAINT fk_vote_result FOREIGN KEY (id, result_opt) REFERENCES vote_option (vote_id, opt);

-- BETA: one member's cast on a vote (a recast updates the row while the vote is open).
CREATE TABLE IF NOT EXISTS vote_cast (
  vote_id     BIGINT UNSIGNED NOT NULL,
  desk_id     BIGINT UNSIGNED NOT NULL,
  opt         TINYINT UNSIGNED NOT NULL,
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  note        VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  PRIMARY KEY (vote_id, desk_id),
  KEY idx_desk (desk_id),
  KEY idx_opt (vote_id, opt),
  CONSTRAINT fk_vote_cast_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT,
  CONSTRAINT fk_vote_cast_opt FOREIGN KEY (vote_id, opt) REFERENCES vote_option (vote_id, opt) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- One human. They hold the bearer. The host stores only the hash.
-- directory_sub is the directory or IAM subject, when that door is on.
CREATE TABLE IF NOT EXISTS human (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  bearer_hash    CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  directory_sub  VARCHAR(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL,
  created        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated        DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY idx_hash (bearer_hash),
  UNIQUE KEY idx_directory_sub (directory_sub)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- One human, many agent desks. A desk belongs to one human.
CREATE TABLE IF NOT EXISTS human_desk (
  human_id  BIGINT UNSIGNED NOT NULL,
  desk_id   BIGINT UNSIGNED NOT NULL,
  created   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (human_id, desk_id),
  UNIQUE KEY idx_desk (desk_id),
  CONSTRAINT fk_human_desk_human FOREIGN KEY (human_id) REFERENCES human (id) ON DELETE CASCADE,
  CONSTRAINT fk_human_desk_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Directory groups mapped onto a mill roster: one roster per human (mill_human_roles replaces it). No row means viewer.
CREATE TABLE IF NOT EXISTS human_member (
  human_id  BIGINT UNSIGNED NOT NULL,
  name_id   BIGINT UNSIGNED NOT NULL,
  name_kind ENUM('desk','roster','label','tree','res') NOT NULL DEFAULT 'roster' CHECK (name_kind = 'roster'),   -- BETA: pins the name kind for fk_human_member_name
  created   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (human_id, name_id),
  KEY idx_role (name_id, name_kind, human_id),
  CONSTRAINT fk_human_member_human FOREIGN KEY (human_id) REFERENCES human (id) ON DELETE CASCADE,
  CONSTRAINT fk_human_member_name FOREIGN KEY (name_id, name_kind) REFERENCES name (id, type) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS mill_invite (
  key_id      VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  token_hash  CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  label       VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  created_by  VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT '',
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ttl_seconds INT NULL,
  expires_at  DATETIME(6) NULL,
  enabled_at  DATETIME(6) NULL,
  revoked_at  DATETIME(6) NULL,
  PRIMARY KEY (key_id),
  UNIQUE KEY idx_hash (token_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS mill_invite_join (
  key_id   VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  party    VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  party_id VARCHAR(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  created  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (key_id, party, party_id),
  CONSTRAINT fk_invite_join_key FOREIGN KEY (key_id) REFERENCES mill_invite (key_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Queue of async pushes waiting for a mill sync. The row is deleted when handed back.
-- kind=expired is the one line for rows the 7-day delete dropped (BETA, owner rule: main was 30 days). It does not age out.
CREATE TABLE IF NOT EXISTS push_queue (
  id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  desk_id  BIGINT UNSIGNED NOT NULL,
  kind     ENUM('hint','mail','receipt','expired') NOT NULL,
  payload  JSON NOT NULL,
  outcome  ENUM('sent','missed','error') NOT NULL,
  created  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_desk (desk_id, id),
  CONSTRAINT fk_push_queue_desk FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- BETA (lab: the glance over traces is 226 ms at M and 4.1 s at 10x history; cached 0.25 ms; RESULTS.md lines
-- 24-25, 52 and 57): the office glance, one row refreshed every 30 s (relaxed tier). No office-wide unread (owner rule).
CREATE TABLE IF NOT EXISTS glance_cache (
  id          TINYINT UNSIGNED NOT NULL DEFAULT 1,
  at          DATETIME(6) NOT NULL,
  refresh_us  INT UNSIGNED NOT NULL,
  present     INT UNSIGNED NOT NULL,
  held        INT UNSIGNED NOT NULL,
  open_n      INT UNSIGNED NOT NULL,
  claimed_n   INT UNSIGNED NOT NULL,
  parked_n    INT UNSIGNED NOT NULL,
  shipped_n   INT UNSIGNED NOT NULL,
  done_n      INT UNSIGNED NOT NULL,
  letters_1d  INT UNSIGNED NOT NULL,
  card_moves_1d INT UNSIGNED NOT NULL,
  doings_1d   INT UNSIGNED NOT NULL,
  holds_1d    INT UNSIGNED NOT NULL,
  points_1d   INT UNSIGNED NOT NULL,
  open_votes  INT UNSIGNED NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT ck_glance_cache_one CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- BETA (owner rule: SP version stamp, client warns or refuses on mismatch): one deploy of beta_sp.sql.
CREATE TABLE IF NOT EXISTS sp_deploy (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  version     CHAR(15) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  file        VARCHAR(200) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  by_user     VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL DEFAULT (CURRENT_USER()),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

DROP TRIGGER IF EXISTS activity_del_watchers;
DROP TRIGGER IF EXISTS todo_no_delete_in_tree;
DROP TRIGGER IF EXISTS mail_no_delete_in_tree;
DROP TRIGGER IF EXISTS hold_no_delete_in_tree;
DROP TRIGGER IF EXISTS hold_no_delete;
DROP TRIGGER IF EXISTS join_no_delete_in_tree;
DROP TRIGGER IF EXISTS doing_no_delete_in_tree;
DROP TRIGGER IF EXISTS score_no_delete_in_tree;
DROP TRIGGER IF EXISTS name_no_delete;
DROP TRIGGER IF EXISTS name_fixed;
DROP TRIGGER IF EXISTS vote_cast_open;
DROP TRIGGER IF EXISTS vote_cast_change;

DELIMITER //

CREATE TRIGGER activity_del_watchers AFTER DELETE ON activity
FOR EACH ROW
BEGIN
  IF OLD.type <> 'mail' THEN
    DELETE FROM watcher WHERE type = OLD.type AND id = OLD.id;
  END IF;
END //

CREATE TRIGGER todo_no_delete_in_tree BEFORE DELETE ON todo
FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM tree WHERE type = 'todo' AND id = OLD.id LIMIT 1) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'todo: still in tree (mill_tree_remove first)';
  END IF;
END //

CREATE TRIGGER mail_no_delete_in_tree BEFORE DELETE ON mail
FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM tree WHERE type = 'mail' AND id = OLD.id LIMIT 1) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'mail: still in tree (mill_tree_remove first)';
  END IF;
END //

-- #97: a hold row is release-only. mill_hold_delete nulls desk_id; DELETE FROM hold always fails.
-- (FK cascades do not fire triggers; this guards direct DELETE only.)
CREATE TRIGGER hold_no_delete BEFORE DELETE ON hold
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'hold: release only (mill_hold_delete); DELETE refused';
END //

CREATE TRIGGER doing_no_delete_in_tree BEFORE DELETE ON doing
FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM tree WHERE type = 'doing' AND id = OLD.id LIMIT 1) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'doing: still in tree (mill_tree_remove first)';
  END IF;
END //

CREATE TRIGGER score_no_delete_in_tree BEFORE DELETE ON score
FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM tree WHERE type = 'score' AND id = OLD.id LIMIT 1) THEN
    SIGNAL SQLSTATE '45000'
      SET MESSAGE_TEXT = 'score: still in tree (mill_tree_remove first)';
  END IF;
END //

-- A name row is never hard-deleted. Retire stamps name.deleted (sp_name_retire; main: mill_name_delete).
CREATE TRIGGER name_no_delete BEFORE DELETE ON name
FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000'
    SET MESSAGE_TEXT = 'name: retire only (sp_name_retire stamps deleted); DELETE refused';
END //

-- BETA (name restore): a name keeps its type and id, and a retired name is not renamed (reclaim first).
-- Clearing deleted is sp_name_reclaim's (Admin); the app user cannot UPDATE (EXECUTE-only).
CREATE TRIGGER name_fixed BEFORE UPDATE ON name
FOR EACH ROW
BEGIN
  IF NEW.type <> OLD.type OR NEW.id <> OLD.id THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name: type and id are fixed';
  END IF;
  IF OLD.deleted IS NOT NULL AND NEW.name <> OLD.name THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name retired: mill reclaim first';
  END IF;
END //

-- BETA (vote): a cast comes from a member of the vote's roster, on an open vote, before its deadline.
CREATE TRIGGER vote_cast_open BEFORE INSERT ON vote_cast
FOR EACH ROW
BEGIN
  IF NOT EXISTS (SELECT 1 FROM vote v JOIN member m ON m.name_id = v.roster_id AND m.desk_id = NEW.desk_id
                  WHERE v.id = NEW.vote_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: not a member of this roster';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM vote WHERE id = NEW.vote_id AND closed IS NULL AND deadline > NEW.created) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: closed';
  END IF;
END //
CREATE TRIGGER vote_cast_change BEFORE UPDATE ON vote_cast
FOR EACH ROW
BEGIN
  IF NEW.vote_id <> OLD.vote_id OR NEW.desk_id <> OLD.desk_id THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: voter and vote are fixed';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM vote WHERE id = NEW.vote_id AND closed IS NULL AND deadline > NEW.created) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: closed';
  END IF;
END //

DELIMITER ;
