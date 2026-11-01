# -*- coding: utf-8 -*-
"""#949 replay unread on connect / wake-done.

Mail stored while no connect-wait sits (send outcome missed) must wake the next
connect-wait. A short connect that drains the push queue without opening the
letter must not leave the desk dark: the next connect sync resurfaces unread
mailbox mail, and wake-done / leave ring again when unread remains.

Related: #826 (push-at-leave). Row F-replay-unread.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push, wake
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


def test_c_wake_done_with_unread_remaining_refires_webhook(office) -> None:
    """(c) wake-done with push drained but mailbox unread remaining refires."""
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
    assert wake.lease_done(office["cn"], "away") == "sent"
    got = _posts(office)
    assert len(got) == 2
    assert got[1]["id"] == 51
    assert got[1]["wake"].get("pending_count", 0) >= 1


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
