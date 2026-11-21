# -*- coding: utf-8 -*-
"""Card 1242: a --desk borrow tells the office it is a borrow (tests/client/test_seat_1080.py);
a sitting connect does not, and the local bridge forwards only the mark it was given."""
from __future__ import annotations

from agent_coord.client.seat import session


def test_sitting_connect_call_is_not_a_borrow(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(session, "look", lambda: type("S", (), {"kind": "sitting", "desk": "hookdesk"})())
    monkeypatch.setattr(
        "agent_coord.client.ws.mill_ws_call",
        lambda body, **kw: seen.append({"body": dict(body), **kw}) or {"ok": True},
    )
    session.command({"verb": "inbox"})
    assert seen and not seen[0].get("borrow")


def _bridge_wire(tmp_path, monkeypatch, extra: dict) -> dict:
    """Send one request through a sitting bridge; return the frame put on the /ws."""
    import asyncio
    import json
    import threading

    from agent_coord.client import ws as ws_cli
    from agent_coord.server.hint_buf import HintBuf

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))

    class FakeWS:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self._q = None

        async def send(self, text: str) -> None:
            self.sent.append(text)
            self._q.put_nowait(json.dumps({"id": json.loads(text)["id"], "ok": True, "result": []}))

        async def recv(self) -> str:
            return await self._q.get()

    stop = threading.Event()
    fake = FakeWS()
    buf = HintBuf("hookdesk", maxsize=8)

    async def go() -> None:
        fake._q = asyncio.Queue()
        sit = asyncio.create_task(ws_cli._sit_session(fake, "hookdesk", stop, buf))
        ep = None
        for _ in range(100):
            ep = ws_cli.read_rpc_bridge("hookdesk")
            if ep:
                break
            await asyncio.sleep(0.02)
        assert ep
        reader, writer = await asyncio.open_connection("127.0.0.1", int(ep["port"]))
        req = {"id": "r1", "verb": "inbox", "args": {}, "secret": ep["secret"], **extra}
        writer.write((json.dumps(req) + "\n").encode("utf-8"))
        await writer.drain()
        await asyncio.wait_for(reader.readline(), timeout=5.0)
        writer.close()
        stop.set()
        sit.cancel()
        try:
            await sit
        except asyncio.CancelledError:
            pass

    asyncio.run(go())
    assert len(fake.sent) == 1
    return json.loads(fake.sent[0])


def test_bridge_forwards_the_borrow_mark(tmp_path, monkeypatch):
    assert _bridge_wire(tmp_path, monkeypatch, {"borrow": 1}).get("borrow") == 1


def test_bridge_adds_no_borrow_mark_on_its_own(tmp_path, monkeypatch):
    assert "borrow" not in _bridge_wire(tmp_path, monkeypatch, {})
