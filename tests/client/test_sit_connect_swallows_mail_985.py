# -*- coding: utf-8 -*-
"""Card 985: plain connect with no chat-wake path exits (sit-exit), does not swallow."""
from __future__ import annotations

import json
import threading

from agent_coord.client.connectors import grok_build
from agent_coord.client.dispatch import dispatch_hint
from agent_coord.server.hint_buf import HintBuf, _drain_one


def test_grok_build_poke_stamp_only_returns_false(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.delenv("AGENT_COORD_GROK_SESSION", raising=False)
    monkeypatch.delenv("AGENT_COORD_BOT_WAKE_URL", raising=False)
    monkeypatch.setattr(grok_build.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        "agent_coord.client.connectors.spawn.spawn_hint",
        lambda _hint: False,
    )
    assert grok_build.poke({"desk": "grok-tui", "hint": "MAIL", "id": 4184, "kind": "mail"}) is False


def test_grok_build_poke_with_session_returns_true(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_GROK_SESSION", "00000000-0000-4000-8000-000000000001")
    monkeypatch.delenv("AGENT_COORD_BOT_WAKE_URL", raising=False)
    monkeypatch.setattr(grok_build.shutil, "which", lambda _name: "/usr/bin/grok")
    calls = []

    def fake_popen(argv, **kw):
        calls.append(argv)
        class P:
            pass
        return P()

    monkeypatch.setattr(grok_build.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        "agent_coord.client.connectors.spawn.spawn_hint",
        lambda _hint: False,
    )
    assert grok_build.poke({"desk": "grok-tui", "hint": "MAIL", "id": 4186, "kind": "mail"}) is True
    assert calls and calls[0][0].endswith("grok")


def test_dispatch_sit_exit_when_poke_does_not_ring(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.delenv("AGENT_COORD_VENDOR", raising=False)

    def fake_poke(vendor, hint):
        assert vendor == "grok-build"
        return False

    monkeypatch.setattr("agent_coord.client.connectors.poke", fake_poke)
    kind = dispatch_hint(
        "grok-tui",
        {"type": "mail", "id": 4184, "hint": "MAIL", "kind": "mail"},
    )
    assert kind == "sit-exit"


def test_dispatch_wake_when_poke_rings(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_VENDOR", "grok-build")

    def fake_poke(vendor, hint):
        return True

    monkeypatch.setattr("agent_coord.client.connectors.poke", fake_poke)
    kind = dispatch_hint(
        "grok-tui",
        {"type": "mail", "id": 4186, "hint": "MAIL", "kind": "mail"},
    )
    assert kind == "wake"


def test_drain_sit_exit_stops_connect(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    stop = threading.Event()
    outcome: dict = {}
    buf = HintBuf("grok-tui")
    frame = {"type": "mail", "id": 4184, "hint": "MAIL", "kind": "mail", "desk": "grok-tui"}

    def fake_dispatch(desk, msg, *, replay=False):
        return "sit-exit"

    monkeypatch.setattr("agent_coord.client.dispatch.dispatch_hint", fake_dispatch)
    _drain_one(buf, frame, "MAIL", 0.0, False, stop, outcome)
    assert stop.is_set()
    assert outcome.get("exit") == 0
    assert outcome.get("sit_exit", {}).get("id") == 4184
    out = capsys.readouterr().out
    row = json.loads(out.strip().splitlines()[-1])
    assert row["mode"] == "sit-exit"
    assert row["ok"] is True
    assert "connect-wait" in row["next"]
