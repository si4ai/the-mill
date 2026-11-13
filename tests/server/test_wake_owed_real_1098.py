# -*- coding: utf-8 -*-
"""Card 1098 item 5: owed hop only on a real miss; empty skip; receipt waiting.

(1) sitting + delivered -> none->queued, queued->sent (no owed).
(2) addressed, not sitting -> none->queued, queued->missed.
(3) room copy, not sitting -> none->queued then sync queued->taken.
(4) live frame found no socket -> queued->missed + one ring.
(5) note_drop put-back still sent->missed.
Also: empty skip, tw exempt, receipt never empty-skipped.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_coord.server import mail_push, push, wake
from agent_coord.server.push import HUB
from agent_coord.server.records import push as rec_push


def _edges(cn, wid: int) -> list[tuple[str, str, str]]:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT from_state, to_state, reason FROM transition"
            " WHERE activity_type='wake' AND activity_id=%s ORDER BY id",
            (wid,),
        )
        return [(str(a), str(b), str(c)) for a, b, c in cur.fetchall() or []]
    finally:
        cur.close()


def _state(cn, wid: int) -> str:
    cur = cn.cursor()
    try:
        cur.execute("SELECT state FROM wake WHERE id=%s", (wid,))
        row = cur.fetchone()
        return str((row or [""])[0] or "")
    finally:
        cur.close()


@pytest.mark.sql
def test_sitting_delivered_queued_then_sent_no_owed(cn, monkeypatch) -> None:
    from tests.server.records.conftest import admin_desk

    desk = admin_desk(cn, "owed-sit-1098")
    monkeypatch.setattr(HUB, "rooms", {desk: {object()}})
    monkeypatch.setattr(HUB, "notify", lambda *a, **k: None)
    # settle runs off-loop; call mark sent directly as broadcast would
    marks: list[tuple] = []
    real_mark = rec_push.mark

    def capture_mark(c, rid, outcome):
        marks.append((rid, outcome))
        return real_mark(c, rid, outcome)

    monkeypatch.setattr(rec_push, "mark", capture_mark)
    # emit returns sent when sitting; settle is async - mark sent ourselves
    assert push.emit(cn, desk, "mail", {"id": 10981, "kind": "mail"}) == "sent"
    cn.commit()
    cur = cn.cursor()
    cur.execute(
        "SELECT id FROM wake WHERE cause='mail' AND state='queued'"
        " AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.id')) AS UNSIGNED)=10981"
        " ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    cur.close()
    assert row, "row should still be queued until settle/mark sent"
    wid = int(row[0])
    assert rec_push.mark(cn, wid, "sent") == 1
    cn.commit()
    edges = _edges(cn, wid)
    assert ("none", "queued", "wake_queue") in edges
    assert ("queued", "sent", "wake_sent") in edges
    assert ("queued", "missed", "wake_owed") not in edges
    assert _state(cn, wid) == "sent"


@pytest.mark.sql
def test_addressed_not_sitting_queued_then_missed(cn, monkeypatch) -> None:
    from tests.server.records.conftest import admin_desk

    desk = admin_desk(cn, "owed-away-1098")
    monkeypatch.setattr(HUB, "rooms", {})
    monkeypatch.setattr(wake, "post_desk", lambda *a, **k: "sent")
    assert push.emit(cn, desk, "mail", {"id": 10982, "kind": "mail"}, reason="addressed") == "missed"
    cn.commit()
    cur = cn.cursor()
    cur.execute(
        "SELECT id FROM wake WHERE cause='mail'"
        " AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.id')) AS UNSIGNED)=10982"
        " ORDER BY id DESC LIMIT 1"
    )
    wid = int(cur.fetchone()[0])
    cur.close()
    edges = _edges(cn, wid)
    assert ("none", "queued", "wake_queue") in edges
    assert ("queued", "missed", "wake_owed") in edges
    assert _state(cn, wid) == "missed"


@pytest.mark.sql
def test_room_copy_not_sitting_stays_queued_then_taken(cn, monkeypatch) -> None:
    from tests.server.records.conftest import admin_desk

    desk = admin_desk(cn, "owed-room-1098")
    monkeypatch.setattr(HUB, "rooms", {})
    posts: list = []
    monkeypatch.setattr(wake, "post_desk", lambda *a, **k: posts.append(1) or "sent")
    assert push.emit(cn, desk, "mail", {"id": 10983, "kind": "mail"}, reason="room") == "queued"
    cn.commit()
    assert posts == []
    cur = cn.cursor()
    cur.execute(
        "SELECT id FROM wake WHERE cause='mail'"
        " AND CAST(JSON_UNQUOTE(JSON_EXTRACT(payload,'$.id')) AS UNSIGNED)=10983"
        " ORDER BY id DESC LIMIT 1"
    )
    wid = int(cur.fetchone()[0])
    cur.close()
    edges = _edges(cn, wid)
    assert edges == [("none", "queued", "wake_queue")]
    assert _state(cn, wid) == "queued"
    taken = rec_push.take(cn, desk)
    cn.commit()
    assert any(int(i.get("id") or 0) == 10983 for i in taken)
    assert _state(cn, wid) == "taken"
    assert ("queued", "taken", "wake_deliver") in _edges(cn, wid)
    assert ("queued", "missed", "wake_owed") not in _edges(cn, wid)


@pytest.mark.sql
def test_settle_undelivered_marks_missed_and_rings(cn, monkeypatch) -> None:
    from tests.server.records.conftest import admin_desk

    desk = admin_desk(cn, "owed-settle-1098")
    rid = rec_push.row_id(rec_push.put(cn, desk, "mail", {"kind": "mail", "id": 10984}, "queued"))
    cn.commit()
    rings: list[tuple] = []
    monkeypatch.setattr(push, "ring_waiting", lambda c, d, why: rings.append((d, why)) or "sent")
    push._settle_row(desk, rid, False)
    cn.commit()
    assert rings == [(desk, "unsent")]
    assert _state(cn, rid) == "missed"
    assert ("queued", "missed", "wake_owed") in _edges(cn, rid)


@pytest.mark.sql
def test_note_drop_put_back_still_sent_to_missed(cn) -> None:
    from tests.server.records.conftest import admin_desk

    desk = admin_desk(cn, "owed-drop-1098")
    rid = rec_push.row_id(rec_push.put(cn, desk, "hint", {"type": "todo", "id": 55}, "queued"))
    assert rec_push.mark(cn, rid, "sent") == 1
    cn.commit()
    assert rec_push.note_drop(cn, desk, {"kind": "hint", "type": "todo", "id": 55}) == "back"
    cn.commit()
    assert _state(cn, rid) == "missed"
    assert ("sent", "missed", "wake_owed") in _edges(cn, rid)


def test_counts_as_waiting_and_has_unopened_receipt_shape() -> None:
    """Mirror item 4 signatures so fold can keep one copy."""
    assert mail_push.counts_as_waiting(pending=0, unread=False, unopened_receipt=False) is False
    assert mail_push.counts_as_waiting(pending=1) is True
    assert mail_push.counts_as_waiting(unread=True) is True
    assert mail_push.counts_as_waiting(unopened_receipt=True) is True
    assert callable(mail_push.has_unopened_receipt)


def test_post_desk_empty_skip_and_tw_exempt(monkeypatch) -> None:
    from agent_coord.server.records import join as rec_join

    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    monkeypatch.setattr(rec_join, "wake_target", lambda cn, d: ("https://hooks.example.test/x", "k"))
    monkeypatch.setattr(rec_join, "wake_state", lambda cn, d: {"armed": True, "wake_on": "addressed"})
    monkeypatch.setattr("agent_coord.server.records.push.pending", lambda cn, d: 0)
    monkeypatch.setattr(push, "unread_mail_frames", lambda cn, d, limit=20: [])
    monkeypatch.setattr(mail_push, "has_unopened_receipt", lambda cn, d: False)
    monkeypatch.setattr(wake, "mail_picked_up", lambda cn, d, mid: False)
    posts: list = []

    def boom(*a, **k):
        posts.append(1)
        raise AssertionError("must not POST")

    monkeypatch.setattr(wake, "_post_status", boom)
    assert wake.post_desk(object(), "away", {"kind": "mail", "id": 1}, hint_id=1) == "skipped"
    assert any("skipped reason=empty" in ln for ln in lines)
    lines.clear()
    # tw stall alert still posts on an empty queue (card 1141: exit and crash do not)
    monkeypatch.setattr(wake, "check_url", lambda u: (u, "hooks.example.test"))
    monkeypatch.setattr(wake, "public_host", lambda h: True)
    monkeypatch.setattr(wake, "_hold_or_take", lambda *a, **k: "lease-tok")
    monkeypatch.setattr(wake, "_post_status", lambda *a, **k: (200, None))
    monkeypatch.setattr(wake, "wake_body", lambda *a, **k: {"ok": 1})
    monkeypatch.setattr(wake, "desk_roster", lambda cn, d: "")
    monkeypatch.setattr("agent_coord.server.wasted_wake.mark_lease", lambda *a, **k: None)
    assert (
        wake.post_desk(object(), "away", {"kind": "stall", "watch_id": "42"})
        == "sent"
    )


def test_post_desk_receipt_blocks_empty_skip(monkeypatch) -> None:
    from agent_coord.server.records import join as rec_join

    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    monkeypatch.setattr(rec_join, "wake_target", lambda cn, d: ("https://hooks.example.test/x", "k"))
    monkeypatch.setattr(rec_join, "wake_state", lambda cn, d: {"armed": True, "wake_on": "addressed"})
    monkeypatch.setattr("agent_coord.server.records.push.pending", lambda cn, d: 0)
    monkeypatch.setattr(push, "unread_mail_frames", lambda cn, d, limit=20: [])
    monkeypatch.setattr(mail_push, "has_unopened_receipt", lambda cn, d: True)
    monkeypatch.setattr(wake, "mail_picked_up", lambda cn, d, mid: False)
    monkeypatch.setattr(wake, "check_url", lambda u: (u, "hooks.example.test"))
    monkeypatch.setattr(wake, "public_host", lambda h: True)
    monkeypatch.setattr(wake, "_hold_or_take", lambda *a, **k: "tok")
    monkeypatch.setattr(wake, "_post_status", lambda *a, **k: (200, None))
    monkeypatch.setattr(wake, "wake_body", lambda *a, **k: {})
    monkeypatch.setattr(wake, "desk_roster", lambda cn, d: "")
    monkeypatch.setattr("agent_coord.server.wasted_wake.mark_lease", lambda *a, **k: None)
    assert wake.post_desk(object(), "away", {"kind": "mail", "id": 7}, hint_id=7) == "sent"
    assert not any("reason=empty" in ln for ln in lines)


def test_emit_unit_put_queued_addressed_marks_missed(monkeypatch) -> None:
    logged: list[tuple] = []
    marks: list[tuple] = []
    posts: list[dict] = []
    monkeypatch.setattr(HUB, "rooms", {})
    monkeypatch.setattr(
        "agent_coord.server.records.join.wake_state",
        lambda cn, desk: {"armed": True, "host": "", "wake_on": "addressed"},
    )
    monkeypatch.setattr(
        rec_push,
        "put",
        lambda cn, desk, kind, payload, outcome: logged.append((desk, kind, outcome))
        or [{"id": 50 + len(logged)}],
    )
    monkeypatch.setattr(rec_push, "mark", lambda cn, rid, outcome: marks.append((rid, outcome)) or 1)
    monkeypatch.setattr(wake, "post_desk", lambda cn, desk, frame, **k: posts.append(k) or "sent")
    assert push.emit(object(), "DESK_one", "mail", {"id": 9}, reason="addressed") == "missed"
    assert push.emit(object(), "DESK_one", "mail", {"id": 10}, reason="room") == "queued"
    assert [row[2] for row in logged] == ["queued", "queued"]
    assert marks == [(51, "missed")]
    assert len(posts) == 1 and posts[0].get("wake_id") == 51
