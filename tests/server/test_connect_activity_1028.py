"""Card 1028: connect FEATURE transitions + score views (no schema)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_coord.server import connect_activity as ca
from agent_coord.server.transition_enums import Reason, State

pytestmark = pytest.mark.sql


def _desk_id(cn, name: str) -> int:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT id FROM name WHERE type='desk' AND name=%s AND deleted IS NULL LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
        assert row, name
        return int(row[0])
    finally:
        cur.close()


def _rows(cn, desk_id: int):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT activity_type, activity_id, from_state, to_state, reason, desk_id, join_key, meta, at"
            " FROM transition WHERE activity_type='doing' AND join_key LIKE %s ORDER BY id",
            (f"connect:{desk_id}:%",),
        )
        return list(cur.fetchall())
    finally:
        cur.close()


def _backdate(cn, join_key: str, reason: str, when) -> None:
    cur = cn.cursor()
    cur.execute(
        "UPDATE transition SET at=%s WHERE id = ("
        " SELECT id FROM ("
        "  SELECT id FROM transition WHERE join_key=%s AND reason=%s"
        "  ORDER BY id DESC LIMIT 1"
        " ) x)",
        (when, join_key, reason),
    )
    cur.close()


def test_emit_connect_disconnect_session_and_startup(cn, monkeypatch):
    """Session duration needs separate connect/disconnect rows (capture)."""
    from tests.server.records.conftest import seed_names

    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "capture")
    seed_names(cn, ("c1028", "roster"), ("desk1028", "desk"))
    did = _desk_id(cn, "desk1028")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    sess = 9001
    ca.emit_connect(cn, desk_id=did, session_id=sess, startup_ms=250)
    _backdate(cn, f"connect:{did}:{sess}", "connect", now - timedelta(minutes=30))
    ca.emit_disconnect(cn, desk_id=did, session_id=sess)
    cn.commit()

    got = _rows(cn, did)
    assert any(
        r["from_state"] == "seated"
        and r["to_state"] == "connected"
        and r["reason"] == "connect"
        and r["join_key"] == f"connect:{did}:{sess}"
        for r in got
    )
    assert any(r["reason"] == "disconnect" and r["to_state"] == "seated" for r in got)
    for r in got:
        text = str(r.get("meta") or "")
        assert "desk1028" not in text
        assert "localhost" not in text
        assert "@" not in text

    view = ca.score_view(cn, desk_id=did)
    assert "session_ms" in view
    assert view["session_ms"]["n"] == 1
    assert view["session_ms"]["median"] >= 1_000_000  # ~30m
    assert "startup_ms" in view
    assert view["startup_ms"]["median"] == 250


def test_drops_and_reconnects(cn):
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("c1028b", "roster"), ("d1028b", "desk"))
    did = _desk_id(cn, "d1028b")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ca.emit_connect(cn, desk_id=did, session_id=1, startup_ms=100)
    _backdate(cn, f"connect:{did}:1", "connect", now - timedelta(minutes=10))
    ca.emit_disconnect(cn, desk_id=did, session_id=1)
    _backdate(cn, f"connect:{did}:1", "disconnect", now - timedelta(minutes=9))
    ca.emit_connect(cn, desk_id=did, session_id=2, startup_ms=80)  # reconnect
    cn.commit()

    view = ca.score_view(cn, desk_id=did)
    assert view["drop_n"]["n"] == 1, view
    assert view["reconnect_n"]["n"] == 1, view
    office = ca.score_view(cn, desk_id=None)
    assert "startup_ms" in office or "session_ms" in office or "drop_n" in office


def _flip_rows(cn, desk_id: int):
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT reason, n FROM transition WHERE activity_type='doing'"
            " AND activity_id=%s ORDER BY id",
            (ca.anchor_id(desk_id),),
        )
        return [(str(r[0]), int(r[1] or 1)) for r in cur.fetchall()]
    finally:
        cur.close()


def test_fresh_compress_exact_drops_and_reconnects(cn, monkeypatch):
    """Card 1098: 2 drops + 2 reconnects on one compressed connect-led row."""
    from tests.server.records.conftest import seed_names

    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "compress")
    monkeypatch.delenv("AGENT_COORD_TRANSITION_PAIRS", raising=False)
    seed_names(cn, ("c1098k1", "roster"), ("d1098k1", "desk"))
    did = _desk_id(cn, "d1098k1")
    for s in (1, 2):
        ca.emit_connect(cn, desk_id=did, session_id=s, startup_ms=10)
        ca.emit_disconnect(cn, desk_id=did, session_id=s)
    ca.emit_connect(cn, desk_id=did, session_id=3, startup_ms=10)
    cn.commit()

    assert _flip_rows(cn, did) == [("connect", 5)]
    view = ca.score_view(cn, desk_id=did)
    assert view["drop_n"]["n"] == 2, view
    assert view["reconnect_n"]["n"] == 2, view


@pytest.mark.parametrize(
    "tail, want_rows, want_drops, want_reconnects",
    [
        # capture C,D then compress C,D,C: real history 2 drops / 2 reconnects
        (("c", "d", "c"), [("connect", 1), ("disconnect", 4)], 2, 2),
        # capture C,D then compress C,D: 2 drops / 1 reconnect (ends disconnected)
        (("c", "d"), [("connect", 1), ("disconnect", 3)], 2, 1),
        # capture C,D then compress C: 1 drop / 1 reconnect
        (("c",), [("connect", 1), ("disconnect", 2)], 1, 1),
    ],
)
def test_upgraded_book_last_row_disconnect(
    cn, monkeypatch, tail, want_rows, want_drops, want_reconnects
):
    """Card 1098: book written one row per flip (0.8.9 / capture) whose latest row is a
    disconnect, then default compress. The disconnect-led row decodes from its own
    first edge: drops = ceil(n/2), reconnects = floor(n/2)."""
    from tests.server.records.conftest import seed_names

    monkeypatch.delenv("AGENT_COORD_TRANSITION_PAIRS", raising=False)
    name = "d1098u" + "".join(tail)
    seed_names(cn, ("c1098u" + "".join(tail), "roster"), (name, "desk"))
    did = _desk_id(cn, name)
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "capture")
    ca.emit_connect(cn, desk_id=did, session_id=1, startup_ms=10)
    ca.emit_disconnect(cn, desk_id=did, session_id=1)
    cn.commit()
    monkeypatch.setenv("AGENT_COORD_TRANSITION_MODE", "compress")
    sess = 2
    for step in tail:
        if step == "c":
            ca.emit_connect(cn, desk_id=did, session_id=sess, startup_ms=10)
        else:
            ca.emit_disconnect(cn, desk_id=did, session_id=sess)
            sess += 1
    cn.commit()

    assert _flip_rows(cn, did) == want_rows
    view = ca.score_view(cn, desk_id=did)
    assert view["drop_n"]["n"] == want_drops, view
    assert view["reconnect_n"]["n"] == want_reconnects, view


def test_score_name_aliases():
    assert "connect.startup_ms" in ca.SCORE_NAMES
    assert "connect.session_ms" in ca.SCORE_NAMES
    assert "connect.drop_n" in ca.SCORE_NAMES
    assert "connect.reconnect_n" in ca.SCORE_NAMES
    assert "connect-startup" in ca.SCORE_NAMES
