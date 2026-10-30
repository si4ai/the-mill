"""#669 a coalesced burst ends in one trailing POST. When a wake POST took the
window, more items coalesced inside it, and the desk has not connected by the
window's end, the wall sends exactly one more POST (pending = the queue size)
and logs it reason=trailing. None when the desk connected inside the window,
none when nothing coalesced. A join test POST carries an id and never takes or
counts toward the window. Row F-wake-trailing."""
from __future__ import annotations

import json

import pytest

from agent_coord.server import push, wake
from tests.server.webhook_fixtures import HOOK_URL, arm, opener


class _Resp:
    status = 200

    def read(self, _n: int = 0) -> bytes:
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> bool:
        return False


class _Book:
    closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def ring(monkeypatch):
    """Armed desk d1, a fake receiver, a captured window-end timer, a queue of 3."""
    arm(monkeypatch)
    monkeypatch.setattr(wake, "_TRAIL", {})
    monkeypatch.setattr("agent_coord.server.records.push.pending", lambda cn, desk: 3)
    timers: list = []
    monkeypatch.setattr(wake, "_schedule", lambda delay, fn, *args: timers.append((delay, fn, args)))
    book = _Book()
    monkeypatch.setattr(wake, "_book", lambda: book)
    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    bodies: list[dict] = []

    def receive(req, timeout):
        bodies.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    with opener(receive):
        yield {"timers": timers, "bodies": bodies, "lines": lines, "book": book}


def _window_end(timers) -> list[str]:
    return [fn(*args) for _delay, fn, args in timers]


def test_coalesced_items_ring_once_more_at_window_end(ring):
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 1}) == "sent"
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 2}) == "coalesced"
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 3}) == "coalesced"
    assert len(ring["timers"]) == 1  # one window-end check per window, not per item
    delay = ring["timers"][0][0]
    assert 0 < delay <= wake.WAKE_WINDOW_S
    assert _window_end(ring["timers"]) == ["sent"]
    assert len(ring["bodies"]) == 2
    trailing = ring["bodies"][1]
    assert trailing["wake"]["pending"] == 3  # the queue size: every item still waits
    assert trailing["id"] == 3  # the latest coalesced item
    assert ring["lines"][-1] == "webhook desk=d1 kind=mail id=3 wake=sent status=200 reason=lease-expired"
    assert ring["book"].closed


def test_a_connect_inside_the_window_sends_no_trailing_post(ring):
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 1}) == "sent"
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 2}) == "coalesced"
    wake.gate_clear("d1")  # the desk connected: its sync took the queue
    assert _window_end(ring["timers"]) == ["none"]
    assert len(ring["bodies"]) == 1


def test_a_window_with_nothing_coalesced_sends_no_trailing_post(ring):
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 1}) == "sent"
    assert ring["timers"] == []
    assert len(ring["bodies"]) == 1


def test_the_trailing_post_opens_its_own_window(ring):
    """At most one POST per window: items after the trailing POST coalesce again
    and get their own single trailing POST at that window's end."""
    wake.post_desk(object(), "d1", {"kind": "mail", "id": 1})
    wake.post_desk(object(), "d1", {"kind": "mail", "id": 2})
    first = list(ring["timers"])
    ring["timers"].clear()
    assert _window_end(first) == ["sent"]
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 4}) == "coalesced"
    assert len(ring["timers"]) == 1
    assert _window_end(ring["timers"]) == ["sent"]
    assert len(ring["bodies"]) == 3


def test_a_new_post_after_the_window_supersedes_the_trailing_one(ring):
    """An item that arrives after the window and rings on its own already woke the
    desk: the stale window-end check sends nothing more."""
    wake.post_desk(object(), "d1", {"kind": "mail", "id": 1})
    wake.post_desk(object(), "d1", {"kind": "mail", "id": 2})
    wake._GATE["d1"] -= wake.WAKE_WINDOW_S + 1  # the window passed
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 5}) == "sent"
    assert _window_end(ring["timers"][:1]) == ["none"]
    assert len(ring["bodies"]) == 2


def test_a_join_test_post_carries_an_id_and_takes_no_window(ring):
    got = wake.test_fire(HOOK_URL, "unit-key-0123456789", "d1")
    assert got["ok"] is True
    body = ring["bodies"][0]
    assert body["kind"] == "wake-test"
    assert str(body["id"]).startswith("wake-test-")
    assert "d1" not in wake._GATE
    # the first real item still rings at once
    assert wake.post_desk(object(), "d1", {"kind": "mail", "id": 1}) == "sent"
    again = wake.test_fire(HOOK_URL, "unit-key-0123456789", "d1")
    assert ring["bodies"][2]["id"] != body["id"]  # one id per test POST
    assert again["ok"] is True
