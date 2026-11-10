# -*- coding: utf-8 -*-
"""Card 970 step 2: local watch and status. No stream bodies on the hop."""
from __future__ import annotations

import json
import os
import sys
import threading
import time

from agent_coord.client.tw.link import open_session, serve
from agent_coord.client.tw.proc import query_status, run_argv
from agent_coord.client.tw.sample import take


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def test_sample_updates_the_buffer_and_does_not_hop(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    calls: list[dict] = []

    def _hop(body):
        calls.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _hop)
    link = serve("tw-buf")
    session = open_session("tw-buf")
    try:
        registered = session.request(
            {"type": "register", "key": "tw-buffer", "argv": ["tool"]}
        )
        assert registered["ok"] is True
        accepted = session.request(
            {
                "type": "event",
                "watch_id": "tw-buffer",
                "kind": "start",
                "pid": 4,
                "stdout": "secret-stream",
                "argv": ["tool"],
                "title": "name",
                "pattern": "seek",
            }
        )
        assert accepted["msg"] == "accepted"
        noted = session.request(
            {
                "type": "sample",
                "watch_id": "tw-buffer",
                "pid": 4,
                "stdout_bytes": 4,
                "stderr_bytes": 1,
                "log": True,
                "stdout": "more-secret",
                "sample": {"threads": 2, "note": "drop-me"},
            }
        )
        assert noted["ok"] is True
        assert noted["msg"] == "noted"
        reply = session.request({"type": "status", "watch_id": "tw-buffer"})
        assert reply["ok"] is True
        snap = reply["snapshot"]
        assert snap["stdout_bytes"] == 4
        assert snap["stderr_bytes"] == 1
        assert snap["log"] is True
        assert snap["sample"] == {"threads": 2}
        assert snap["kind"] == "start"
        dumped = json.dumps(snap)
        assert "secret" not in dumped
        assert "drop-me" not in dumped
        assert "tool" not in dumped
        assert len(calls) == 1
        banned = ("stdout", "stderr", "log", "sample", "argv", "title", "pattern")
        for body in calls:
            for key in banned:
                assert key not in body
    finally:
        session.close()
        link.close()


def test_run_counts_stdout_and_writes_the_log(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    calls: list[dict] = []

    def _hop(body):
        calls.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", _hop)
    link = serve("tw-watch")
    log_path = tmp_path / "child.log"
    box: dict = {}

    def go() -> None:
        try:
            box["code"] = run_argv(
                "tw-watch",
                [sys.executable, "-c", "print('hello-step2', flush=True)"],
                log_path=str(log_path),
            )
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=go, daemon=True)
    thread.start()
    thread.join(10)
    try:
        assert not thread.is_alive(), box
        assert "error" not in box, box
        assert box["code"] == 0
        reply = query_status("tw-watch")
        assert reply["ok"] is True
        rows = reply["snapshot"]
        assert rows and rows[0]["stdout_bytes"] >= len("hello-step2")
        assert rows[0]["log"] is True
        assert "stdout" not in rows[0]
        assert "argv" not in rows[0]
        assert b"hello-step2" in log_path.read_bytes()
        deadline = time.time() + 3
        while time.time() < deadline and not any(body.get("kind") == "exit" for body in calls):
            time.sleep(0.05)
        assert calls
        banned = ("stdout", "stderr", "log", "sample", "argv", "title", "pattern")
        for body in calls:
            for key in banned:
                assert key not in body
    finally:
        link.close()


def test_take_returns_numbers_for_this_process() -> None:
    sample = take(os.getpid())
    assert isinstance(sample, dict)
    assert sample
    for value in sample.values():
        assert isinstance(value, int)
