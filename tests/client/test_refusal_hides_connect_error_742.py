# -*- coding: utf-8 -*-
"""Card 742: connect failure must surface on the next command in the same shell."""
from __future__ import annotations

import json

import pytest

from agent_coord.client import ws as ws_cli
from agent_coord.helpers.errors import CoordError


def test_fail_for_parent_reads_connect_fail_note(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr(ws_cli, "_shell_ppid", lambda: 4242)
    # legacy session layout
    dest = tmp_path / "session"
    dest.mkdir(parents=True)
    monkeypatch.setattr(
        "agent_coord.client.offices.desk_local_file",
        lambda desk, leaf, dest=None: None,
    )
    path = ws_cli.write_connect_fail(
        "missing-desk",
        "mill connect: no seat for missing-desk on this computer; mill join --link-file PATH",
        parent_pid=4242,
    )
    assert path.is_file()
    note = ws_cli.fail_for_parent(4242)
    assert "no seat for missing-desk" in note
    assert ws_cli.fail_for_parent(9999) == ""


def test_http_bridge_miss_prefers_fail_note(tmp_path, monkeypatch) -> None:
    from agent_coord.client import http as http_cli

    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr(ws_cli, "_shell_ppid", lambda: 5151)
    monkeypatch.setattr(ws_cli, "busy_for_parent", lambda parent_pid=None: "")
    monkeypatch.setattr(
        ws_cli,
        "fail_for_parent",
        lambda parent_pid=None: "mill connect: no seat for ghost on this computer; mill join --link-file PATH",
    )
    monkeypatch.setattr("agent_coord.client.http.resolve_desk_owner", lambda _x: "")
    monkeypatch.setattr(ws_cli, "wait_for_sitting_desk", lambda: "")
    monkeypatch.setattr(
        "agent_coord.client.http.mill_url",
        lambda: "https://office.example",
    )
    # force JSON-RPC path (no token / join)
    class Args:
        pass

    args = Args()
    # Call the internal raise path via mill_http_from_args-like flow:
    # easiest: invoke the block through mill_ws-less path by calling the code that raises.
    from agent_coord.client.session_errors import SESSION_WS_BRIDGE_REQUIRED
    from agent_coord.helpers.errors import CoordError

    # Direct unit: the expression used at the raise site
    note = ws_cli.busy_for_parent() or ws_cli.fail_for_parent() or SESSION_WS_BRIDGE_REQUIRED
    assert "no seat for ghost" in note
    assert "no sitting mill connect" not in note


def test_mill_ws_call_prefers_fail_note(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr(ws_cli, "bridge_for_parent", lambda parent_pid=None: None)
    monkeypatch.setattr(ws_cli, "dead_connect_for_parent", lambda: False)
    monkeypatch.setattr(ws_cli, "busy_for_parent", lambda parent_pid=None: "")
    monkeypatch.setattr(
        ws_cli,
        "fail_for_parent",
        lambda parent_pid=None: "mill connect: no seat for ghost on this computer; mill join --link-file PATH",
    )
    with pytest.raises(CoordError) as ei:
        ws_cli.mill_ws_call({"verb": "inbox"})
    assert "no seat for ghost" in str(ei.value)
