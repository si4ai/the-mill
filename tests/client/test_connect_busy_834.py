# -*- coding: utf-8 -*-
"""Card 834: a connect to a held seat is refused as busy and exits 0. Regression row F125 (connect-busy).

Wakeup storms item 3 (room wakeup-storms, letter 2706). Before, a plain connect took
the seat and the working holder exited 5 (superseded); woken sessions did that to
the session already working. Now connect and connect-wait refuse by default, the
refused session exits 0 with one busy line, and `--take` takes a dead seat.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
from types import SimpleNamespace

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client import ws as ws_cli

REASON = "seat in use: alice since 2026-10-19T23:00:00Z"


class _Rcvd:
    def __init__(self, code: int, reason: str = "") -> None:
        self.code = code
        self.reason = reason


class ConnectionClosedError(Exception):
    def __init__(self, code: int, reason: str = "") -> None:
        super().__init__(f"received {code} ({reason})")
        self.rcvd = _Rcvd(code, reason)


@pytest.fixture(autouse=True)
def _mill_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(ws_cli, "_READY_DESKS", set())
    monkeypatch.setattr(ws_cli, "BUSY_SETTLE_S", (0.0, 0.0), raising=False)
    yield


@pytest.mark.parametrize("command", ["connect", "connect-wait"])
def test_connect_refuses_by_default_and_take_takes(command: str) -> None:
    p = _build_parser()
    assert p.parse_args([command, "alice"]).refuse is True
    assert p.parse_args([command, "alice", "-r"]).refuse is True
    assert p.parse_args([command, "alice", "--take"]).refuse is False


def _busy_line(out: str) -> dict:
    rows = [json.loads(x) for x in out.strip().splitlines() if x.startswith("{")]
    hits = [r for r in rows if r.get("busy")]
    assert len(hits) == 1, rows
    return hits[0]


def test_refused_first_sit_exits_0_with_one_busy_line(capsys) -> None:
    stop = threading.Event()
    outcome: dict = {}

    class _Refused:
        async def recv(self):
            raise ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON)

        async def send(self, text):
            pass

    async def reopen():
        raise AssertionError("a busy first sit does not reconnect")

    asyncio.run(ws_cli._sit_session(_Refused(), "alice", stop, None, reconnect=reopen, outcome=outcome))
    assert outcome["exit"] == 0
    line = _busy_line(capsys.readouterr().out)
    assert line["desk"] == "alice"
    assert "another session has the seat" in line["next"]
    assert "stop" in line["next"]
    assert "--take" in line["next"]
    assert "since 2026-10-19T23:00:00Z" in line["next"]


class _CM:
    def __init__(self, sock):
        self.sock = sock

    async def __aenter__(self):
        return self.sock

    async def __aexit__(self, *a):
        return False


class _Sock:
    def __init__(self, fail, stop):
        self.fail, self.stop = fail, stop

    async def send(self, text):
        pass

    async def recv(self):
        if self.fail is not None:
            raise self.fail
        while not self.stop.is_set():
            await asyncio.sleep(0.01)
        raise ConnectionClosedError(1000, "")


def _patch_connect(monkeypatch, socks, stop, seen):
    def _connect(url, **kw):
        seen.append(url)
        return _CM(_Sock(socks.pop(0), stop))

    monkeypatch.setattr(ws_cli, "mill_ws_url", lambda desk: "ws://127.0.0.1/ws/alice")
    monkeypatch.setattr("websockets.connect", _connect)


def test_busy_connect_exits_0_and_leaves_a_busy_note(monkeypatch, capsys) -> None:
    stop = threading.Event()
    outcome: dict = {}
    seen: list[str] = []
    refused = [ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON) for _ in range(3)]
    _patch_connect(monkeypatch, refused, stop, seen)
    ws_cli.run_ws_loop("alice", "seat", stop, None, outcome, True)
    # Two short settle retries, then busy: a holder that just closed is not busy.
    assert len(seen) == 3 and all(u.endswith("?refuse=1") for u in seen)
    assert outcome["exit"] == 0
    assert '"ready"' not in capsys.readouterr().out
    note = ws_cli.busy_for_parent(ws_cli._shell_ppid())
    assert note and "another session has the seat" in note


def test_a_holder_that_just_closed_is_not_busy(monkeypatch, capsys) -> None:
    stop = threading.Event()
    outcome: dict = {}
    seen: list[str] = []
    socks = [ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON), None]
    _patch_connect(monkeypatch, socks, stop, seen)
    threading.Timer(0.5, stop.set).start()
    ws_cli.run_ws_loop("alice", "seat", stop, None, outcome, True)
    assert len(seen) == 2
    assert outcome.get("exit") in (None, 0)
    assert "busy" not in capsys.readouterr().out
    assert ws_cli.busy_for_parent(ws_cli._shell_ppid()) == ""


def test_take_sends_no_refuse(monkeypatch) -> None:
    stop = threading.Event()
    seen: list[str] = []
    _patch_connect(monkeypatch, [None], stop, seen)
    threading.Timer(0.3, stop.set).start()
    ws_cli.run_ws_loop("alice", "seat", stop, None, {}, False)
    assert seen == ["ws://127.0.0.1/ws/alice"]


def test_connect_wait_busy_exits_0(monkeypatch, capsys) -> None:
    from agent_coord.client.http import mill_here_over_http

    def _run(coro):
        coro.close()
        raise ConnectionClosedError(ws_cli.WS_IN_USE_CLOSE, REASON)

    monkeypatch.setattr(asyncio, "run", _run)
    got = ws_cli.wait_one_hint("alice", "seat", refuse=True)
    assert got["busy"] is True and got["exit"] == 0
    assert "another session has the seat" in got["next"]

    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat")
    monkeypatch.setattr("agent_coord.client.ws.wait_one_hint", lambda desk, token, **kw: dict(got))
    args = SimpleNamespace(cmd="connect", desk="alice", project="", vendor="", session="",
                           foreground=True, refuse=True)
    assert mill_here_over_http(args) == 0


def test_a_command_in_a_busy_shell_says_busy(monkeypatch) -> None:
    from agent_coord.client import http as http_cli
    from agent_coord.helpers.errors import CoordError

    ws_cli.write_connect_busy("alice", "busy: another session has the seat; stop", parent_pid=ws_cli._shell_ppid())
    monkeypatch.setattr(http_cli, "mill_url", lambda: "https://wall.example.com")
    monkeypatch.setattr("agent_coord.client.offices.read_office_invite", lambda: "")
    monkeypatch.setattr(http_cli, "resolve_desk_owner", lambda *a, **k: "")
    monkeypatch.setattr(ws_cli, "wait_for_sitting_desk", lambda: "")
    with pytest.raises(CoordError) as ei:
        http_cli.mill_http_call({"verb": "inbox"})
    assert "another session has the seat" in str(ei.value)


def test_an_old_busy_note_is_ignored() -> None:
    path = ws_cli.write_connect_busy("alice", "busy", parent_pid=ws_cli._shell_ppid())
    old = os.path.getmtime(path) - ws_cli.BUSY_NOTE_S - 5
    os.utime(path, (old, old))
    assert ws_cli.busy_for_parent(ws_cli._shell_ppid()) == ""
