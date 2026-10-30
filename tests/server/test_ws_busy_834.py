# -*- coding: utf-8 -*-
"""Card 834, server side. Regression row F125 (connect-busy).

Validator's condition (letter 2709): a refused (busy) connect drains nothing, and
the session holding the seat still gets the letter that caused the refused wake.
The wake hint names `mill connect -r DESK` and says what busy means.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.websockets import WebSocketDisconnect

from agent_coord.server import wake
from agent_coord.server.push import HUB, WS_IN_USE

HDR = {"authorization": "Bearer seat"}


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app

    class _Ctx:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    drained: list[str] = []

    def _sync(cn, desk, **k):
        drained.append(desk)
        return {"kind": "sync", "sync": []}

    monkeypatch.setattr("agent_coord.server.push._mark_join_socket", lambda desk, *, up: None)
    monkeypatch.setattr("agent_coord.server.book.Book", lambda *a, **k: _Ctx())
    monkeypatch.setattr("agent_coord.server.records.join.token_matches", lambda cn, d, h: True)
    monkeypatch.setattr("agent_coord.server.records.join.note_connect", lambda cn, d: None)
    monkeypatch.setattr("agent_coord.server.push.connect_sync_frame", _sync)
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr("agent_coord.server.push._settle_row", lambda *a: None)
    monkeypatch.setattr("agent_coord.server.push._ring_after", lambda *a: None)
    monkeypatch.setattr(HUB, "rooms", {})
    root = Path(__file__).resolve().parents[2]
    with TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True)) as c:
        c.drained = drained
        yield c


def test_busy_connect_drains_nothing_and_the_holder_gets_the_letter(client, monkeypatch) -> None:
    from agent_coord.server import push
    from agent_coord.server.records import push as rec_push

    monkeypatch.setattr(rec_push, "put", lambda cn, desk, kind, frame, outcome: 41)
    monkeypatch.setattr(rec_push, "row_id", lambda r: int(r))
    posts: list = []
    monkeypatch.setattr(wake, "post_desk", lambda *a, **k: posts.append(a) or "sent")
    with client.websocket_connect("/ws/alice?refuse=1", headers=HDR) as holder:
        assert json.loads(holder.receive_text())["kind"] == "sync"
        with client.websocket_connect("/ws/alice?refuse=1", headers=HDR) as woken:
            with pytest.raises(WebSocketDisconnect) as ei:
                woken.receive_text()
        assert ei.value.code == WS_IN_USE
        # Only the holder's connect read the queue.
        assert client.drained == ["alice"]
        assert push.emit(object(), "alice", "mail", {"id": 2706, "sender": "builder"}) == "sent"
        frame = json.loads(holder.receive_text())
        assert frame["id"] == 2706 and frame["kind"] == "mail"
    assert posts == []


def test_the_wake_hint_names_refuse_and_busy() -> None:
    body = wake.wake_body("alice", {"kind": "mail", "id": 7}, pending=1)
    nxt = body["wake"]["next"]
    assert "mill connect -r alice" in nxt
    assert "busy" in nxt and "another session has the seat" in nxt and "stop" in nxt
