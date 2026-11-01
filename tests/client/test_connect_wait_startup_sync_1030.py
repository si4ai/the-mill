# -*- coding: utf-8 -*-
"""Card 1030: connect-wait holds past the first sync; exits 0 on a live HINT.

Regression row F-connect-wait-startup-sync. The office may put unread backlog
on the first connect sync (card 949). connect-wait must not treat that as the
HINT; it waits for a live frame after hold. Stdout is one final JSON result
line (no mode=ws / mode=hold chatter). No stderr banner. Delivered HINT exits 0.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_coord.client import ws as ws_client
from agent_coord.client.http import mill_here_over_http
from tests.client.test_mill_hold import _patch_socket

ROOT = Path(__file__).resolve().parents[2]


def _sync(*items):
    return json.dumps({"kind": "sync", "sync": list(items)})


MISSED = {"kind": "mail", "id": 42, "outcome": "missed", "body": "old"}
LIVE = json.dumps({"hint": "MAIL", "type": "mail", "id": 9, "kind": "mail"})


def test_connect_wait_startup_sync_alone_times_out(monkeypatch):
    """First sync with unread backlog must not end the wait."""
    _patch_socket(monkeypatch, [_sync(MISSED)])
    got = ws_client.wait_one_hint(
        "x",
        "tok",
        skip_ping=True,
        timeout_s=0.4,
        hold_empty_sync=True,
        skip_first_sync=True,
    )
    assert got["ok"] is False and got["error"] == "timeout"


def test_connect_wait_skips_startup_sync_then_holds_for_live_hint(monkeypatch):
    """Startup sync is skipped; the next live HINT ends the wait."""
    _patch_socket(monkeypatch, [_sync(MISSED), LIVE])
    got = ws_client.wait_one_hint(
        "x",
        "tok",
        skip_ping=True,
        timeout_s=5,
        hold_empty_sync=True,
        skip_first_sync=True,
    )
    assert got["ok"] is True
    assert got["hint"]["id"] == 9
    assert got["hint"].get("kind") != "sync"


def test_connect_wait_delivered_hint_exits_0(monkeypatch, capsys):
    """mill_here_over_http returns process exit 0 when wait_one_hint is ok."""
    monkeypatch.setattr(
        "agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat"
    )
    monkeypatch.setattr(
        "agent_coord.client.ws.wait_one_hint",
        lambda desk, token, **kw: {
            "ok": True,
            "mode": "hold",
            "hint": {"hint": "MAIL", "type": "mail", "id": 9},
            "desk": "d1",
        },
    )
    monkeypatch.setattr(
        "agent_coord.client.older.attach_older_once", lambda row, **k: row
    )
    args = SimpleNamespace(
        cmd="connect",
        desk="d1",
        project="Office",
        vendor="",
        session="",
        foreground=True,
        refuse=True,
        doing="present",
        role="",
        root="",
        reset=False,
    )
    assert mill_here_over_http(args) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1, out
    row = json.loads(out[0])
    assert row["ok"] is True and row["hint"]["id"] == 9


def test_connect_wait_no_stderr_banner(monkeypatch, capsys):
    """connect-wait does not print the mill connect stderr banner."""
    import agent_coord.__main__ as m

    monkeypatch.setattr(
        "agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat"
    )

    def fake_http(args):
        assert bool(getattr(args, "foreground", False)) is True
        print(json.dumps({"ok": True, "hint": {"id": 1}}, default=str), flush=True)
        return 0

    monkeypatch.setattr("agent_coord.client.http.mill_here_over_http", fake_http)
    # Also patch the name used after local import inside main's connect branch.
    monkeypatch.setattr(m, "mill_here_over_http", fake_http, raising=False)
    code = m.main(["connect-wait", "d1"])
    err = capsys.readouterr().err
    assert code == 0
    assert "mill connect:" not in err
    assert "connecting" not in err.lower()


def test_docs_name_startup_sync_hold():
    conn = (ROOT / "docs" / "protocol" / "connect.md").read_text(encoding="utf-8")
    cli = (ROOT / "docs" / "protocol" / "cli-desk.md").read_text(encoding="utf-8")
    assert "F-connect-wait-startup-sync" in conn or "first sync" in conn.lower()
    assert "last line" in cli.lower() or "final JSON" in cli or "one JSON" in cli.lower()
