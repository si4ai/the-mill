# -*- coding: utf-8 -*-
"""#949 replay unread on connect / wake-done.

Mail stored while no connect-wait sits (send outcome missed) must wake the next
connect-wait. A short connect that drains the push queue without opening the
letter must not leave the desk dark: the next connect sync resurfaces unread
mailbox mail. Picked-up or wake-done letters do not ring again; new mail does.

Related: #826 (push-at-leave). Row F-replay-unread.
"""
from __future__ import annotations

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push, wake
from agent_coord.server.records.opened import picked_up_ids
from tests.server.test_desk_webhook_618 import _Queue, _Resp
from tests.server.webhook_fixtures import HOOK_HOST, arm


@pytest.fixture
def office(monkeypatch):
    """Armed desk, in-memory push queue, fake webhook receiver, settable clock."""
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    monkeypatch.setattr(wake, "_NOTE", {}, raising=False)
    clock = {"t": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])
    timers: list = []
    monkeypatch.setattr(wake, "_schedule", lambda delay, fn, *args: timers.append((delay, fn, args)))
    monkeypatch.setattr(wake, "_book", lambda: MagicMock())
    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    # Default: no mailbox unread unless a test stubs it.
    monkeypatch.setattr(push, "unread_mail_frames", lambda cn, desk, **k: [])
    bodies: list[dict] = []

    def receive(req, timeout=0):
        bodies.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    with patch("agent_coord.server.wake._open", receive):
        yield {
            "q": q,
            "clock": clock,
            "timers": timers,
            "lines": lines,
            "bodies": bodies,
            "cn": MagicMock(),
            "monkeypatch": monkeypatch,
        }


def _letter(o, n: int, desk: str = "away") -> str:
    return push.emit(o["cn"], desk, "mail", {"id": n, "body": f"letter {n}", "sender": "s"})


def _posts(o, desk: str = "away") -> list[dict]:
    return [b for b in o["bodies"] if b.get("desk") == desk]


def _unread_frame(n: int) -> dict:
    return {"kind": "mail", "id": n, "outcome": "missed", "body": f"letter {n}", "sender": "s"}


def test_a_missed_letter_exits_the_next_connect_wait_sync(office) -> None:
    """(a) Letter sent while no wait sits -> next connect sync carries that hint."""
    assert _letter(office, 41) == "missed"
    frame = push.connect_sync_frame(office["cn"], "away")
    assert any(r.get("kind") == "mail" and r.get("id") == 41 for r in frame["sync"])
    assert any(r.get("outcome") == "missed" and r.get("id") == 41 for r in frame["sync"])


def test_b_reconnect_after_drop_gets_unread_mailbox_hint(office) -> None:
    """(b) After a short connect drains the push queue, unread mailbox mail still
    rides the next connect sync so connect-wait exits at once."""
    assert _letter(office, 42) == "missed"
    # First sit (short connect / reply) takes the push row.
    first = push.connect_sync_frame(office["cn"], "away")
    assert [r["id"] for r in first["sync"]] == [42]
    assert office["q"].rows == []
    # Letter still unread in the mailbox (never mail-thread / opened).
    office["monkeypatch"].setattr(
        push, "unread_mail_frames", lambda cn, desk, **k: [_unread_frame(42)]
    )
    second = push.connect_sync_frame(office["cn"], "away")
    assert any(r.get("kind") == "mail" and r.get("id") == 42 for r in second["sync"])


def test_c_wake_done_with_seen_unread_does_not_refire_webhook(office) -> None:
    """(c) Replayed unread is not NEW work after the run says done."""
    assert _letter(office, 50) == "missed"
    assert _letter(office, 51) == "missed"
    assert len(_posts(office)) == 1
    # Run's short connect took every push row (pending now 0).
    push.connect_sync_frame(office["cn"], "away")
    assert office["q"].rows == []
    # But letter 51 was never opened.
    office["monkeypatch"].setattr(
        push, "unread_mail_frames", lambda cn, desk, **k: [_unread_frame(51)]
    )
    assert wake.lease_done(office["cn"], "away") == "none"
    assert len(_posts(office)) == 1
    for _ in range(10):
        push.connect_sync_frame(office["cn"], "away")
        assert push.ring_waiting(office["cn"], "away", "leave") == "none"
    assert len(_posts(office)) == 1


def test_d_no_duplicate_wake_when_nothing_unread(office) -> None:
    """(d) wake-done with empty push queue and no unread mail sends nothing."""
    assert _letter(office, 60) == "missed"
    assert _letter(office, 61) == "missed"  # coalesced so trail exists
    push.connect_sync_frame(office["cn"], "away")
    office["monkeypatch"].setattr(push, "unread_mail_frames", lambda cn, desk, **k: [])
    assert wake.lease_done(office["cn"], "away") == "none"
    assert len(_posts(office)) == 1
    assert any("wake=none reason=drained" in ln for ln in office["lines"])


def test_e_already_read_mail_does_not_refire(office) -> None:
    """(e) Opened mail is not unread: wake-done and reconnect sync stay quiet."""
    assert _letter(office, 70) == "missed"
    push.connect_sync_frame(office["cn"], "away")
    # unread_mail_frames returns only opened-IS-NULL rows; opened mail is absent.
    office["monkeypatch"].setattr(push, "unread_mail_frames", lambda cn, desk, **k: [])
    assert wake.lease_done(office["cn"], "away") == "none"
    third = push.connect_sync_frame(office["cn"], "away")
    assert third["sync"] == []


def test_leave_rings_when_mailbox_unread_and_push_empty(office) -> None:
    """#826-adjacent: last socket leaving with unread mailbox mail rings again."""
    office["monkeypatch"].setattr(
        push, "unread_mail_frames", lambda cn, desk, **k: [_unread_frame(80)]
    )
    office["monkeypatch"].setattr(
        "agent_coord.server.records.push.waiting", lambda cn, desk: None
    )
    assert push.ring_waiting(office["cn"], "away", "leave") == "sent"
    assert _posts(office)[-1]["id"] == 80


@pytest.mark.parametrize("pickup", ["read", "mark", "doing"])
def test_picked_up_mail_never_rings_even_with_stale_push(office, pickup):
    from agent_coord.server.records import opened

    assert _letter(office, 90) == "missed"
    # Run the real pickup query against mail_to/doing, translating placeholders only.
    db = sqlite3.connect(":memory:")
    db.executescript("""
        CREATE TABLE name (id INTEGER, type TEXT, name TEXT, deleted TEXT, trashed TEXT);
        INSERT INTO name VALUES (1, 'desk', 'away', NULL, NULL);
        CREATE TABLE mail_to (type TEXT, id INTEGER, desk_id INTEGER, opened TEXT);
        INSERT INTO mail_to VALUES ('mail', 90, 1, NULL);
        CREATE TABLE doing (desk_id INTEGER, on_type TEXT, on_id INTEGER, act TEXT);
    """)
    if pickup == "doing":
        db.execute("INSERT INTO doing VALUES (1, 'mail', 90, 'focus')")
    else:
        db.execute("UPDATE mail_to SET opened='read'")

    class Cursor:
        def __init__(self):
            self.cur = db.cursor()

        def execute(self, sql, params=()):
            return self.cur.execute(sql.replace("%s", "?"), params)

        def fetchone(self):
            return self.cur.fetchone()

        def fetchall(self):
            return self.cur.fetchall()

        def close(self):
            self.cur.close()

    class Book:
        def cursor(self, **kw):
            return Cursor()

    office["monkeypatch"].setattr(
        opened, "picked_up_ids", lambda cn, ids, desk: picked_up_ids(Book(), ids, desk)
    )
    office["clock"]["t"] += wake.lease_s() + 1
    assert wake.post_desk(office["cn"], "away", _unread_frame(90), hint_id=90) == "none"
    assert len(_posts(office)) == 1


def test_done_preserves_new_mail_arriving_after_sync(office):
    _letter(office, 91)
    push.connect_sync_frame(office["cn"], "away")
    _letter(office, 92)
    assert wake.lease_done(office["cn"], "away") == "sent"
    assert [b["id"] for b in _posts(office)] == [91, 92]


def test_done_stops_original_wake_without_connect(office):
    _letter(office, 93)
    assert wake.lease_done(office["cn"], "away") == "none"
    assert wake.post_desk(office["cn"], "away", _unread_frame(93), hint_id=93) == "none"
    assert len(_posts(office)) == 1


def test_pending_same_letter_backs_off_then_stops(office):
    _letter(office, 94)
    wake._GATE.pop("away")
    for delay in (60, 120, 240, 480):
        office["timers"].clear()
        assert wake.post_desk(office["cn"], "away", _unread_frame(94), hint_id=94) == "deferred"
        wait, callback, args = office["timers"].pop()
        assert wait == delay
        office["clock"]["t"] += wait
        callback(*args)
        wake._GATE.pop("away")
    assert len(_posts(office)) == 5
    assert wake.post_desk(office["cn"], "away", _unread_frame(94), hint_id=94) == "none"
    assert office["timers"] == []
    assert any("wake=stuck-ring" in line for line in office["lines"])


def test_deferred_rering_is_cancelled_by_done(office):
    _letter(office, 95)
    wake._GATE["away"] -= wake.lease_s() + 1
    assert wake.post_desk(office["cn"], "away", _unread_frame(95), hint_id=95) == "deferred"
    assert wake.lease_done(office["cn"], "away") == "none"
    for delay, callback, args in office["timers"]:
        office["clock"]["t"] += delay
        callback(*args)
    assert len(_posts(office)) == 1


def test_new_letter_bypasses_exhausted_old_letter(office):
    _letter(office, 96)
    wake._RERINGS[("away", 96)]["n"] = 4
    wake._GATE.pop("away")
    assert wake.post_desk(office["cn"], "away", _unread_frame(96), hint_id=96) == "none"
    _letter(office, 97)
    assert [b["id"] for b in _posts(office)] == [96, 97]
