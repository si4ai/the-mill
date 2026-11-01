# -*- coding: utf-8 -*-
"""#831 a superseded connect must not lose the sync batch it took (spin model W05, card 830).

Seen (throwaway office, real Wall on loopback, at d1c1ae5): ws_endpoint takes the
desk's push_queue rows (connect_sync_frame -> mill_push_take deletes and commits),
then sends the sync frame (asgi.py 609-616). A newer plain connect of the same desk
sits in between and kicks the old socket (4000); the old send fails ("ws sync
fail") and the rows are gone. The new connect's sync is empty, and so is every
later one. The letter is still in mail, but the desk is never told.

Wanted: a letter whose sync frame never reached the desk still reaches it in a
later sync. The barrier sits between the take and the send, so the order is
forced, not timed.

Fixed: the sync rows are read without deleting them (hold=True) and deleted by id
only after send_text returns (ack_sync). A row is always queued, delivered, or both.
"""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.lib.observe import parse_roots
from agent_coord.server import push, wake
from agent_coord.server.asgi import make_asgi_app, uvicorn_config
from agent_coord.server.push import HUB
from agent_coord.server.records import apply, connect
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import conn_kwargs
from tests.sql_isolate import throwaway_db

pytestmark = pytest.mark.sql

# Own schema: a live Wall holds seats open; sharing mill_records_test with other
# suites under xdist -n2 lets a peer wipe wipe=True mid-test (ws auth bad token).
TEST_DB = throwaway_db("mill_sync_batch_831")
ROSTER, D1, D2 = "fx-wake", "fx-wake-d1", "fx-wake-d2"
TOK = {D1: "fx-seat-token-d1-0123456789", D2: "fx-seat-token-d2-0123456789"}

# ---- shared arrange: a real Wall on loopback over a throwaway book, real /ws clients ----


@pytest.fixture
def book(monkeypatch):
    import mysql.connector

    kw = conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    try:
        admin = mysql.connector.connect(**kw)
    except Exception as e:  # pragma: no cover - no MySQL here
        pytest.skip(f"mysql: {e}")
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    monkeypatch.setenv("AGENT_COORD_DATABASE", TEST_DB)
    c = connect(TEST_DB)
    apply(c, wipe=True)
    for n, k in ((ROSTER, "roster"), (D1, "desk"), (D2, "desk")):
        rec_name.get_or_insert(c, n, k)
    for d in (D1, D2):
        rec_join.upsert(c, ROSTER, d, "", token_hash(TOK[d]), None)
    c.commit()
    monkeypatch.setattr(HUB, "rooms", {})
    monkeypatch.setattr(wake, "_GATE", {})
    monkeypatch.setattr(wake, "_TRAIL", {})
    yield c
    c.close()


@pytest.fixture
def wall(book):
    import uvicorn

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    root = Path(__file__).resolve().parents[2]
    app = make_asgi_app(parse_roots(cwd=root), host="127.0.0.1", port=port)
    server = uvicorn.Server(uvicorn_config(app, "127.0.0.1", port))
    server.install_signal_handlers = lambda: None
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    end = time.time() + 10
    while not server.started and time.time() < end:
        time.sleep(0.02)
    assert server.started, "wall did not start"
    yield port
    server.should_exit = True
    t.join(5)


def queued(desk: str) -> list[int]:
    """Mail ids in push_queue for desk, read on a connection of its own."""
    c = connect(TEST_DB)
    try:
        cur = c.cursor()
        cur.execute(
            "SELECT JSON_EXTRACT(p.payload, '$.id') FROM push_queue p JOIN name d ON d.id = p.desk_id"
            " WHERE d.type = 'desk' AND d.name = %s AND p.kind = 'mail' ORDER BY p.id",
            (desk,),
        )
        out = [int(r[0]) for r in cur.fetchall()]
        cur.close()
        return out
    finally:
        c.close()


class Desk:
    """One real mill connect socket: /ws/<desk> with the seat token, frames kept in order."""

    def __init__(self, port: int, name: str) -> None:
        self.port, self.name, self.frames = port, name, []
        self.close_code = None

    async def up(self) -> "Desk":
        from websockets.asyncio.client import connect as ws_connect

        self.ws = await ws_connect(
            f"ws://127.0.0.1:{self.port}/ws/{self.name}",
            additional_headers={"Authorization": "Bearer " + TOK[self.name]},
        )
        self.task = asyncio.create_task(self._read())
        return self

    async def _read(self) -> None:
        try:
            async for m in self.ws:
                self.frames.append(json.loads(m))
        except Exception:
            pass
        self.close_code = self.ws.close_code

    async def wait_for(self, pred, t: float = 5.0):
        end = time.time() + t
        while time.time() < end:
            for f in self.frames:
                if pred(f):
                    return f
            await asyncio.sleep(0.02)
        return None

    async def synced(self) -> dict:
        f = await self.wait_for(lambda f: f.get("kind") == "sync")
        assert f is not None, f"{self.name}: no sync frame"
        return f

    def got(self, mail_id: int) -> bool:
        """The letter reached this socket: in a sync list or as a live frame."""
        for f in self.frames:
            if f.get("kind") == "sync" and any(
                i.get("kind") == "mail" and int(i.get("id") or 0) == mail_id for i in f.get("sync") or []
            ):
                return True
            if f.get("kind") == "mail" and int(f.get("id") or 0) == mail_id:
                return True
        return False

    async def rpc(self, rid: str, command: str, args: dict) -> dict:
        await self.ws.send(json.dumps({"id": rid, "verb": command, "args": args}))
        f = await self.wait_for(lambda f: f.get("id") == rid, 10)
        assert f is not None and f.get("ok"), f
        return f

    async def down(self) -> None:
        await self.ws.close()
        await asyncio.sleep(0.2)


def test_superseded_connect_keeps_the_batch_it_never_sent(wall, monkeypatch) -> None:
    port = wall
    orig = push.connect_sync_frame
    taken, release, seen = threading.Event(), threading.Event(), {}

    def take_then_hold(cn, desk, **kw):
        out = orig(cn, desk, **kw)
        if desk == D1 and not seen:
            seen["took"] = [int(i.get("id") or 0) for i in out["sync"] if i.get("kind") == "mail"]
            taken.set()
            release.wait(15)  # after the read, before send_text (asgi.py 612 -> 616)
        return out

    monkeypatch.setattr(push, "connect_sync_frame", take_then_hold)

    async def run() -> None:
        d2 = await Desk(port, D2).up()
        await d2.synced()
        sent = await d2.rpc("831-send", "send", {"mail_tos": [D1], "body": "a letter for d1"})
        mid = int(sent["result"]["id"])
        assert queued(D1) == [mid]

        a = await Desk(port, D1).up()  # connect A: reads the row, its send is held
        assert await asyncio.to_thread(taken.wait, 10)
        assert seen["took"] == [mid]

        b = await Desk(port, D1).up()  # connect B: plain connect, takes the seat
        await b.synced()
        release.set()
        await asyncio.sleep(1.0)
        assert a.close_code == 4000, "A was not superseded; the race did not happen"
        await b.down()

        c = await Desk(port, D1).up()  # a later connect
        await c.synced()
        await c.down()
        await d2.down()
        assert any(d.got(mid) for d in (a, b, c)), (
            "the letter's push_queue row was deleted by connect A's sync, A was superseded "
            "before its sync frame was sent, and no later sync carried it"
        )
        assert queued(D1) == [], "a sent sync frame leaves its rows queued"

    try:
        asyncio.run(run())
    finally:
        release.set()


def test_peek_leaves_rows_and_ack_deletes_only_those(book) -> None:
    from agent_coord.server.records import push as rec_push

    rec_push.put(book, D1, "mail", {"kind": "mail", "id": 901}, "missed")
    rec_push.put(book, D1, "mail", {"kind": "mail", "id": 902}, "missed")
    book.commit()
    held = rec_push.peek(book, D1)
    assert [i["id"] for i in held] == [901, 902] and len(held.ids) == 2
    assert queued(D1) == [901, 902]  # read, not deleted
    rec_push.put(book, D1, "mail", {"kind": "mail", "id": 903}, "missed")
    book.commit()
    assert rec_push.ack(book, D1, held.ids) == 2
    assert queued(D1) == [903]  # a row put after the read stays
    assert rec_push.ack(book, D1, held.ids) == 0  # a second ack is harmless

