# -*- coding: utf-8 -*-
"""Route runs the handler. No route wakes. Empty route does neither."""
import json
import os
import shlex
import subprocess
import sys

import pytest

from agent_coord.client.dispatch import dispatch_hint, public_frame
from agent_coord.client.route_chain import save_routes
from agent_coord.client.watch_filter import save_want


def test_public_frame_drops_secrets_and_caps_detail() -> None:
    frame = public_frame(
        {
            "type": "todo",
            "id": 9,
            "hint": "TODO",
            "detail": "x" * 5000,
            "token": "sekret",
            "authorization": "Bearer abc",
            "body": "the whole letter",
        },
        "grok-tui",
    )
    assert frame["desk"] == "grok-tui"
    assert frame["detail"] == "x" * 4096
    assert "token" not in frame
    assert "authorization" not in frame
    assert "body" not in frame


def test_route_hit_runs_handler_and_does_not_wake(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    seen = {}

    class FakeProc:
        returncode = 0

        def communicate(self, data=None, timeout=None):
            seen["raw"] = data
            seen["closed"] = True
            return b"handled\n", b""

    def fake_popen(argv, **kw):
        seen["argv"] = argv
        seen["shell"] = kw.get("shell", False)
        return FakeProc()

    monkeypatch.setattr("agent_coord.client.route_chain.subprocess.Popen", fake_popen)
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    argv = [sys.executable, os.path.join("work", "on_mail.py")]
    stored = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    save_routes("builder", {"mail:MAIL": stored})
    kind = dispatch_hint(
        "builder",
        {
            "type": "mail",
            "id": 3,
            "hint": "MAIL",
            "route": "mail:MAIL",
            "detail": "src,dst",
            "token": "sekret",
        },
    )
    assert kind == "work"
    assert seen["shell"] is False
    assert seen["argv"] == argv
    body = json.loads(seen["raw"].decode("utf-8"))
    assert body["detail"] == "src,dst"
    assert body["id"] == 3
    assert "token" not in body


def test_no_route_wakes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_VENDOR", "grok-build")
    calls = []

    def fake_poke(vendor, hint):
        calls.append((vendor, hint))
        return True

    monkeypatch.setattr("agent_coord.client.connectors.poke", fake_poke)
    monkeypatch.setattr(
        "agent_coord.client.route_chain.subprocess.Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn")),
    )
    kind = dispatch_hint(
        "builder",
        {"type": "mail", "id": 3, "hint": "MAIL", "detail": "src", "password": "nope"},
    )
    assert kind == "wake"
    assert calls[0][0] == "grok-build"
    assert calls[0][1]["detail"] == "src"
    assert "password" not in calls[0][1]


def test_empty_route_suppresses(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    save_routes("builder", {"mail:MAIL": ""})
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    monkeypatch.setattr(
        "agent_coord.client.route_chain.subprocess.Popen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("spawn")),
    )
    kind = dispatch_hint("builder", {"type": "mail", "id": 1, "hint": "MAIL", "route": "mail:MAIL"})
    assert kind == "suppress"


def test_watch_allowlist_skips(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    save_want("builder", {"todo:TODO": ""})
    monkeypatch.setattr(
        "agent_coord.client.connectors.poke",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("wake")),
    )
    kind = dispatch_hint("builder", {"type": "mail", "id": 1, "hint": "MAIL", "route": "mail:MAIL"})
    assert kind == "skip"


def test_ping_skips() -> None:
    assert dispatch_hint("builder", {"type": "heartbeat", "id": 0, "hint": "PING"}) == "skip"


def test_oversized_frame_does_not_spawn(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.route_chain.FRAME_MAX", 32)
    save_routes("builder", {"mail:MAIL": "python on_mail.py"})
    with pytest.raises(ValueError):
        dispatch_hint(
            "builder",
            {"type": "mail", "id": 1, "hint": "MAIL", "route": "mail:MAIL", "detail": "x" * 80},
        )


def test_no_route_sit_exit_when_poke_false(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setenv("AGENT_COORD_VENDOR", "grok-build")

    def fake_poke(vendor, hint):
        return False

    monkeypatch.setattr("agent_coord.client.connectors.poke", fake_poke)
    kind = dispatch_hint(
        "builder",
        {"type": "mail", "id": 3, "hint": "MAIL", "detail": "src"},
    )
    assert kind == "sit-exit"
