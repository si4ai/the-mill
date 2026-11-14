-- card 1200. every foreign key gains ON UPDATE CASCADE and keeps its ON DELETE rule.
-- name_fixed still refuses a type change. an id change is allowed only when
-- @mill_allow_name_id_change is 1. fresh books already have this shape in tables.sql.
-- running this file again drops and re-adds the same keys.
-- card 1207: fk_doing_peer and fk_seat_doing are not here; apply_1207 drops them.

ALTER TABLE `seat` DROP FOREIGN KEY `fk_seat_desk`;
ALTER TABLE `seat` ADD CONSTRAINT `fk_seat_desk` FOREIGN KEY (desk_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `seat` DROP FOREIGN KEY `fk_seat_focus_label`;
ALTER TABLE `seat` ADD CONSTRAINT `fk_seat_focus_label` FOREIGN KEY (focus_label_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `member` DROP FOREIGN KEY `fk_member_name`;
ALTER TABLE `member` ADD CONSTRAINT `fk_member_name` FOREIGN KEY (name_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `member` DROP FOREIGN KEY `fk_member_desk`;
ALTER TABLE `member` ADD CONSTRAINT `fk_member_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `activity` DROP FOREIGN KEY `fk_activity_desk`;
ALTER TABLE `activity` ADD CONSTRAINT `fk_activity_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `activity` DROP FOREIGN KEY `fk_activity_roster`;
ALTER TABLE `activity` ADD CONSTRAINT `fk_activity_roster` FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `label` DROP FOREIGN KEY `fk_label_activity`;
ALTER TABLE `label` ADD CONSTRAINT `fk_label_activity` FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `label` DROP FOREIGN KEY `fk_label_name`;
ALTER TABLE `label` ADD CONSTRAINT `fk_label_name` FOREIGN KEY (name_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `tree` DROP FOREIGN KEY `fk_tree_name`;
ALTER TABLE `tree` ADD CONSTRAINT `fk_tree_name` FOREIGN KEY (name_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `tree` DROP FOREIGN KEY `fk_tree_activity`;
ALTER TABLE `tree` ADD CONSTRAINT `fk_tree_activity` FOREIGN KEY (type, id) REFERENCES activity (type, id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `watcher` DROP FOREIGN KEY `fk_watcher_desk`;
ALTER TABLE `watcher` ADD CONSTRAINT `fk_watcher_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `mail` DROP FOREIGN KEY `fk_mail_desk`;
ALTER TABLE `mail` ADD CONSTRAINT `fk_mail_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `mail` DROP FOREIGN KEY `fk_mail_body_updater`;
ALTER TABLE `mail` ADD CONSTRAINT `fk_mail_body_updater` FOREIGN KEY (body_updater_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `mail` DROP FOREIGN KEY `fk_mail_roster`;
ALTER TABLE `mail` ADD CONSTRAINT `fk_mail_roster` FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `mail_to` DROP FOREIGN KEY `fk_mail_to_mail`;
ALTER TABLE `mail_to` ADD CONSTRAINT `fk_mail_to_mail` FOREIGN KEY (type, id) REFERENCES mail (type, id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `mail_to` DROP FOREIGN KEY `fk_mail_to_desk`;
ALTER TABLE `mail_to` ADD CONSTRAINT `fk_mail_to_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `tree_read` DROP FOREIGN KEY `fk_tree_read_desk`;
ALTER TABLE `tree_read` ADD CONSTRAINT `fk_tree_read_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `tree_read` DROP FOREIGN KEY `fk_tree_read_tree`;
ALTER TABLE `tree_read` ADD CONSTRAINT `fk_tree_read_tree` FOREIGN KEY (tree_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `todo` DROP FOREIGN KEY `fk_todo_roster`;
ALTER TABLE `todo` ADD CONSTRAINT `fk_todo_roster` FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `todo` DROP FOREIGN KEY `fk_todo_updated`;
ALTER TABLE `todo` ADD CONSTRAINT `fk_todo_updated` FOREIGN KEY (updated_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `todo` DROP FOREIGN KEY `fk_todo_creator`;
ALTER TABLE `todo` ADD CONSTRAINT `fk_todo_creator` FOREIGN KEY (creator_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `todo` DROP FOREIGN KEY `fk_todo_assigned`;
ALTER TABLE `todo` ADD CONSTRAINT `fk_todo_assigned` FOREIGN KEY (assigned_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `todo` DROP FOREIGN KEY `fk_todo_body_updater`;
ALTER TABLE `todo` ADD CONSTRAINT `fk_todo_body_updater` FOREIGN KEY (body_updater_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `activity_history` DROP FOREIGN KEY `fk_history_activity`;
ALTER TABLE `activity_history` ADD CONSTRAINT `fk_history_activity` FOREIGN KEY (type, activity_id) REFERENCES activity (type, id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `activity_history` DROP FOREIGN KEY `fk_history_old_updater`;
ALTER TABLE `activity_history` ADD CONSTRAINT `fk_history_old_updater` FOREIGN KEY (old_updater_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `activity_history` DROP FOREIGN KEY `fk_history_replaced_by`;
ALTER TABLE `activity_history` ADD CONSTRAINT `fk_history_replaced_by` FOREIGN KEY (replaced_by) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `doing` DROP FOREIGN KEY `fk_doing_desk`;
ALTER TABLE `doing` ADD CONSTRAINT `fk_doing_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `doing` DROP FOREIGN KEY `fk_doing_roster`;
ALTER TABLE `doing` ADD CONSTRAINT `fk_doing_roster` FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `hold` DROP FOREIGN KEY `fk_hold_desk`;
ALTER TABLE `hold` ADD CONSTRAINT `fk_hold_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `hold` DROP FOREIGN KEY `fk_hold_res`;
ALTER TABLE `hold` ADD CONSTRAINT `fk_hold_res`  FOREIGN KEY (resource_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `score` DROP FOREIGN KEY `fk_score_roster`;
ALTER TABLE `score` ADD CONSTRAINT `fk_score_roster` FOREIGN KEY (roster_id) REFERENCES name (id) ON DELETE RESTRICT ON UPDATE CASCADE;

-- fk_score_desk stays as it is here. desk_key is still present, and that generated column
-- refuses ON UPDATE CASCADE. Card 1214 drops desk_key, then sets the same key as the
-- other kind tables: REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE.

ALTER TABLE `score_point` DROP FOREIGN KEY `fk_score_point_score`;
ALTER TABLE `score_point` ADD CONSTRAINT `fk_score_point_score` FOREIGN KEY (score_id) REFERENCES score (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `score_point` DROP FOREIGN KEY `fk_score_point_desk`;
ALTER TABLE `score_point` ADD CONSTRAINT `fk_score_point_desk`  FOREIGN KEY (desk_id) REFERENCES seat (desk_id)  ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `score_evidence` DROP FOREIGN KEY `fk_score_evidence_score`;
ALTER TABLE `score_evidence` ADD CONSTRAINT `fk_score_evidence_score` FOREIGN KEY (score_id) REFERENCES score (id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `wake` DROP FOREIGN KEY `fk_wake_desk`;
ALTER TABLE `wake` ADD CONSTRAINT `fk_wake_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `transition` DROP FOREIGN KEY `fk_transition_activity`;
ALTER TABLE `transition` ADD CONSTRAINT `fk_transition_activity` FOREIGN KEY (activity_type, activity_id) REFERENCES activity (type, id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `transition` DROP FOREIGN KEY `fk_transition_desk`;
ALTER TABLE `transition` ADD CONSTRAINT `fk_transition_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE RESTRICT ON UPDATE CASCADE;

ALTER TABLE `human_desk` DROP FOREIGN KEY `fk_human_desk_human`;
ALTER TABLE `human_desk` ADD CONSTRAINT `fk_human_desk_human` FOREIGN KEY (human_id) REFERENCES human (id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `human_desk` DROP FOREIGN KEY `fk_human_desk_desk`;
ALTER TABLE `human_desk` ADD CONSTRAINT `fk_human_desk_desk` FOREIGN KEY (desk_id) REFERENCES seat (desk_id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `human_member` DROP FOREIGN KEY `fk_human_member_human`;
ALTER TABLE `human_member` ADD CONSTRAINT `fk_human_member_human` FOREIGN KEY (human_id) REFERENCES human (id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `human_member` DROP FOREIGN KEY `fk_human_member_name`;
ALTER TABLE `human_member` ADD CONSTRAINT `fk_human_member_name` FOREIGN KEY (name_id) REFERENCES name (id) ON DELETE CASCADE ON UPDATE CASCADE;

ALTER TABLE `mill_invite_join` DROP FOREIGN KEY `fk_invite_join_key`;
ALTER TABLE `mill_invite_join` ADD CONSTRAINT `fk_invite_join_key` FOREIGN KEY (key_id) REFERENCES mill_invite (key_id) ON DELETE CASCADE ON UPDATE CASCADE;

DROP TRIGGER IF EXISTS name_fixed;
DELIMITER //
CREATE TRIGGER name_fixed BEFORE UPDATE ON name
FOR EACH ROW
BEGIN
  IF NEW.type <> OLD.type THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name: type is fixed';
  END IF;
  IF NEW.id <> OLD.id AND IFNULL(@mill_allow_name_id_change, 0) <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name: id is fixed';
  END IF;
  IF OLD.deleted IS NOT NULL AND NEW.name <> OLD.name
     AND IFNULL(@mill_allow_retired_rename, 0) <> 1 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'name retired: mill reclaim first';
  END IF;
END
//
DELIMITER ;
