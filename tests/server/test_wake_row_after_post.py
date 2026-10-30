# -*- coding: utf-8 -*-
"""#832 a woken desk must not miss a letter whose row lands after its sync (spin model W07, card 830).

Seen (throwaway office, real Wall on loopback, at d1c1ae5): emit reads HUB.rooms,
rings the desk's webhook (post_desk), and only then writes the push_queue row
(push.py 565-587; fanout 453-489 the same). When the woken run connects before
that write, its sync is empty and gate_clear drops the window; the row lands
after it, no live frame goes out (the desk was not sitting when emit looked),
no window-end timer is set and no second POST is ever made. The letter waits
until something else connects the desk.

Wanted: the letter reaches the woken desk, or the desk is rung again. The
receiver answers 2xx and starts the desk's real connect; a barrier holds the
row write until that connect has its sync, so the order is forced, not timed.

Fixed: the row is put first, as missed, and a live send that reaches a socket marks
it sent; the last socket leaving with rows still missed rings the desk again.
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
from agent_coord.server.records import push as rec_push
from agent_coord.server.records.db import conn_kwargs
from tests.sql_isolate import throwaway_db

pytestmark = pytest.mark.sql

# The process pool follows AGENT_COORD_DATABASE; share the name the other sql suites use.
TEST_DB = throwaway_db("mill_records_test")
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


HOOK_URL = "https://hooks.example.test/automations/webhook/fx832-routine"
HOOK_KEY = "fx832-key-0123456789"


class _Resp:
    status = 200

    def read(self, _n: int = 0) -> bytes:
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_a) -> bool:
        return False


def test_woken_desk_gets_a_letter_whose_row_lands_after_its_sync(wall, book, monkeypatch) -> None:
    port = wall
    monkeypatch.setenv("AGENT_COORD_WAKE_HOSTS", "hooks.example.test/automations/webhook/")
    monkeypatch.setattr(wake, "public_host", lambda host: True)
    rec_join.wake_arm(book, D1, HOOK_URL, HOOK_KEY)
    book.commit()
    posts: list[dict] = []
    timers: list[str] = []
    synced = threading.Event()
    box: dict = {}

    async def scenario() -> None:
        loop = asyncio.get_running_loop()

        async def woken_run() -> None:
            d = await Desk(port, D1).up()
            await d.synced()
            box["woken"] = d
            synced.set()

        def receiver(req, timeout):  # the routine: answers 2xx; its run connects
            posts.append(json.loads(req.data))
            asyncio.run_coroutine_threadsafe(woken_run(), loop)
            return _Resp()

        orig_put = rec_push.put

        def put_after_sync(cn, desk, kind, payload, outcome):
            if desk == D1 and kind == "mail" and posts and "held" not in box:
                # The row is written after the doorbell (push.py 587): hold it
                # until the woken connect has its sync.
                box["held"] = True
                synced.wait(15)
            return orig_put(cn, desk, kind, payload, outcome)

        monkeypatch.setattr(wake, "_open", receiver)
        monkeypatch.setattr(rec_push, "put", put_after_sync)
        monkeypatch.setattr(wake, "_schedule", lambda delay, fn, *a: timers.append(fn.__name__))

        d2 = await Desk(port, D2).up()
        await d2.synced()
        sent = await d2.rpc("832-send", "send", {"mail_tos": [D1], "body": "a letter for d1"})
        mid = int(sent["result"]["id"])
        assert await asyncio.to_thread(synced.wait, 10), "the receiver's run never connected"
        woken = box["woken"]
        await asyncio.sleep(1.5)  # the woken run sits on /ws
        await woken.down()  # and exits
        await asyncio.sleep(1.5)
        await d2.down()
        assert woken.got(mid) or len(posts) > 1 or timers, (
            "the woken connect synced before the letter's row was written; the row then "
            "waited with no live frame, no window-end timer and no second POST"
        )

    asyncio.run(scenario())


def test_desk_that_leaves_before_its_live_frame_is_rung(wall, book, monkeypatch) -> None:
    """#832 ring on leave (spin W14): emit saw the desk sitting, the desk left before
    the live frame went out. The row is queued as missed, so the last socket leaving
    (or the frame finding no socket) rings the armed desk. A barrier holds the live
    send until the desk has left."""
    port = wall
    monkeypatch.setenv("AGENT_COORD_WAKE_HOSTS", "hooks.example.test/automations/webhook/")
    monkeypatch.setattr(wake, "public_host", lambda host: True)
    rec_join.wake_arm(book, D1, HOOK_URL, HOOK_KEY)
    book.commit()
    posts: list[dict] = []
    left, at_send = threading.Event(), threading.Event()

    def receiver(req, timeout):  # answers 2xx; nothing connects
        posts.append(json.loads(req.data))
        return _Resp()

    orig_notify = push._notify_rooms

    def hold_send(rooms, frame, *a, **k):
        if frame.get("kind") == "mail" and not left.is_set():
            at_send.set()
            left.wait(15)  # emit read the desk as sitting; the send waits for it to leave
        return orig_notify(rooms, frame, *a, **k)

    monkeypatch.setattr(wake, "_open", receiver)
    monkeypatch.setattr(push, "_notify_rooms", hold_send)

    async def scenario() -> None:
        d1 = await Desk(port, D1).up()
        await d1.synced()
        d2 = await Desk(port, D2).up()
        await d2.synced()
        task = asyncio.create_task(
            d2.rpc("832-leave", "send", {"mail_tos": [D1], "body": "a letter for d1"})
        )
        assert await asyncio.to_thread(at_send.wait, 10), "emit never reached the live send"
        await d1.down()
        left.set()
        sent = await task
        mid = int(sent["result"]["id"])
        await asyncio.sleep(1.5)
        await d2.down()
        assert not d1.got(mid)
        assert queued(D1) == [mid], "the letter's row is not waiting for D1's next sync"
        assert posts, "D1 left before its live frame went out and was never rung"
        assert posts[0]["idem"] == f"letter:{mid}:{D1}"

    asyncio.run(scenario())


def test_mark_and_waiting(book) -> None:
    """#832: a row goes in missed; mark sets sent or error once; waiting names the
    newest hint or letter not had live (receipts never ring)."""
    rid = rec_push.row_id(rec_push.put(book, D1, "mail", {"kind": "mail", "id": 801}, "missed"))
    book.commit()
    assert rid > 0 and rec_push.waiting(book, D1)["payload"]["id"] == 801
    assert rec_push.mark(book, rid, "sent") == 1
    assert rec_push.waiting(book, D1) is None
    assert rec_push.mark(book, rid, "error") == 0  # only a missed row changes
    rec_push.put(book, D1, "receipt", {"kind": "receipt", "id": 802}, "missed")
    book.commit()
    assert rec_push.waiting(book, D1) is None
    rid = rec_push.row_id(rec_push.put(book, D1, "hint", {"kind": "hint", "type": "todo", "id": 9}, "missed"))
    book.commit()
    assert rec_push.mark(book, rid, "error") == 1
    assert rec_push.waiting(book, D1)["id"] == rid  # a raised live send still waits

