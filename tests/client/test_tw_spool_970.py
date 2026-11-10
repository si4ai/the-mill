# -*- coding: utf-8 -*-
"""Sit-end leaves the child running. The pointer and the tw launcher stay."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from agent_coord.client.tw.link import open_session, pointer_path, serve
from agent_coord.client.tw.proc import list_runs, run_argv, stop_run
from agent_coord.lib.proc import CONSOLE_LAUNCHERS


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def test_sit_end_keeps_the_child(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-live")
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-live",
                [sys.executable, "-c", "import time; time.sleep(30)"],
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    try:
        sent = False
        rows: list = []
        deadline = time.time() + 5
        while time.time() < deadline:
            rows = list_runs("tw-live")
            if rows and link.stop(rows[0]["watch_id"], "sit-end"):
                sent = True
                break
            time.sleep(0.05)
        assert sent, box
        time.sleep(0.3)
        assert thread.is_alive(), box
        assert list_runs("tw-live"), box
        assert stop_run("tw-live", rows[0]["watch_id"]) == 0
        thread.join(5)
        assert not thread.is_alive(), box
        assert "error" not in box
    finally:
        link.close()


def test_pointer_comes_back_on_the_same_path(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    path = pointer_path("tw-back")
    link = serve("tw-back")
    try:
        assert path.name.endswith(".tw")
        assert path.is_file()
    finally:
        link.close()
    assert not path.exists()
    link = serve("tw-back")
    try:
        assert path.is_file()
        session = open_session("tw-back")
        session.close()
    finally:
        link.close()


def test_tw_launcher_sits_beside_mill() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'mill = "agent_coord.__main__:main"' in text
    assert 'tw = "agent_coord.client.tw.cli:main"' in text
    assert "tw.exe" in CONSOLE_LAUNCHERS
    assert "mill.exe" in CONSOLE_LAUNCHERS
