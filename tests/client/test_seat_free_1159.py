# -*- coding: utf-8 -*-
"""Card 1159: a SIGTERM close frame frees the seat. A drop with no close frame does not."""
from __future__ import annotations

import asyncio
import signal
import threading
import time

import pytest

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


def test_sigterm_close_frame_frees_the_seat(tmp_path, monkeypatch) -> None:
    """A real hold() child, SIGTERM, then a reconnect.

    The edge keeps the office socket up when the client vanishes without a
    close frame. The seat frees only because the handler closes the socket
    before the process exits.
    """
    import sys

    if sys.platform == "win32":
        pytest.skip("a Windows process kill does not run the SIGTERM handler")

    import json
    import os
    import socket
    import subprocess
    from pathlib import Path

    import uvicorn
    import websockets
    from websockets.exceptions import ConnectionClosed

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server.asgi import make_asgi_app
    from agent_coord.server.push import HUB

    class _Ctx:
        _cn = object()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.book.Book", lambda *a, **k: _Ctx())
    monkeypatch.setattr("agent_coord.server.records.join.token_matches", lambda cn, d, h: True)
    monkeypatch.setattr("agent_coord.server.records.join.note_connect", lambda cn, d: None)
    monkeypatch.setattr("agent_coord.server.records.join.mark_socket", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.records.db.warm_pool", lambda: None)
    monkeypatch.setattr("agent_coord.server.records.db.warm_read_paths", lambda *a, **k: None)
    monkeypatch.setattr(
        "agent_coord.server.push.connect_sync_frame",
        lambda cn, d, **k: {"kind": "sync", "sync": []},
    )
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr(HUB, "rooms", {})

    root = Path(__file__).resolve().parents[2]
    app = make_asgi_app(parse_roots(cwd=root), api_only=True)
    office_sock = socket.socket()
    office_sock.bind(("127.0.0.1", 0))
    office_port = office_sock.getsockname()[1]
    office_sock.close()
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=office_port,
            log_level="error",
            access_log=False,
        )
    )
    office_thread = threading.Thread(target=server.run, name="mill-1159-office", daemon=True)
    office_thread.start()
    edge_box: dict = {"report": [], "ready": threading.Event()}

    def _edge() -> None:
        async def main() -> None:
            stop = asyncio.Event()
            edge_box["stop"] = stop
            edge_box["loop"] = asyncio.get_running_loop()

            async def handler(client) -> None:
                path = client.request.path
                headers = {}
                auth = client.request.headers.get("Authorization")
                if auth:
                    headers["Authorization"] = auth
                url = f"ws://127.0.0.1:{office_port}{path}"
                async with websockets.connect(
                    url,
                    additional_headers=headers,
                    open_timeout=5,
                    ping_interval=None,
                ) as office:
                    async def pump(src, dst) -> None:
                        async for msg in src:
                            await dst.send(msg)

                    to_office = asyncio.create_task(pump(client, office))
                    to_client = asyncio.create_task(pump(office, client))
                    done, _pending = await asyncio.wait(
                        {to_office, to_client}, return_when=asyncio.FIRST_COMPLETED
                    )
                    for task in (to_office, to_client):
                        if task not in done:
                            task.cancel()
                    for task in (to_office, to_client):
                        try:
                            await task
                        except (asyncio.CancelledError, Exception):
                            pass
                    for _ in range(10):
                        if client.close_code is not None:
                            break
                        await asyncio.sleep(0.02)
                    if to_office in done and client.close_code not in (None, 1006):
                        await office.close()
                        edge_box["report"].append("forwarded")
                    elif to_office in done:
                        edge_box["report"].append("held")
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=15)
                        except asyncio.TimeoutError:
                            pass

            served = await websockets.serve(
                handler, "127.0.0.1", 0, ping_interval=None
            )
            edge_box["port"] = served.sockets[0].getsockname()[1]
            edge_box["ready"].set()
            await stop.wait()
            served.close()
            await served.wait_closed()

        try:
            asyncio.run(main())
        except Exception as exc:
            edge_box["err"] = exc
            edge_box["ready"].set()

    edge_thread = threading.Thread(target=_edge, name="mill-1159-edge", daemon=True)
    edge_thread.start()
    child = None
    try:
        assert edge_box["ready"].wait(5), edge_box.get("err")
        assert "err" not in edge_box, edge_box["err"]
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("office did not start")
        env = os.environ.copy()
        env["AGENT_COORD_MILL_HOME"] = str(tmp_path)
        env["AGENT_COORD_MILL_URL"] = f"http://127.0.0.1:{edge_box['port']}"
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import agent_coord.client.http as http\n"
                "http.seat_then_focus = lambda *a, **k: None\n"
                "import os, sys\n"
                "from agent_coord.lib.proc import parent_gone\n"
                "from agent_coord.client.seat.session import hold\n"
                "sys.exit(hold('alice', 'seat', parent=os.getppid(), refuse=True,"
                " parent_gone=parent_gone, project=''))\n",
            ],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(root),
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if HUB.rooms.get("alice"):
                break
            if child.poll() is not None:
                break
            time.sleep(0.05)
        out, err = b"", b""
        if not HUB.rooms.get("alice"):
            if child.poll() is None:
                child.kill()
            out, err = child.communicate()
            raise AssertionError(
                f"connect never sat rooms={list(HUB.rooms)} out={out!r} err={err!r}"
            )
        child.send_signal(signal.SIGTERM)
        try:
            out, err = child.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            child.kill()
            out, err = child.communicate()
            raise AssertionError(f"child stayed up out={out!r} err={err!r}")
        assert child.returncode == 0, f"out={out!r} err={err!r}"
        seen = time.monotonic() + 3
        while time.monotonic() < seen and not edge_box["report"]:
            time.sleep(0.05)
        assert edge_box["report"] == ["forwarded"], edge_box["report"]

        async def again() -> dict:
            last = ""
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try:
                    async with websockets.connect(
                        f"ws://127.0.0.1:{office_port}/ws/alice?refuse=1",
                        additional_headers={"Authorization": "Bearer seat"},
                        open_timeout=2,
                        ping_interval=None,
                    ) as ws:
                        raw = await asyncio.wait_for(ws.recv(), 2)
                    return json.loads(raw)
                except ConnectionClosed as exc:
                    last = str(exc)
                    await asyncio.sleep(0.1)
            raise AssertionError(f"seat stayed busy: {last}")

        sat = asyncio.run(again())
        assert sat.get("kind") == "sync"
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.communicate()
        loop = edge_box.get("loop")
        stop = edge_box.get("stop")
        if loop is not None and stop is not None:
            loop.call_soon_threadsafe(stop.set)
        edge_thread.join(timeout=5)
        server.should_exit = True
        office_thread.join(timeout=5)
        HUB.rooms.clear()
