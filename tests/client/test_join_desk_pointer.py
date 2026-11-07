# -*- coding: utf-8 -*-
"""Join and connect write the host desk pointer the one-shot reads."""
from __future__ import annotations

from argparse import Namespace

from agent_coord.client.http import mill_here_over_http, mill_http_call
from agent_coord.client.offices import bind_cli_office, read_host_active, write_alias
from agent_coord.client.tokens import read_active_desk, write_session_token


def test_join_writes_the_desk_pointer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_URL", "https://office.example")
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_COORD_TOKEN", raising=False)
    bind_cli_office("")
    write_session_token("desk", "gl-style-pat", dest=tmp_path)

    class Resp:
        def read(self):
            return b'{"ok":true,"token":"fresh-seat","owner":"desk"}'

        headers = {"X-Mill-Version": "0"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(req, context=None, timeout=None):
        return Resp()

    monkeypatch.setattr("agent_coord.client.http._open", fake_urlopen)
    row = mill_http_call({"verb": "join", "project": "the-mill", "owner": "desk"})
    assert row["ok"] is True
    assert read_active_desk() == "desk"


def test_join_writes_the_host_desk_pointer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.delenv("AGENT_COORD_TOKEN", raising=False)
    write_alias("Offsite", "203.0.113.10")
    bind_cli_office("Offsite")
    try:
        write_session_token("desk", "gl-style-pat")

        class Resp:
            def read(self):
                return b'{"ok":true,"token":"fresh-seat","owner":"desk"}'

            headers = {"X-Mill-Version": "0"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        monkeypatch.setattr("agent_coord.client.http._open", lambda *a, **k: Resp())
        row = mill_http_call({"verb": "join", "project": "the-mill", "owner": "desk"})
        assert row["ok"] is True
        assert read_host_active("203.0.113.10") == "desk"
    finally:
        bind_cli_office("")


def test_connect_writes_the_host_desk_pointer(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    write_alias("Offsite", "203.0.113.10")
    bind_cli_office("Offsite")
    try:
        write_session_token("grok-tui", "seat-secret")
        monkeypatch.setattr("agent_coord.client.http._open_tw_link", lambda desk: None)
        monkeypatch.setattr("agent_coord.client.http._sit_mill_here", lambda **kwargs: 0)
        code = mill_here_over_http(
            Namespace(desk="grok-tui", foreground=True, vendor="", session="", refuse=False)
        )
        assert code == 0
        assert read_host_active("203.0.113.10") == "grok-tui"
    finally:
        bind_cli_office("")
