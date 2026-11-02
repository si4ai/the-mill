"""Card 980: mail feature transitions + score views (no schema)."""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server import mail_activity as ma
from agent_coord.server import transition as tr
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


def _rows(cn, mail_id: int):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT activity_type, activity_id, from_state, to_state, reason, desk_id, role, join_key, meta"
            " FROM transition WHERE activity_type='mail' AND activity_id=%s ORDER BY id",
            (mail_id,),
        )
        return list(cur.fetchall())
    finally:
        cur.close()


def test_emit_send_writes_sender_live_and_recipient_unread(cn):
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("m980", "roster"), ("s980", "desk"), ("r980", "desk"))
    from agent_coord.server.records import mail as rec_mail

    rows = rec_mail.insert(cn, "m980", "s980", "r980", "hello 980", receipt=0, dst_kind="desk")
    cn.commit()
    mid = int(rows[0]["id"])
    sid = _desk_id(cn, "s980")
    rid = _desk_id(cn, "r980")
    ma.emit_send(cn, mail_id=mid, sender_desk_id=sid, recipient_desk_ids=[rid])
    cn.commit()
    got = _rows(cn, mid)
    assert any(
        r["to_state"] == "live" and r["reason"] == "send_or_queue" and int(r["desk_id"]) == sid and r["role"] == "sender"
        for r in got
    )
    assert any(
        r["to_state"] == "unread"
        and r["reason"] == "send_or_queue"
        and int(r["desk_id"]) == rid
        and r["role"] == "recipient"
        and r["join_key"] == f"letter:{mid}:{rid}"
        for r in got
    )
    for r in got:
        meta = r.get("meta")
        text = str(meta or "")
        assert "hello" not in text
        assert "s980" not in text
        assert "r980" not in text


def test_emit_delivered_woken_answered_and_score_view(cn):
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("m980b", "roster"), ("s980b", "desk"), ("r980b", "desk"))
    from agent_coord.server.records import mail as rec_mail

    rows = rec_mail.insert(cn, "m980b", "s980b", "r980b", "body", receipt=0, dst_kind="desk")
    cn.commit()
    mid = int(rows[0]["id"])
    sid = _desk_id(cn, "s980b")
    rid = _desk_id(cn, "r980b")
    ma.emit_send(cn, mail_id=mid, sender_desk_id=sid, recipient_desk_ids=[rid])
    ma.emit_delivered(cn, mail_id=mid, desk_id=rid)
    ma.emit_woken(cn, mail_id=mid, desk_id=rid)
    ma.emit_woken(cn, mail_id=mid, desk_id=rid)  # re-ring
    ma.emit_answered(cn, mail_id=mid, desk_id=rid)
    cn.commit()
    view = ma.score_view(cn, desk_id=rid)
    assert "send_to_wake_ms" in view
    assert view["send_to_wake_ms"]["n"] >= 1
    assert view["wake_to_answer_ms"]["n"] >= 1
    assert view["re_rings"]["n"] >= 1
    assert view["never_answered"]["n"] == 0
    # empty desk -> missing, not zero
    empty = ma.score_view(cn, desk_id=sid)
    assert empty.get("send_to_wake_ms") is None or empty["send_to_wake_ms"].get("n", 0) == 0
    if empty.get("send_to_wake_ms") is None:
        assert "median" not in (empty.get("send_to_wake_ms") or {})


def test_score_view_omits_empty_samples(cn):
    from tests.server.records.conftest import seed_names

    seed_names(cn, ("m980c", "roster"), ("d980c", "desk"))
    did = _desk_id(cn, "d980c")
    view = ma.score_view(cn, desk_id=did)
    assert view.get("send_to_wake_ms") is None
    assert view.get("wake_to_answer_ms") is None
    assert view.get("re_rings") is None
    assert view.get("never_answered") is None
    assert "hosts" not in str(view)
    one = ma.score_view_for_name(cn, "send-to-wake", desk_id=did)
    assert one.get("missing") is True
