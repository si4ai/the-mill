"""Soft-delete stack: #95 score keep + evidence RESTRICT, #96 join RESTRICT + reset
disconnect stamp, #97 hold release-only + watcher clear before the deleted stamp,
F1 fk_activity_desk RESTRICT, F2 score upsert revive. Reconsidered punch: delete SPs take the
card off every plan (children move up); mill FKs to name and payload FKs to activity RESTRICT;
name_no_delete refuses a hard name delete."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import apply, connect, hold, join as here, label, score, todo
from agent_coord.server.records import tree as rec_tree
from agent_coord.server.records import watcher
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_soft_delete_stack_test")


def _cn():
    import mysql.connector

    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    os.environ["AGENT_COORD_DATABASE"] = TEST_DB
    cn = connect(TEST_DB)
    apply(cn, wipe=True)
    return cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = _cn()
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    yield c
    c.close()


def _exec(cn, sql: str, args=()) -> None:
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        cn.commit()
    finally:
        cur.close()


def _rule(cn, table: str, name: str) -> str:
    return str(
        scalar(
            cn,
            "SELECT DELETE_RULE FROM information_schema.REFERENTIAL_CONSTRAINTS "
            "WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME=%s AND CONSTRAINT_NAME=%s",
            (table, name),
        )
    ).upper()


def _desk_id(cn, desk: str) -> int:
    return int(scalar(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,)))


# ---- #95 score keep + score_evidence RESTRICT ----


def test_score_evidence_fk_restrict(cn) -> None:
    assert _rule(cn, "score_evidence", "fk_score_evidence_score") in ("RESTRICT", "NO ACTION")
    # #216: payloads have no FK to activity (activity is the timeline, not a parent).
    assert _rule(cn, "score", "fk_score_activity") == "NONE"


def test_score_delete_keeps_card_and_evidence(cn) -> None:
    seed_names(cn, ("sk_proj", "roster"), ("sk_desk", "desk"))
    sid = int(score.upsert(cn, "sk_proj", "sk_desk", "kpi_keep", "3", "5", "n")[0]["id"])
    _exec(
        cn,
        "INSERT INTO score_evidence (score_id, `timestamp`, value, taken) VALUES "
        "(%s, '1970-01-01 03:00:00', JSON_OBJECT('n', 1), CURDATE()), "
        "(%s, CURDATE(), JSON_OBJECT('n', 2), CURDATE())",
        (sid, sid),
    )
    desk_before = scalar(cn, "SELECT desk_id FROM activity WHERE type='score' AND id=%s", (sid,))
    aff_before = scalar(cn, "SELECT roster_id FROM activity WHERE type='score' AND id=%s", (sid,))
    n_before = scalar(cn, "SELECT n FROM activity WHERE type='score' AND id=%s", (sid,))
    score.delete(cn, sid, "sk_desk")
    assert scalar(cn, "SELECT id FROM score WHERE id=%s", (sid,)) == sid
    assert scalar(cn, "SELECT COUNT(*) FROM score_evidence WHERE score_id=%s", (sid,)) == 2
    stamp = scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,))
    assert stamp is not None
    assert scalar(cn, "SELECT desk_id FROM activity WHERE type='score' AND id=%s", (sid,)) == desk_before
    assert scalar(cn, "SELECT roster_id FROM activity WHERE type='score' AND id=%s", (sid,)) == aff_before
    assert scalar(cn, "SELECT n FROM activity WHERE type='score' AND id=%s", (sid,)) == n_before
    # second delete keeps the first stamp
    score.delete(cn, sid, "sk_desk")
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,)) == stamp


def test_score_hard_delete_blocked_by_evidence(cn) -> None:
    seed_names(cn, ("sk2_proj", "roster"), ("sk2_desk", "desk"))
    sid = int(score.upsert(cn, "sk2_proj", "sk2_desk", "kpi_hard", "1", "", "")[0]["id"])
    _exec(
        cn,
        "INSERT INTO score_evidence (score_id, `timestamp`, value, taken) "
        "VALUES (%s, CURDATE(), JSON_OBJECT('n', 1), CURDATE())",
        (sid,),
    )
    with pytest.raises(Exception):
        _exec(cn, "DELETE FROM score WHERE id=%s", (sid,))
    assert scalar(cn, "SELECT id FROM score WHERE id=%s", (sid,)) == sid
    assert scalar(cn, "SELECT COUNT(*) FROM score_evidence WHERE score_id=%s", (sid,)) == 1


def test_score_delete_detaches_from_plan(cn) -> None:
    """mill_score_delete takes the card off every plan (children move up), then stamps."""
    seed_names(cn, ("sk3_proj", "roster"), ("sk3_desk", "desk"))
    sid = int(score.upsert(cn, "sk3_proj", "sk3_desk", "kpi_tree", "1", "", "")[0]["id"])
    kid = int(score.upsert(cn, "sk3_proj", "sk3_desk", "kpi_tree_kid", "1", "", "")[0]["id"])
    rec_tree.create(cn, "sk3_plan", "score", sid)
    rec_tree.add(cn, "score", sid, "score", kid, tree="sk3_plan")
    assert scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='score' AND id=%s", (sid,)) >= 1
    score.delete(cn, sid, "sk3_desk")
    assert scalar(cn, "SELECT id FROM score WHERE id=%s", (sid,)) == sid
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,)) is not None
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='score' AND id=%s", (sid,)) == 0
    assert scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='score' AND id=%s", (sid,)) == 0
    assert scalar(
        cn,
        "SELECT CONCAT(lft, ':', rgt) FROM tree t JOIN name n ON n.id = t.name_id"
        " WHERE n.name='sk3_plan' AND t.type='score' AND t.id=%s",
        (kid,),
    ) == "1:2"


# ---- F2 score upsert revive (not via mill_activity_put) ----


def test_score_upsert_revives_soft_deleted(cn) -> None:
    seed_names(cn, ("srv_proj", "roster"), ("srv_desk", "desk"))
    sid = int(score.upsert(cn, "srv_proj", "srv_desk", "kpi_revive", "1", "2", "a")[0]["id"])
    _exec(
        cn,
        "INSERT INTO score_evidence (score_id, `timestamp`, value, taken) "
        "VALUES (%s, CURDATE(), JSON_OBJECT('n', 1), CURDATE())",
        (sid,),
    )
    score.delete(cn, sid, "sk_desk")
    stamp = scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,))
    assert stamp is not None
    # upsert same roster/desk/kpi revives; evidence stays; value updates
    out = score.upsert(cn, "srv_proj", "srv_desk", "kpi_revive", "9", "10", "revived")[0]
    assert int(out["id"]) == sid
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,)) is None
    assert scalar(cn, "SELECT value FROM score WHERE id=%s", (sid,)) == "9"
    assert scalar(cn, "SELECT target FROM score WHERE id=%s", (sid,)) == "10"
    assert scalar(cn, "SELECT note FROM score WHERE id=%s", (sid,)) == "revived"
    assert scalar(cn, "SELECT COUNT(*) FROM score_evidence WHERE score_id=%s", (sid,)) == 1
    # mill_activity_put alone must not clear deleted (mail/todo safety): re-stamp, put, still deleted
    _exec(
        cn,
        "UPDATE activity SET deleted = %s WHERE type='score' AND id=%s",
        (stamp, sid),
    )
    _exec(
        cn,
        "CALL mill_activity_put('score', %s, MILL_NOW(), "
        "(SELECT desk_id FROM score WHERE id=%s), "
        "(SELECT roster_id FROM score WHERE id=%s), NULL, NULL)",
        (sid, sid, sid),
    )
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,)) is not None


# ---- #97 watcher clear + labels stay + hold release-only ----


def test_todo_score_soft_delete_clears_watchers_keeps_labels(cn) -> None:
    seed_names(cn, ("sw_proj", "roster"), ("sw_desk", "desk"), ("sw_other", "desk"), ("sw_tag", "label"))
    tid = int(todo.insert(cn, "sw_proj", "sw_desk", "open", "watch me")[0]["id"])
    sid = int(score.upsert(cn, "sw_proj", "sw_desk", "kpi_w", "1", "", "")[0]["id"])
    other = _desk_id(cn, "sw_other")
    watcher.put(cn, "todo", tid, other)
    watcher.put(cn, "score", sid, other)
    label.put(cn, "todo", tid, "sw_tag")
    label.put(cn, "score", sid, "sw_tag")
    assert scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='todo' AND id=%s", (tid,)) >= 2
    assert scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='score' AND id=%s", (sid,)) >= 2
    todo.delete(cn, tid, "sw_desk")
    score.delete(cn, sid, "sk_desk")
    for typ, nid in (("todo", tid), ("score", sid)):
        assert scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type=%s AND id=%s", (typ, nid)) == 0
        assert scalar(cn, "SELECT deleted FROM activity WHERE type=%s AND id=%s", (typ, nid)) is not None
        assert scalar(cn, "SELECT COUNT(*) FROM label WHERE type=%s AND id=%s", (typ, nid)) == 1


def test_todo_delete_failure_rolls_back_detach_and_watchers(cn) -> None:
    """A failed stamp rolls the whole delete back: plan rows, watchers, and the card stay."""
    seed_names(cn, ("swt_proj", "roster"), ("swt_desk", "desk"))
    tid = int(todo.insert(cn, "swt_proj", "swt_desk", "open", "planned")[0]["id"])
    rec_tree.create(cn, "swt_plan", "todo", tid)
    n_w = scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='todo' AND id=%s", (tid,))
    assert n_w >= 1
    _exec(cn, "DROP TRIGGER IF EXISTS t_swt_fail")
    _exec(
        cn,
        "CREATE TRIGGER t_swt_fail BEFORE UPDATE ON activity FOR EACH ROW "
        "BEGIN IF NEW.type = 'todo' AND NEW.deleted IS NOT NULL THEN "
        "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'forced stamp failure'; END IF; END",
    )
    try:
        with pytest.raises(Exception) as ei:
            todo.delete(cn, tid, "swt_desk")
        assert "forced stamp failure" in str(ei.value)
    finally:
        _exec(cn, "DROP TRIGGER IF EXISTS t_swt_fail")
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (tid,)) == tid
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='todo' AND id=%s", (tid,)) == 1
    assert scalar(cn, "SELECT COUNT(*) FROM watcher WHERE type='todo' AND id=%s", (tid,)) == n_w
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='todo' AND id=%s", (tid,)) is None
    todo.delete(cn, tid, "swt_desk")
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (tid,)) is None
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='todo' AND id=%s", (tid,)) == 0


def test_hold_delete_always_refused_release_still_works(cn) -> None:
    seed_names(cn, ("sh_proj", "roster"), ("sh_desk", "desk"), ("sh_tag", "label"))
    hid = int(hold.upsert(cn, "sh_proj", "sh_desk", "sh_res")[0]["id"])
    label.put(cn, "hold", hid, "sh_tag")
    assert scalar(cn, "SELECT COUNT(*) FROM tree WHERE type='hold' AND id=%s", (hid,)) == 0
    with pytest.raises(Exception) as ei:
        _exec(cn, "DELETE FROM hold WHERE id=%s", (hid,))
    assert "release only" in str(ei.value)
    assert scalar(cn, "SELECT id FROM hold WHERE id=%s", (hid,)) == hid
    out = hold.delete(cn, hid, "sh_desk")
    assert int(out[0]["ok"]) == 1
    assert scalar(cn, "SELECT desk_id FROM hold WHERE id=%s", (hid,)) is None
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='hold' AND id=%s", (hid,)) is None
    assert scalar(cn, "SELECT COUNT(*) FROM label WHERE type='hold' AND id=%s", (hid,)) == 1


def test_trigger_set(cn) -> None:
    cur = cn.cursor()
    cur.execute(
        "SELECT TRIGGER_NAME FROM information_schema.TRIGGERS "
        "WHERE TRIGGER_SCHEMA = DATABASE() ORDER BY TRIGGER_NAME"
    )
    names = [r[0] for r in cur.fetchall()]
    cur.close()
    assert "hold_no_delete" in names
    assert "hold_no_delete_in_tree" not in names
    assert "activity_del_watchers" in names
    assert "name_no_delete" in names
    for t in ("todo_no_delete_in_tree", "mail_no_delete_in_tree", "doing_no_delete_in_tree", "score_no_delete_in_tree"):
        assert t in names


# ---- #96 join RESTRICT + reset is a disconnect stamp ----


def test_join_desk_fk_restrict(cn) -> None:
    assert _rule(cn, "seat", "fk_seat_desk") in ("RESTRICT", "NO ACTION")  # #818: was join
    assert _rule(cn, "doing", "fk_doing_desk") in ("RESTRICT", "NO ACTION")
    assert _rule(cn, "doing", "fk_join_activity") == "NONE"  # #216
    # F1: activity desk RESTRICT so name delete cannot cascade through activity to join
    assert _rule(cn, "activity", "fk_activity_desk") in ("RESTRICT", "NO ACTION")


def test_join_reset_stamps_disconnect_keeps_row(cn) -> None:
    seed_names(cn, ("sj_proj", "roster"), ("sj_desk", "desk"))
    jid = int(here.upsert(cn, "sj_proj", "sj_desk", "", "d" * 64, "busy")[0]["id"])
    did = _desk_id(cn, "sj_desk")
    assert scalar(cn, "SELECT time_disconnect FROM seat WHERE desk_id=%s", (did,)) is None
    here.reset(cn, "sj_proj", "sj_desk")
    assert scalar(cn, "SELECT token_hash FROM seat WHERE desk_id=%s", (did,)) is None
    assert scalar(cn, "SELECT time_disconnect FROM seat WHERE desk_id=%s", (did,)) is not None
    assert scalar(cn, "SELECT id FROM activity WHERE type='doing' AND id=%s", (jid,)) == jid
    # --dead no longer prunes: the seat, its doing rows and their activity stay
    out = here.prune_dead(cn)
    assert out["pruned"] == 0 and out["dead"] >= 1
    assert scalar(cn, "SELECT COUNT(*) FROM seat WHERE desk_id=%s", (did,)) == 1
    assert scalar(cn, "SELECT id FROM doing WHERE id=%s", (jid,)) == jid
    assert scalar(cn, "SELECT id FROM activity WHERE type='doing' AND id=%s", (jid,)) == jid


def test_name_delete_with_seat_refused(cn) -> None:
    seed_names(cn, ("sjr_proj", "roster"), ("sjr_desk", "desk"))
    jid = int(here.upsert(cn, "sjr_proj", "sjr_desk", "", "e" * 64, "")[0]["id"])
    did = _desk_id(cn, "sjr_desk")
    with pytest.raises(Exception):
        _exec(cn, "DELETE FROM name WHERE id=%s", (did,))
    assert scalar(cn, "SELECT id FROM doing WHERE id=%s", (jid,)) == jid
    assert scalar(cn, "SELECT COUNT(*) FROM seat WHERE desk_id=%s", (did,)) == 1


def test_name_hard_delete_refused_even_unreferenced(cn) -> None:
    seed_names(cn, ("snd_lonely", "label"))
    nid = int(scalar(cn, "SELECT id FROM name WHERE type='label' AND name='snd_lonely'"))
    with pytest.raises(Exception) as ei:
        _exec(cn, "DELETE FROM name WHERE id=%s", (nid,))
    assert "retire only" in str(ei.value)
    assert scalar(cn, "SELECT id FROM name WHERE id=%s", (nid,)) == nid


def test_mill_fks_to_name_are_restrict(cn) -> None:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT TABLE_NAME, CONSTRAINT_NAME, REFERENCED_TABLE_NAME, DELETE_RULE"
            " FROM information_schema.REFERENTIAL_CONSTRAINTS"
            " WHERE CONSTRAINT_SCHEMA = DATABASE()"
        )
        rows = cur.fetchall()
    finally:
        cur.close()
    by = {str(r[1]): (str(r[0]), str(r[2]), str(r[3]).upper()) for r in rows}
    # Parked for the human-table redo: human_* FKs stay as they are.
    keep = {"fk_human_desk_desk", "fk_human_member_name"}
    for name, (_table, ref, rule) in by.items():
        if ref == "name" and name not in keep:
            assert rule in ("RESTRICT", "NO ACTION"), name
    assert by["fk_tree_activity"][2] in ("RESTRICT", "NO ACTION")
    assert by["fk_label_activity"][2] == "CASCADE"
    for name in ("fk_mail_activity", "fk_todo_activity", "fk_join_activity", "fk_hold_activity", "fk_score_activity"):
        assert name not in by, name  # #216
    assert by["fk_mail_to_mail"][2] == "CASCADE"
    assert by["fk_score_evidence_score"][2] in ("RESTRICT", "NO ACTION")
    assert "fk_human_desk_desk" in by and "fk_human_member_name" in by


# ---- migrate ensure flips FK rules on an existing book ----


def test_ensure_fk_rules_flips_cascade(cn) -> None:
    from agent_coord.install.migrate import _ensure_fk_rules

    _exec(cn, "ALTER TABLE seat DROP FOREIGN KEY fk_seat_desk")
    _exec(
        cn,
        "ALTER TABLE seat ADD CONSTRAINT fk_seat_desk FOREIGN KEY (desk_id) "
        "REFERENCES name (id) ON DELETE CASCADE",
    )
    _exec(cn, "ALTER TABLE score_evidence DROP FOREIGN KEY fk_score_evidence_score")
    _exec(
        cn,
        "ALTER TABLE score_evidence ADD CONSTRAINT fk_score_evidence_score FOREIGN KEY (score_id) "
        "REFERENCES score (id) ON DELETE CASCADE",
    )
    _exec(cn, "ALTER TABLE activity DROP FOREIGN KEY fk_activity_desk")
    _exec(
        cn,
        "ALTER TABLE activity ADD CONSTRAINT fk_activity_desk FOREIGN KEY (desk_id) "
        "REFERENCES name (id) ON DELETE CASCADE",
    )
    _exec(cn, "ALTER TABLE tree DROP FOREIGN KEY fk_tree_activity")
    _exec(
        cn,
        "ALTER TABLE tree ADD CONSTRAINT fk_tree_activity FOREIGN KEY (type, id) "
        "REFERENCES activity (type, id) ON DELETE CASCADE",
    )
    _exec(cn, "ALTER TABLE member DROP FOREIGN KEY fk_member_desk")
    _exec(
        cn,
        "ALTER TABLE member ADD CONSTRAINT fk_member_desk FOREIGN KEY (desk_id) "
        "REFERENCES name (id) ON DELETE CASCADE",
    )
    assert _rule(cn, "seat", "fk_seat_desk") == "CASCADE"
    assert _rule(cn, "activity", "fk_activity_desk") == "CASCADE"
    assert _rule(cn, "tree", "fk_tree_activity") == "CASCADE"
    applied = _ensure_fk_rules(cn)
    assert "fk_seat_desk:RESTRICT" in applied
    assert "fk_score_evidence_score:RESTRICT" in applied
    assert "fk_activity_desk:RESTRICT" in applied
    assert "fk_tree_activity:RESTRICT" in applied
    assert "fk_member_desk:RESTRICT" in applied
    assert _rule(cn, "tree", "fk_tree_activity") in ("RESTRICT", "NO ACTION")
    assert _rule(cn, "mail", "fk_mail_activity") == "NONE"  # #216: never re-added
    assert _rule(cn, "member", "fk_member_desk") in ("RESTRICT", "NO ACTION")
    assert _rule(cn, "seat", "fk_seat_desk") in ("RESTRICT", "NO ACTION")
    assert _rule(cn, "score_evidence", "fk_score_evidence_score") in ("RESTRICT", "NO ACTION")
    assert _rule(cn, "activity", "fk_activity_desk") in ("RESTRICT", "NO ACTION")
    assert _ensure_fk_rules(cn) == []
