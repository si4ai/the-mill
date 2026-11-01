# -*- coding: utf-8 -*-
"""Card 985: a sitting /ws desk must stay alive on the hub without RPC heartbeats."""
from __future__ import annotations

from datetime import datetime, timedelta

from agent_coord.lib.observe import HEARTBEAT_STALE_S, heartbeat_flags
from agent_coord.server import asgi as asgi_mod


def test_stale_heartbeat_alone_is_not_alive() -> None:
    now = datetime(2026, 11, 1, 9, 0, 0)
    old = now - timedelta(seconds=HEARTBEAT_STALE_S + 1)
    assert heartbeat_flags(old, now=now) == (False, True)


def test_touch_sitting_desks_bumps_each_room_desk(monkeypatch) -> None:
    """The hub ping loop must bump seat.updated for every sitting desk (card 985)."""
    touched: list[str] = []

    class FakeBook:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        @property
        def _cn(self):
            return object()

    def fake_touch(cn, project, desk):
        touched.append(desk)
        return [{"id": 1}]

    monkeypatch.setattr("agent_coord.server.book.Book", FakeBook)
    monkeypatch.setattr("agent_coord.server.records.join.touch", fake_touch)

    assert hasattr(asgi_mod, "touch_sitting_desks")
    asgi_mod.touch_sitting_desks(["grok-tui", "builder"])
    assert touched == ["grok-tui", "builder"]


def test_heartbeat_flags_with_sitting_override() -> None:
    """sitting=True keeps alive even when seat.updated is old (card 985)."""
    now = datetime(2026, 11, 1, 9, 0, 0)
    old = now - timedelta(seconds=HEARTBEAT_STALE_S + 60)
    alive, stale = heartbeat_flags(old, now=now, sitting=True)
    assert alive is True and stale is False
    alive2, stale2 = heartbeat_flags(old, now=now, sitting=False)
    assert alive2 is False and stale2 is True
