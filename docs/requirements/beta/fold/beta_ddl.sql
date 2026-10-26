-- the-mill beta book: one table per entity, typed foreign keys, no (type, id) pairs and no shared name catalog.
-- Not in apply_order.txt: the 0.7 book is untouched. agent_coord/install/beta_migrate.py installs this file into
-- its own database (fresh, or copied from a 0.7 book by beta_migrate.sql) together with beta_sp.sql.
-- Rules: every FK is RESTRICT. Every write goes through a routine in beta_sp.sql (the app user holds EXECUTE only).
-- Run the office at READ COMMITTED; no invariant here depends on a repeatable-read snapshot.

-- Desk ids start at 3: 1 and 2 are the Office and Admin names in a 0.7 book, and a rollback keeps desk ids.
CREATE TABLE desk (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name       VARCHAR(64) NOT NULL,
  created    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  retired_at DATETIME(6) NULL,
  live       TINYINT NULL DEFAULT 1,           -- 1 = live, NULL = retired: the FK target for rows only a live desk may own
  PRIMARY KEY (id), UNIQUE KEY uq_name (name), UNIQUE KEY uq_live (id, live),
  CONSTRAINT ck_desk_live CHECK (live = 1 OR live IS NULL),
  CONSTRAINT ck_desk_retired CHECK ((retired_at IS NULL) = (live IS NOT NULL))
) AUTO_INCREMENT = 3;

-- Presence: socket_at NOT NULL = connected now; else last_seen.
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
  seen_seq      BIGINT UNSIGNED NOT NULL DEFAULT 0,   -- newest activity.seq this desk has looked at
  PRIMARY KEY (desk_id), UNIQUE KEY uq_token (token_hash),
  CONSTRAINT fk_seat_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
);

-- Roles grant powers, not membership of a conversation. Admin is role 2 (the 0.7 name id). There is no lead role.
CREATE TABLE role (
  id INT UNSIGNED NOT NULL, name VARCHAR(64) NOT NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_name (name)
);
CREATE TABLE role_member (
  role_id INT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (role_id, desk_id), KEY ix_desk (desk_id),
  CONSTRAINT fk_rlm_role FOREIGN KEY (role_id) REFERENCES role (id),
  CONSTRAINT fk_rlm_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
);

-- A roster IS its room: one membership set (room_member). kind 'roster' = a project roster; kind 'room' = a plain
-- discussion room, optionally inside a roster (roster_id). Room 1 is the Office roster: every desk is on it, always
-- (desk_on_office adds the row, office_member_stays refuses leaving). A desk may be on many rosters.
CREATE TABLE room (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  kind        ENUM('roster','room') NOT NULL,
  name        VARCHAR(64) NOT NULL,
  roster_id   INT UNSIGNED NULL,
  roster_kind ENUM('roster') NULL,                   -- 'roster' whenever roster_id is set: makes the FK below hit a roster
  created     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  retired_at  DATETIME(6) NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_kind_name (kind, name), UNIQUE KEY uq_id_kind (id, kind), KEY ix_roster (roster_id),
  CONSTRAINT ck_room_roster CHECK ((roster_id IS NULL) = (roster_kind IS NULL) AND (kind = 'room' OR roster_id IS NULL)),
  CONSTRAINT fk_room_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES room (id, kind)
);
CREATE TABLE room_member (
  room_id INT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL,
  joined_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), left_at DATETIME(6) NULL,
  PRIMARY KEY (room_id, desk_id), KEY ix_desk (desk_id, room_id),
  CONSTRAINT ck_rm_office CHECK (room_id <> 1 OR left_at IS NULL),
  CONSTRAINT fk_rm_room FOREIGN KEY (room_id) REFERENCES room (id),
  CONSTRAINT fk_rm_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
);

CREATE TABLE score (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT, desk_id INT UNSIGNED NULL,          -- NULL: the roster's own score (system KPIs)
  roster_id INT UNSIGNED NOT NULL, roster_kind ENUM('roster') NOT NULL DEFAULT 'roster',
  owner_key INT UNSIGNED AS (IFNULL(desk_id, 0)) STORED,
  kpi VARCHAR(64) NOT NULL, target DOUBLE NULL, better ENUM('up','down') NOT NULL DEFAULT 'up',
  unit VARCHAR(16) NOT NULL DEFAULT '', note VARCHAR(200) NOT NULL DEFAULT '',
  created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), retired_at DATETIME(6) NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_who (roster_id, owner_key, kpi),
  CONSTRAINT fk_score_desk FOREIGN KEY (desk_id) REFERENCES desk (id),
  CONSTRAINT fk_score_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES room (id, kind)
);
CREATE TABLE score_point (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, score_id INT UNSIGNED NOT NULL, at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  desk_id INT UNSIGNED NOT NULL, value DOUBLE NOT NULL, note VARCHAR(200) NOT NULL DEFAULT '',
  PRIMARY KEY (id), KEY ix_score (score_id, id),
  CONSTRAINT fk_sp_score FOREIGN KEY (score_id) REFERENCES score (id),
  CONSTRAINT fk_sp_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
);
CREATE TABLE score_evidence (
  score_id INT UNSIGNED NOT NULL, at DATETIME(6) NOT NULL, value JSON NOT NULL, taken DATE NULL,
  PRIMARY KEY (score_id, at),
  CONSTRAINT fk_se_score FOREIGN KEY (score_id) REFERENCES score (id)
);

-- A letter lives in one room (a roster, the Office, or a discussion room); its sender is a member of that room and a
-- reply stays in its parent's room. The parent never changes after send (letter_reply_fixed), so threads are a forest.
CREATE TABLE letter (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  sender_id INT UNSIGNED NOT NULL, room_id INT UNSIGNED NOT NULL DEFAULT 1, reply_to_id BIGINT UNSIGNED NULL,
  body VARCHAR(4096) NOT NULL, retired_at DATETIME(6) NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_id_room (id, room_id),
  KEY ix_room (room_id, id), KEY ix_reply (reply_to_id), KEY ix_sender (sender_id, id),
  CONSTRAINT fk_letter_sender FOREIGN KEY (sender_id) REFERENCES desk (id),
  CONSTRAINT fk_letter_sender_member FOREIGN KEY (room_id, sender_id) REFERENCES room_member (room_id, desk_id),
  CONSTRAINT fk_letter_reply FOREIGN KEY (reply_to_id, room_id) REFERENCES letter (id, room_id)
);

-- One row per recipient, the only read state. named = addressed (may be woken); copied = reached as a room member.
CREATE TABLE letter_to (
  letter_id BIGINT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, room_id INT UNSIGNED NOT NULL,
  kind ENUM('named','copied') NOT NULL DEFAULT 'named', asked TINYINT NOT NULL DEFAULT 0,
  read_at DATETIME(6) NULL, receipt TINYINT NOT NULL DEFAULT 0,
  PRIMARY KEY (letter_id, desk_id), UNIQUE KEY uq_kind (letter_id, desk_id, kind),
  KEY ix_unread (desk_id, read_at, letter_id),
  CONSTRAINT ck_lt_asked CHECK (kind = 'named' OR asked = 0),
  CONSTRAINT fk_lt_letter FOREIGN KEY (letter_id, room_id) REFERENCES letter (id, room_id),
  CONSTRAINT fk_lt_member FOREIGN KEY (room_id, desk_id) REFERENCES room_member (room_id, desk_id)
);

-- Cards. status is a cache of the newest card_event (composite FK fk_card_status_event). Came-from: at most one parent.
-- ord: signed gapped ordinal among siblings, step 2^20. Front and back inserts never renumber.
CREATE TABLE card (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  creator_id INT UNSIGNED NOT NULL,
  roster_id INT UNSIGNED NOT NULL DEFAULT 1, roster_kind ENUM('roster') NOT NULL DEFAULT 'roster',
  status ENUM('parked','open','claimed','shipped','done') NOT NULL DEFAULT 'open',
  status_event_id BIGINT UNSIGNED NULL,
  volunteer_id INT UNSIGNED NULL, claimed_at DATETIME(6) NULL, retired_at DATETIME(6) NULL,
  body VARCHAR(4096) NOT NULL DEFAULT '',
  done_when VARCHAR(1000) NULL,                      -- acceptance: what makes this card done (the asker sets it)
  from_letter_id BIGINT UNSIGNED NULL, from_card_id BIGINT UNSIGNED NULL, from_score_id INT UNSIGNED NULL,
  ord BIGINT NOT NULL DEFAULT 0,
  PRIMARY KEY (id), KEY ix_status (status, retired_at), KEY ix_vol (volunteer_id, status), KEY ix_roster (roster_id, status),
  KEY ix_from_card (from_card_id, ord), KEY ix_from_letter (from_letter_id), KEY ix_from_score (from_score_id),
  CONSTRAINT ck_card_one_parent CHECK ((from_letter_id IS NOT NULL) + (from_card_id IS NOT NULL) + (from_score_id IS NOT NULL) <= 1),
  CONSTRAINT ck_card_volunteer CHECK (status NOT IN ('claimed','shipped') OR volunteer_id IS NOT NULL),
  CONSTRAINT ck_card_claimed_at CHECK ((status = 'claimed') = (claimed_at IS NOT NULL)),
  CONSTRAINT fk_card_creator FOREIGN KEY (creator_id) REFERENCES desk (id),
  CONSTRAINT fk_card_roster FOREIGN KEY (roster_id, roster_kind) REFERENCES room (id, kind),
  CONSTRAINT fk_card_vol FOREIGN KEY (volunteer_id) REFERENCES desk (id),
  CONSTRAINT fk_card_from_letter FOREIGN KEY (from_letter_id) REFERENCES letter (id),
  CONSTRAINT fk_card_from_card FOREIGN KEY (from_card_id) REFERENCES card (id),
  CONSTRAINT fk_card_from_score FOREIGN KEY (from_score_id) REFERENCES score (id)
);
CREATE TABLE card_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, card_id BIGINT UNSIGNED NOT NULL,
  at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), desk_id INT UNSIGNED NOT NULL,
  from_status ENUM('parked','open','claimed','shipped','done') NULL,
  to_status ENUM('parked','open','claimed','shipped','done') NOT NULL,
  volunteer_id INT UNSIGNED NULL, note VARCHAR(200) NOT NULL DEFAULT '',
  evidence VARCHAR(2000) NULL,                       -- a pass may carry evidence (a PR, a commit, a test run)
  PRIMARY KEY (id), UNIQUE KEY uq_card_ev (card_id, id, to_status), KEY ix_at (at),
  CONSTRAINT ck_ev_vol CHECK (to_status NOT IN ('claimed','shipped') OR volunteer_id IS NOT NULL),
  CONSTRAINT ck_ev_evidence CHECK (evidence IS NULL OR to_status IN ('shipped','done')),
  CONSTRAINT fk_ev_card FOREIGN KEY (card_id) REFERENCES card (id),
  CONSTRAINT fk_ev_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
);
ALTER TABLE card ADD CONSTRAINT fk_card_status_event FOREIGN KEY (id, status_event_id, status) REFERENCES card_event (card_id, id, to_status);

CREATE TABLE tag (id INT UNSIGNED NOT NULL AUTO_INCREMENT, name VARCHAR(64) NOT NULL, PRIMARY KEY (id), UNIQUE KEY uq (name));
CREATE TABLE card_tag (card_id BIGINT UNSIGNED NOT NULL, tag_id INT UNSIGNED NOT NULL, PRIMARY KEY (card_id, tag_id), KEY ix_tag (tag_id),
  CONSTRAINT fk_ct_card FOREIGN KEY (card_id) REFERENCES card (id), CONSTRAINT fk_ct_tag FOREIGN KEY (tag_id) REFERENCES tag (id));
CREATE TABLE letter_tag (letter_id BIGINT UNSIGNED NOT NULL, tag_id INT UNSIGNED NOT NULL, PRIMARY KEY (letter_id, tag_id), KEY ix_tag (tag_id),
  CONSTRAINT fk_ltg_letter FOREIGN KEY (letter_id) REFERENCES letter (id), CONSTRAINT fk_ltg_tag FOREIGN KEY (tag_id) REFERENCES tag (id));
-- A desk's ranked cards (signed gapped ordinal, step 2^20).
CREATE TABLE focus (desk_id INT UNSIGNED NOT NULL, card_id BIGINT UNSIGNED NOT NULL, rank_ord BIGINT NOT NULL,
  PRIMARY KEY (desk_id, card_id), KEY ix_rank (desk_id, rank_ord),
  CONSTRAINT fk_focus_desk FOREIGN KEY (desk_id) REFERENCES desk (id), CONSTRAINT fk_focus_card FOREIGN KEY (card_id) REFERENCES card (id));

CREATE TABLE resource (id INT UNSIGNED NOT NULL AUTO_INCREMENT, name VARCHAR(128) NOT NULL, PRIMARY KEY (id), UNIQUE KEY uq (name));
-- A row exists iff the resource is held, by a live desk (FK to desk(id, live)).
CREATE TABLE hold (
  resource_id INT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, desk_live TINYINT NOT NULL DEFAULT 1,
  card_id BIGINT UNSIGNED NULL, taken_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (resource_id), KEY ix_desk (desk_id),
  CONSTRAINT ck_hold_live CHECK (desk_live = 1),
  CONSTRAINT fk_hold_res FOREIGN KEY (resource_id) REFERENCES resource (id),
  CONSTRAINT fk_hold_desk FOREIGN KEY (desk_id, desk_live) REFERENCES desk (id, live),
  CONSTRAINT fk_hold_card FOREIGN KEY (card_id) REFERENCES card (id)
);
CREATE TABLE hold_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, resource_id INT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL,
  card_id BIGINT UNSIGNED NULL, verb ENUM('take','drop','release') NOT NULL, at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id), KEY ix_res (resource_id, id), KEY ix_at (at),
  CONSTRAINT fk_he_res FOREIGN KEY (resource_id) REFERENCES resource (id),
  CONSTRAINT fk_he_desk FOREIGN KEY (desk_id) REFERENCES desk (id),
  CONSTRAINT fk_he_card FOREIGN KEY (card_id) REFERENCES card (id)
);

-- Append-only. The current doing per desk is doing_now (same transaction, composite FKs to a row of that desk).
CREATE TABLE doing (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, desk_id INT UNSIGNED NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  text VARCHAR(512) NOT NULL DEFAULT '',
  on_card_id BIGINT UNSIGNED NULL, on_letter_id BIGINT UNSIGNED NULL, on_resource_id INT UNSIGNED NULL, on_score_id INT UNSIGNED NULL,
  wait_desk_id INT UNSIGNED NULL, wait_card_id BIGINT UNSIGNED NULL, wait_letter_id BIGINT UNSIGNED NULL, wait_resource_id INT UNSIGNED NULL,
  waiting_why VARCHAR(200) NULL, directory_sub VARCHAR(255) NULL,
  PRIMARY KEY (id), UNIQUE KEY uq_id_desk (id, desk_id), UNIQUE KEY uq_id_desk_wait (id, desk_id, wait_desk_id),
  KEY ix_desk (desk_id, id), KEY ix_on_card (on_card_id), KEY ix_wait_desk (wait_desk_id), KEY ix_created (created),
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
);
CREATE TABLE doing_now (
  desk_id INT UNSIGNED NOT NULL, doing_id BIGINT UNSIGNED NOT NULL, wait_desk_id INT UNSIGNED NULL,
  PRIMARY KEY (desk_id), KEY ix_wait (wait_desk_id),
  CONSTRAINT fk_dn_doing FOREIGN KEY (doing_id, desk_id) REFERENCES doing (id, desk_id),
  CONSTRAINT fk_dn_wait FOREIGN KEY (doing_id, desk_id, wait_desk_id) REFERENCES doing (id, desk_id, wait_desk_id)
);

-- Consensus. A vote is a decision letter to a roster: its members answer yes/no or keep/drop; the deadline closes it
-- (ev_vote_close). The result is data: outcome, tallies, and needs_human when nobody decided (no quorum or a tie).
CREATE TABLE vote (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  letter_id BIGINT UNSIGNED NOT NULL, room_id INT UNSIGNED NOT NULL, room_kind ENUM('roster') NOT NULL DEFAULT 'roster',
  opened_by INT UNSIGNED NOT NULL,
  choices ENUM('yes_no','keep_drop') NOT NULL,
  opened_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), deadline DATETIME(6) NOT NULL,
  closed_at DATETIME(6) NULL,
  outcome ENUM('yes','no','keep','drop','tie','no_quorum') NULL,
  voters INT UNSIGNED NULL, ballots INT UNSIGNED NULL, for_n INT UNSIGNED NULL, against_n INT UNSIGNED NULL,
  needs_human TINYINT NOT NULL DEFAULT 0,
  PRIMARY KEY (id), UNIQUE KEY uq_letter (letter_id), UNIQUE KEY uq_id_room_choices (id, room_id, choices),
  KEY ix_open (closed_at, deadline), KEY ix_room (room_id, id),
  CONSTRAINT ck_vote_deadline CHECK (deadline > opened_at),
  CONSTRAINT ck_vote_closed CHECK ((closed_at IS NULL) = (outcome IS NULL) AND (closed_at IS NULL) = (ballots IS NULL)),
  CONSTRAINT ck_vote_outcome CHECK (outcome IS NULL OR outcome IN ('tie','no_quorum')
                                    OR (choices = 'yes_no' AND outcome IN ('yes','no')) OR (choices = 'keep_drop' AND outcome IN ('keep','drop'))),
  CONSTRAINT ck_vote_human CHECK (needs_human = (outcome IS NOT NULL AND outcome IN ('tie','no_quorum'))),
  CONSTRAINT fk_vote_letter FOREIGN KEY (letter_id, room_id) REFERENCES letter (id, room_id),
  CONSTRAINT fk_vote_roster FOREIGN KEY (room_id, room_kind) REFERENCES room (id, kind),
  CONSTRAINT fk_vote_opener FOREIGN KEY (opened_by) REFERENCES desk (id)
);
CREATE TABLE ballot (
  vote_id BIGINT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, room_id INT UNSIGNED NOT NULL,
  choices ENUM('yes_no','keep_drop') NOT NULL,
  choice ENUM('yes','no','keep','drop') NOT NULL,
  at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (vote_id, desk_id), KEY ix_desk (desk_id),
  CONSTRAINT ck_ballot_choice CHECK ((choices = 'yes_no' AND choice IN ('yes','no')) OR (choices = 'keep_drop' AND choice IN ('keep','drop'))),
  CONSTRAINT fk_ballot_vote FOREIGN KEY (vote_id, room_id, choices) REFERENCES vote (id, room_id, choices),
  CONSTRAINT fk_ballot_member FOREIGN KEY (room_id, desk_id) REFERENCES room_member (room_id, desk_id)
);

-- Wake queue. A letter wake is a recipient row of that letter (named, or copied when the seat wakes on all);
-- one wake per (letter, desk) and per (card event, desk).
-- A row exists iff undelivered. Kept 7 days (sp_push_purge); what aged out is counted per desk in push_expired.
CREATE TABLE push (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, desk_id INT UNSIGNED NOT NULL,
  letter_id BIGINT UNSIGNED NULL, named ENUM('named','copied') NULL, card_event_id BIGINT UNSIGNED NULL,
  created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), attempts TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (id), KEY ix_desk (desk_id, id), KEY ix_created (created),
  UNIQUE KEY uq_letter (letter_id, desk_id), UNIQUE KEY uq_event (card_event_id, desk_id),
  CONSTRAINT ck_push_one CHECK ((letter_id IS NOT NULL) + (card_event_id IS NOT NULL) = 1),
  CONSTRAINT ck_push_named CHECK ((letter_id IS NULL) = (named IS NULL)),
  CONSTRAINT fk_push_desk FOREIGN KEY (desk_id) REFERENCES desk (id),
  CONSTRAINT fk_push_recipient FOREIGN KEY (letter_id, desk_id, named) REFERENCES letter_to (letter_id, desk_id, kind),
  CONSTRAINT fk_push_event FOREIGN KEY (card_event_id) REFERENCES card_event (id)
);
CREATE TABLE push_expired (
  desk_id INT UNSIGNED NOT NULL, n INT UNSIGNED NOT NULL, since DATETIME(6) NOT NULL, last DATETIME(6) NOT NULL,
  PRIMARY KEY (desk_id), CONSTRAINT fk_pe_desk FOREIGN KEY (desk_id) REFERENCES desk (id)
);

-- Timeline read model: pointers only, exactly one per row, each trace at most once. Written only by the routines.
CREATE TABLE activity (
  seq BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  letter_id BIGINT UNSIGNED NULL, card_event_id BIGINT UNSIGNED NULL, doing_id BIGINT UNSIGNED NULL,
  hold_event_id BIGINT UNSIGNED NULL, score_point_id BIGINT UNSIGNED NULL, vote_id BIGINT UNSIGNED NULL,
  PRIMARY KEY (seq), KEY ix_at (at),
  UNIQUE KEY uq_l (letter_id), UNIQUE KEY uq_ce (card_event_id), UNIQUE KEY uq_d (doing_id), UNIQUE KEY uq_he (hold_event_id),
  UNIQUE KEY uq_sp (score_point_id), UNIQUE KEY uq_v (vote_id),
  CONSTRAINT ck_act_one CHECK ((letter_id IS NOT NULL) + (card_event_id IS NOT NULL) + (doing_id IS NOT NULL) + (hold_event_id IS NOT NULL)
                               + (score_point_id IS NOT NULL) + (vote_id IS NOT NULL) = 1),
  CONSTRAINT fk_act_l FOREIGN KEY (letter_id) REFERENCES letter (id),
  CONSTRAINT fk_act_ce FOREIGN KEY (card_event_id) REFERENCES card_event (id),
  CONSTRAINT fk_act_d FOREIGN KEY (doing_id) REFERENCES doing (id),
  CONSTRAINT fk_act_he FOREIGN KEY (hold_event_id) REFERENCES hold_event (id),
  CONSTRAINT fk_act_sp FOREIGN KEY (score_point_id) REFERENCES score_point (id),
  CONSTRAINT fk_act_v FOREIGN KEY (vote_id) REFERENCES vote (id)
);

-- relaxed tier: office-wide glance counts, one row, one writer (ev_glance_refresh, every 30 s). No office-wide unread.
CREATE TABLE glance_cache (
  id TINYINT UNSIGNED NOT NULL DEFAULT 1, at DATETIME(6) NOT NULL, refresh_us INT UNSIGNED NOT NULL,
  present INT UNSIGNED NOT NULL, held INT UNSIGNED NOT NULL,
  open_n INT UNSIGNED NOT NULL, claimed_n INT UNSIGNED NOT NULL, parked_n INT UNSIGNED NOT NULL, shipped_n INT UNSIGNED NOT NULL, done_n INT UNSIGNED NOT NULL,
  letters_1d INT UNSIGNED NOT NULL, card_moves_1d INT UNSIGNED NOT NULL, doings_1d INT UNSIGNED NOT NULL, holds_1d INT UNSIGNED NOT NULL, points_1d INT UNSIGNED NOT NULL,
  votes_open INT UNSIGNED NOT NULL, votes_need_human INT UNSIGNED NOT NULL,
  PRIMARY KEY (id), CONSTRAINT ck_glance_one CHECK (id = 1)
);

-- Carried from 0.7 as they are (human sign-in, invites), re-pointed at the typed tables.
CREATE TABLE human (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  bearer_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  directory_sub VARCHAR(255) NULL,
  created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id), UNIQUE KEY idx_hash (bearer_hash), UNIQUE KEY idx_directory_sub (directory_sub)
);
CREATE TABLE human_desk (human_id BIGINT UNSIGNED NOT NULL, desk_id INT UNSIGNED NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (human_id, desk_id), UNIQUE KEY idx_desk (desk_id),
  CONSTRAINT fk_hd_human FOREIGN KEY (human_id) REFERENCES human (id), CONSTRAINT fk_hd_desk FOREIGN KEY (desk_id) REFERENCES desk (id));
-- A human's memberships: a role (Admin) or a roster. Exactly one of the two per row.
CREATE TABLE human_member (id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, human_id BIGINT UNSIGNED NOT NULL, role_id INT UNSIGNED NULL, room_id INT UNSIGNED NULL,
  created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id), UNIQUE KEY uq_role (human_id, role_id), UNIQUE KEY uq_room (human_id, room_id), KEY idx_role (role_id, human_id),
  CONSTRAINT ck_hm_one CHECK ((role_id IS NULL) <> (room_id IS NULL)),
  CONSTRAINT fk_hm_human FOREIGN KEY (human_id) REFERENCES human (id), CONSTRAINT fk_hm_role FOREIGN KEY (role_id) REFERENCES role (id),
  CONSTRAINT fk_hm_room FOREIGN KEY (room_id) REFERENCES room (id));
CREATE TABLE mill_invite (
  key_id VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  label VARCHAR(64) NOT NULL DEFAULT '', created_by VARCHAR(64) NOT NULL DEFAULT '',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ttl_seconds INT NULL, expires_at DATETIME(6) NULL, enabled_at DATETIME(6) NULL, revoked_at DATETIME(6) NULL,
  PRIMARY KEY (key_id), UNIQUE KEY idx_hash (token_hash),
  CONSTRAINT ck_inv_revoked CHECK (revoked_at IS NULL OR revoked_at >= created_at),
  CONSTRAINT ck_inv_expiry CHECK ((ttl_seconds IS NULL) = (expires_at IS NULL))
);
CREATE TABLE mill_invite_join (
  key_id VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  party VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  party_id VARCHAR(64) NOT NULL, created DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (key_id, party, party_id),
  CONSTRAINT fk_invite_join_key FOREIGN KEY (key_id) REFERENCES mill_invite (key_id)
);

-- Which routine file this book runs (beta_migrate.stamp writes one row per deploy; mill_sp_version() names the newest).
CREATE TABLE sp_deploy (
  id INT UNSIGNED NOT NULL AUTO_INCREMENT, version CHAR(15) CHARACTER SET ascii NOT NULL,
  at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), by_user VARCHAR(100) NOT NULL DEFAULT '',
  PRIMARY KEY (id)
);
-- What a migration repaired or dropped from the 0.7 book (empty on a fresh install).
CREATE TABLE mig_repair (what VARCHAR(100) NOT NULL PRIMARY KEY, n INT NOT NULL);

INSERT INTO room (id, kind, name) VALUES (1, 'roster', 'Office');
INSERT INTO role (id, name) VALUES (2, 'Admin');

DELIMITER //
-- Every desk is on the Office roster from the moment it exists.
CREATE TRIGGER desk_on_office AFTER INSERT ON desk FOR EACH ROW
BEGIN
  INSERT INTO room_member (room_id, desk_id, joined_at) VALUES (1, NEW.id, NEW.created);
END //
-- The plan tree stays a forest (adjacency cannot say it declaratively).
CREATE TRIGGER card_no_cycle BEFORE UPDATE ON card FOR EACH ROW
BEGIN
  IF NEW.from_card_id IS NOT NULL AND NOT (NEW.from_card_id <=> OLD.from_card_id) THEN
    IF EXISTS (WITH RECURSIVE up (id, p, n) AS (
                 SELECT id, from_card_id, 0 FROM card WHERE id = NEW.from_card_id
                 UNION ALL SELECT c.id, c.from_card_id, up.n + 1 FROM card c JOIN up ON c.id = up.p WHERE up.n < 10000)
               SELECT 1 FROM up WHERE id = NEW.id) THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'card: plan cycle';
    END IF;
  END IF;
END //
-- The Office roster stays a live roster (a CHECK cannot name an AUTO_INCREMENT column).
CREATE TRIGGER room_office_stays BEFORE UPDATE ON room FOR EACH ROW
BEGIN
  IF OLD.id = 1 AND (NEW.id <> 1 OR NEW.kind <> 'roster' OR NEW.retired_at IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'room: the Office roster cannot be retired or changed';
  END IF;
END //
-- Only a current member writes into a room (an FK cannot see left_at).
CREATE TRIGGER letter_sender_current BEFORE INSERT ON letter FOR EACH ROW
BEGIN
  IF EXISTS (SELECT 1 FROM room_member WHERE room_id = NEW.room_id AND desk_id = NEW.sender_id AND left_at IS NOT NULL) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'letter: sender is not a current member of this room';
  END IF;
END //
CREATE TRIGGER letter_reply_fixed BEFORE UPDATE ON letter FOR EACH ROW
BEGIN
  IF NOT (NEW.reply_to_id <=> OLD.reply_to_id) OR NEW.room_id <> OLD.room_id THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'letter: room and reply_to are fixed at send';
  END IF;
END //
DELIMITER ;
