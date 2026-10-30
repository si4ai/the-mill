# -*- coding: utf-8 -*-
"""Backchannel sequence: write -> activity+watchers -> WS hint -> catch-up."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql
from fastapi.testclient import TestClient

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.lib.observe import parse_roots
from agent_coord.server.records import apply, connect
from agent_coord.server.records import activity, join as here, mail, todo, watcher as watchers
from agent_coord.server.asgi import make_asgi_app
from agent_coord.server.push import HUB, fanout

from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_records_test")


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


def test_sequence_write_watchers_ws_hint_catchup(cn) -> None:
    """Mail lands on mail_to and on an activity row. It does not plant a watcher."""
    p = "seq"
    alice = "alice"
    bob = "bob"
    here.upsert(cn, p, alice, "builder", token_hash="a" * 64)
    here.upsert(cn, p, bob, "builder", token_hash="b" * 64)

    rows = mail.insert(cn, p, bob, alice, "hello backchannel")
    assert rows and rows[0].get("id")
    mid = int(rows[0]["id"])

    cur = cn.cursor()
    cur.execute(
        "SELECT 1 FROM mail_to WHERE type='mail' AND id=%s "
        "AND desk_id=(SELECT id FROM name WHERE type='desk' AND name=%s)",
        (mid, "alice"),
    )
    assert cur.fetchone()
    cur.close()
    assert any(r.get("type") == "mail" for r in activity.select(cn, limit=20))


def test_todo_open_watchers_fanout(cn) -> None:
    """W4: mill open fills watchers; fanout TODO is the same path as MAIL."""
    p = "seq"
    alice = "alice"
    here.upsert(cn, p, alice, "builder", token_hash="a" * 64)
    rows = todo.insert(cn, p, alice, "open", '{"slug":"fanout-todo"}')
    tid = int(rows[0]["id"])
    watched = watchers.select(cn, "todo", tid)
    assert watched, watched
    fanout(cn, "todo", tid, "TODO")


def test_sequence_hub_broadcast_matches_mods_hint() -> None:
    """Wire hop: Hub sends the same tiny JSON the mods sequence drew."""
    import asyncio
    import json

    class FakeWS:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_text(self, text: str) -> None:
            self.sent.append(text)

    async def go() -> None:
        fake = FakeWS()
        desk = "DESK_alice"
        await HUB.add(desk, fake)
        try:
            await HUB._broadcast(desk, {"type": "mail", "id": 100, "hint": "MAIL"})
        finally:
            HUB.discard(desk, fake)
        assert fake.sent
        msg = json.loads(fake.sent[0])
        from agent_coord.server.mill_json import mill_version

        assert msg == {
            "type": "mail",
            "id": 100,
            "hint": "MAIL",
            "mill": mill_version(),
        }

    asyncio.run(go())


def test_polling_desk_mail_is_an_activity_row(cn) -> None:
    p = "seq"
    desk = "poller"
    here.upsert(cn, p, desk, "builder", token_hash="c" * 64)
    cur = cn.cursor()
    cur.execute(
        "UPDATE seat SET delivery_mode='polling' WHERE desk_id=(SELECT id FROM name WHERE name=%s)",
        (desk,),
    )
    cn.commit()
    cur.close()
    rows = mail.insert(cn, p, desk, desk, "self")
    assert rows and int(rows[0]["id"])
    assert any(r.get("type") == "mail" for r in activity.select(cn, limit=20))


def test_fanout_pokes_connected_desk_even_if_polling() -> None:
    """A desk sitting on /ws gets the poke even when seat.delivery_mode is still polling."""
    import asyncio
    import json

    class FakeWS:
        def __init__(self) -> None:
            self.sent: list[str] = []

        async def send_text(self, text: str) -> None:
            self.sent.append(text)

    async def go() -> None:
        fake = FakeWS()
        HUB.bind_loop(asyncio.get_running_loop())
        await HUB.add("DESK_poller", fake)
        try:
            HUB.notify("DESK_poller", {"type": "mail", "id": 1, "hint": "MAIL"})
            await asyncio.sleep(0.05)
        finally:
            HUB.discard("DESK_poller", fake)
        assert fake.sent
        assert json.loads(fake.sent[0])["hint"] == "MAIL"

    asyncio.run(go())
