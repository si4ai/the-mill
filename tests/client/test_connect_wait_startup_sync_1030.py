# -*- coding: utf-8 -*-
"""Card 1030: connect-wait first sync ends only on push_queue work.

Regression row F-connect-wait-startup-sync. The office may put unread mailbox
mail on the first connect sync (card 949; frames omit time). connect-wait must
not treat that mailbox-only resurfacing as the HINT. A missed push_queue row
(has time) on the first sync does end the wait: that is mail queued while no
wait was running. A live frame after hold also ends it. Stdout is one final
JSON result line. No stderr banner. Delivered HINT exits 0. mill-hold still
ends on a non-empty first sync.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent_coord.client import ws as ws_client
from agent_coord.client.http import mill_here_over_http
from tests.client.test_mill_hold import _patch_socket

ROOT = Path(__file__).resolve().parents[2]


def _sync(*items):
    return json.dumps({"kind": "sync", "sync": list(items)})


# Card 949 mailbox resurfacing: no time (not a push_queue row).
MAILBOX = {"kind": "mail", "id": 42, "outcome": "missed", "body": "old"}
# Genuine push_queue row queued while no wait sat (has time).
QUEUED = {
    "kind": "mail",
    "id": 99,
    "outcome": "missed",
    "body": "new while away",
    "time": "2026-11-01 12:00:00.000000",
}
SENT = {"kind": "hint", "type": "todo", "id": 3, "hint": "TODO", "outcome": "sent", "time": "2026-11-01 11:00:00"}
LIVE = json.dumps({"hint": "MAIL", "type": "mail", "id": 9, "kind": "mail"})


def test_connect_wait_mailbox_backlog_alone_times_out(monkeypatch):
    """(a) Stale mailbox-only resurfacing on the first sync must not end the wait."""
    _patch_socket(monkeypatch, [_sync(MAILBOX)])
    got = ws_client.wait_one_hint(
        "x",
        "tok",
        skip_ping=True,
        timeout_s=0.4,
        hold_empty_sync=True,
        skip_first_sync=True,
    )
    assert got["ok"] is False and got["error"] == "timeout"


def test_connect_wait_queued_mail_on_first_sync_ends_wait(monkeypatch):
    """(b) A letter queued while no wait sat (push_queue, has time) ends the wait."""
    _patch_socket(monkeypatch, [_sync(QUEUED)])
    got = ws_client.wait_one_hint(
        "x",
        "tok",
        skip_ping=True,
        timeout_s=5,
        hold_empty_sync=True,
        skip_first_sync=True,
    )
    assert got["ok"] is True
    assert got["hint"]["kind"] == "sync"
    assert got["hint"]["sync"][0]["id"] == 99


def test_connect_wait_queued_mail_http_exits_0_one_line(monkeypatch, capsys):
    """(b) via http: exit 0 and one stdout JSON line when first sync has push work."""
    monkeypatch.setattr(
        "agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat"
    )
    monkeypatch.setattr(
        "agent_coord.client.older.attach_older_once", lambda row, **k: row
    )
    _patch_socket(monkeypatch, [_sync(QUEUED)])
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
    assert row["ok"] is True
    assert row["hint"]["sync"][0]["id"] == 99


def test_connect_wait_skips_mailbox_then_holds_for_live_hint(monkeypatch):
    """(c) Mailbox-only first sync is skipped; the next live HINT ends the wait."""
    _patch_socket(monkeypatch, [_sync(MAILBOX), LIVE])
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


def test_connect_wait_sent_and_mailbox_on_first_sync_hold(monkeypatch):
    """First sync of only sent + mailbox resurfacing still holds."""
    _patch_socket(monkeypatch, [_sync(SENT, MAILBOX)])
    got = ws_client.wait_one_hint(
        "x",
        "tok",
        skip_ping=True,
        timeout_s=0.4,
        hold_empty_sync=True,
        skip_first_sync=True,
    )
    assert got["ok"] is False and got["error"] == "timeout"


def test_http_passes_skip_first_sync(monkeypatch, capsys):
    """Major 2: mill_here_over_http must turn skip_first_sync on (mutant K3)."""
    seen: dict = {}

    def capture(desk, token, **kw):
        seen.clear()
        seen.update(kw)
        seen["desk"] = desk
        return {
            "ok": True,
            "mode": "hold",
            "hint": {"hint": "MAIL", "type": "mail", "id": 9},
            "desk": desk,
        }

    monkeypatch.setattr(
        "agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat"
    )
    monkeypatch.setattr("agent_coord.client.ws.wait_one_hint", capture)
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
    assert seen.get("skip_first_sync") is True
    assert seen.get("hold_empty_sync") is True
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert json.loads(out[0])["ok"] is True


def test_connect_wait_delivered_hint_exits_0(monkeypatch, capsys):
    """mill_here_over_http returns process exit 0 when wait_one_hint is ok."""
    monkeypatch.setattr(
        "agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat"
    )

    def fake_wait(desk, token, **kw):
        assert kw.get("skip_first_sync") is True
        return {
            "ok": True,
            "mode": "hold",
            "hint": {"hint": "MAIL", "type": "mail", "id": 9},
            "desk": "d1",
        }

    monkeypatch.setattr("agent_coord.client.ws.wait_one_hint", fake_wait)
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
    """(d) connect-wait does not print the mill connect stderr banner."""
    import agent_coord.__main__ as m

    monkeypatch.setattr(
        "agent_coord.client.tokens.read_session_token", lambda owner, **k: "seat"
    )

    def fake_http(args):
        assert bool(getattr(args, "foreground", False)) is True
        print(json.dumps({"ok": True, "hint": {"id": 1}}, default=str), flush=True)
        return 0

    monkeypatch.setattr("agent_coord.client.http.mill_here_over_http", fake_http)
    monkeypatch.setattr(m, "mill_here_over_http", fake_http, raising=False)
    code = m.main(["connect-wait", "d1"])
    err = capsys.readouterr().err
    assert code == 0
    assert "mill connect:" not in err
    assert "connecting" not in err.lower()


def test_docs_name_startup_sync_hold():
    conn = (ROOT / "docs" / "protocol" / "connect.md").read_text(encoding="utf-8")
    cli = (ROOT / "docs" / "protocol" / "cli-desk.md").read_text(encoding="utf-8")
    fg = (ROOT / "docs" / "protocol" / "grok-foreground.md").read_text(encoding="utf-8")
    skill = (
        ROOT / "docs" / "protocol" / "models" / "grok-bot" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "F-connect-wait-startup-sync" in conn
    assert "push_queue" in conn.lower() or "push queue" in conn.lower() or "time" in conn
    assert "last line" in cli.lower() or "final JSON" in cli or "one JSON" in cli.lower()
    # Major 1: these must not still say a non-empty first sync always ends connect-wait.
    assert "Non-empty: print it and exit" not in fg
    assert "Its first sync drains what queued" not in fg
    assert "connect-wait` holds the same way" not in skill
