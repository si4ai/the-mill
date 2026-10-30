# -*- coding: utf-8 -*-
"""Card #332: client side of mill connect -r/--refuse. Regression row F43 (connect-refuse).

Card 834 (F125) made refusing the default and a busy seat exit 0; `--take` takes it.
"""
from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client import ws as ws_cli


class _Rcvd:
    def __init__(self, code: int, reason: str = "") -> None:
        self.code = code
        self.reason = reason


class ConnectionClosedError(Exception):
    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(f"received {code} ({reason})")
        self.rcvd = _Rcvd(code, reason)


class FakeWS:
    def __init__(self, fail: BaseException) -> None:
        self.fail = fail

    async def send(self, text: str) -> None:
        pass

    async def recv(self) -> str:
        raise self.fail


REASON = "seat in use: alice since 2026-10-19T23:00:00Z"


@pytest.fixture(autouse=True)
def _mill_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    # _sit_session prints the ready line once per desk per process; keep that set local.
    monkeypatch.setattr(ws_cli, "_READY_DESKS", set())
    monkeypatch.setattr(ws_cli, "BUSY_SETTLE_S", ())
    yield


@pytest.mark.parametrize("command", ["connect", "connect-wait"])
def test_refuse_flag_parses(command: str) -> None:
    p = _build_parser()
    assert p.parse_args([command, "alice", "-r"]).refuse is True
    assert p.parse_args([command, "alice", "--refuse"]).refuse is True
    assert p.parse_args([command, "alice"]).refuse is True  # card 834: the default
    assert p.parse_args([command, "alice", "--take"]).refuse is False


def test_refuse_adds_query_param() -> None:
    url = "wss://wall.example.com/ws/alice"
    assert ws_cli.refuse_url(url, False) == url
    assert ws_cli.refuse_url(url, True) == url + "?refuse=1"


def test_in_use_close_is_terminal_with_distinct_exit(capsys) -> None:
    stop = threading.Event()
    outcome: dict = {}

    async def reopen():
        raise AssertionError("a refused connect must not reconnect")

    async def go() -> None:
        fake = FakeWS(ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON))
        await ws_cli._sit_session(fake, "alice", stop, None, reconnect=reopen, outcome=outcome)

    asyncio.run(go())
    assert outcome["exit"] == 0  # card 834: busy is not an error
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["busy"] is True
    assert "since 2026-10-19T23:00:00Z" in line["next"]
    # Names the command that does take the seat.
    assert "mill connect --take alice" in line["next"]
    assert ws_cli.reconnect_stopped(ws_cli.WS_IN_USE_CLOSE, {}) is True


def test_connect_wait_refused_returns_in_use_with_exit(monkeypatch) -> None:
    def _run(coro):
        coro.close()
        raise ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON)

    monkeypatch.setattr(asyncio, "run", _run)
    got = ws_cli.wait_one_hint("alice", "seat", refuse=True)
    assert got["ok"] is False
    assert got["exit"] == 0
    assert got["busy"] is True
    assert "mill connect --take alice" in got["next"]


def test_connect_wait_exits_with_the_in_use_code(monkeypatch, capsys) -> None:
    from agent_coord.client.http import mill_here_over_http

    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat")
    seen: dict = {}

    def _wait(desk, token, **kw):
        seen.update(kw)
        return {"ok": False, "error": "seat in use", "desk": desk, "exit": 6}

    monkeypatch.setattr("agent_coord.client.ws.wait_one_hint", _wait)
    args = SimpleNamespace(cmd="connect", desk="alice", project="", vendor="", session="",
                           foreground=True, refuse=True)
    assert mill_here_over_http(args) == 6
    assert seen["refuse"] is True


def test_plain_connect_passes_refuse_to_the_socket(monkeypatch) -> None:
    from agent_coord.client import http as http_cli

    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat")
    seen: dict = {}

    def _start(who, tok, stop, outcome, refuse=False):
        seen["refuse"] = refuse
        outcome["exit"] = 6
        stop.set()

    monkeypatch.setattr("agent_coord.client.ws.start_ws_thread", _start)
    monkeypatch.setattr(http_cli, "check_project_on_socket", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.client.ws.hold_sync_lines", lambda: None)
    args = SimpleNamespace(cmd="connect", desk="alice", project="Office", vendor="", session="",
                           foreground=False, refuse=True)
    assert http_cli.mill_here_over_http(args) == 6
    assert seen["refuse"] is True


def test_refused_connect_leaves_the_local_holder_bridge(monkeypatch, capsys) -> None:
    """Holder and connect -r on one computer share the bridge file: a refusal must not touch it."""
    holder = ws_cli.write_rpc_bridge("alice", port=40001, secret="holder", pid=1, parent_pid=1)
    before = holder.read_text(encoding="utf-8")

    class _Refused:
        async def recv(self):
            raise ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON)

        async def send(self, text):
            pass

    class _CM:
        async def __aenter__(self):
            return _Refused()

        async def __aexit__(self, *a):
            return False

    seen: list[str] = []

    def _connect(url, **kw):
        seen.append(url)
        return _CM()

    monkeypatch.setattr(ws_cli, "mill_ws_url", lambda desk: "ws://127.0.0.1/ws/alice")
    monkeypatch.setattr("websockets.connect", _connect)
    stop = threading.Event()
    outcome: dict = {}
    ws_cli.run_ws_loop("alice", "seat", stop, None, outcome, True)
    assert seen == ["ws://127.0.0.1/ws/alice?refuse=1"]
    assert outcome["exit"] == 0
    assert holder.read_text(encoding="utf-8") == before
    assert '"ready"' not in capsys.readouterr().out


class _Seq:
    """A socket whose recv raises one close, or blocks until stop when fail is None."""

    def __init__(self, fail, stop):
        self.fail, self.stop = fail, stop

    async def send(self, text):
        pass

    async def recv(self):
        if self.fail is not None:
            raise self.fail
        import asyncio as _a

        while not self.stop.is_set():
            await _a.sleep(0.01)
        raise ConnectionClosedError(1000, "")


@pytest.fixture
def _fast_retry(monkeypatch):
    monkeypatch.setattr(ws_cli, "reconnect_delay_s", lambda attempt, jitter=None: 0.0)
    monkeypatch.setattr(ws_cli, "retry_notice_seconds", lambda delay: 0)


def test_reconnect_retries_4409_from_its_own_stale_socket(_fast_retry, capsys) -> None:
    """#336: after a drop, a 4409 inside the stale-socket window is retried, not exit 6."""
    stop = threading.Event()
    outcome: dict = {}
    socks = [ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON), None]
    calls: list[int] = []

    async def reopen():
        calls.append(1)
        fail = socks.pop(0)
        if fail is None:
            asyncio.get_running_loop().call_later(0.05, stop.set)
        return _Seq(fail, stop)

    async def go() -> None:
        first = _Seq(ConnectionClosedError(1012, "restart"), stop)
        await ws_cli._sit_session(first, "alice", stop, None, reconnect=reopen, outcome=outcome)

    asyncio.run(go())
    assert calls == [1, 1]
    assert "exit" not in outcome
    assert "seat in use" not in capsys.readouterr().out


def test_reconnect_4409_after_the_window_is_busy(_fast_retry, monkeypatch, capsys) -> None:
    monkeypatch.setattr(ws_cli, "_STALE_SEAT_S", 0.0)
    stop = threading.Event()
    outcome: dict = {}

    async def reopen():
        return _Seq(ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON), stop)

    async def go() -> None:
        first = _Seq(ConnectionClosedError(1012, "restart"), stop)
        await ws_cli._sit_session(first, "alice", stop, None, reconnect=reopen, outcome=outcome)

    asyncio.run(go())
    assert outcome["exit"] == 0
    assert '"busy": true' in capsys.readouterr().out


def test_first_sit_4409_is_not_retried(_fast_retry) -> None:
    stop = threading.Event()
    outcome: dict = {}

    async def reopen():
        raise AssertionError("a refused first sit must not reconnect")

    async def go() -> None:
        first = _Seq(ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON), stop)
        await ws_cli._sit_session(first, "alice", stop, None, reconnect=reopen, outcome=outcome)

    asyncio.run(go())
    assert outcome["exit"] == 0
