"""#892: reset seat / retire desk clear the wake lease.

After Admin reset (or retire desk), the next holder must not inherit a live
lease: the next wake POST is sent, not coalesced. wake.gate_clear already
exists for this; _h_reset and desk retire must call it.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from agent_coord.server import push, wake
from agent_coord.server.api.mill import rpc
from tests.server.test_desk_webhook_618 import _Queue, _Resp
from tests.server.webhook_fixtures import arm


@pytest.fixture
def office(monkeypatch):
    arm(monkeypatch)
    q = _Queue()
    q.install(monkeypatch)
    monkeypatch.setattr(push.HUB, "rooms", {})
    monkeypatch.setattr(wake, "_NOTE", {}, raising=False)
    monkeypatch.setattr(wake, "_EPOCH", {}, raising=False)
    clock = {"t": 1000.0}
    monkeypatch.setattr("time.monotonic", lambda: clock["t"])
    monkeypatch.setattr(wake, "_schedule", lambda delay, fn, *args: None)
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
            "lines": lines,
            "bodies": bodies,
            "cn": MagicMock(),
            "monkeypatch": monkeypatch,
        }


def _letter(o, n: int, desk: str = "away") -> str:
    return push.emit(o["cn"], desk, "mail", {"id": n, "body": f"letter {n}", "sender": "s"})


def _posts(o, desk: str = "away") -> list[dict]:
    return [b for b in o["bodies"] if b.get("desk") == desk]


class _B:
    def __init__(self, cn):
        self._cn = cn


def test_after_reset_seat_the_next_wake_is_sent_not_coalesced(office, monkeypatch) -> None:
    """Lease taken, reset seat, next letter POSTs (not coalesced under the old lease)."""
    assert _letter(office, 1) == "missed"
    assert len(_posts(office)) == 1
    # A second letter under the live lease coalesces.
    assert _letter(office, 2) == "missed"
    assert len(_posts(office)) == 1
    assert any("wake=coalesced reason=lease" in ln for ln in office["lines"])

    cleared: list[str] = []
    real_clear = wake.gate_clear

    def capture(desk):
        cleared.append(desk)
        return real_clear(desk)

    monkeypatch.setattr(wake, "gate_clear", capture)
    # Reset must not need a real book join: stub rec_join.reset and admin gate.
    monkeypatch.setattr(
        "agent_coord.server.records.join.reset",
        lambda cn, project, desk: [{"desk": desk, "ok": 1}],
    )
    monkeypatch.setattr(
        "agent_coord.server.records.hold.find",
        lambda cn, desk="", held=True: [],
    )
    monkeypatch.setattr(
        "agent_coord.server.admin.guard.require_admin",
        lambda cn, who: None,
    )
    out = rpc._h_reset(_B(office["cn"]), {"desk": "away"}, "Office", "admin")
    assert out["ok"] is True
    assert cleared == ["away"]

    # Next letter after reset must POST, not coalesce on the inherited lease.
    office["lines"].clear()
    assert _letter(office, 3) == "missed"
    assert len(_posts(office)) == 2
    assert _posts(office)[1]["id"] == 3
    assert not any("wake=coalesced reason=lease" in ln for ln in office["lines"])


def test_after_retire_desk_the_next_wake_is_sent_not_coalesced(office, monkeypatch) -> None:
    """Same lease inheritance bug on mill retire desk."""
    assert _letter(office, 10) == "missed"
    assert _letter(office, 11) == "missed"
    assert len(_posts(office)) == 1

    cleared: list[str] = []
    real_clear = wake.gate_clear

    def capture(desk):
        cleared.append(desk)
        return real_clear(desk)

    monkeypatch.setattr(wake, "gate_clear", capture)
    monkeypatch.setattr(
        "agent_coord.server.records.hold.find",
        lambda cn, desk="", held=True: [],
    )
    monkeypatch.setattr(
        "agent_coord.server.admin.catalog.retire",
        lambda cn, desk, body: [{"ok": 1, "name": body.get("slug") or "away"}],
    )
    # Admin retire --yes path.
    out = rpc._h_retire(
        _B(office["cn"]),
        {"slug": "away", "confirm": "away", "yes": True, "name_type": "desk"},
        "Office",
        "admin",
    )
    assert out is not None
    assert "away" in cleared

    office["lines"].clear()
    assert _letter(office, 12) == "missed"
    assert len(_posts(office)) == 2
    assert not any("wake=coalesced reason=lease" in ln for ln in office["lines"])


def test_without_gate_clear_reset_would_leave_the_lease(office) -> None:
    """Red shape: a live lease without gate_clear keeps coalescing (documents the bug)."""
    assert _letter(office, 20) == "missed"
    assert _letter(office, 21) == "missed"
    assert len(_posts(office)) == 1
    # No reset: still coalesced.
    assert _letter(office, 22) == "missed"
    assert len(_posts(office)) == 1
