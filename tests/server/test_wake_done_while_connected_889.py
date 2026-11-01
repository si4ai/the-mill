"""#889: wake-done inside an open connect must not POST a trailing wake.

A routine run ends with mill wake-done while its mill connect is still open.
Ending the lease must not start a new cold run for a desk that is still
sitting and can drain the rows itself. Return sitting; leave / sync cover
the held-back items. Card done_when: a wake-done sent inside an open
connect never wakes that still-connected desk.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push, wake
from tests.server.test_desk_webhook_618 import _Queue, _Resp
from tests.server.webhook_fixtures import arm


@pytest.fixture
def office(monkeypatch):
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


def test_wake_done_while_sitting_does_not_post_trailing(office) -> None:
    """Lease holds items; desk still has a live /ws; wake-done ends lease, no POST."""
    assert _letter(office, 1) == "missed"
    assert _letter(office, 2) == "missed"
    assert len(_posts(office)) == 1
    # Desk is still connected (open connect around wake-done).
    office["monkeypatch"].setattr(push.HUB, "rooms", {"away": {object()}})
    assert wake.lease_done(office["cn"], "away") == "sitting"
    assert len(_posts(office)) == 1  # no trailing wake
    assert "away" not in wake._GATE
    # Next letter after the lease ended posts at once (lease cleared).
    office["monkeypatch"].setattr(push.HUB, "rooms", {})
    assert _letter(office, 3) == "missed"
    assert len(_posts(office)) == 2


def test_wake_done_while_away_still_sends_trailing(office) -> None:
    """Not sitting: existing F144 behavior - one trailing POST for held items."""
    assert _letter(office, 10) == "missed"
    assert _letter(office, 11) == "missed"
    assert wake.lease_done(office["cn"], "away") == "sent"
    assert len(_posts(office)) == 2
    assert _posts(office)[1]["wake"]["pending_count"] == 1


def test_wake_done_rpc_while_sitting_reports_sitting(office, monkeypatch) -> None:
    from agent_coord.server.api.mill import rpc

    # Take a lease with held items while away, then sit before wake-done.
    assert _letter(office, 20) == "missed"
    assert _letter(office, 21) == "missed"
    monkeypatch.setattr(push.HUB, "rooms", {"away": {object()}})
    book = MagicMock()
    book._cn = office["cn"]
    out = rpc.HANDLERS["wake-done"](book, {"verb": "wake-done", "note": "done in connect"}, "the-mill", "away")
    assert out["ok"] is True and out["wake"] == "sitting"
    assert len(_posts(office)) == 1
