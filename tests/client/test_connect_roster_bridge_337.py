"""The connect bridge sends its connect roster on send and reply (#337). Regression row F48 (connect-roster-stamp)."""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

from agent_coord.client import ws as ws_cli


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(ws_cli, "SITTING_BRIDGE_RETRY_WAIT_S", 0)
    monkeypatch.setitem(ws_cli.READY_ROSTER, "roster", "the-mill")


@pytest.mark.parametrize("command", ["send", "reply"])
def test_send_and_reply_get_the_connect_roster(command):
    assert ws_cli.with_connect_roster(command, {"body": "x"}) == {"body": "x", "connect_roster": "the-mill"}


@pytest.mark.parametrize("roster", ["grok-tui", " grok-tui "])
def test_explicit_roster_is_left_alone(roster):
    args = {"body": "x", "roster": roster}
    assert ws_cli.with_connect_roster("send", args) == args


@pytest.mark.parametrize("command", ["inbox", "todo", "claim", "mark", "hold"])
def test_other_commands_are_left_alone(command):
    assert ws_cli.with_connect_roster(command, {"project": "x"}) == {"project": "x"}


@pytest.mark.parametrize("named", ["", None])
def test_connect_without_a_roster_adds_nothing(monkeypatch, named):
    if named is None:
        monkeypatch.delitem(ws_cli.READY_ROSTER, "roster")
    else:
        monkeypatch.setitem(ws_cli.READY_ROSTER, "roster", named)
    assert ws_cli.with_connect_roster("send", {"body": "x"}) == {"body": "x"}


def test_input_args_are_not_mutated():
    args = {"body": "x"}
    ws_cli.with_connect_roster("send", args)
    assert args == {"body": "x"}


def test_bridge_wire_carries_connect_roster():
    """A send through the sitting bridge reaches the socket with connect_roster."""

    class FakeWS:
        def __init__(self) -> None:
            self.sent: list[str] = []
            self._q: asyncio.Queue[str] | None = None

        async def send(self, text: str) -> None:
            self.sent.append(text)
            req = json.loads(text)
            self._q.put_nowait(json.dumps({"id": req["id"], "ok": True, "result": {}}))

        async def recv(self) -> str:
            return await self._q.get()

    stop = threading.Event()
    fake = FakeWS()
    from agent_coord.server.hint_buf import HintBuf

    async def go() -> None:
        fake._q = asyncio.Queue()
        sit = asyncio.create_task(ws_cli._sit_session(fake, "DESK_alice", stop, HintBuf("DESK_alice", maxsize=8)))
        ep = None
        for _ in range(100):
            ep = ws_cli.read_rpc_bridge("DESK_alice")
            if ep:
                break
            await asyncio.sleep(0.02)
        assert ep
        for rid, args in (("r1", {"body": "x", "dst": "bob"}), ("r2", {"body": "x", "dst": "bob", "roster": "grok-tui"})):
            reader, writer = await asyncio.open_connection("127.0.0.1", int(ep["port"]))
            writer.write((json.dumps({"id": rid, "verb": "send", "args": args, "secret": ep["secret"]}) + "\n").encode())
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
    wires = [json.loads(s) for s in fake.sent]
    assert wires[0]["args"]["connect_roster"] == "the-mill"
    assert "connect_roster" not in wires[1]["args"]
