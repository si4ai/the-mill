# -*- coding: utf-8 -*-
"""#831 the command reply's sync rows are deleted only after the reply is sent.

ws_endpoint passes an acks list to _ws_handle_client_text. The reply's sync is read
with hold=True (rows stay queued) and its row ids land in acks. ws_endpoint deletes
them after send_text returns. Without acks (older callers) the read still deletes.

SPIN W23: sync take then send; rows survive a failed send (card 831).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server import asgi as asgi_mod
from agent_coord.server import push
from agent_coord.server.api.mill import rpc
from agent_coord.server.push import HUB
from agent_coord.server.records import push as rec_push


class _WS:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)


class _Book:
    _cn = object()

    def resolve_bearer(self, token: str) -> str:
        return "alice"


@pytest.fixture
def seated(monkeypatch):
    class _Ctx:
        def __enter__(self):
            return _Book()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.book.Book", lambda *a, **k: _Ctx())
    monkeypatch.setitem(rpc.HANDLERS, "inbox", lambda c, body, project, owner: [])
    calls: list[str] = []

    def peek(cn, desk):
        calls.append("peek")
        out = rec_push.Held([{"kind": "mail", "id": 5}])
        out.ids = (11, 12)
        return out

    def take(cn, desk):
        calls.append("take")
        return [{"kind": "mail", "id": 5}]

    monkeypatch.setattr(rec_push, "peek", peek)
    monkeypatch.setattr(rec_push, "take", take)
    ws = _WS()
    HUB.rooms.clear()
    HUB.rooms.setdefault("alice", set()).add(ws)
    yield ws, calls
    HUB.rooms.clear()


def _ask(ws, acks):
    raw = json.dumps({"id": "r831", "verb": "inbox", "args": {"project": "the-mill"}})
    return asyncio.run(asgi_mod._ws_handle_client_text("alice", ws, raw, acks))


def test_reply_sync_is_held_and_its_ids_are_returned(seated) -> None:
    ws, calls = seated
    acks: list = []
    reply = _ask(ws, acks)
    assert reply["sync"] == [{"kind": "mail", "id": 5}]
    assert calls == ["peek"] and acks == [11, 12]


def test_without_acks_the_read_still_deletes(seated) -> None:
    ws, calls = seated
    reply = _ask(ws, None)
    assert reply["sync"] == [{"kind": "mail", "id": 5}] and calls == ["take"]


def test_failed_reply_sync_is_held_too(seated, monkeypatch) -> None:
    ws, calls = seated

    def boom(*a, **k):
        raise CoordError("handler failed")

    monkeypatch.setattr(rpc, "dispatch_ws", boom)
    acks: list = []
    reply = _ask(ws, acks)
    assert reply["ok"] is False and acks == [11, 12] and calls == ["peek"]


def test_sync_ids_of_a_plain_list_is_empty() -> None:
    assert push.sync_ids([{"kind": "mail"}]) == []
    held = rec_push.Held([])
    held.ids = (3,)
    assert push.sync_ids(held) == [3]
