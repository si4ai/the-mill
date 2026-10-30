# -*- coding: utf-8 -*-
"""Card 835: a letter to a connected desk goes over its open connection and wakes nothing.

Wakeup storms item 1 (room wakeup-storms, letter 2706); Validator's probe (2709).
Regression row F126 (connected-no-wake). Already true on 0.7.16 (live probe:
letter 2722); this guards it on the real /ws endpoint: the frame reaches the
desk's socket, its push row is settled as sent, and no webhook POST or
`webhook desk=` wake line is written.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_coord.server import push, wake
from agent_coord.server.push import HUB

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

    monkeypatch.setattr("agent_coord.server.push._mark_join_socket", lambda desk, *, up: None)
    monkeypatch.setattr("agent_coord.server.book.Book", lambda *a, **k: _Ctx())
    monkeypatch.setattr("agent_coord.server.records.join.token_matches", lambda cn, d, h: True)
    monkeypatch.setattr("agent_coord.server.records.join.note_connect", lambda cn, d: None)
    monkeypatch.setattr(
        "agent_coord.server.push.connect_sync_frame", lambda cn, d, **k: {"kind": "sync", "sync": []}
    )
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr("agent_coord.server.push._ring_after", lambda *a: None)
    monkeypatch.setattr(HUB, "rooms", {})
    root = Path(__file__).resolve().parents[2]
    with TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True)) as c:
        yield c


@pytest.mark.parametrize("reason", ["addressed", "room"])
def test_a_letter_to_a_connected_desk_rides_its_socket_and_wakes_nothing(client, monkeypatch, reason) -> None:
    from agent_coord.server.records import push as rec_push

    rows: list[tuple] = []
    settled: list[tuple] = []
    posts: list = []
    lines: list[str] = []
    monkeypatch.setattr(rec_push, "put", lambda cn, desk, kind, frame, outcome: rows.append((desk, kind, outcome)) or 77)
    monkeypatch.setattr(rec_push, "row_id", lambda r: int(r))
    monkeypatch.setattr(push, "_settle_row", lambda desk, rid, delivered: settled.append((desk, rid, delivered)))
    monkeypatch.setattr(wake, "post_desk", lambda *a, **k: posts.append(a) or "sent")
    monkeypatch.setattr(wake, "_open", lambda *a, **k: posts.append("open"))
    real_log = push._bc_log
    monkeypatch.setattr(push, "_bc_log", lambda text: lines.append(text) or real_log(text))
    with client.websocket_connect("/ws/alice", headers=HDR) as desk:
        assert json.loads(desk.receive_text())["kind"] == "sync"
        got = push.emit(object(), "alice", "mail", {"id": 2722, "sender": "builder"}, reason=reason)
        frame = json.loads(desk.receive_text())
        import time

        deadline = time.monotonic() + 2.0
        while not settled and time.monotonic() < deadline:  # the settle runs off the loop
            time.sleep(0.01)
    assert got == "sent"
    assert frame["kind"] == "mail" and frame["id"] == 2722
    assert frame["idem"] == "letter:2722:alice"
    # The row went in as missed first (#832) and the live frame settled it as sent.
    assert rows == [("alice", "mail", "missed")]
    assert settled == [("alice", 77, True)]
    assert posts == []
    assert not [t for t in lines if t.startswith("webhook desk=")]
