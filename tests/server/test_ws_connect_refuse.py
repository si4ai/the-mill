# -*- coding: utf-8 -*-
"""Card #332: mill connect -r/--refuse does not take a seat another live /ws holds.

Regression row F43 (connect-refuse). The check is in Hub.add, so two connects
cannot both pass it. Without the flag the newest connect still replaces the older.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from agent_coord.server.push import HUB, WS_IN_USE, WS_REPLACED, Hub


class _FakeWS:
    def __init__(self, name: str = "") -> None:
        self.name = name
        self.sent: list[str] = []
        self.closed: list[int] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000) -> None:
        self.closed.append(code)


class _State:
    def __init__(self, name: str) -> None:
        self.name = name


@pytest.fixture
def marks(monkeypatch):
    seen: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "agent_coord.server.push._mark_join_socket",
        lambda desk, *, up: seen.append((desk, up)),
    )
    return seen


def test_refuse_while_holder_live_keeps_holder(marks) -> None:
    hub = Hub()
    old, new = _FakeWS("old"), _FakeWS("new")

    async def go():
        assert await hub.add("DESK_alice", old) is None
        return await hub.add("DESK_alice", new, refuse=True)

    held = asyncio.run(go())
    assert held is not None
    assert held["desk"]
    assert held["since"]
    assert hub.rooms.get("DESK_alice") == {old}
    assert old.closed == [] and old.sent == []
    assert new.closed == [] and new.sent == []
    assert marks == [("DESK_alice", True)]


def test_refuse_sits_when_holder_gone(marks) -> None:
    hub = Hub()
    old, new = _FakeWS("old"), _FakeWS("new")

    async def go():
        await hub.add("DESK_alice", old)
        hub.discard("DESK_alice", old)
        return await hub.add("DESK_alice", new, refuse=True)

    assert asyncio.run(go()) is None
    assert hub.rooms.get("DESK_alice") == {new}


def test_refuse_sits_when_holder_socket_already_disconnected(marks) -> None:
    """A dead socket the hub has not discarded yet does not block the seat."""
    hub = Hub()
    old, new = _FakeWS("old"), _FakeWS("new")

    async def go():
        await hub.add("DESK_alice", old)
        old.client_state = _State("DISCONNECTED")
        return await hub.add("DESK_alice", new, refuse=True)

    assert asyncio.run(go()) is None
    assert hub.rooms.get("DESK_alice") == {new}
    assert old.closed == []


def test_refuse_on_empty_seat_sits(marks) -> None:
    hub = Hub()
    ws = _FakeWS("only")
    assert asyncio.run(hub.add("DESK_alice", ws, refuse=True)) is None
    assert hub.rooms.get("DESK_alice") == {ws}
    assert marks == [("DESK_alice", True)]


def test_no_flag_still_replaces(marks) -> None:
    hub = Hub()
    old, new = _FakeWS("old"), _FakeWS("new")

    async def go():
        await hub.add("DESK_alice", old)
        return await hub.add("DESK_alice", new)

    assert asyncio.run(go()) is None
    assert hub.rooms.get("DESK_alice") == {new}
    assert old.closed == [WS_REPLACED]


# --- the /ws endpoint: ?refuse=1 closes the newcomer with WS_IN_USE ---------


@pytest.fixture
def client(monkeypatch, marks):
    from fastapi.testclient import TestClient

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    class _Ctx:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    joins: list[str] = []
    monkeypatch.setattr("agent_coord.server.book.Book", lambda *a, **k: _Ctx())
    monkeypatch.setattr("agent_coord.server.records.join.token_matches", lambda cn, d, h: True)
    monkeypatch.setattr("agent_coord.server.records.join.note_connect", lambda cn, d: joins.append(d))
    monkeypatch.setattr(
        "agent_coord.server.push.connect_sync_frame", lambda cn, d, **k: {"kind": "sync", "sync": []}
    )
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr(HUB, "rooms", {})
    root = Path(__file__).resolve().parents[2]
    c = TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))
    c.joins = joins
    return c


HDR = {"authorization": "Bearer seat"}


def test_ws_refuse_closes_newcomer_with_in_use(client) -> None:
    with client.websocket_connect("/ws/alice", headers=HDR) as first:
        assert json.loads(first.receive_text())["kind"] == "sync"
        with client.websocket_connect("/ws/alice?refuse=1", headers=HDR) as second:
            with pytest.raises(WebSocketDisconnect) as ei:
                second.receive_text()
        assert ei.value.code == WS_IN_USE
        assert "seat in use" in ei.value.reason
        assert "alice" in ei.value.reason
        assert "since" in ei.value.reason
        assert len(HUB.rooms.get("alice") or ()) == 1
    # The refused connect is not recorded as a connect.
    assert client.joins == ["alice"]


def test_ws_refuse_sits_on_a_free_seat(client) -> None:
    with client.websocket_connect("/ws/alice?refuse=1", headers=HDR) as ws:
        assert json.loads(ws.receive_text())["kind"] == "sync"
        assert len(HUB.rooms.get("alice") or ()) == 1


def test_ws_refuse_reason_fits_the_close_frame(client, monkeypatch) -> None:
    """A close reason is at most 123 UTF-8 bytes; a long non-ASCII desk still gets 4409."""
    long_desk = "\u00e9" * 100

    async def _held(desk, ws, *, refuse=False):
        return {"desk": long_desk, "since": "2026-10-19T23:00:00Z"}

    monkeypatch.setattr(HUB, "add", _held)
    with client.websocket_connect("/ws/alice?refuse=1", headers=HDR) as ws:
        with pytest.raises(WebSocketDisconnect) as ei:
            ws.receive_text()
    assert ei.value.code == WS_IN_USE
    assert len(ei.value.reason.encode("utf-8")) <= 123
    assert ei.value.reason.startswith("seat in use: ")
