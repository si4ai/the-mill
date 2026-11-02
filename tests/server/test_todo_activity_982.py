"""Card 982: open-cards queue FEATURE transitions + score views (no schema)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from agent_coord.server import todo_activity as ta
from agent_coord.server.transition_enums import State

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


def _rows(cn, todo_id: int):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT activity_type, activity_id, from_state, to_state, reason, desk_id, role, join_key, meta, at"
            " FROM transition WHERE activity_type='todo' AND activity_id=%s ORDER BY id",
            (todo_id,),
        )
        return list(cur.fetchall())
    finally:
        cur.close()


def _ensure_activity(cn, todo_id: int, desk_id: int) -> None:
    cur = cn.cursor()
    cur.execute(
        "INSERT INTO activity (type, id, desk_id, roster_id, act)"
        " VALUES ('todo', %s, %s, 1, 'create')"
        " ON DUPLICATE KEY UPDATE desk_id=VALUES(desk_id)",
        (todo_id, desk_id),
    )
    cur.close()
    cn.commit()


def _backdate(cn, todo_id: int, reason: str, when) -> None:
    cur = cn.cursor()
    cur.execute(
        "UPDATE transition SET at=%s WHERE id = ("
        " SELECT id FROM ("
        "  SELECT id FROM transition WHERE activity_type='todo' AND activity_id=%s AND reason=%s"
        "  ORDER BY id DESC LIMIT 1"
        " ) x)",
        (when, todo_id, reason),
    )
    cur.close()


def test_emit_flow_and_score_ages(cn):
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("t982", "roster"), ("d982a", "desk"), ("d982b", "desk"))
    a = _desk_id(cn, "d982a")
    b = _desk_id(cn, "d982b")
    tid = 982001
    _ensure_activity(cn, tid, a)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    ta.emit_create(cn, todo_id=tid, desk_id=a, parked=False, fixture=False)
    _backdate(cn, tid, "create", now - timedelta(hours=3))
    ta.emit_claim(cn, todo_id=tid, desk_id=a, take_over=False)
    _backdate(cn, tid, "claim", now - timedelta(hours=2))
    ta.emit_ship(cn, todo_id=tid, desk_id=a)
    _backdate(cn, tid, "pass_ship", now - timedelta(hours=1))
    ta.emit_done(cn, todo_id=tid, desk_id=b)
    cn.commit()

    got = _rows(cn, tid)
    assert any(r["to_state"] == "open" and r["reason"] == "create" and r["join_key"] == f"card:{tid}" for r in got)
    assert any(r["to_state"] == "claimed" and r["reason"] == "claim" for r in got)
    assert any(r["to_state"] == "shipped" and r["reason"] == "pass_ship" for r in got)
    assert any(r["to_state"] == "done" and r["reason"] == "pass_done" for r in got)
    for r in got:
        text = str(r.get("meta") or "")
        assert "d982a" not in text and "d982b" not in text
        assert "t982" not in text
        assert "localhost" not in text

    view = ta.score_view(cn, desk_id=None)
    assert "open_to_claim_ms" in view
    assert view["open_to_claim_ms"]["n"] >= 1
    # create -3h, claim -2h => ~1h
    assert view["open_to_claim_ms"]["median"] >= 3_500_000
    assert "claim_to_ship_ms" in view
    assert "ship_to_done_ms" in view
    desk_a = ta.score_view(cn, desk_id=a)
    assert "open_to_claim_ms" in desk_a


def test_open_claimed_ages_and_fixture_excluded(cn):
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("fx-982", "roster"), ("c982", "desk"), ("e982", "desk"))
    c = _desk_id(cn, "c982")
    e = _desk_id(cn, "e982")
    live = 982010
    fx = 982011
    _ensure_activity(cn, live, c)
    _ensure_activity(cn, fx, e)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    ta.emit_create(cn, todo_id=live, desk_id=c, parked=False, fixture=False)
    _backdate(cn, live, "create", now - timedelta(minutes=30))
    ta.emit_claim(cn, todo_id=live, desk_id=c, take_over=False)
    _backdate(cn, live, "claim", now - timedelta(minutes=10))

    ta.emit_create(cn, todo_id=fx, desk_id=e, parked=False, fixture=True)
    _backdate(cn, fx, "create", now - timedelta(days=30))
    cn.commit()

    view = ta.score_view(cn, desk_id=None)
    assert view.get("claimed_n", {}).get("n", 0) >= 1
    # fixture must not inflate stuck/open ages as the oldest
    if "claimed_age_ms" in view:
        # live claimed ~10 min; fixture open 30d would be huge if included
        assert view["claimed_age_ms"]["worst"] < 24 * 3600 * 1000
    named = ta.score_view_for_name(cn, "todo.open_to_claim_ms", desk_id=c)
    # live card still claimed, not done - open_to_claim may still exist from flow
    assert named.get("score") == "todo.open_to_claim_ms"
    assert "median" in named or named.get("missing") is True

    assert ta.roster_excluded("fx-foo") is True
    assert ta.roster_excluded("cold-test") is True
    assert ta.roster_excluded("the-mill") is False


def test_score_name_aliases():
    assert "todo.open_to_claim_ms" in ta.SCORE_NAMES
    assert "todo.claim_to_ship_ms" in ta.SCORE_NAMES
    assert "todo.ship_to_done_ms" in ta.SCORE_NAMES
    assert "todo.open_age_ms" in ta.SCORE_NAMES
    assert "todo.claimed_age_ms" in ta.SCORE_NAMES
    assert "todo.open_n" in ta.SCORE_NAMES
    assert "todo.claimed_n" in ta.SCORE_NAMES
    assert "open-cards-open-to-claim" in ta.SCORE_NAMES
