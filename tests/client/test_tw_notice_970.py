# -*- coding: utf-8 -*-
"""Card 970 step 3: match, stall, no-wake, and one recipe lifecycle."""
from __future__ import annotations

import json
import sys
import threading
import time

from agent_coord.client.tw.link import open_session, serve
from agent_coord.client.tw.notice import Notices
from agent_coord.client.tw.proc import run_argv


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def test_notices_match_once_and_stall_then_resume() -> None:
    notes = Notices("hello", 5.0)
    notes.start(0.0)
    assert notes.feed("", 0, 4.9) == []
    assert notes.feed("", 0, 5.0) == [("stall", "quiet")]
    assert notes.feed("", 0, 9.0) == []
    got = notes.feed("hello-step2", 11, 9.1)
    assert ("resume", "output") in got
    assert ("match", "pattern") in got
    assert notes.feed("hello again", 22, 9.2) == []


def test_pattern_and_no_wake_stay_off_the_stream(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    calls: list[dict] = []

    def _hop(body):
        calls.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _hop)
    link = serve("tw-note")
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-note",
                [sys.executable, "-c", "print('hello-step2', flush=True)"],
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    thread.join(10)
    try:
        assert not thread.is_alive(), box
        assert box.get("code") == 0, box
        deadline = time.time() + 3
        while time.time() < deadline and not any(body.get("kind") == "exit" for body in calls):
            time.sleep(0.05)
        kinds = [body.get("kind") for body in calls if body.get("verb") == "tw.event"]
        assert kinds == ["start", "exit"], kinds
        for body in calls:
            assert "wake" not in body
            assert "pattern" not in body
            assert "stdout" not in body
            assert "argv" not in body
            dumped = json.dumps(body)
            assert "hello-step2" not in dumped
    finally:
        link.close()


def test_recipe_is_one_lifecycle(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    calls: list[dict] = []

    def _hop(body):
        calls.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _hop)
    link = serve("tw-recipe")
    log_path = tmp_path / "recipe.log"
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-recipe",
                [sys.executable, "-c", "print('HELLO-STEP2', end='')"],
                log_path=str(log_path),
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    thread.join(10)
    try:
        assert not thread.is_alive(), box
        assert box.get("code") == 0, box
        deadline = time.time() + 3
        while time.time() < deadline and not any(body.get("kind") == "exit" for body in calls):
            time.sleep(0.05)
        kinds = [body.get("kind") for body in calls if body.get("verb") == "tw.event"]
        assert kinds == ["start", "exit"], kinds
        assert b"HELLO-STEP2" in log_path.read_bytes()
    finally:
        link.close()
