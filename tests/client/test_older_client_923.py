# -*- coding: utf-8 -*-
"""Card 923: say once when this client is older than the office mill field."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

from agent_coord.client import http
from agent_coord.client.older import (
    attach_older_once,
    older_client_line,
    reset_older_once,
)
from agent_coord.client.ws import sync_view

_LINE = (
    "this mill client is older than the office (0.7.13 < 0.8.0): "
    "pip install -U the-mill"
)


def test_line_when_the_client_is_older():
    assert older_client_line("0.7.13", "0.8.0") == _LINE


def test_line_quiet_when_not_older():
    assert older_client_line("0.8.0", "0.8.0") == ""
    assert older_client_line("0.8.2", "0.8.0") == ""
    assert older_client_line("0.8.10", "0.8.9") == ""
    assert older_client_line("0.7.13", "") == ""
    assert older_client_line("0+local", "0.8.0") == ""
    assert older_client_line("0.8.0+gab", "0.8.1") == ""


def test_line_orders_numeric_parts():
    assert older_client_line("0.8.9", "0.8.10").startswith(
        "this mill client is older than the office (0.8.9 < 0.8.10):"
    )


def test_sync_view_says_once(monkeypatch):
    reset_older_once()
    monkeypatch.setattr("agent_coord.install.packver.package_version", lambda: "0.7.13")
    frame = {"kind": "sync", "sync": [], "holds": [], "mill": "0.8.0"}
    first = sync_view(frame)
    assert first["mill"] == "0.8.0"
    assert first["older"] == _LINE
    assert "hello" not in first
    second = sync_view(frame)
    assert "older" not in second


def test_sync_view_stays_quiet_when_the_office_is_older():
    reset_older_once()
    out = sync_view({"kind": "sync", "sync": [], "holds": [], "mill": "0.6.33"})
    assert out["mill"] == "0.6.33"
    assert "older" not in out


def test_sync_view_stays_quiet_when_the_office_omits_mill(monkeypatch):
    reset_older_once()
    monkeypatch.setattr("agent_coord.install.packver.package_version", lambda: "0.7.13")
    out = sync_view({"kind": "sync", "sync": [], "holds": []})
    assert out["mill"] == "0.7.13"
    assert "older" not in out


def test_command_reply_says_once_then_stays_quiet(monkeypatch, capsys):
    reset_older_once()
    monkeypatch.setattr("agent_coord.install.packver.package_version", lambda: "0.7.13")
    reply = {"ok": True, "mill": "0.8.0", "result": {"id": 1}, "sync": []}
    with patch.object(http, "mill_http_call", return_value=reply), patch(
        "agent_coord.client.outbound.body_from_args", return_value={"verb": "send"}
    ):
        assert http.mill_http_from_args(SimpleNamespace(cmd="send")) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["older"] == _LINE
    assert first["result"]["id"] == 1
    with patch.object(http, "mill_http_call", return_value=dict(reply)), patch(
        "agent_coord.client.outbound.body_from_args", return_value={"verb": "send"}
    ):
        assert http.mill_http_from_args(SimpleNamespace(cmd="send")) == 0
    second = json.loads(capsys.readouterr().out)
    assert "older" not in second


def test_connect_wait_result_carries_the_line():
    reset_older_once()
    got = attach_older_once(
        {"ok": True, "mode": "hold", "hint": {"kind": "sync", "mill": "0.8.0", "sync": []}},
        client="0.7.13",
    )
    assert got["older"] == _LINE
    again = attach_older_once(
        {"ok": True, "mode": "hold", "hint": {"kind": "sync", "mill": "0.8.0", "sync": []}},
        client="0.7.13",
    )
    assert "older" not in again
