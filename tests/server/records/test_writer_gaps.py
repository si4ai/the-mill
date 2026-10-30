"""Writer gaps (0.6.13, reconsidered): mail insert letter first (mail.id allocates,
FKs off only around letter + activity) and project|role roster; join reset / hold release keep activity roster; reclaim gate
blocks only a live seat; score/todo delete take the caller desk."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records import apply, connect, hold, join as here, mail, score, todo
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import call, conn_kwargs as _conn_kwargs
from agent_coord.server.records.db import scalar
from tests.server.records.conftest import seed_names
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_writer_gaps_test")


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


def _id(cn, kind: str, name: str) -> int:
    return int(scalar(cn, "SELECT id FROM name WHERE type=%s AND name=%s", (kind, name)))


def test_roster_name_bare() -> None:
    assert rec_name.roster_name("  the-mill ") == "the-mill"
    assert rec_name.roster_name("") == ""


# ---- mill_mail_insert ----


def test_mail_insert_role_roster_no_project_mint(cn) -> None:
    seed_names(cn, ("wg_role", "roster"), ("wg_rd", "desk"), ("wg_rr", "desk"))
    mid = int(mail.insert(cn, "wg_role", "wg_rd", "wg_rr", "to a desk under a role")[0]["id"])
    role = _id(cn, "roster", "wg_role")
    assert scalar(cn, "SELECT roster_id FROM mail WHERE id=%s", (mid,)) == role
    assert scalar(cn, "SELECT roster_id FROM activity WHERE type='mail' AND id=%s", (mid,)) == role
    # one roster namespace: neither insert nor mill_mail_to_put minted a second name
    assert scalar(cn, "SELECT COUNT(*) FROM name WHERE name='wg_role'") == 1
    ids = {int(r["id"]) for r in mail.list_project(cn, "wg_role")}
    assert mid in ids


def test_mail_insert_role_broadcast_goes_to_role_members(cn) -> None:
    seed_names(cn, ("wg_brole", "roster"), ("wg_bd", "desk"), ("wg_bm", "desk"))
    _exec(
        cn,
        "INSERT IGNORE INTO member (name_id, desk_id) VALUES (%s, %s)",
        (_id(cn, "roster", "wg_brole"), _id(cn, "desk", "wg_bm")),
    )
    mid = int(mail.insert(cn, "wg_brole", "wg_bd", "", "role cast")[0]["id"])
    tos = {
        int(r[0])
        for r in _rows(cn, "SELECT desk_id FROM mail_to WHERE type='mail' AND id=%s", (mid,))
    }
    assert _id(cn, "desk", "wg_bm") in tos
    assert scalar(cn, "SELECT COUNT(*) FROM name WHERE name='wg_brole'") == 1


def _rows(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return list(cur.fetchall())
    finally:
        cur.close()


def test_mail_insert_unknown_roster_refused(cn) -> None:
    seed_names(cn, ("wg_ud", "desk"), ("wg_ur", "desk"))
    with pytest.raises(Exception) as ei:
        mail.insert(cn, "wg_no_such_aff", "wg_ud", "wg_ur", "x")
    assert "no such roster" in str(ei.value)
    assert scalar(cn, "SELECT id FROM name WHERE name='wg_no_such_aff'") is None


def test_mail_insert_ids_never_reused(cn) -> None:
    seed_names(cn, ("wg_p", "roster"), ("wg_d", "desk"), ("wg_r", "desk"))
    a = int(mail.insert(cn, "wg_p", "wg_d", "wg_r", "one")[0]["id"])
    mail.delete(cn, a, "wg_d")
    assert scalar(cn, "SELECT id FROM mail WHERE id=%s", (a,)) is None
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (a,)) is not None
    b = int(mail.insert(cn, "wg_p", "wg_d", "wg_r", "two")[0]["id"])
    assert b > a
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='mail' AND id=%s", (b,)) is None
    assert scalar(cn, "SELECT n FROM activity WHERE type='mail' AND id=%s", (b,)) == 1
    # Checks stay on for the whole call (#205, #216).
    assert int(scalar(cn, "SELECT @@SESSION.foreign_key_checks")) == 1


def test_mail_insert_orphan_rolls_back_activity(cn) -> None:
    seed_names(cn, ("wg_op", "roster"), ("wg_od", "desk"), ("wg_empty_role", "roster"))
    before = scalar(cn, "SELECT COUNT(*) FROM activity WHERE type='mail'")
    with pytest.raises(Exception) as ei:
        mail.insert(cn, "wg_op", "wg_od", "wg_empty_role", "nobody", dst_kind="roster")
    assert "no recipients" in str(ei.value)
    assert scalar(cn, "SELECT COUNT(*) FROM activity WHERE type='mail'") == before
    assert int(scalar(cn, "SELECT @@SESSION.foreign_key_checks")) == 1


def test_mail_insert_failed_activity_rolls_letter_back(cn) -> None:
    seed_names(cn, ("wg_fp", "roster"), ("wg_fd", "desk"), ("wg_fr", "desk"))
    letters = scalar(cn, "SELECT COUNT(*) FROM mail")
    acts = scalar(cn, "SELECT COUNT(*) FROM activity WHERE type='mail'")
    _exec(cn, "DROP TRIGGER IF EXISTS t_wg_act_fail")
    _exec(
        cn,
        "CREATE TRIGGER t_wg_act_fail BEFORE INSERT ON activity FOR EACH ROW "
        "BEGIN IF NEW.type = 'mail' THEN "
        "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'forced activity failure'; END IF; END",
    )
    try:
        with pytest.raises(Exception) as ei:
            mail.insert(cn, "wg_fp", "wg_fd", "wg_fr", "doomed")
        assert "forced activity failure" in str(ei.value)
    finally:
        _exec(cn, "DROP TRIGGER IF EXISTS t_wg_act_fail")
    assert scalar(cn, "SELECT COUNT(*) FROM mail") == letters
    assert scalar(cn, "SELECT COUNT(*) FROM activity WHERE type='mail'") == acts
    assert int(scalar(cn, "SELECT @@SESSION.foreign_key_checks")) == 1
    mid = int(mail.insert(cn, "wg_fp", "wg_fd", "wg_fr", "ok")[0]["id"])
    assert scalar(cn, "SELECT id FROM activity WHERE type='mail' AND id=%s", (mid,)) == mid


def test_mail_insert_sp_letter_allocates_id() -> None:
    """Payload first (#216): INSERT letter, LAST_INSERT_ID(), then activity. No lock, no catalog read."""
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[3] / "agent_coord" / "server" / "sql" / "sp_mail.sql"
    ).read_text(encoding="utf-8")
    body = text.split("CREATE PROCEDURE mill_mail_insert", 1)[1].split("CREATE PROCEDURE", 1)[0]
    for gone in ("MAX(", "GET_LOCK", "MILL_NEXT_ID", "FOREIGN_KEY_CHECKS", "information_schema", "FOR UPDATE"):
        assert gone not in body
    ins = body.index("INSERT INTO mail (desk_id, roster_id, body)")
    lid = body.index("SET v_id = LAST_INSERT_ID()")
    put = body.index("CALL mill_activity_put")
    assert ins < lid < put < body.index("CALL mill_mail_to_put")


# ---- NULL roster on join reset / hold release ----


def test_join_reset_keeps_activity_roster(cn) -> None:
    seed_names(cn, ("wg_jp", "roster"), ("wg_jd", "desk"))
    jid = int(here.upsert(cn, "wg_jp", "wg_jd", "", "a" * 64, "busy")[0]["id"])
    proj = _id(cn, "roster", "wg_jp")
    _exec(cn, "UPDATE activity SET roster_id=%s WHERE type='doing' AND id=%s", (proj, jid))
    here.reset(cn, "wg_jp", "wg_jd")
    # #818: reset ends the doing with a new empty entry; it keeps the roster.
    cur = scalar(cn, "SELECT MAX(id) FROM doing WHERE desk_id=(SELECT desk_id FROM doing WHERE id=%s)", (jid,))
    assert int(cur) > jid
    assert scalar(cn, "SELECT roster_id FROM activity WHERE type='doing' AND id=%s", (cur,)) == proj
    assert scalar(cn, "SELECT roster_id FROM activity WHERE type='doing' AND id=%s", (jid,)) == proj


def test_hold_release_keeps_activity_roster(cn) -> None:
    seed_names(cn, ("wg_hp", "roster"), ("wg_hd", "desk"))
    hid = int(hold.upsert(cn, "wg_hp", "wg_hd", "wg_res")[0]["id"])
    proj = _id(cn, "roster", "wg_hp")
    _exec(cn, "UPDATE activity SET roster_id=%s WHERE type='hold' AND id=%s", (proj, hid))
    out = hold.delete(cn, hid, "wg_hd")
    assert int(out[0]["ok"]) == 1
    assert scalar(cn, "SELECT roster_id FROM activity WHERE type='hold' AND id=%s", (hid,)) == proj
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='hold' AND id=%s", (hid,)) is None


# ---- mill_name_reclaim gate ----


def _retire_raw(cn, kind: str, name: str) -> None:
    _exec(cn, "UPDATE name SET deleted = NOW(6) WHERE type=%s AND name=%s", (kind, name))


def test_reclaim_desk_with_dead_seat_ok(cn) -> None:
    seed_names(cn, ("wg_rcp", "roster"), ("wg_rc_dead", "desk"))
    here.upsert(cn, "wg_rcp", "wg_rc_dead", "", "b" * 64, "")
    here.reset(cn, "wg_rcp", "wg_rc_dead")
    _retire_raw(cn, "desk", "wg_rc_dead")
    out = rec_name.reclaim(cn, "wg_rc_dead", "desk")
    assert out[0]["op"] == "reclaimed"


def test_reclaim_desk_with_live_seat_blocked(cn) -> None:
    seed_names(cn, ("wg_rcl", "roster"), ("wg_rc_live", "desk"))
    here.upsert(cn, "wg_rcl", "wg_rc_live", "", "c" * 64, "")
    _retire_raw(cn, "desk", "wg_rc_live")
    with pytest.raises(Exception) as ei:
        rec_name.reclaim(cn, "wg_rc_live", "desk")
    assert "name in use" in str(ei.value)


def test_reclaim_role_blocked_only_by_live_member(cn) -> None:
    seed_names(cn, ("wg_rcr_p", "roster"), ("wg_rcr", "roster"), ("wg_rcr_m", "desk"))
    here.upsert(cn, "wg_rcr_p", "wg_rcr_m", "", "f" * 64, "")
    _exec(
        cn,
        "INSERT IGNORE INTO member (name_id, desk_id) VALUES (%s, %s)",
        (_id(cn, "roster", "wg_rcr"), _id(cn, "desk", "wg_rcr_m")),
    )
    _retire_raw(cn, "roster", "wg_rcr")
    with pytest.raises(Exception):
        rec_name.reclaim(cn, "wg_rcr", "roster")
    here.reset(cn, "wg_rcr_p", "wg_rcr_m")
    out = rec_name.reclaim(cn, "wg_rcr", "roster")
    assert out[0]["op"] == "reclaimed"


def test_reclaim_unrelated_live_seat_does_not_block(cn) -> None:
    seed_names(cn, ("wg_rcu_p", "roster"), ("wg_rcu_live", "desk"), ("wg_rcu_name", "label"))
    here.upsert(cn, "wg_rcu_p", "wg_rcu_live", "", "9" * 64, "")
    _retire_raw(cn, "label", "wg_rcu_name")
    out = rec_name.reclaim(cn, "wg_rcu_name", "label")
    assert out[0]["op"] == "reclaimed"


# ---- delete signatures ----


def test_score_delete_takes_desk(cn) -> None:
    seed_names(cn, ("wg_sp", "roster"), ("wg_sd", "desk"))
    sid = int(score.upsert(cn, "wg_sp", "wg_sd", "kpi_wg", "1", "", "")[0]["id"])
    desk = _id(cn, "desk", "wg_sd")
    with pytest.raises(CoordError):
        score.delete(cn, sid, "")
    score.delete(cn, sid, "wg_sd")
    assert scalar(cn, "SELECT id FROM score WHERE id=%s", (sid,)) == sid
    assert scalar(cn, "SELECT deleted FROM activity WHERE type='score' AND id=%s", (sid,)) is not None
    assert scalar(cn, "SELECT desk_id FROM activity WHERE type='score' AND id=%s", (sid,)) == desk
    params = scalar(
        cn,
        "SELECT COUNT(*) FROM information_schema.PARAMETERS "
        "WHERE SPECIFIC_SCHEMA = DATABASE() AND SPECIFIC_NAME = 'mill_score_delete'",
    )
    assert int(params) == 2


def test_todo_delete_requires_desk(cn) -> None:
    seed_names(cn, ("wg_tp", "roster"), ("wg_td", "desk"), ("wg_tother", "desk"))
    tid = int(todo.insert(cn, "wg_tp", "wg_td", "open", "card")[0]["id"])
    desk = _id(cn, "desk", "wg_td")
    with pytest.raises(CoordError):
        todo.delete(cn, tid, "")
    todo.delete(cn, tid, "wg_tother")
    # stamp only: activity.desk_id is not rewritten to the deleting desk
    assert scalar(cn, "SELECT desk_id FROM activity WHERE type='todo' AND id=%s", (tid,)) == desk
    assert scalar(cn, "SELECT n FROM activity WHERE type='todo' AND id=%s", (tid,)) == 1
