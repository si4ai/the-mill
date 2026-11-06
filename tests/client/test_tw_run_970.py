# -*- coding: utf-8 -*-
"""Card 970 slice (b): tw run, list, and stop. No doing write."""
from __future__ import annotations

import sys
import threading
import time

from agent_coord.client.route_chain import load_routes
from agent_coord.client.tw.link import serve
from agent_coord.client.tw.proc import list_runs, run_argv, stop_run


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def test_run_registers_lists_and_stops(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-run")
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-run",
                [sys.executable, "-c", "import time; time.sleep(30)"],
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    try:
        rows: list = []
        deadline = time.time() + 5
        while time.time() < deadline:
            rows = list_runs("tw-run")
            if rows:
                break
            time.sleep(0.05)
        assert rows, box
        watch_id = rows[0]["watch_id"]
        assert stop_run("tw-run", watch_id) == 0
        thread.join(5)
        assert not thread.is_alive(), box
        assert "error" not in box
        keys = [key for key, _argv in load_routes("tw-run")]
        assert watch_id in keys
        assert list_runs("tw-run") == []
    finally:
        link.close()


def test_connect_stop_ends_the_child(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-stop")
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-stop",
                [sys.executable, "-c", "import time; time.sleep(30)"],
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    try:
        rows: list = []
        deadline = time.time() + 5
        while time.time() < deadline:
            rows = list_runs("tw-stop")
            if rows:
                break
            time.sleep(0.05)
        assert rows, box
        assert link.stop(rows[0]["watch_id"], "desk") is True
        thread.join(5)
        assert not thread.is_alive(), box
        assert "error" not in box
    finally:
        link.close()
