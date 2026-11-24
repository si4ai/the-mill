# -*- coding: utf-8 -*-
"""Card 1303: the command word on a tw start, and the exit count line."""
from __future__ import annotations

import sys
import threading

import pytest

from agent_coord.client.tw.link import Session, serve
from agent_coord.client.tw.proc import run_argv
from agent_coord.client.tw.protocol import command_word, error_lines


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def _within(fn, seconds=3):
    box: dict = {}

    def run():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        raise AssertionError("timed out")
    if "error" in box:
        raise box["error"]
    return box.get("value")


@pytest.mark.parametrize(
    ("argv", "want"),
    [
        (["pytest"], "pytest"),
        (["pytest", "tests/x.py"], "pytest"),
        ([r"C:\Git\cmd\git.EXE", "push"], "git push"),
        (["git", "-C", "repo", "status"], "git"),
        (["git", "push", "origin"], "git push"),
        (["mill", "send"], "mill send"),
        (["mill", "--office", "local", "send"], "mill"),
        (["python", "-m", "pytest", "tests/x.py"], "pytest"),
        (["python", "-m", "pip", "install"], "pip install"),
        (["py", "-m", "rco", "pack"], "rco pack"),
        (["python3", "-m", "agent_coord.client.build_wake"], "agent_coord.client.build_wake"),
        (["Python.EXE"], "python"),
        (["g++", "main.cpp"], "g++"),
        (["git", "--no-pager"], "git"),
        ([], None),
        (["..."], None),
    ],
)
def test_command_word(argv, want) -> None:
    assert command_word(argv) == want


def test_error_lines_use_the_office_count() -> None:
    lines = error_lines({
        "kind": "usage",
        "cmd": "pytest",
        "count": 23,
        "n": 100,
        "span_s": 3600,
        "next": "exit 4: check the args and paths",
    })
    assert lines == [
        "pytest usage error: 23 of your last 100 runs, over the past 1h",
        "exit 4: check the args and paths",
    ]
    assert error_lines({"kind": "usage", "cmd": "pytest", "count": 1, "n": 41, "span_s": 172800}) == []
    assert error_lines({"kind": "git_fatal", "count": 3, "n": 41, "span_s": 172800}) == [
        "fatal error: 3 of your last 41 runs, over the past 2d",
    ]
    assert error_lines({"kind": "other_nonzero", "count": True, "n": 2, "span_s": 10}) == []
    assert error_lines({"kind": "usage", "count": 4, "span_s": 10}) == []


def test_start_hop_keeps_a_command_word_and_drops_a_bad_one(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops = []

    def fake_http(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", fake_http)
    link = serve("tw-cmd")
    session = Session(link)
    try:
        _within(lambda: session.request({
            "type": "event", "watch_id": "w-cmd", "kind": "start", "cmd": "git push",
        }))
        _within(lambda: session.request({
            "type": "event", "watch_id": "w-bad", "kind": "start", "cmd": "Git Push",
        }))
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert events[0]["cmd"] == "git push"
        assert "cmd" not in events[1]
    finally:
        session.close()
        link.close()


def test_nonzero_exit_returns_errors_and_a_zero_exit_does_not(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    hops = []
    errors = {
        "kind": "usage",
        "cmd": "pytest",
        "count": 23,
        "n": 100,
        "span_s": 1800,
        "next": "exit 4: check the args and paths",
        "extra": "nope",
    }

    def fake_http(body):
        hops.append(dict(body))
        if body.get("kind") == "exit" and body.get("exit_code") == 4:
            return {"ok": True, "result": {"ok": True, "errors": errors}}
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", fake_http)
    link = serve("tw-count")
    session = Session(link)
    try:
        failed = _within(lambda: session.request({
            "type": "event", "watch_id": "w-fail", "kind": "exit", "exit_code": 4,
        }))
        assert failed["ok"] is True
        assert failed["errors"] == {
            "kind": "usage",
            "cmd": "pytest",
            "count": 23,
            "n": 100,
            "span_s": 1800,
            "next": "exit 4: check the args and paths",
        }
        clean = _within(lambda: session.request({
            "type": "event", "watch_id": "w-ok", "kind": "exit", "exit_code": 0,
        }))
        assert clean["ok"] is True
        assert "errors" not in clean
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert [item.get("exit_code") for item in events] == [4, 0]
    finally:
        session.close()
        link.close()


def test_run_prints_the_count_on_a_nonzero_exit(tmp_path, monkeypatch, capsys) -> None:
    _home(monkeypatch, tmp_path)
    hops = []

    def fake_http(body):
        hops.append(dict(body))
        if body.get("kind") == "exit":
            return {
                "ok": True,
                "result": {
                    "ok": True,
                    "errors": {
                        "kind": "usage",
                        "cmd": "pytest",
                        "count": 23,
                        "n": 100,
                        "span_s": 3600,
                        "next": "exit 4: check the args and paths",
                    },
                },
            }
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", fake_http)
    link = serve("tw-print")
    argv = [sys.executable, "-c", "import sys; sys.exit(4)"]
    try:
        code = run_argv("tw-print", argv)
        assert code == 4
        err = capsys.readouterr().err
        assert "pytest usage error: 23 of your last 100 runs, over the past 1h" in err
        assert "exit 4: check the args and paths" in err
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert events[0]["kind"] == "start"
        assert events[0]["cmd"] == command_word(argv)
        assert "cmd" not in events[1]
    finally:
        link.close()
