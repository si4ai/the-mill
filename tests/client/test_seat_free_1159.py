# -*- coding: utf-8 -*-
"""Card 1159: stop and SIGTERM close a sitting connect instead of leaving the seat busy."""
from __future__ import annotations

import asyncio
import signal
import threading
import time

from agent_coord.client import ws as ws_cli
from agent_coord.client.seat.session import hold


class _HoldRecv:
    def __init__(self) -> None:
        self.cancelled = False
        self.started = threading.Event()

    async def recv(self) -> str:
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return ""

    async def send(self, _text: str) -> None:
        return None


def test_stop_unblocks_sit_while_recv_is_blocked() -> None:
    stop = threading.Event()
    outcome: dict = {}
    ws = _HoldRecv()
    mark: dict[str, float] = {}

    def later() -> None:
        assert ws.started.wait(3)
        time.sleep(0.3)
        mark["stop"] = time.monotonic()
        stop.set()

    threading.Thread(target=later, daemon=True).start()

    async def go() -> None:
        await asyncio.wait_for(
            ws_cli._sit_session(ws, "alice", stop, None, outcome=outcome),
            timeout=5,
        )
        mark["returned"] = time.monotonic()

    asyncio.run(go())
    assert mark["returned"] >= mark["stop"]
    assert mark["returned"] - mark["stop"] < 1.0
    assert ws.cancelled


def test_sigterm_sets_stop_so_hold_returns(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    monkeypatch.setattr("agent_coord.client.http.seat_then_focus", lambda *a, **k: None)
    calls = {"n": 0, "handler": None, "fired": False}

    def fake_start(desk, token, stop, outcome, refuse=False):
        thread = threading.Thread(target=stop.wait, args=(5,))
        thread.start()
        return thread

    def capture(sig, handler):
        if sig == signal.SIGTERM and calls["handler"] is None:
            calls["handler"] = handler
        return signal.SIG_DFL

    def parent_gone(_pid: int) -> bool:
        calls["n"] += 1
        handler = calls["handler"]
        if handler is not None and not calls["fired"]:
            calls["fired"] = True
            handler(signal.SIGTERM, None)
        return calls["n"] > 3

    monkeypatch.setattr(ws_cli, "start_ws_thread", fake_start)
    monkeypatch.setattr(signal, "signal", capture)
    assert hold("alice", "seat", parent=1, refuse=True, parent_gone=parent_gone, project="") == 0
    assert calls["fired"] is True
    assert calls["n"] == 1
