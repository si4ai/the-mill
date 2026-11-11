# -*- coding: utf-8 -*-
"""Card 1112: --desk borrows a seat only when this shell has no connect."""
from __future__ import annotations

import os

import pytest

from agent_coord.__main__ import _build_parser
from agent_coord.client import http as mill_client
from agent_coord.client import ws as ws_cli
from agent_coord.client.outbound import body_from_args
from agent_coord.client.seat import command
from agent_coord.client.session_errors import desk_flag_required
from agent_coord.helpers.errors import CoordError


def test_inbox_takes_sender_desk():
    args = _build_parser().parse_args(["inbox", "--desk", "grok-tui"])
    assert args.sender_desk == "grok-tui"


def test_join_does_not_take_sender_desk():
    with pytest.raises(SystemExit):
        _build_parser().parse_args(["join", "--desk", "grok-tui"])


def test_connected_who_is_the_filter():
    """card 1130: --desk is the seat borrow here too; the filter is --who."""
    args = _build_parser().parse_args(["connected", "--who", "grok-tui"])
    assert args.desk == "grok-tui"
    assert getattr(args, "sender_desk", "") == ""


def test_body_keeps_sender_desk_off_the_owner(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    args = _build_parser().parse_args(["inbox", "--desk", "grok-tui"])
    body = body_from_args(args)
    assert body["sender_desk"] == "grok-tui"
    assert body["owner"] == ""
    assert body.get("desk") in (None, "")


def test_command_refuses_desk_flag_when_this_shell_is_connected(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    parent = ws_cli._shell_ppid()
    ws_cli.write_rpc_bridge("grok-tui", port=9, secret="s", pid=os.getpid(), parent_pid=parent)

    def fail_borrow(*_a, **_k):
        raise AssertionError("borrow")

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fail_borrow)
    with pytest.raises(CoordError) as ei:
        command({"verb": "inbox", "sender_desk": "builder"})
    assert str(ei.value) == "--desk is not necessary; grok-tui is already connected"


def test_command_without_desk_or_sit_names_the_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr("agent_coord.client.session_errors._typed", [])

    def boom(*_a, **_k):
        raise AssertionError("active desk")

    monkeypatch.setattr("agent_coord.client.tokens.read_active_desk", boom)
    with pytest.raises(CoordError) as ei:
        command({"verb": "inbox"})
    assert str(ei.value) == desk_flag_required("inbox")


def test_active_desk_file_is_not_a_bearer(tmp_path, monkeypatch):
    """The sticky desk file must not choose whose seat a command borrows."""
    from agent_coord.client.tokens import write_active_desk, write_session_token

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr("agent_coord.client.session_errors._typed", [])
    write_active_desk("builder")
    write_session_token("builder", "seat-builder")
    write_session_token("grok-tui", "seat-grok")
    borrowed: dict = {}

    def fake_borrow(desk, token, body):
        borrowed["desk"] = desk
        borrowed["token"] = token
        return {"ok": True, "result": {}, "sync": []}

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fake_borrow)
    with pytest.raises(CoordError) as ei:
        command({"verb": "inbox"})
    assert str(ei.value) == desk_flag_required("inbox")
    assert borrowed == {}

    out = command({"verb": "inbox", "sender_desk": "grok-tui"})
    assert out["ok"] is True
    assert borrowed == {"desk": "grok-tui", "token": "seat-grok"}


def test_sitting_connect_desk_wins_over_the_active_file(tmp_path, monkeypatch):
    from agent_coord.client.tokens import write_active_desk, write_session_token

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    write_active_desk("builder")
    write_session_token("builder", "seat-builder")
    parent = ws_cli._shell_ppid()
    ws_cli.write_rpc_bridge("grok-tui", port=9, secret="s", pid=os.getpid(), parent_pid=parent)
    seen: dict = {}

    def fake_call(body, token="", desk=""):
        seen["verb"] = body.get("verb")
        return {"ok": True, "result": {}, "sync": []}

    monkeypatch.setattr(ws_cli, "mill_ws_call", fake_call)

    def fail_borrow(*_a, **_k):
        raise AssertionError("borrow")

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fail_borrow)
    out = command({"verb": "send"})
    assert out["ok"] is True
    assert seen["verb"] == "send"


def test_http_call_refuses_desk_flag_when_sitting(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    parent = ws_cli._shell_ppid()
    ws_cli.write_rpc_bridge("grok-tui", port=9, secret="s", pid=os.getpid(), parent_pid=parent)

    def fail_ws(*_a, **_k):
        raise AssertionError("ws")

    monkeypatch.setattr(ws_cli, "mill_ws_call", fail_ws)
    with pytest.raises(CoordError) as ei:
        mill_client.mill_http_call({"verb": "inbox", "sender_desk": "grok-tui"})
    assert str(ei.value) == "--desk is not necessary; grok-tui is already connected"


def test_http_call_without_sit_borrows_named_desk(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr(ws_cli, "wait_for_sitting_desk", lambda: "")
    seen: dict = {}

    def fake_command(body):
        seen["body"] = dict(body)
        return {"ok": True, "result": {}, "sync": []}

    monkeypatch.setattr("agent_coord.client.seat.command", fake_command)
    out = mill_client.mill_http_call({"verb": "inbox", "sender_desk": "grok-tui"})
    assert out["ok"] is True
    assert seen["body"]["sender_desk"] == "grok-tui"
    assert "desk" not in seen["body"] or seen["body"].get("desk") in (None, "")


def test_same_desk_on_two_offices_asks_for_office(tmp_path, monkeypatch):
    from agent_coord.client.offices import bind_cli_office, write_alias, write_desk_token

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    bind_cli_office("")
    write_alias("cloud", "203.0.113.10", dest=tmp_path)
    write_alias("lan", "198.51.100.10", dest=tmp_path)
    write_desk_token("grok-tui", "seat-cloud", host="203.0.113.10", dest=tmp_path)
    write_desk_token("grok-tui", "seat-lan", host="198.51.100.10", dest=tmp_path)
    borrowed: dict = {}

    def fake_borrow(desk, token, body):
        borrowed["desk"] = desk
        borrowed["token"] = token
        return {"ok": True}

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fake_borrow)
    with pytest.raises(CoordError) as ei:
        command({"verb": "inbox", "sender_desk": "grok-tui"})
    assert str(ei.value) == (
        "multiple offices have desk grok-tui (cloud, lan); pass --office ALIAS"
    )
    assert borrowed == {}


def test_office_flag_picks_one_desk_among_two(tmp_path, monkeypatch):
    from agent_coord.client.offices import bind_cli_office, write_alias, write_desk_token

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    write_alias("cloud", "203.0.113.10", dest=tmp_path)
    write_alias("lan", "198.51.100.10", dest=tmp_path)
    write_desk_token("grok-tui", "seat-cloud", host="203.0.113.10", dest=tmp_path)
    write_desk_token("grok-tui", "seat-lan", host="198.51.100.10", dest=tmp_path)
    bind_cli_office("lan")
    borrowed: dict = {}

    def fake_borrow(desk, token, body):
        borrowed["token"] = token
        return {"ok": True, "result": {}, "sync": []}

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fake_borrow)
    try:
        out = command({"verb": "inbox", "sender_desk": "grok-tui"})
    finally:
        bind_cli_office("")
    assert out["ok"] is True
    assert borrowed["token"] == "seat-lan"


def test_two_aliases_for_one_wall_are_one_office(tmp_path, monkeypatch):
    from agent_coord.client.offices import bind_cli_office, write_alias, write_desk_token, write_global_active

    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    bind_cli_office("")
    write_alias("cloud", "203.0.113.10", dest=tmp_path)
    write_alias("cloud-again", "203.0.113.10", dest=tmp_path)
    write_desk_token("grok-tui", "seat-cloud", host="203.0.113.10", dest=tmp_path)
    write_global_active("cloud", dest=tmp_path)
    borrowed: dict = {}

    def fake_borrow(desk, token, body):
        borrowed["token"] = token
        return {"ok": True, "result": {}, "sync": []}

    monkeypatch.setattr("agent_coord.client.seat.session.borrow", fake_borrow)
    out = command({"verb": "inbox", "sender_desk": "grok-tui"})
    assert out["ok"] is True
    assert borrowed["token"] == "seat-cloud"
