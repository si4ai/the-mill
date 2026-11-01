"""card 1022: transition table, wake activity, System desk id 0."""
from __future__ import annotations

import pytest

from agent_coord.install.migrate import apply_transition_1022, transition_1022_needed
from agent_coord.server import transition as tr
from agent_coord.server.records.db import call
from tests.server.records.conftest import admin_desk

pytestmark = pytest.mark.sql


def _q(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
        return cur.fetchall() if cur.with_rows else []
    finally:
        cur.close()


def _exec(cn, sql, args=()):
    cur = cn.cursor()
    try:
        cur.execute(sql, args)
    finally:
        cur.close()


def test_fresh_book_has_system_zero(cn):
    rows = _q(cn, "SELECT id, type, name FROM name WHERE id = 0")
    assert rows == [(0, "desk", "System")]
    seats = _q(cn, "SELECT desk_id, token_hash FROM seat WHERE desk_id = 0")
    assert seats == [(0, None)]
    assert transition_1022_needed(cn) is False
    assert apply_transition_1022(cn) == []


def test_transition_desk_id_not_null_default_zero(cn):
    rows = _q(
        cn,
        "SELECT IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'transition'"
        " AND COLUMN_NAME = 'desk_id'",
    )
    assert rows and str(rows[0][0]).upper() == "NO"
    assert str(rows[0][1]) in ("0", "0.0")
    rows = _q(
        cn,
        "SELECT IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'wake'"
        " AND COLUMN_NAME = 'desk_id'",
    )
    assert rows and str(rows[0][0]).upper() == "NO"
    assert str(rows[0][1]) in ("0", "0.0")


def test_synthetic_transition_insert_select_by_type_to_state(cn):
    """Auditor check: after migrate, insert + SELECT by (activity_type, to_state)."""
    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    # wake activity + payload (explicit id; wake has no AUTO_INCREMENT in the draft)
    wid = 910022
    _exec(
        cn,
        "INSERT INTO activity (type, id, desk_id, roster_id, act)"
        " VALUES ('wake', %s, 0, 1, 'create')",
        (wid,),
    )
    cn.commit()
    assert _q(cn, "SELECT type, id FROM activity WHERE type='wake' AND id=%s", (wid,)) == [
        ("wake", wid)
    ]
    _exec(
        cn,
        "INSERT INTO wake (id, type, desk_id, cause, state)"
        " VALUES (%s, 'wake', %s, 'test', 'queued')",
        (wid, desk_id),
    )
    cn.commit()
    tr.put(
        cn,
        activity_type="wake",
        activity_id=wid,
        from_state="",
        to_state="queued",
        reason="create",
        desk_id=0,
        role="office",
        join_key=f"wake:{wid}",
    )
    cn.commit()
    rows = _q(
        cn,
        "SELECT activity_type, activity_id, from_state, to_state, reason, desk_id"
        " FROM transition WHERE activity_type = %s AND to_state = %s"
        " ORDER BY id DESC LIMIT 1",
        ("wake", "queued"),
    )
    assert rows == [("wake", wid, "", "queued", "create", 0)]


def test_unknown_edge_refused_by_sp_and_helper(cn):
    wid = 910023
    _exec(
        cn,
        "INSERT INTO activity (type, id, desk_id, roster_id, act)"
        " VALUES ('wake', %s, 0, 1, 'create')",
        (wid,),
    )
    cn.commit()
    assert _q(cn, "SELECT id FROM activity WHERE type='wake' AND id=%s", (wid,)) == [(wid,)]
    with pytest.raises(tr.UnknownTransition):
        tr.check_edge("wake", "queued", "nope")
    with pytest.raises(Exception) as ei:
        call(
            cn,
            "mill_transition_put",
            ["wake", wid, "queued", "nope", "bogus", 0, "office", None, None],
        )
    assert "unknown" in str(ei.value).lower()


def test_system_survives_dump_restore(cn):
    """Id 0 must survive a logical dump/restore under NO_AUTO_VALUE_ON_ZERO."""
    import mysql.connector

    from agent_coord.server.records.db import conn_kwargs
    from tests.sql_isolate import throwaway_db

    src = _q(cn, "SELECT DATABASE()")[0][0]
    dst = throwaway_db("mill_1022_restore")
    kw = conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS `{dst}`")
    cur.execute(
        f"CREATE DATABASE `{dst}` DEFAULT CHARACTER SET utf8mb4"
        " DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    # copy name + seat rows only (enough for System id 0)
    cur.execute(f"CREATE TABLE `{dst}`.name LIKE `{src}`.name")
    cur.execute(f"CREATE TABLE `{dst}`.seat LIKE `{src}`.seat")
    # restore with NO_AUTO_VALUE_ON_ZERO so id 0 sticks
    cur.execute("SET @old := @@SESSION.sql_mode")
    cur.execute("SET SESSION sql_mode = CONCAT(@@SESSION.sql_mode, ',NO_AUTO_VALUE_ON_ZERO')")
    cur.execute(
        f"INSERT INTO `{dst}`.name (id, type, name, deleted, trashed, n)"
        f" SELECT id, type, name, deleted, trashed, n FROM `{src}`.name WHERE id IN (0,1,2)"
    )
    cur.execute(
        f"INSERT INTO `{dst}`.seat (desk_id, token_hash, delivery_mode, wake_on)"
        f" SELECT desk_id, token_hash, delivery_mode, wake_on FROM `{src}`.seat WHERE desk_id = 0"
    )
    cur.execute("SET SESSION sql_mode = @old")
    cur.execute(f"SELECT id, type, name FROM `{dst}`.name WHERE id = 0")
    row = cur.fetchone()
    cur.execute(f"SELECT desk_id, token_hash FROM `{dst}`.seat WHERE desk_id = 0")
    seat = cur.fetchone()
    cur.execute(f"DROP DATABASE `{dst}`")
    cur.close()
    admin.close()
    assert row == (0, "desk", "System")
    assert seat == (0, None)


def test_allowed_edges_match_sp_comment_contract():
    """Python list is the model SoT; must include the wake create edge used in tests."""
    assert ("wake", "", "queued") in tr.ALLOWED_EDGES
    assert ("wake", "taken", "wasted") in tr.ALLOWED_EDGES


def test_new_name_id_at_least_100(cn):
    """Fresh install reserves 0-99; next minted name is id >= 100."""
    cur = cn.cursor()
    try:
        cur.execute("SHOW TABLE STATUS LIKE 'name'")
        row = cur.fetchone()
        # Auto_increment column index varies; use information_schema
        cur.execute(
            "SELECT AUTO_INCREMENT FROM information_schema.TABLES"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'name'"
        )
        auto = cur.fetchone()[0]
        assert auto is None or int(auto) >= 100, auto
        cur.execute(
            "INSERT INTO name (type, name) VALUES ('label', 'card-1022-builtin-reserve')"
        )
        new_id = cur.lastrowid
        cn.commit()
        assert new_id >= 100, new_id
        # leave the row; shared-book reset truncates name between tests
    finally:
        cur.close()
