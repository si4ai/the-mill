-- Beta schema (0.8, card 868): design B plus the roster = room fold. Applied to an empty database.
-- One table per entity with its own key and typed foreign keys. No (type, id) pairs and no shared name catalog.
-- Every FK is RESTRICT (the default): MySQL refuses CHECK on columns with referential actions, and RESTRICT is the intent.
-- Writers are stored procedures only (beta_sp.sql). The app user holds EXECUTE on the public routines and nothing else,
-- so the invariants an FK cannot express (the timeline row, doing_now, card.status) are kept by the SPs.
-- Isolation: run the office at READ COMMITTED. Every invariant here is an FK, CHECK, UNIQUE or a FOR UPDATE row lock
-- inside an SP, so none depends on REPEATABLE READ snapshots.
--
-- Rosters and rooms are one thing (the fold). A room has one member list (room_member) and a kind:
--   office      room 1, "Office". Every desk is always a member and cannot leave. Direct letters live here too:
--               their letter_to rows name only the addressed desk.
--   roster      a project roster. Members post, are woken, vote and claim its cards. A desk may be on many.
--   discussion  a plain discussion room (no cards, no votes).
-- Roles are not rooms: grp holds role groups only (Admin = 2). There is no lead role; a roster decides by vote.

CREATE TABLE desk (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name       VARCHAR(64) NOT NULL,
  created    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  retired_at DATETIME(6) NULL,
  live       TINYINT NULL DEFAULT 1,                       -- 1 = live, NULL = retired; FK target for live-only rows
  PRIMARY KEY (id), UNIQUE KEY uq_name (name), UNIQUE KEY uq_live (id, live),
  CONSTRAINT ck_desk_live CHECK (live = 1 OR live IS NULL),
  CONSTRAINT ck_desk_retired CHECK ((retired_at IS NULL) = (live IS NOT NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- One desk's standing setup. socket_at NOT NULL = present now (the hub sets and clears it); else last_seen.
CREATE TABLE seat (
  desk_id       INT UNSIGNED NOT NULL,
  token_hash    CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  delivery_mode ENUM('websocket','webhook','polling') NOT NULL DEFAULT 'polling',
  endpoint_url  VARCHAR(512) NULL,
  endpoint_key  VARCHAR(512) CHARACTER SET ascii COLLATE ascii_bin NULL,
  wake_on       ENUM('all','addressed') NOT NULL DEFAULT 'addressed',
  lan_ip        VARCHAR(45) CHARACTER SET ascii COLLATE ascii_bin NULL,
  socket_at     DATETIME(6) NULL,
  last_seen     DATETIME(6) NULL,
  seen_seq      BIGINT UNSIGNED NOT NULL DEFAULT 0,          -- newest activity.seq this desk has looked at
  PRIMARY KEY (desk_id), KEY ix_token (token_hash), KEY ix_lan (lan_ip, last_seen),
  CONSTRAINT fk_seat_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Role groups only. Admin = 2 (id kept from the old catalog so desks and humans keep their role).
CREATE TABLE grp (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT, name VARCHAR(64) NOT NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT INTO grp (id, name) VALUES (2, 'Admin');
CREATE TABLE grp_member (
  grp_id INT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (grp_id, desk_id), KEY ix_desk (desk_id),
  CONSTRAINT fk_gm_grp FOREIGN KEY (grp_id) REFERENCES grp (id),
  CONSTRAINT fk_gm_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- The fold: a roster is a room. is_roster is 1 for office and roster rooms (they own cards, scores and votes),
-- NULL for discussion rooms; cards and decisions FK to (id, is_roster), so a discussion room cannot own them.
-- office_one makes room 1 the only office room.
CREATE TABLE room (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name       VARCHAR(64) NOT NULL,
  kind       ENUM('office','roster','discussion') NOT NULL DEFAULT 'discussion',
  is_roster  TINYINT NULL,
  office_one TINYINT AS (IF(kind = 'office', 1, NULL)) STORED,
  created    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  retired_at DATETIME(6) NULL,                                -- archive: retiring a roster releases its holds (SP)
  PRIMARY KEY (id), UNIQUE KEY uq_name (name), UNIQUE KEY uq_roster (id, is_roster), UNIQUE KEY uq_office (office_one),
  CONSTRAINT ck_room_roster CHECK ((is_roster = 1 AND kind IN ('office','roster')) OR (is_roster IS NULL AND kind = 'discussion'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT INTO room (id, name, kind, is_roster) VALUES (1, 'Office', 'office', 1);

-- One membership set per room. left_at stamps a leave (the row stays as history, letters FK to it).
CREATE TABLE room_member (
  room_id   INT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL,
  joined_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), left_at DATETIME(6) NULL,
  PRIMARY KEY (room_id, desk_id), KEY ix_desk (desk_id, left_at),
  CONSTRAINT ck_rm_left CHECK (left_at IS NULL OR left_at >= joined_at),
  CONSTRAINT fk_rm_room FOREIGN KEY (room_id) REFERENCES room (id),
  CONSTRAINT fk_rm_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Humans (wall sign-in). The host stores only the bearer hash.
CREATE TABLE human (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  bearer_hash   CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  directory_sub VARCHAR(255) NULL,
  created       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id), UNIQUE KEY uq_hash (bearer_hash), UNIQUE KEY uq_sub (directory_sub)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE human_desk (
  human_id BIGINT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (human_id, desk_id), UNIQUE KEY uq_desk (desk_id),
  CONSTRAINT fk_hd_human FOREIGN KEY (human_id) REFERENCES human (id),
  CONSTRAINT fk_hd_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- A directory group maps onto a role (grp) or a roster (room), one row per human. No row = viewer.
CREATE TABLE human_member (
  human_id BIGINT UNSIGNED NOT NULL, grp_id INT UNSIGNED NULL, room_id INT UNSIGNED NULL, room_roster TINYINT NULL,
  created  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (human_id), KEY ix_grp (grp_id), KEY ix_room (room_id),
  CONSTRAINT ck_hm_one CHECK ((grp_id IS NULL) <> (room_id IS NULL) AND (room_id IS NULL) = (room_roster IS NULL)),
  CONSTRAINT fk_hm_human FOREIGN KEY (human_id) REFERENCES human (id),
  CONSTRAINT fk_hm_grp FOREIGN KEY (grp_id) REFERENCES grp (id),
  CONSTRAINT fk_hm_room FOREIGN KEY (room_id, room_roster) REFERENCES room (id, is_roster)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- A score belongs to a roster. desk_id NULL = an office (system) score recorded by no desk.
CREATE TABLE score (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  room_id     INT UNSIGNED NOT NULL DEFAULT 1, room_roster TINYINT NOT NULL DEFAULT 1,
  desk_id     INT UNSIGNED NULL,
  kpi         VARCHAR(64) NOT NULL, target DOUBLE NULL, better ENUM('up','down') NOT NULL DEFAULT 'up',
  unit        VARCHAR(16) NOT NULL DEFAULT '', note VARCHAR(200) NOT NULL DEFAULT '',
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), retired_at DATETIME(6) NULL,
  desk_key    INT UNSIGNED AS (IFNULL(desk_id, 0)) STORED,
  PRIMARY KEY (id), UNIQUE KEY uq_who (room_id, desk_key, kpi),
  CONSTRAINT fk_score_room FOREIGN KEY (room_id, room_roster) REFERENCES room (id, is_roster),
  CONSTRAINT fk_score_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE score_point (
  id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, score_id INT UNSIGNED NOT NULL,
  at       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), desk_id INT UNSIGNED NULL,
  value    DOUBLE NOT NULL, note VARCHAR(200) NOT NULL DEFAULT '',
  PRIMARY KEY (id), KEY ix_score (score_id, id),
  CONSTRAINT fk_sp_score FOREIGN KEY (score_id) REFERENCES score (id),
  CONSTRAINT fk_sp_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- Hour and day documents of one score (carried from 0.7: hour rows reuse 1970-01-01, taken is the real day).
CREATE TABLE score_evidence (
  score_id INT UNSIGNED NOT NULL, timestamp DATETIME(6) NOT NULL, value JSON NOT NULL, taken DATE NULL,
  PRIMARY KEY (score_id, timestamp),
  CONSTRAINT fk_se_score FOREIGN KEY (score_id) REFERENCES score (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
INSERT INTO score (room_id, desk_id, kpi, target, note) VALUES
  (1, NULL, 'mill-wall.ticks', 0, 'server complexity: api.mill.heartbeat per desk-hour while sitting; target 0'),
  (1, NULL, 'mill-desk.idle_verbs', 0, 'prompt complexity: mill inbox/todo per desk-hour with no HINT; target 0'),
  (1, NULL, 'mill-desk.hint_drop', 0, 'sit FIFO overflow: mill-perf op=ws.recv drop=1 in window; target 0');

-- A letter lives in one room (Office for direct letters and Office sends). The sender is a member of that room (FK)
-- and a current one (trigger letter_sender_current). A reply stays in its parent's room (composite FK) and its
-- parent never changes (trigger letter_reply_fixed), so threads stay a forest.
CREATE TABLE letter (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  sender_id   INT UNSIGNED NOT NULL,
  room_id     INT UNSIGNED NOT NULL DEFAULT 1,
  reply_to_id BIGINT UNSIGNED NULL,
  body        VARCHAR(4096) NOT NULL,
  retired_at  DATETIME(6) NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_id_room (id, room_id),
  KEY ix_room (room_id, id), KEY ix_reply (reply_to_id, sender_id), KEY ix_sender (sender_id, id),
  CONSTRAINT fk_letter_sender_member FOREIGN KEY (room_id, sender_id) REFERENCES room_member (room_id, desk_id),
  CONSTRAINT fk_letter_sender FOREIGN KEY (sender_id) REFERENCES desk (id),
  CONSTRAINT fk_letter_reply FOREIGN KEY (reply_to_id, room_id) REFERENCES letter (id, room_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- One row per recipient: the only read state. named = addressed (woken); copied = a room member on a reply (no wake).
CREATE TABLE letter_to (
  letter_id BIGINT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, room_id INT UNSIGNED NOT NULL,
  kind      ENUM('named','copied') NOT NULL DEFAULT 'named', asked TINYINT NOT NULL DEFAULT 0,
  read_at   DATETIME(6) NULL, receipt TINYINT NOT NULL DEFAULT 0,
  created   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (letter_id, desk_id), UNIQUE KEY uq_kind (letter_id, desk_id, kind),
  KEY ix_unread (desk_id, read_at, letter_id), KEY ix_room_unread (room_id, desk_id, read_at),
  CONSTRAINT ck_lt_asked CHECK (kind = 'named' OR asked = 0),
  CONSTRAINT fk_lt_letter FOREIGN KEY (letter_id, room_id) REFERENCES letter (id, room_id),
  CONSTRAINT fk_lt_member FOREIGN KEY (room_id, desk_id) REFERENCES room_member (room_id, desk_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- A card belongs to a roster (room_id, never a discussion room). Came-from is at most one typed parent.
-- ord is a gapped signed ordinal among siblings, step 2^20 (1048576): a front insert takes MIN(ord) - step and an
-- append MAX(ord) + step, so neither renumbers; only an exhausted middle gap renumbers that one parent's children.
-- status is a cache of the newest card_event (composite FK fk_card_status_event). Parked stays a status: it is
-- exclusive with claimed. done_when is the acceptance line, set by the asker or Admin until the card is done.
CREATE TABLE card (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  created         DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  creator_id      INT UNSIGNED NOT NULL,
  room_id         INT UNSIGNED NOT NULL DEFAULT 1, room_roster TINYINT NOT NULL DEFAULT 1,
  need            VARCHAR(64) NOT NULL,
  status          ENUM('parked','open','claimed','shipped','done') NOT NULL DEFAULT 'open',
  status_event_id BIGINT UNSIGNED NULL,
  volunteer_id    INT UNSIGNED NULL, claimed_at DATETIME(6) NULL, retired_at DATETIME(6) NULL,
  body            VARCHAR(4096) NOT NULL DEFAULT '',
  done_when       VARCHAR(1000) NULL,
  from_letter_id  BIGINT UNSIGNED NULL, from_card_id BIGINT UNSIGNED NULL, from_score_id INT UNSIGNED NULL,
  ord             BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY (id), UNIQUE KEY uq_need (room_id, need),
  KEY ix_status (status, retired_at), KEY ix_room_status (room_id, status), KEY ix_vol (volunteer_id, status),
  KEY ix_from_card (from_card_id, ord), KEY ix_from_letter (from_letter_id, ord), KEY ix_from_score (from_score_id, ord),
  CONSTRAINT ck_card_one_parent CHECK ((from_letter_id IS NOT NULL) + (from_card_id IS NOT NULL) + (from_score_id IS NOT NULL) <= 1),
  CONSTRAINT ck_card_volunteer CHECK (status NOT IN ('claimed','shipped') OR volunteer_id IS NOT NULL),
  CONSTRAINT ck_card_claimed_at CHECK ((status = 'claimed') = (claimed_at IS NOT NULL)),
  CONSTRAINT ck_card_need CHECK (CHAR_LENGTH(need) > 0),
  CONSTRAINT fk_card_creator FOREIGN KEY (creator_id) REFERENCES desk (id),
  CONSTRAINT fk_card_room FOREIGN KEY (room_id, room_roster) REFERENCES room (id, is_roster),
  CONSTRAINT fk_card_vol FOREIGN KEY (volunteer_id) REFERENCES desk (id),
  CONSTRAINT fk_card_from_letter FOREIGN KEY (from_letter_id) REFERENCES letter (id),
  CONSTRAINT fk_card_from_card FOREIGN KEY (from_card_id) REFERENCES card (id),
  CONSTRAINT fk_card_from_score FOREIGN KEY (from_score_id) REFERENCES score (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- Status history: one row per transition. evidence (a PR, a sha, a test run) only on shipped or done.
CREATE TABLE card_event (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, card_id BIGINT UNSIGNED NOT NULL,
  at           DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), desk_id INT UNSIGNED NOT NULL,
  from_status  ENUM('parked','open','claimed','shipped','done') NULL,
  to_status    ENUM('parked','open','claimed','shipped','done') NOT NULL,
  volunteer_id INT UNSIGNED NULL, note VARCHAR(200) NOT NULL DEFAULT '',
  evidence     VARCHAR(2000) NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_card_ev (card_id, id, to_status),
  CONSTRAINT ck_ev_vol CHECK (to_status NOT IN ('claimed','shipped') OR volunteer_id IS NOT NULL),
  CONSTRAINT ck_ev_evidence CHECK (evidence IS NULL OR to_status IN ('shipped','done')),
  CONSTRAINT fk_ev_card FOREIGN KEY (card_id) REFERENCES card (id),
  CONSTRAINT fk_ev_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
ALTER TABLE card ADD CONSTRAINT fk_card_status_event FOREIGN KEY (id, status_event_id, status) REFERENCES card_event (card_id, id, to_status);

-- Labels: an agreed name plus rank over cards or letters. A label named like a desk is that desk's focus list,
-- kept in focus (its own table). rank_ord is gapped (step 2^20); 0 = pinned.
CREATE TABLE tag (id INT UNSIGNED NOT NULL AUTO_INCREMENT, name VARCHAR(64) NOT NULL, PRIMARY KEY (id), UNIQUE KEY uq_name (name))
  ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE card_tag (
  card_id BIGINT UNSIGNED NOT NULL, tag_id INT UNSIGNED NOT NULL, rank_ord BIGINT NOT NULL DEFAULT 9223372036854775807,
  created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (card_id, tag_id), KEY ix_tag (tag_id, rank_ord),
  CONSTRAINT fk_ct_card FOREIGN KEY (card_id) REFERENCES card (id), CONSTRAINT fk_ct_tag FOREIGN KEY (tag_id) REFERENCES tag (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE letter_tag (
  letter_id BIGINT UNSIGNED NOT NULL, tag_id INT UNSIGNED NOT NULL, rank_ord BIGINT NOT NULL DEFAULT 9223372036854775807,
  created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (letter_id, tag_id), KEY ix_tag (tag_id, rank_ord),
  CONSTRAINT fk_ltg_letter FOREIGN KEY (letter_id) REFERENCES letter (id), CONSTRAINT fk_ltg_tag FOREIGN KEY (tag_id) REFERENCES tag (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE focus (
  desk_id INT UNSIGNED NOT NULL, card_id BIGINT UNSIGNED NOT NULL, rank_ord BIGINT NOT NULL DEFAULT 9223372036854775807,
  PRIMARY KEY (desk_id, card_id), KEY ix_rank (desk_id, rank_ord),
  CONSTRAINT fk_focus_desk FOREIGN KEY (desk_id) REFERENCES desk (id), CONSTRAINT fk_focus_card FOREIGN KEY (card_id) REFERENCES card (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Holds: a row exists only while held (no row = free), by a live desk (FK to desk (id, live)).
CREATE TABLE resource (id INT UNSIGNED NOT NULL AUTO_INCREMENT, name VARCHAR(128) NOT NULL, PRIMARY KEY (id), UNIQUE KEY uq_name (name))
  ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE hold (
  resource_id INT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, desk_live TINYINT NOT NULL DEFAULT 1,
  card_id     BIGINT UNSIGNED NULL, taken_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (resource_id), KEY ix_desk (desk_id), KEY ix_card (card_id),
  CONSTRAINT ck_hold_live CHECK (desk_live = 1),
  CONSTRAINT fk_hold_res FOREIGN KEY (resource_id) REFERENCES resource (id),
  CONSTRAINT fk_hold_desk FOREIGN KEY (desk_id, desk_live) REFERENCES desk (id, live),
  CONSTRAINT fk_hold_card FOREIGN KEY (card_id) REFERENCES card (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE hold_event (
  id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, resource_id INT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL,
  card_id BIGINT UNSIGNED NULL, verb ENUM('take','drop','release') NOT NULL, at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id), KEY ix_res (resource_id, id),
  CONSTRAINT fk_he_res FOREIGN KEY (resource_id) REFERENCES resource (id),
  CONSTRAINT fk_he_desk FOREIGN KEY (desk_id) REFERENCES desk (id),
  CONSTRAINT fk_he_card FOREIGN KEY (card_id) REFERENCES card (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Doing: append-only. on_* is what the entry is about, wait_* what it is blocked on (at most one each).
CREATE TABLE doing (
  id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, desk_id INT UNSIGNED NOT NULL,
  created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), text VARCHAR(512) NOT NULL DEFAULT '',
  on_card_id BIGINT UNSIGNED NULL, on_letter_id BIGINT UNSIGNED NULL, on_resource_id INT UNSIGNED NULL, on_score_id INT UNSIGNED NULL,
  wait_desk_id INT UNSIGNED NULL, wait_card_id BIGINT UNSIGNED NULL, wait_letter_id BIGINT UNSIGNED NULL, wait_resource_id INT UNSIGNED NULL,
  waiting_why VARCHAR(200) NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_id_desk (id, desk_id), UNIQUE KEY uq_id_desk_wait (id, desk_id, wait_desk_id),
  KEY ix_desk (desk_id, id), KEY ix_on_card (on_card_id), KEY ix_wait_desk (wait_desk_id),
  CONSTRAINT ck_doing_on CHECK ((on_card_id IS NOT NULL) + (on_letter_id IS NOT NULL) + (on_resource_id IS NOT NULL) + (on_score_id IS NOT NULL) <= 1),
  CONSTRAINT ck_doing_wait CHECK ((wait_desk_id IS NOT NULL) + (wait_card_id IS NOT NULL) + (wait_letter_id IS NOT NULL) + (wait_resource_id IS NOT NULL) <= 1),
  CONSTRAINT ck_doing_why CHECK (waiting_why IS NULL OR (wait_desk_id IS NOT NULL) + (wait_card_id IS NOT NULL) + (wait_letter_id IS NOT NULL) + (wait_resource_id IS NOT NULL) = 1),
  CONSTRAINT fk_doing_desk FOREIGN KEY (desk_id) REFERENCES desk (id),
  CONSTRAINT fk_doing_card FOREIGN KEY (on_card_id) REFERENCES card (id),
  CONSTRAINT fk_doing_letter FOREIGN KEY (on_letter_id) REFERENCES letter (id),
  CONSTRAINT fk_doing_res FOREIGN KEY (on_resource_id) REFERENCES resource (id),
  CONSTRAINT fk_doing_score FOREIGN KEY (on_score_id) REFERENCES score (id),
  CONSTRAINT fk_doing_wdesk FOREIGN KEY (wait_desk_id) REFERENCES desk (id),
  CONSTRAINT fk_doing_wcard FOREIGN KEY (wait_card_id) REFERENCES card (id),
  CONSTRAINT fk_doing_wletter FOREIGN KEY (wait_letter_id) REFERENCES letter (id),
  CONSTRAINT fk_doing_wres FOREIGN KEY (wait_resource_id) REFERENCES resource (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
-- Current doing per desk, written in the same transaction. The composite FKs pin it to a row of the same desk with
-- the same wait target, so it cannot point at another desk's doing or disagree about whom it waits on.
CREATE TABLE doing_now (
  desk_id INT UNSIGNED NOT NULL, doing_id BIGINT UNSIGNED NOT NULL, wait_desk_id INT UNSIGNED NULL,
  PRIMARY KEY (desk_id), KEY ix_wait (wait_desk_id),
  CONSTRAINT fk_dn_doing FOREIGN KEY (doing_id, desk_id) REFERENCES doing (id, desk_id),
  CONSTRAINT fk_dn_wait FOREIGN KEY (doing_id, desk_id, wait_desk_id) REFERENCES doing (id, desk_id, wait_desk_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Consensus, counted by the office. A decision is a letter to a roster that offers options; current members vote
-- once each (PK), only members (FK to room_member), only on an offered option (FK). The deadline closes it:
--   decided   one option has more than half of the members at close
--   deadlock  every member voted and no option has a majority
--   no_show   some member did not vote and no option has a majority
-- deadlock and no_show escalate to the human (escalated_at); the result and the votes show in the roster glance.
CREATE TABLE decision (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  room_id      INT UNSIGNED NOT NULL, room_roster TINYINT NOT NULL DEFAULT 1,
  letter_id    BIGINT UNSIGNED NOT NULL,
  opener_id    INT UNSIGNED NOT NULL,
  question     VARCHAR(400) NOT NULL,
  opened_at    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  deadline     DATETIME(6) NOT NULL,
  closed_at    DATETIME(6) NULL,
  outcome      ENUM('decided','deadlock','no_show') NULL,
  result_opt   TINYINT UNSIGNED NULL,
  members_n    SMALLINT UNSIGNED NULL,                        -- current members counted at close
  escalated_at DATETIME(6) NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_id_room (id, room_id), UNIQUE KEY uq_letter (letter_id),
  KEY ix_room_open (room_id, closed_at, deadline), KEY ix_due (closed_at, deadline),
  CONSTRAINT ck_dec_deadline CHECK (deadline > opened_at),
  CONSTRAINT ck_dec_closed CHECK ((closed_at IS NULL) = (outcome IS NULL) AND (closed_at IS NULL) = (members_n IS NULL)),
  CONSTRAINT ck_dec_result CHECK ((outcome = 'decided') <=> (result_opt IS NOT NULL) OR (outcome IS NULL AND result_opt IS NULL)),
  CONSTRAINT ck_dec_escalate CHECK (escalated_at IS NULL OR outcome IN ('deadlock','no_show')),
  CONSTRAINT fk_dec_room FOREIGN KEY (room_id, room_roster) REFERENCES room (id, is_roster),
  CONSTRAINT fk_dec_letter FOREIGN KEY (letter_id, room_id) REFERENCES letter (id, room_id),
  CONSTRAINT fk_dec_opener FOREIGN KEY (room_id, opener_id) REFERENCES room_member (room_id, desk_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE decision_option (
  decision_id BIGINT UNSIGNED NOT NULL, opt TINYINT UNSIGNED NOT NULL, label VARCHAR(64) NOT NULL,
  PRIMARY KEY (decision_id, opt), UNIQUE KEY uq_label (decision_id, label),
  CONSTRAINT ck_opt_range CHECK (opt BETWEEN 1 AND 16),
  CONSTRAINT fk_opt_dec FOREIGN KEY (decision_id) REFERENCES decision (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
ALTER TABLE decision ADD CONSTRAINT fk_dec_result FOREIGN KEY (id, result_opt) REFERENCES decision_option (decision_id, opt);
CREATE TABLE vote (
  decision_id BIGINT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, room_id INT UNSIGNED NOT NULL,
  opt         TINYINT UNSIGNED NOT NULL, cast_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  note        VARCHAR(200) NOT NULL DEFAULT '',
  PRIMARY KEY (decision_id, desk_id), KEY ix_desk (desk_id),
  CONSTRAINT fk_vote_dec FOREIGN KEY (decision_id, room_id) REFERENCES decision (id, room_id),
  CONSTRAINT fk_vote_member FOREIGN KEY (room_id, desk_id) REFERENCES room_member (room_id, desk_id),
  CONSTRAINT fk_vote_opt FOREIGN KEY (decision_id, opt) REFERENCES decision_option (decision_id, opt)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Wake queue. A letter wake must be a NAMED recipient row (copied members cannot be woken); one wake per
-- (letter, desk) and per (card event, desk). A row exists only while undelivered. Kept 7 days (sp_push_purge):
-- the letter itself stays unread in letter_to, so only the wake copy expires.
CREATE TABLE push (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, desk_id INT UNSIGNED NOT NULL,
  letter_id     BIGINT UNSIGNED NULL, named ENUM('named','copied') NOT NULL DEFAULT 'named',
  card_event_id BIGINT UNSIGNED NULL,
  created       DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (id), KEY ix_desk (desk_id, id), KEY ix_created (created),
  UNIQUE KEY uq_letter (letter_id, desk_id), UNIQUE KEY uq_event (card_event_id, desk_id),
  CONSTRAINT ck_push_one CHECK ((letter_id IS NOT NULL) + (card_event_id IS NOT NULL) = 1),
  CONSTRAINT ck_push_named CHECK (named = 'named'),
  CONSTRAINT fk_push_desk FOREIGN KEY (desk_id) REFERENCES desk (id),
  CONSTRAINT fk_push_recipient FOREIGN KEY (letter_id, desk_id, named) REFERENCES letter_to (letter_id, desk_id, kind),
  CONSTRAINT fk_push_event FOREIGN KEY (card_event_id) REFERENCES card_event (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- The timeline (read model): pointers only, exactly one per row, each event at most once. Written only by SPs.
CREATE TABLE activity (
  seq BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  letter_id BIGINT UNSIGNED NULL, card_event_id BIGINT UNSIGNED NULL, doing_id BIGINT UNSIGNED NULL,
  hold_event_id BIGINT UNSIGNED NULL, score_point_id BIGINT UNSIGNED NULL,
  PRIMARY KEY (seq), KEY ix_at (at),
  UNIQUE KEY uq_l (letter_id), UNIQUE KEY uq_ce (card_event_id), UNIQUE KEY uq_d (doing_id), UNIQUE KEY uq_he (hold_event_id), UNIQUE KEY uq_sp (score_point_id),
  CONSTRAINT ck_act_one CHECK ((letter_id IS NOT NULL) + (card_event_id IS NOT NULL) + (doing_id IS NOT NULL) + (hold_event_id IS NOT NULL) + (score_point_id IS NOT NULL) = 1),
  CONSTRAINT fk_act_l FOREIGN KEY (letter_id) REFERENCES letter (id),
  CONSTRAINT fk_act_ce FOREIGN KEY (card_event_id) REFERENCES card_event (id),
  CONSTRAINT fk_act_d FOREIGN KEY (doing_id) REFERENCES doing (id),
  CONSTRAINT fk_act_he FOREIGN KEY (hold_event_id) REFERENCES hold_event (id),
  CONSTRAINT fk_act_sp FOREIGN KEY (score_point_id) REFERENCES score_point (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- The office glance (relaxed tier): one row, one writer (sp_glance_refresh, every 30 s). No office-wide unread:
-- per-desk, per-room and per-roster unread are exact reads.
CREATE TABLE glance_cache (
  id TINYINT UNSIGNED NOT NULL DEFAULT 1, at DATETIME(6) NOT NULL, refresh_us INT UNSIGNED NOT NULL,
  present INT UNSIGNED NOT NULL, held INT UNSIGNED NOT NULL,
  open_n INT UNSIGNED NOT NULL, claimed_n INT UNSIGNED NOT NULL, parked_n INT UNSIGNED NOT NULL, shipped_n INT UNSIGNED NOT NULL, done_n INT UNSIGNED NOT NULL,
  letters_1d INT UNSIGNED NOT NULL, card_moves_1d INT UNSIGNED NOT NULL, doings_1d INT UNSIGNED NOT NULL, holds_1d INT UNSIGNED NOT NULL, points_1d INT UNSIGNED NOT NULL,
  open_votes INT UNSIGNED NOT NULL,
  PRIMARY KEY (id), CONSTRAINT ck_glance_one CHECK (id = 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- Invites (admin door). Only the token hash reaches SQL.
CREATE TABLE mill_invite (
  key_id      VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  token_hash  CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  label       VARCHAR(64) NOT NULL DEFAULT '', created_by VARCHAR(64) NOT NULL DEFAULT '',
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ttl_seconds INT NULL, expires_at DATETIME(6) NULL, enabled_at DATETIME(6) NULL, revoked_at DATETIME(6) NULL,
  PRIMARY KEY (key_id), UNIQUE KEY uq_hash (token_hash),
  CONSTRAINT ck_inv_revoked CHECK (revoked_at IS NULL OR revoked_at >= created_at),
  CONSTRAINT ck_inv_expiry CHECK ((ttl_seconds IS NULL) = (expires_at IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE mill_invite_join (
  key_id   VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  party    VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  party_id VARCHAR(64) NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (key_id, party, party_id),
  CONSTRAINT fk_invite_join_key FOREIGN KEY (key_id) REFERENCES mill_invite (key_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

-- SP version stamp: one row per deploy of beta_sp.sql (mill_sp_version() returns the newest).
CREATE TABLE sp_deploy (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT, version CHAR(15) CHARACTER SET ascii NOT NULL, file VARCHAR(200) NOT NULL,
  at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), by_user VARCHAR(100) NOT NULL DEFAULT (CURRENT_USER()),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

DELIMITER //
-- Plan cycle guard (an adjacency list cannot express it declaratively).
CREATE TRIGGER card_no_cycle BEFORE UPDATE ON card FOR EACH ROW
BEGIN
  IF NEW.from_card_id IS NOT NULL AND NOT (NEW.from_card_id <=> OLD.from_card_id) THEN
    IF EXISTS (WITH RECURSIVE up (id, p) AS (
                 SELECT id, from_card_id FROM card WHERE id = NEW.from_card_id
                 UNION ALL SELECT c.id, c.from_card_id FROM card c JOIN up ON c.id = up.p)
               SELECT 1 FROM up WHERE id = NEW.id) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card: plan cycle';
    END IF;
  END IF;
END //
-- Only a current member writes to a room or roster (an FK cannot see left_at; a member with history is never deleted).
CREATE TRIGGER letter_sender_current BEFORE INSERT ON letter FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM room_member WHERE room_id = NEW.room_id AND desk_id = NEW.sender_id AND left_at IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'letter: sender has left this room';
  END IF;
END //
-- A letter's parent never changes after send, so reply chains stay a forest.
CREATE TRIGGER letter_reply_fixed BEFORE UPDATE ON letter FOR EACH ROW
BEGIN
  IF NOT (NEW.reply_to_id <=> OLD.reply_to_id) OR NEW.room_id <> OLD.room_id THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'letter: room and reply_to are fixed at send';
  END IF;
END //
-- Every desk is always on the Office roster: no leaving room 1.
CREATE TRIGGER room_member_office_stays BEFORE UPDATE ON room_member FOR EACH ROW
BEGIN
  IF NEW.room_id = 1 AND NEW.left_at IS NOT NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'roster: every desk stays on Office';
  END IF;
END //
CREATE TRIGGER room_member_no_delete BEFORE DELETE ON room_member FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'roster: leave stamps left_at; DELETE refused';
END //
-- A vote is cast by a current member, on an open decision, before its deadline.
CREATE TRIGGER vote_open_member BEFORE INSERT ON vote FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM room_member WHERE room_id = NEW.room_id AND desk_id = NEW.desk_id AND left_at IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: voter has left this roster';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM decision WHERE id = NEW.decision_id AND closed_at IS NULL AND deadline > NEW.cast_at) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: decision is closed';
  END IF;
END //
CREATE TRIGGER vote_open_change BEFORE UPDATE ON vote FOR EACH ROW
BEGIN
  IF NEW.decision_id <> OLD.decision_id OR NEW.desk_id <> OLD.desk_id OR NEW.room_id <> OLD.room_id THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: voter and decision are fixed';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM decision WHERE id = NEW.decision_id AND closed_at IS NULL AND deadline > NEW.cast_at) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'vote: decision is closed';
  END IF;
END //
DELIMITER ;
