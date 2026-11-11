# -*- coding: utf-8 -*-
"""Two sitting desks: a command follows its parent bridge, never host active."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from agent_coord.client import http as mill_client
from agent_coord.client import ws as ws_cli
from agent_coord.client.offices import bind_cli_office, write_alias, write_host_active
from agent_coord.client.outbound import body_from_args
from agent_coord.client.session_errors import (
    SESSION_CONNECT_DIED,
    SESSION_WS_BRIDGE_REQUIRED,
    bridge_hint,
    desk_flag_required,
)
from agent_coord.client.tokens import write_session_token
from agent_coord.helpers.errors import CoordError


class _Sock:
    def __init__(self, captured: list) -> None:
        self._captured = captured
        self._reply = b""

    def settimeout(self, _t: float) -> None:
        return None

    def sendall(self, data: bytes) -> None:
        req = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
        self._captured.append(req)
        reply = {"id": req["id"], "ok": True, "result": {"via": "bridge"}, "sync": []}
        self._reply = (json.dumps(reply) + "\n").encode("utf-8")

    def recv(self, _n: int) -> bytes:
        chunk = self._reply
        self._reply = b""
        return chunk

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_parent_bridges_do_not_cross_and_missing_fails_closed(tmp_path, monkeypatch):
    """Parent B cannot send on parent A's bridge. No bridge does not read active."""
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(ws_cli, "SITTING_BRIDGE_RETRY_WAIT_S", 0)
    monkeypatch.setattr("agent_coord.client.session_errors._typed", [])
    monkeypatch.delenv("AGENT_COORD_OWNER", raising=False)
    monkeypatch.delenv("AGENT_COORD_TOKEN", raising=False)
    bind_cli_office("")
    write_alias("lan", "203.0.113.10")
    bind_cli_office("lan")
    try:
        write_host_active("203.0.113.10", "alice")
        write_session_token("alice", "tok-alice")
        write_session_token("bob", "tok-bob")
        ws_cli.write_rpc_bridge(
            "alice", port=1111, secret="sec-a", pid=os.getpid(), parent_pid=1001
        )
        ws_cli.write_rpc_bridge(
            "bob", port=2222, secret="sec-b", pid=os.getpid(), parent_pid=2002
        )
        active = tmp_path / "203.0.113.10" / "active"
        assert active.read_text(encoding="utf-8").strip() == "alice"

        captured: list = []
        ports: list[int] = []

        def fake_connect(addr, timeout=None):
            ports.append(int(addr[1]))
            return _Sock(captured)

        monkeypatch.setattr(ws_cli.socket, "create_connection", fake_connect)

        allow_active = {"on": False}

        def forbid_open(file, *args, **kwargs):
            name = str(file).replace("\\", "/")
            if (name.endswith("/active") or name.endswith("/active.tmp")) and not allow_active["on"]:
                raise AssertionError("command opened host active: " + name)
            return open_real(file, *args, **kwargs)

        import builtins

        open_real = builtins.open
        monkeypatch.setattr(builtins, "open", forbid_open)

        token_owners: list[str] = []
        real_read = mill_client.read_session_token

        def spy_read(owner, **kwargs):
            token_owners.append(str(owner))
            return real_read(owner, **kwargs)

        monkeypatch.setattr(mill_client, "read_session_token", spy_read)

        monkeypatch.setattr(os, "getppid", lambda: 2002)
        got = body_from_args(
            SimpleNamespace(cmd="inbox", project="the-mill", owner="DESK_alice")
        )
        assert got["owner"] == "bob"
        out = mill_client.mill_http_call(
            {"verb": "send", "project": "the-mill", "owner": "DESK_alice", "body": "hi", "dst": "carol"}
        )
        assert out["ok"] is True
        assert ports == [2222]
        assert captured[-1]["secret"] == "sec-b"
        assert "alice" not in " ".join(token_owners).lower()

        direct = ws_cli.mill_ws_call(
            {"verb": "inbox", "project": "the-mill", "owner": "DESK_alice"},
            token="tok-alice",
            desk="DESK_alice",
        )
        assert direct["ok"] is True
        assert ports[-1] == 2222
        assert captured[-1]["secret"] == "sec-b"

        monkeypatch.setattr(os, "getppid", lambda: 1001)
        ws_cli.mill_ws_call(
            {"verb": "member", "project": "the-mill", "owner": "DESK_bob"},
            token="tok-bob",
            desk="DESK_bob",
        )
        assert ports[-1] == 1111
        assert captured[-1]["secret"] == "sec-a"

        monkeypatch.setattr(os, "getppid", lambda: 3003)
        with pytest.raises(CoordError) as ei:
            mill_client.mill_http_call(
                {"verb": "inbox", "project": "the-mill", "owner": "DESK_alice"}
            )
        assert str(ei.value) == desk_flag_required("inbox")

        borrowed: dict = {}

        def fake_borrow(desk, token, body):
            borrowed["desk"] = desk
            borrowed["token"] = token
            borrowed["verb"] = body.get("verb")
            return {"ok": True, "result": {"via": "borrow"}, "sync": []}

        monkeypatch.setattr("agent_coord.client.seat.session.borrow", fake_borrow)
        out_once = mill_client.mill_http_call(
            {
                "verb": "inbox",
                "project": "the-mill",
                "owner": "DESK_alice",
                "sender_desk": "bob",
            }
        )
        assert out_once["result"]["via"] == "borrow"
        assert borrowed["desk"] == "bob"
        assert borrowed["token"] == "tok-bob"
        assert borrowed["verb"] == "inbox"
        assert ports[-1] == 1111
        assert open_real(active, encoding="utf-8").read().strip() == "alice"
    finally:
        bind_cli_office("")


def test_dead_connect_pid_is_a_disconnect_notice(tmp_path, monkeypatch):
    """A bridge whose connect pid is gone says the connect died (#228)."""
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(ws_cli, "SITTING_BRIDGE_RETRY_WAIT_S", 0)
    monkeypatch.delenv("AGENT_COORD_OWNER", raising=False)
    monkeypatch.delenv("AGENT_COORD_TOKEN", raising=False)
    bind_cli_office("")
    write_alias("lan", "203.0.113.10")
    bind_cli_office("lan")
    try:
        monkeypatch.setattr(os, "getppid", lambda: 1001)

        def alive(pid: int) -> bool:
            return int(pid) != 424242

        monkeypatch.setattr(ws_cli, "_pid_alive", alive)
        ws_cli.write_rpc_bridge(
            "alice", port=1111, secret="sec-a", pid=424242, parent_pid=1001
        )
        with pytest.raises(CoordError) as ei:
            ws_cli.mill_ws_call(
                {"verb": "inbox", "project": "the-mill"},
                token="t",
                desk="alice",
            )
        notice = str(ei.value)
        assert notice == SESSION_CONNECT_DIED
        assert notice.startswith("disconnected:")
        assert "died" in notice
        assert "no sitting mill connect" not in notice
        notice.encode("ascii")
    finally:
        bind_cli_office("")


def test_bridge_hint_posix_and_nt():
    """POSIX keeps the bash recipe. Windows prints Start-Process (#179, #236)."""
    posix = bridge_hint("posix")
    nt = bridge_hint("nt")
    bash = "bash -c 'mill connect DESK >/dev/null 2>&1 & trap \"kill $!\" EXIT; mill COMMAND ARGS'"
    assert bash in posix
    assert "foreground just blocks" in posix
    assert "bash" not in nt
    assert "/dev/null" not in nt
    assert "Start-Process mill -ArgumentList 'connect','DESK'" in nt
    assert "mill COMMAND ARGS" in nt
    for text in (posix, nt):
        assert text.startswith("no sitting mill connect for this process")
        assert "same parent process" in text
        assert "a command outside one has none" in text
        assert "then retry this command" not in text
        assert "bound to the process" not in text
        assert "retry loop will not help" not in text
        text.encode("ascii")
    assert SESSION_WS_BRIDGE_REQUIRED == bridge_hint(os.name)
    assert SESSION_CONNECT_DIED != posix
    assert SESSION_CONNECT_DIED != nt
    assert "bash" not in SESSION_CONNECT_DIED
    assert "no sitting mill connect" not in SESSION_CONNECT_DIED
    SESSION_CONNECT_DIED.encode("ascii")
