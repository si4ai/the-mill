"""Card 1283: a send or reply to the sender's own desk returns the letter.

The sit must not close on that letter's hint before the reply is queued.
Before the fix the bridge answered sitting socket closed, ok false, exit 1.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from agent_coord.server.hint_buf import HintBuf, _drain_one, finish_sit_exit


def _exit_code(row: dict) -> int:
    """Same gate as the client print path: ok false or an error string exits 1."""
    failed = row.get("ok") is False or bool(row.get("error"))
    return 1 if failed else 0


def test_an_open_rpc_holds_sit_exit_until_the_reply(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    stop = threading.Event()
    outcome: dict = {}
    buf = HintBuf("grok-tui")
    frame = {"type": "mail", "id": 7, "hint": "MAIL", "kind": "mail", "desk": "grok-tui"}
    monkeypatch.setattr("agent_coord.client.dispatch.dispatch_hint", lambda *a, **k: "sit-exit")
    buf.rpc_hold("r1")
    _drain_one(buf, frame, "MAIL", 0.0, False, stop, outcome)
    assert not stop.is_set()
    assert "sit_exit" not in outcome
    held = buf.rpc_release("r1")
    assert held is not None
    finish_sit_exit(buf, held[0], held[1], held[2], stop, outcome)
    assert stop.is_set()
    assert outcome.get("exit") == 0
    assert outcome.get("sit_exit", {}).get("id") == 7


def _bridge(tmp_path, monkeypatch, verb: str) -> tuple[dict, int]:
    """One borrow RPC. The office writes one letter, then hints, then replies."""
    from agent_coord.client import ws as ws_cli
    from agent_coord.server.hint_buf import _drain_one as drain_one

    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.connectors.poke", lambda vendor, frame: False)
    letters: list[dict] = []

    class FakeWS:
        def __init__(self) -> None:
            self._q: asyncio.Queue | None = None

        async def send(self, text: str) -> None:
            wire = json.loads(text)
            letters.append(wire)
            hint = {
                "type": "mail",
                "id": 7,
                "hint": "MAIL",
                "kind": "mail",
                "desk": "grok-tui",
            }
            assert self._q is not None
            self._q.put_nowait(json.dumps(hint))
            self._q.put_nowait(json.dumps({
                "id": wire["id"],
                "ok": True,
                "result": {"id": 7},
            }))

        async def recv(self) -> str:
            assert self._q is not None
            return await self._q.get()

    stop = threading.Event()
    outcome: dict = {}
    fake = FakeWS()
    buf = HintBuf("grok-tui", maxsize=8)
    orig = buf.put_recv

    def put_and_drain(msg: dict) -> None:
        orig(msg)
        frame = buf.q.get_nowait()
        drain_one(buf, frame, str(frame.get("hint") or ""), 0.0, False, stop, outcome)

    buf.put_recv = put_and_drain

    async def go() -> dict:
        fake._q = asyncio.Queue()
        sit = asyncio.create_task(ws_cli._sit_session(fake, "grok-tui", stop, buf, outcome=outcome))
        ep = None
        for _ in range(100):
            ep = ws_cli.read_rpc_bridge("grok-tui")
            if ep:
                break
            await asyncio.sleep(0.02)
        assert ep
        reader, writer = await asyncio.open_connection("127.0.0.1", int(ep["port"]))
        req = {
            "id": "r1",
            "verb": verb,
            "args": {"dst": "office"} if verb == "send" else {"mail_id": 7},
            "secret": ep["secret"],
            "borrow": 1,
        }
        writer.write((json.dumps(req) + "\n").encode("utf-8"))
        await writer.drain()
        raw = await asyncio.wait_for(reader.readline(), timeout=5.0)
        writer.close()
        stop.set()
        sit.cancel()
        try:
            await sit
        except asyncio.CancelledError:
            pass
        return json.loads(raw.decode("utf-8"))

    reply = asyncio.run(go())
    return reply, len(letters)


@pytest.mark.parametrize("verb", ["send", "reply"])
def test_self_hint_returns_one_letter_and_exit_0(tmp_path, monkeypatch, verb):
    reply, n = _bridge(tmp_path, monkeypatch, verb)
    assert n == 1
    assert reply.get("ok") is True
    assert reply.get("result", {}).get("id") == 7
    assert "sitting socket closed" not in json.dumps(reply)
    assert _exit_code(reply) == 0
