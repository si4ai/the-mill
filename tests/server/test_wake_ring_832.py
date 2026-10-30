# -*- coding: utf-8 -*-
"""#832 ring on leave: rows a desk never got live ring its webhook when it is not sitting.

The last socket leaving, or a live frame that found no socket, runs ring_waiting off
the event loop. ring_waiting names the newest missed hint or letter; post_desk's
window, wake_on and URL checks apply as for any other wake.
"""
from __future__ import annotations

import asyncio

import pytest

from agent_coord.server import push
from agent_coord.server import wake
from agent_coord.server.push import HUB
from agent_coord.server.records import push as rec_push


@pytest.fixture(autouse=True)
def _rooms(monkeypatch):
    monkeypatch.setattr(HUB, "rooms", {})


@pytest.fixture
def posted(monkeypatch):
    got: list[dict] = []

    def post_desk(cn, desk, frame, **k):
        got.append({"desk": desk, "frame": dict(frame), **k})
        return "sent"

    monkeypatch.setattr(wake, "post_desk", post_desk)
    return got


def test_ring_names_the_newest_waiting_letter(monkeypatch, posted) -> None:
    monkeypatch.setattr(
        rec_push, "waiting", lambda cn, d: {"id": 4, "kind": "mail", "payload": {"kind": "mail", "id": 77}}
    )
    assert push.ring_waiting(object(), "DESK_away", "leave") == "sent"
    (p,) = posted
    assert p["desk"] == "DESK_away" and p["ring"] == "leave" and p["reason"] == wake.ADDRESSED
    assert p["hint_id"] == 77 and p["frame"]["idem"] == "letter:77:DESK_away"


def test_a_room_row_rings_as_room(monkeypatch, posted) -> None:
    row = {"kind": "hint", "type": "todo", "id": 5, "hint": "TODO", rec_push.WAKE_REASON: "room"}
    monkeypatch.setattr(rec_push, "waiting", lambda cn, d: {"id": 4, "kind": "hint", "payload": row})
    push.ring_waiting(object(), "DESK_away", "unsent")
    (p,) = posted
    assert p["reason"] == wake.ROOM and rec_push.WAKE_REASON not in p["frame"]
    assert p["frame"]["idem"] == "hint:todo:5:DESK_away"


def test_no_ring_while_sitting_or_with_nothing_waiting(monkeypatch, posted) -> None:
    monkeypatch.setattr(rec_push, "waiting", lambda cn, d: None)
    assert push.ring_waiting(object(), "DESK_away", "leave") == "none"
    HUB.rooms["DESK_away"] = {object()}
    assert push.ring_waiting(object(), "DESK_away", "leave") == "sitting"
    assert posted == []


def test_last_socket_leaving_rings_and_an_earlier_one_does_not(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(push, "_off_loop", lambda fn, *a: calls.append((fn.__name__, *a)))
    monkeypatch.setattr(push, "_mark_join_socket", lambda *a, **k: None)
    a, b = object(), object()
    HUB.rooms["DESK_one"] = {a, b}
    HUB.discard("DESK_one", a)
    assert calls == []
    HUB.discard("DESK_one", b)
    assert calls == [("_ring_after", "DESK_one", "leave")]


class _WS:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def send_text(self, text: str) -> None:
        if self.fail:
            raise RuntimeError("gone")


def test_broadcast_settles_its_row(monkeypatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(push, "_off_loop", lambda fn, *a: calls.append((fn.__name__, *a)))
    monkeypatch.setattr(push, "_mark_join_socket", lambda *a, **k: None)
    HUB.rooms["DESK_one"] = {_WS()}
    asyncio.run(HUB._broadcast("DESK_one", {"kind": "mail", "id": 1}, ("DESK_one", 9)))
    assert calls == [("_settle_row", "DESK_one", 9, True)]
    calls.clear()
    HUB.rooms.clear()
    asyncio.run(HUB._broadcast("DESK_one", {"kind": "mail", "id": 1}, ("DESK_one", 9)))
    assert calls == [("_settle_row", "DESK_one", 9, False)]
    calls.clear()
    asyncio.run(HUB._broadcast("DESK_one", {"kind": "mail", "id": 1}))
    assert calls == []  # no row, nothing to settle


def test_settle_marks_sent_or_rings(monkeypatch) -> None:
    class _Ctx:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.book.Book", lambda *a, **k: _Ctx())
    marks: list[tuple] = []
    rings: list[tuple] = []
    monkeypatch.setattr(rec_push, "mark", lambda cn, rid, outcome: marks.append((rid, outcome)) or 1)
    monkeypatch.setattr(push, "ring_waiting", lambda cn, d, why: rings.append((d, why)) or "sent")
    push._settle_row("DESK_one", 9, True)
    push._settle_row("DESK_one", 9, False)
    assert marks == [(9, "sent")] and rings == [("DESK_one", "unsent")]

