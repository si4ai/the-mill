# -*- coding: utf-8 -*-
"""mill-hold: a non-empty kind:sync list returns; an empty list does not."""
from __future__ import annotations

import asyncio
import json

from agent_coord.client import ws as ws_client
from agent_coord.client.hold import main as hold_main
from agent_coord.client.offices import bind_cli_office


class _FakeWS:
    def __init__(self, frames):
        self._frames = list(frames)
        self._i = 0

    async def recv(self):
        if self._i >= len(self._frames):
            await asyncio.sleep(10)
            raise asyncio.TimeoutError()
        raw = self._frames[self._i]
        self._i += 1
        return raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _ConnCM:
    def __init__(self, ws):
        self._ws = ws

    async def __aenter__(self):
        return self._ws

    async def __aexit__(self, *a):
        return False


def _patch_socket(monkeypatch, frames):
    fake = _FakeWS(frames)

    def _connect(url, **kw):
        return _ConnCM(fake)

    monkeypatch.setattr(ws_client, "mill_ws_url", lambda desk: "ws://127.0.0.1/ws/DESK_x")
    monkeypatch.setattr("websockets.connect", _connect)


def test_nonempty_sync_returns_empty_sync_does_not(monkeypatch):
    queued = {
        "kind": "sync",
        "sync": [
            {
                "kind": "hint",
                "type": "doing",
                "hint": "DOING",
                "outcome": "missed",
            }
        ],
        "mill": "0.6.5",
    }
    _patch_socket(monkeypatch, [json.dumps(queued)])
    got = ws_client.wait_one_hint(
        "x",
        "tok",
        skip_ping=True,
        timeout_s=5,
        skip_kinds=(),
        hold_empty_sync=True,
    )
    assert got["ok"] is True
    assert got["hint"]["sync"] == queued["sync"]
    assert got["hint"]["sync"][0]["hint"] == "DOING"

    _patch_socket(
        monkeypatch,
        [
            json.dumps({"kind": "sync", "sync": [], "mill": "0.6.5"}),
            json.dumps({"hint": "MAIL", "type": "mail", "id": 7}),
        ],
    )
    held = ws_client.wait_one_hint(
        "x",
        "tok",
        skip_ping=True,
        timeout_s=5,
        hold_empty_sync=True,
    )
    assert held["ok"] is True
    assert held["hint"]["hint"] == "MAIL"
    assert held["hint"]["id"] == 7

    _patch_socket(monkeypatch, [json.dumps({"kind": "sync", "sync": []})])
    empty = ws_client.wait_one_hint(
        "x",
        "tok",
        skip_ping=True,
        timeout_s=0.4,
        hold_empty_sync=True,
    )
    assert empty["ok"] is False
    assert empty["error"] == "timeout"
    assert "sync" not in empty


def test_foreground_one_shot_returns_empty_sync(monkeypatch):
    frame = {"kind": "sync", "sync": [], "mill": "0.6.5"}
    _patch_socket(monkeypatch, [json.dumps(frame)])
    got = ws_client.wait_one_hint("x", "tok", skip_ping=True, timeout_s=5)
    assert got["ok"] is True
    assert got["mode"] == "foreground"
    assert got["hint"]["sync"] == []


def test_mill_hold_prints_queue_and_does_not_join(monkeypatch, capsys):
    def _boom(*_a, **_k):
        raise AssertionError("mill-hold must not join or install a CA")

    monkeypatch.setattr("agent_coord.client.offices.join_office", _boom)
    monkeypatch.setattr("agent_coord.client.http.materialize_mill_ca", _boom)
    monkeypatch.setattr("agent_coord.client.http.fetch_mill_ca", _boom)
    monkeypatch.setattr(
        "agent_coord.client.hold.read_session_token",
        lambda owner, **k: "seat-token",
    )
    seen = {}

    def _wait(desk, token, **kw):
        seen["desk"] = desk
        seen["token"] = token
        seen["kw"] = kw
        return {
            "ok": True,
            "mode": "hold",
            "hint": {
                "kind": "sync",
                "sync": [{"kind": "hint", "hint": "DOING", "outcome": "missed"}],
            },
        }

    monkeypatch.setattr("agent_coord.client.hold.wait_one_hint", _wait)
    try:
        code = hold_main(["the-mill", "builder", "--office", "lab"])
    finally:
        bind_cli_office("")
    assert code == 0
    assert seen["desk"] == "builder"
    assert seen["token"] == "seat-token"
    assert seen["kw"]["hold_empty_sync"] is True
    skipped = {str(k).strip().lower() for k in seen["kw"]["skip_kinds"]}
    assert "sync" not in skipped
    printed = json.loads(capsys.readouterr().out)
    assert printed["kind"] == "sync"
    assert printed["sync"][0]["hint"] == "DOING"
