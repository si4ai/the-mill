# -*- coding: utf-8 -*-
"""Hub /ws gate: HTTP desk-acting commands refuse; identity is the sitting socket."""
from __future__ import annotations

import asyncio

import pytest

from agent_coord.client.session_errors import SESSION_WS_REQUIRED, SESSION_WS_RPC_ONLY
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.push import HUB, WS_REPLACED, desk_sitting, socket_seated


class _FakeWS:
    def __init__(self, name: str = "") -> None:
        self.name = name
        self.sent: list[str] = []
        self.closed: list[int] = []

    async def send_text(self, text: str) -> None:
        self.sent.append(text)

    async def close(self, code: int = 1000) -> None:
        self.closed.append(code)


class _Book:
    _tokens: dict = {}

    def __init__(self, desk: str = "alice") -> None:
        self._desk = desk
        self._cn = object()

    def resolve_bearer(self, token: str) -> str:
        return self._desk if token else ""

    def _guard_owner(self, *a, **k):
        return {}


@pytest.fixture(autouse=True)
def _clean_hub():
    HUB.rooms.clear()
    yield
    HUB.rooms.clear()


def _sit(desk: str = "alice", ws: object | None = None) -> object:
    sock = ws if ws is not None else object()
    HUB.rooms.setdefault(desk, set()).add(sock)
    return sock


def test_desk_sitting_false_when_empty() -> None:
    assert desk_sitting("alice") is False
    assert desk_sitting("") is False


def test_desk_sitting_true_when_room_has_socket() -> None:
    _sit("alice")
    assert desk_sitting("alice") is True
    assert desk_sitting("alice") is True


def test_socket_seated_requires_exact_ws() -> None:
    a, b = object(), object()
    _sit("alice", a)
    assert socket_seated("alice", a) is True
    assert socket_seated("alice", b) is False


def test_http_desk_command_refused_even_when_sitting(monkeypatch) -> None:
    """HTTP path is cut: sit-stamp does not unlock POST /mill/v1 desk commands."""
    _sit("alice")
    monkeypatch.setitem(
        rpc.HANDLERS, "inbox", lambda c, body, project, owner: [{"id": 1}]
    )
    with pytest.raises(CoordError) as ei:
        rpc.dispatch(
            _Book(),
            {"verb": "inbox", "project": "the-mill", "dst": "alice"},
            token="tok",
        )
    assert str(ei.value) == SESSION_WS_RPC_ONLY
    assert "ws" in str(ei.value).lower()
    assert "rpc" in str(ei.value).lower() or "json" in str(ei.value).lower()


@pytest.mark.parametrize(
    "command",
    ["inbox", "send", "reply", "mail-thread", "todo", "mark", "hold", "claim"],
)
def test_http_no_ws_refuses_desk_acting_commands(command: str) -> None:
    assert desk_sitting("alice") is False
    with pytest.raises(CoordError) as ei:
        rpc.dispatch(
            _Book(),
            {"verb": command, "project": "the-mill"},
            token="tok",
        )
    assert str(ei.value) == SESSION_WS_RPC_ONLY


def test_join_open_skips_ws_gate(monkeypatch) -> None:
    """join stays OPEN_COMMANDS: mint token before /ws sit."""
    monkeypatch.setitem(
        rpc.HANDLERS, "join", lambda c, body, project, owner: {"token": "new"}
    )
    out = rpc.dispatch(
        _Book(),
        {"verb": "join", "project": "the-mill", "owner": "alice"},
        token="",
    )
    assert out["token"] == "new"


def test_dispatch_ws_inbox_uses_socket_desk(monkeypatch) -> None:
    monkeypatch.setitem(
        rpc.HANDLERS,
        "inbox",
        lambda c, body, project, owner: {"owner": owner, "dst": body.get("dst")},
    )
    out = rpc.dispatch_ws(
        _Book(),
        "alice",
        "inbox",
        {"project": "the-mill", "owner": "bob", "dst": "spoof"},
    )
    # Identity from sitting desk, not client-supplied owner.
    assert out["owner"] == "alice"


def test_dispatch_ws_join_refused() -> None:
    with pytest.raises(CoordError) as ei:
        rpc.dispatch_ws(_Book(), "alice", "join", {"project": "the-mill"})
    assert "http" in str(ei.value).lower()


def test_after_replace_kick_old_socket_not_seated(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.server.push._mark_join_socket", lambda desk, *, up: None)
    hub = HUB
    old, new = _FakeWS("old"), _FakeWS("new")

    async def go() -> None:
        await hub.add("alice", old)
        await hub.add("alice", new)

    asyncio.run(go())
    assert old.closed == [WS_REPLACED]
    assert socket_seated("alice", old) is False
    assert socket_seated("alice", new) is True
    assert desk_sitting("alice") is True


def test_session_ws_rpc_only_is_cp1252_safe() -> None:
    SESSION_WS_RPC_ONLY.encode("cp1252")
    SESSION_WS_REQUIRED.encode("cp1252")
