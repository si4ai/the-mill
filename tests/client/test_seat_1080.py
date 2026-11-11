# -*- coding: utf-8 -*-
"""Card 1080: one seat package for mill connect and a one-call command."""
from __future__ import annotations

import os
import threading

import pytest

from agent_coord.client import ws as ws_cli
from agent_coord.client.seat import command, hold, look, other_holder
from agent_coord.client.seat.open import connect_websocket
from agent_coord.client.seat.session import borrow
from agent_coord.client.seat.status import held_message
from agent_coord.helpers.errors import CoordError


def test_look_reports_a_sitting_bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    parent = ws_cli._shell_ppid()
    ws_cli.write_rpc_bridge("alice", port=9, secret="s", pid=os.getpid(), parent_pid=parent)
    state = look()
    assert state.kind == "sitting"
    assert state.desk == "alice"


def test_other_holder_is_a_live_pid_that_is_not_us(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(ws_cli, "_pid_alive", lambda pid: int(pid) == 4242)
    ws_cli.write_rpc_bridge("alice", port=9, secret="s", pid=4242, parent_pid=999)
    assert other_holder("alice") == 4242
    assert "4242" in held_message(4242)
    assert "token" not in held_message(4242)


def test_command_uses_a_sitting_bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    parent = ws_cli._shell_ppid()
    ws_cli.write_rpc_bridge("alice", port=9, secret="s", pid=os.getpid(), parent_pid=parent)
    seen: dict = {}

    def fake_call(body, token="", desk=""):
        seen["verb"] = body.get("verb")
        return {"ok": True, "result": {}, "sync": []}

    monkeypatch.setattr(ws_cli, "mill_ws_call", fake_call)

    def fail_borrow(*_a, **_k):
        raise AssertionError("borrow")

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fail_borrow)
    out = command({"verb": "inbox"})
    assert out["ok"] is True
    assert seen["verb"] == "inbox"


def test_command_borrows_the_named_desk_when_no_sit(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))

    def boom(*_a, **_k):
        raise AssertionError("active desk")

    monkeypatch.setattr("agent_coord.client.tokens.read_active_desk", boom)
    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat-alice")
    borrowed: dict = {}

    def fake_borrow(desk, token, body):
        borrowed["desk"] = desk
        borrowed["token"] = token
        borrowed["verb"] = body.get("verb")
        borrowed["sender"] = body.get("sender_desk")
        return {"ok": True, "result": {"via": "borrow"}, "sync": []}

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fake_borrow)
    out = command({"verb": "todo", "sender_desk": "alice"})
    assert out["result"]["via"] == "borrow"
    assert borrowed == {"desk": "alice", "token": "seat-alice", "verb": "todo", "sender": None}


def test_command_does_not_open_when_another_connect_holds_the_seat(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(ws_cli, "_pid_alive", lambda pid: int(pid) == 4242)
    ws_cli.write_rpc_bridge("alice", port=9, secret="s", pid=4242, parent_pid=999)
    monkeypatch.setattr("agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat-alice")

    def fail_borrow(*_a, **_k):
        raise AssertionError("borrow")

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fail_borrow)
    with pytest.raises(CoordError) as ei:
        command({"verb": "inbox", "sender_desk": "alice"})
    assert "held by another connect" in str(ei.value)
    assert "4242" in str(ei.value)


def test_borrow_sends_one_call_and_releases(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    parent = ws_cli._shell_ppid()
    state: dict = {}

    def fake_start(desk, token, stop, outcome, refuse=False):
        state["refuse"] = refuse
        state["token"] = token

        def run():
            ws_cli.write_rpc_bridge(
                desk, port=9, secret="s", pid=os.getpid(), parent_pid=parent
            )
            stop.wait(5)

        thread = threading.Thread(target=run)
        thread.start()
        state["thread"] = thread
        return thread

    def fake_call(body, token="", desk=""):
        state["verb"] = body.get("verb")
        return {"ok": True, "result": {"n": 1}, "sync": []}

    monkeypatch.setattr(ws_cli, "start_ws_thread", fake_start)
    monkeypatch.setattr(ws_cli, "mill_ws_call", fake_call)
    out = borrow("alice", "seat-alice", {"verb": "hold"})
    assert out["result"]["n"] == 1
    assert state["verb"] == "hold"
    assert state["refuse"] is True
    assert state["thread"].is_alive() is False


def test_hold_returns_when_the_parent_exits(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(
        "agent_coord.client.http.seat_then_focus",
        lambda *a, **k: None,
    )

    def fake_start(desk, token, stop, outcome, refuse=False):
        thread = threading.Thread(target=stop.wait, args=(5,))
        thread.start()
        return thread

    monkeypatch.setattr(ws_cli, "start_ws_thread", fake_start)
    calls = {"n": 0}

    def parent_gone(_pid: int) -> bool:
        calls["n"] += 1
        return calls["n"] > 1

    assert hold("alice", "seat", parent=1, refuse=True, parent_gone=parent_gone, project="") == 0
    assert calls["n"] >= 2


def test_connect_websocket_accepts_the_older_header_name():
    import websockets

    seen: list[dict] = []

    def fake_connect(url, **kw):
        seen.append(kw)
        if "additional_headers" in kw:
            raise TypeError("old")
        return "ctx"

    original = websockets.connect
    websockets.connect = fake_connect
    try:
        assert connect_websocket("ws://127.0.0.1/ws/alice", headers={"Authorization": "Bearer seat"}) == "ctx"
    finally:
        websockets.connect = original
    assert seen[0]["additional_headers"]["Authorization"] == "Bearer seat"
    assert seen[1]["extra_headers"]["Authorization"] == "Bearer seat"
