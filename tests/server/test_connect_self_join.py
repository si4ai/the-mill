# -*- coding: utf-8 -*-
"""A desk's own /ws connect must not come back to it as a missed DOING in the sync queue.

Card 1207: a connect writes no doing row and fans out no DOING, so neither the
connecting desk nor another desk finds a DOING from it in the sync queue.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.sql

from fastapi.testclient import TestClient

from agent_coord.client.tokens import token_hash
from agent_coord.lib.observe import parse_roots
from agent_coord.server.asgi import make_asgi_app
from agent_coord.server.push import HUB, take_sync
from agent_coord.server.records import join as here
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs

TOKEN = "self-join-token"

def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    root = Path(__file__).resolve().parents[2]
    return TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))

def _connect_sync(client: TestClient, desk: str) -> list[dict]:
    with client.websocket_connect(f"/ws/{desk}", headers={"authorization": f"Bearer {TOKEN}"}) as ws:
        frame = json.loads(ws.receive_text())
    assert frame.get("kind") == "sync", frame
    return list(frame.get("sync") or [])

def _joins(items: list[dict]) -> list[dict]:
    return [it for it in items if str(it.get("type") or "") == "doing" and it.get("hint") == "DOING"]

def test_connect_does_not_echo_own_join_as_missed(cn, monkeypatch) -> None:
    monkeypatch.setattr(HUB, "rooms", {})
    here.upsert(cn, "unit", "alice", "builder", token_hash=token_hash(TOKEN))
    take_sync(cn, "alice")

    client = _client(monkeypatch)
    first = _connect_sync(client, "alice")
    assert _joins(first) == [], first
    second = _connect_sync(client, "alice")
    assert _joins(second) == [], second

def test_connect_queues_no_doing_for_another_desk(cn, monkeypatch) -> None:
    monkeypatch.setattr(HUB, "rooms", {})
    here.upsert(cn, "unit", "alice", "builder", token_hash=token_hash(TOKEN))
    here.upsert(cn, "unit", "bob", "builder", token_hash="b" * 64)
    take_sync(cn, "alice")
    take_sync(cn, "bob")

    client = _client(monkeypatch)
    assert _joins(_connect_sync(client, "alice")) == []
    assert _joins(take_sync(cn, "bob")) == []
