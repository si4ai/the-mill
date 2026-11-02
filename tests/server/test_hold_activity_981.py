"""Card 981: hold feature transitions + score views (no schema)."""
from __future__ import annotations

import pytest

from agent_coord.server import hold_activity as ha
from agent_coord.server.transition_enums import ActivityType, Reason, State

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


def _rows(cn, hold_id: int):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT activity_type, activity_id, from_state, to_state, reason, desk_id, role, join_key, meta"
            " FROM transition WHERE activity_type='hold' AND activity_id=%s ORDER BY id",
            (hold_id,),
        )
        return list(cur.fetchall())
    finally:
        cur.close()


def _meta_text(row) -> str:
    meta = row.get("meta")
    return str(meta or "")


def test_emit_grant_drop_and_held_wait_scores(cn):
    """Grant then drop: held_ms median/worst; meta has no names/hosts."""
    from datetime import datetime, timedelta, timezone

    from tests.server.records.conftest import seed_names

    seed_names(cn, ("h981", "roster"), ("a981", "desk"), ("b981", "desk"))
    aid = _desk_id(cn, "a981")
    bid = _desk_id(cn, "b981")
    hid = 981001
    # activity row required by fk_transition_activity
    cur = cn.cursor()
    cur.execute(
        "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('hold', %s, %s, 1, 'hold')",
        (hid, aid),
    )
    cur.close()
    cn.commit()

    ha.emit_grant(cn, hold_id=hid, desk_id=aid, from_state=State.no_row)
    # backdate grant so held_ms is measurable without sleeping
    cur = cn.cursor()
    cur.execute(
        "UPDATE transition SET at=%s WHERE activity_type='hold' AND activity_id=%s AND reason='hold_grant'",
        (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=2), hid),
    )
    cur.close()
    ha.emit_drop(cn, hold_id=hid, desk_id=aid)
    cn.commit()

    got = _rows(cn, hid)
    assert any(
        r["from_state"] == "no_row"
        and r["to_state"] == "held"
        and r["reason"] == "hold_grant"
        and int(r["desk_id"]) == aid
        and r["join_key"] == f"hold:{hid}:{aid}"
        for r in got
    )
    assert any(
        r["from_state"] == "held"
        and r["to_state"] == "free"
        and r["reason"] == "hold_drop"
        and int(r["desk_id"]) == aid
        for r in got
    )
    for r in got:
        text = _meta_text(r)
        assert "a981" not in text
        assert "b981" not in text
        assert "localhost" not in text
        assert "@" not in text

    view = ha.score_view(cn, desk_id=aid)
    assert "held_ms" in view
    assert view["held_ms"]["n"] == 1
    assert view["held_ms"]["median"] >= 1000
    assert view["held_ms"]["worst"] >= view["held_ms"]["median"]
    # other desk sees empty (omit)
    other = ha.score_view(cn, desk_id=bid)
    assert "held_ms" not in other


def test_refuse_wait_acquire_contention_and_force(cn):
    from datetime import datetime, timedelta, timezone

    from tests.server.records.conftest import seed_names

    seed_names(cn, ("h981c", "roster"), ("c981", "desk"), ("d981", "desk"))
    cid = _desk_id(cn, "c981")
    did = _desk_id(cn, "d981")
    hid = 981002
    cur = cn.cursor()
    cur.execute(
        "INSERT INTO activity (type, id, desk_id, roster_id, act) VALUES ('hold', %s, %s, 1, 'hold')",
        (hid, cid),
    )
    cur.close()
    cn.commit()

    ha.emit_grant(cn, hold_id=hid, desk_id=cid, from_state=State.free)
    ha.emit_refuse(cn, hold_id=hid, desk_id=did, holder_desk_id=cid)
    cur = cn.cursor()
    cur.execute(
        "UPDATE transition SET at=%s WHERE activity_type='hold' AND activity_id=%s"
        " AND reason='hold_refuse' AND desk_id=%s",
        (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(milliseconds=500), hid, did),
    )
    cur.close()
    ha.emit_wait_acquire(cn, hold_id=hid, desk_id=did)
    ha.emit_force(cn, hold_id=hid, desk_id=cid, by_desk_id=did)
    ha.emit_expire(cn, hold_id=hid, desk_id=did)
    cn.commit()

    got = _rows(cn, hid)
    assert any(r["reason"] == "hold_refuse" and int(r["desk_id"]) == did for r in got)
    assert any(r["reason"] == "hold_wait_acquire" and r["to_state"] == "held" for r in got)
    assert any(r["reason"] == "hold_force" and r["to_state"] == "free" for r in got)
    assert any(r["reason"] == "hold_expire" and r["to_state"] == "expired" for r in got)
    for r in got:
        text = _meta_text(r)
        assert "c981" not in text and "d981" not in text

    office = ha.score_view(cn, desk_id=None)
    assert "wait_ms" in office
    assert office["wait_ms"]["n"] >= 1
    assert "contention_n" in office and office["contention_n"]["n"] >= 1
    assert "force_taken_n" in office and office["force_taken_n"]["n"] >= 1
    assert "expired_n" in office and office["expired_n"]["n"] >= 1

    named = ha.score_view_for_name(cn, "hold.wait_ms", desk_id=did)
    assert named.get("score") == "hold.wait_ms"
    assert "median" in named
    missing = ha.score_view_for_name(cn, "hold.wait_ms", desk_id=cid)
    # holder did not wait
    assert missing.get("missing") is True or "median" not in missing


def test_score_names_aliases(cn):
    assert "hold.wait_ms" in ha.SCORE_NAMES
    assert "hold-wait" in ha.SCORE_NAMES
    assert "hold.held_ms" in ha.SCORE_NAMES
    assert "hold.contention_n" in ha.SCORE_NAMES
    assert "hold.force_taken_n" in ha.SCORE_NAMES
    assert "hold.expired_n" in ha.SCORE_NAMES
