"""card 1022: transition table, wake activity, System desk id 0; enums in code, text in rows."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_coord.install.migrate import apply_transition_1022, transition_1022_needed
from agent_coord.server import transition as tr
from agent_coord.server.records.db import call
from agent_coord.server.transition_enums import (
    ALLOWED_TRANSITIONS,
    AMBIGUOUS_MAP_NOTES,
    ActivityType,
    Reason,
    State,
    WakeCause,
)
from tests.server.records.conftest import admin_desk

pytestmark = pytest.mark.sql

ROOT = Path(__file__).resolve().parents[3]
STATE_MAP = ROOT / "docs" / "protocol" / "state-instrumentation.md"


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


def test_state_reason_columns_are_varchar_not_enum(cn):
    """Owner 2026-11-01: enums in code, text in rows."""
    for table, col in (
        ("transition", "from_state"),
        ("transition", "to_state"),
        ("transition", "reason"),
        ("wake", "state"),
        ("wake", "cause"),
    ):
        rows = _q(
            cn,
            "SELECT DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, CHARACTER_SET_NAME, COLLATION_NAME,"
            " COLUMN_DEFAULT FROM information_schema.COLUMNS"
            " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
            (table, col),
        )
        assert rows, (table, col)
        dtype, maxlen, charset, coll, default = rows[0]
        assert str(dtype).lower() == "varchar", (table, col, dtype)
        assert int(maxlen) == 32, (table, col, maxlen)
        assert charset == "ascii"
        assert coll == "ascii_bin"
        if (table, col) == ("transition", "from_state"):
            assert str(default).strip("'") == "none"


def test_synthetic_transition_insert_select_by_type_to_state(cn):
    """Auditor check: after migrate, insert + SELECT by (activity_type, to_state)."""
    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
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
        " VALUES (%s, 'wake', %s, %s, %s)",
        (wid, desk_id, WakeCause.test.value, State.idle.value),
    )
    cn.commit()
    tr.put(
        cn,
        activity_type=ActivityType.wake,
        activity_id=wid,
        from_state=State.idle,
        to_state=State.push_pending,
        reason=Reason.wake_queue,
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
        (ActivityType.wake.value, State.push_pending.value),
    )
    assert rows == [
        (
            ActivityType.wake.value,
            wid,
            State.idle.value,
            State.push_pending.value,
            Reason.wake_queue.value,
            0,
        )
    ]


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
        tr.check_edge(
            ActivityType.wake,
            State.idle,
            State.deleted,
            Reason.other,
        )
    with pytest.raises(Exception) as ei:
        call(
            cn,
            "mill_transition_put",
            [
                ActivityType.wake.value,
                wid,
                State.idle.value,
                State.deleted.value,
                Reason.other.value,
                0,
                "office",
                None,
                None,
            ],
        )
    assert "unknown" in str(ei.value).lower()


def test_helper_rejects_raw_string():
    """Enums only: a bare str for state/reason/type is TypeError."""
    with pytest.raises(TypeError):
        tr.check_edge("wake", State.idle, State.push_pending, Reason.wake_queue)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        tr.check_edge(ActivityType.wake, "idle", State.push_pending, Reason.wake_queue)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        tr.check_edge(ActivityType.wake, State.idle, "push_pending", Reason.wake_queue)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        tr.check_edge(ActivityType.wake, State.idle, State.push_pending, "wake_queue")  # type: ignore[arg-type]


def test_enum_values_fit_varchar_32_ascii():
    for cls in (ActivityType, State, Reason, WakeCause):
        for m in cls:
            v = m.value
            assert isinstance(v, str)
            assert v.isascii(), (cls.__name__, v)
            assert 1 <= len(v) <= 32, (cls.__name__, v, len(v))
            assert " " not in v


def test_allowed_edges_use_enums_and_cover_wake_create():
    assert (ActivityType.wake, State.idle, State.push_pending, Reason.wake_queue) in tr.ALLOWED_TRANSITIONS
    assert (ActivityType.wake, State.none, State.unread_owed, Reason.wake_owed) in tr.ALLOWED_TRANSITIONS
    for edge in ALLOWED_TRANSITIONS:
        assert all(isinstance(x, (ActivityType, State, Reason)) for x in edge)


def test_state_map_coverage():
    """Every map row id (W1..S7 etc.) has at least one ALLOWED_TRANSITIONS edge (expansions ok)."""
    text = STATE_MAP.read_text(encoding="utf-8")
    # Map ids like | W1 | or | M1 | or | Tsk1 | in transition tables
    ids = set(re.findall(r"^\|\s*([A-Za-z]+\d+)\s*\|", text, flags=re.M))
    # Drop non-transition legend noise if any
    ids = {i for i in ids if re.match(r"^(W|M|T|D|H|S|Tsk)\d*$", i) or i.startswith("Tsk")}
    covered = set()
    src = Path(tr.__file__).with_name("transition_enums.py").read_text(encoding="utf-8")
    for m in re.finditer(r"#\s*([A-Za-z]+\d*[a-z]?)\s*$", src, flags=re.M):
        covered.add(re.sub(r"[a-z]$", "", m.group(1)))  # W3a -> W3
        covered.add(m.group(1))
    # Map total ~70; our edges expand some rows
    missing = sorted(i for i in ids if i not in covered and re.sub(r"[a-z]$", "", i) not in covered)
    # Known map sections use W1-W18, M1-M9, T1-T15, D1-D11, H1-H9, S1-S7, Tsk1-Tsk8
    assert len(ids) >= 60, sorted(ids)[:20]
    assert not missing, f"state-map ids not covered by ALLOWED_TRANSITIONS comments: {missing}; notes={AMBIGUOUS_MAP_NOTES[:2]}"


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
    cur.execute(f"CREATE TABLE `{dst}`.name LIKE `{src}`.name")
    cur.execute(f"CREATE TABLE `{dst}`.seat LIKE `{src}`.seat")
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


def test_new_name_id_at_least_100(cn):
    """Fresh install reserves 0-99; next minted name is id >= 100."""
    cur = cn.cursor()
    try:
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
    finally:
        cur.close()
