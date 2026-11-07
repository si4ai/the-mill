"""card 1098: compress two-state transition cycles into one row with count n."""
from __future__ import annotations

import time

import pytest

from agent_coord.server import transition as tr
from agent_coord.server.transition_enums import ActivityType, Reason, State
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


def _ensure_activity(cn, typ: str, aid: int, desk_id: int) -> None:
    act = "focus" if typ == "doing" else "create"
    _exec(
        cn,
        "INSERT INTO activity (type, id, desk_id, roster_id, act)"
        " VALUES (%s, %s, %s, 1, %s)",
        (typ, aid, desk_id, act),
    )
    cn.commit()


def _rows_for(cn, activity_type: str, activity_id: int):
    return _q(
        cn,
        "SELECT id, from_state, to_state, reason, n, at"
        " FROM transition WHERE activity_type=%s AND activity_id=%s"
        " ORDER BY id",
        (activity_type, activity_id),
    )


def test_compress_sit_unsit_one_row_n_even_odd(cn, monkeypatch):
    """F-row: seated->connected then connected->seated updates one row n=2; odd/even hold."""
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "compress")
    monkeypatch.setenv(
        "AGENT_COORD_TRANSITION_PAIRS",
        "doing:seated/connected,hold:free/held",
    )

    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    aid = 9109801
    _ensure_activity(cn, "doing", aid, desk_id)

    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.seated,
        to_state=State.connected,
        reason=Reason.connect,
        desk_id=desk_id,
        role="actor",
        join_key=f"connect:{desk_id}:1",
    )
    cn.commit()
    rows = _rows_for(cn, "doing", aid)
    assert len(rows) == 1
    assert rows[0][1] == "seated" and rows[0][2] == "connected"
    assert int(rows[0][4]) == 1  # odd => still at connected
    at1 = rows[0][5]

    time.sleep(0.02)
    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.connected,
        to_state=State.seated,
        reason=Reason.disconnect,
        desk_id=desk_id,
        role="actor",
        join_key=f"connect:{desk_id}:1",
    )
    cn.commit()
    rows = _rows_for(cn, "doing", aid)
    assert len(rows) == 1, f"expected one compressed row, got {rows!r}"
    assert rows[0][1] == "seated" and rows[0][2] == "connected"
    assert int(rows[0][4]) == 2  # even => back at seated (from_state)
    assert rows[0][5] >= at1

    time.sleep(0.02)
    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.seated,
        to_state=State.connected,
        reason=Reason.connect,
        desk_id=desk_id,
        role="actor",
        join_key=f"connect:{desk_id}:2",
    )
    cn.commit()
    rows = _rows_for(cn, "doing", aid)
    assert len(rows) == 1
    assert int(rows[0][4]) == 3  # odd => at connected again


def test_pair_not_in_config_inserts_every_row(cn, monkeypatch):
    """Pair left off the compress list still writes every flip."""
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "compress")
    monkeypatch.setenv("AGENT_COORD_TRANSITION_PAIRS", "hold:free/held")

    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    aid = 9109802
    _ensure_activity(cn, "doing", aid, desk_id)

    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.seated,
        to_state=State.connected,
        reason=Reason.connect,
        desk_id=desk_id,
    )
    cn.commit()
    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.connected,
        to_state=State.seated,
        reason=Reason.disconnect,
        desk_id=desk_id,
    )
    cn.commit()
    rows = _rows_for(cn, "doing", aid)
    assert len(rows) == 2
    assert int(rows[0][4]) == 1 and int(rows[1][4]) == 1


def test_capture_mode_inserts_every_row(cn, monkeypatch):
    """capture mode keeps the full timeline even for default pairs."""
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "capture")
    monkeypatch.setenv(
        "AGENT_COORD_TRANSITION_PAIRS",
        "doing:seated/connected,hold:free/held",
    )

    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    aid = 9109803
    _ensure_activity(cn, "doing", aid, desk_id)

    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.seated,
        to_state=State.connected,
        reason=Reason.connect,
        desk_id=desk_id,
    )
    cn.commit()
    tr.put(
        cn,
        activity_type=ActivityType.doing,
        activity_id=aid,
        from_state=State.connected,
        to_state=State.seated,
        reason=Reason.disconnect,
        desk_id=desk_id,
    )
    cn.commit()
    rows = _rows_for(cn, "doing", aid)
    assert len(rows) == 2


def test_hold_free_held_compresses(cn, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "compress")
    monkeypatch.setenv(
        "AGENT_COORD_TRANSITION_PAIRS",
        "doing:seated/connected,hold:free/held",
    )

    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    aid = 9109804
    _ensure_activity(cn, "hold", aid, desk_id)

    tr.put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=aid,
        from_state=State.free,
        to_state=State.held,
        reason=Reason.hold_grant,
        desk_id=desk_id,
        role="holder",
    )
    cn.commit()
    tr.put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=aid,
        from_state=State.held,
        to_state=State.free,
        reason=Reason.hold_drop,
        desk_id=desk_id,
        role="holder",
    )
    cn.commit()
    rows = _rows_for(cn, "hold", aid)
    assert len(rows) == 1, f"expected one hold cycle row, got {rows!r}"
    assert rows[0][1] == "free" and rows[0][2] == "held"
    assert int(rows[0][4]) == 2


def test_same_state_refresh_compresses(cn, monkeypatch):
    """Consecutive A->A refreshes share one row and bump n."""
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "compress")
    monkeypatch.setenv(
        "AGENT_COORD_TRANSITION_PAIRS",
        "doing:seated/connected,hold:free/held,hold:held/held",
    )

    desk = admin_desk(cn)
    desk_id = _q(cn, "SELECT id FROM name WHERE type='desk' AND name=%s", (desk,))[0][0]
    aid = 9109805
    _ensure_activity(cn, "hold", aid, desk_id)

    tr.put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=aid,
        from_state=State.held,
        to_state=State.held,
        reason=Reason.hold_refresh,
        desk_id=desk_id,
        role="holder",
    )
    cn.commit()
    tr.put(
        cn,
        activity_type=ActivityType.hold,
        activity_id=aid,
        from_state=State.held,
        to_state=State.held,
        reason=Reason.hold_refresh,
        desk_id=desk_id,
        role="holder",
    )
    cn.commit()
    rows = _rows_for(cn, "hold", aid)
    assert len(rows) == 1
    assert rows[0][1] == "held" and rows[0][2] == "held"
    assert int(rows[0][4]) == 2


def test_transition_n_column_exists(cn):
    rows = _q(
        cn,
        "SELECT DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT FROM information_schema.COLUMNS"
        " WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME='transition' AND COLUMN_NAME='n'",
    )
    assert rows, "transition.n missing"
    assert str(rows[0][0]).lower() in ("int", "bigint")
    assert str(rows[0][1]).upper() == "NO"
    assert str(rows[0][2]).split(".")[0] in ("1", "'1'")
