# -*- coding: utf-8 -*-
"""A desk's own /ws connect must not come back to it as a missed DOING in the sync queue.

The connect write fans out DOING before the socket sits in the Hub, so the connecting
desk used to get its own DOING recorded as missed and replayed in the connect sync.
A DOING another desk genuinely missed must still be queued for that desk.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.sql

from fastapi.testclient import TestClient

from agent_coord.client.tokens import token_hash
from agent_coord.lib.observe import parse_roots
from agent_coord.server.asgi import make_asgi_app
from agent_coord.server.push import HUB, take_sync
from agent_coord.server.records import apply, connect
from agent_coord.server.records import join as here, name, watcher as watchers
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs

from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_connect_self_join")
TOKEN = "self-join-token"


@pytest.fixture
def cn():
    import mysql.connector

    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    os.environ["AGENT_COORD_DATABASE"] = TEST_DB
    c = connect(TEST_DB)
    apply(c, wipe=True)
    yield c
    c.close()


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


def _joins(items: list[dict], jid: int) -> list[dict]:
    return [
        it
        for it in items
        if str(it.get("type") or "") == "doing" and int(it.get("id") or 0) == jid and it.get("hint") == "DOING"
    ]


def test_connect_does_not_echo_own_join_as_missed(cn, monkeypatch) -> None:
    monkeypatch.setattr(HUB, "rooms", {})
    rec = here.upsert(cn, "unit", "alice", "builder", token_hash=token_hash(TOKEN), doing="present")
    jid = int(rec[0]["id"])
    assert watchers.select(cn, "doing", jid), "alice should watch her own doing entry"
    take_sync(cn, "alice")

    client = _client(monkeypatch)
    first = _connect_sync(client, "alice")
    assert _joins(first, jid) == [], first
    second = _connect_sync(client, "alice")
    assert _joins(second, jid) == [], second


def test_connect_join_still_queued_for_other_watcher(cn, monkeypatch) -> None:
    monkeypatch.setattr(HUB, "rooms", {})
    rec = here.upsert(cn, "unit", "alice", "builder", token_hash=token_hash(TOKEN), doing="present")
    jid = int(rec[0]["id"])
    here.upsert(cn, "unit", "bob", "builder", token_hash="b" * 64, doing="present")
    watchers.put(cn, "doing", jid, int(name.get(cn, "bob", "desk")))
    take_sync(cn, "alice")
    take_sync(cn, "bob")

    client = _client(monkeypatch)
    assert _joins(_connect_sync(client, "alice"), jid) == []
    missed = _joins(take_sync(cn, "bob"), jid)
    assert missed, "bob is not sitting and should find alice's DOING in his queue"
    assert missed[0]["outcome"] == "missed"
