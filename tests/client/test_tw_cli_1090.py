# -*- coding: utf-8 -*-
"""Card 1090: tw CMD, bare tw, and the two flags that stand alone."""
from __future__ import annotations

import json
import os
import sys

from agent_coord.client.session_errors import bridge_hint
from agent_coord.client.tw.cli import main
from agent_coord.client.tw.link import serve
from agent_coord.client.tw.proc import _save


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def test_help_and_version_need_no_sit(capsys) -> None:
    assert main(["--help"]) == 0
    text = capsys.readouterr().out
    assert text.startswith("usage: tw CMD ARGS")
    assert "mill connect" not in text
    assert main(["-h"]) == 0
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("usage: tw CMD ARGS")
    assert main(["--version"]) == 0
    assert main(["-V"]) == 0
    version = capsys.readouterr().out.strip().splitlines()
    assert len(version) == 2
    assert version[0] == version[1]


def test_no_sit_prints_the_recipe(monkeypatch, capsys) -> None:
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda *_a, **_k: "")
    marker_args = [sys.executable, "-c", "import sys; sys.exit(0)"]
    assert main(marker_args) == 1
    assert main(["--list"]) == 1
    assert main(["-l"]) == 1
    assert main(["--list-json"]) == 1
    err = capsys.readouterr().err
    assert err.count(bridge_hint().strip()) == 4


def test_list_shows_a_running_row(monkeypatch, tmp_path, capsys) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.tokens.resolve_desk_owner", lambda *_a, **_k: "tw-list"
    )
    _save(
        "tw-list",
        {
            "tw-live": {
                "pid": os.getpid(),
                "argv": ["tool", "arg"],
                "stop": False,
                "tw_pid": os.getpid(),
                "start": "2026-11-10T06:00:00Z",
                "log": str(tmp_path / "run.log"),
            },
            "tw-done": {
                "pid": 0,
                "argv": ["tool"],
                "stop": False,
                "tw_pid": 0,
                "state": "finished",
                "exit_code": 0,
                "start": "2026-11-10T05:00:00Z",
                "log": str(tmp_path / "old.log"),
            },
        },
    )
    assert main(["--list"]) == 0
    text = capsys.readouterr().out
    assert "tw-live %s 2026-11-10T06:00:00Z" % os.getpid() in text
    assert "tw-done" not in text
    assert main(["--list-json"]) == 0
    row = json.loads(capsys.readouterr().out.strip())
    assert row["watch_id"] == "tw-live"
    assert row["tw_pid"] == os.getpid()
    assert row["command"] == ["tool", "arg"]
    assert row["start"] == "2026-11-10T06:00:00Z"


def test_old_run_words_are_the_command(monkeypatch, tmp_path, capsys) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True},
    )
    monkeypatch.setattr(
        "agent_coord.client.tokens.resolve_desk_owner", lambda *_a, **_k: "tw-old"
    )
    link = serve("tw-old")
    try:
        code = main(["run", "--desk", "nope"])
        assert code == 1
        err = capsys.readouterr().err
        assert bridge_hint().strip() not in err
        assert "run" in err.lower() or err
    finally:
        link.close()


def test_child_output_passes_through(monkeypatch, tmp_path, capsys) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True},
    )
    link = serve("tw-out")
    try:
        from agent_coord.client.tw.proc import run_argv

        code = run_argv(
            "tw-out",
            [sys.executable, "-c", "print('passed-through', flush=True)"],
        )
        assert code == 0
        captured = capsys.readouterr()
        assert "passed-through" in captured.out
        line = captured.err.splitlines()[0]
        watch_id, pid, raw_path = line.split(" ", 2)
        assert watch_id.startswith("tw-")
        assert int(pid) == os.getpid()
        assert b"passed-through" in open(raw_path, "rb").read()
    finally:
        link.close()
