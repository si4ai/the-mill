# -*- coding: utf-8 -*-
"""Card 1090: tw CMD, bare tw, and the two flags that stand alone."""
from __future__ import annotations

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
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip()


def test_no_sit_prints_the_recipe(monkeypatch, capsys) -> None:
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda *_a, **_k: "")
    marker_args = [sys.executable, "-c", "import sys; sys.exit(0)"]
    assert main([]) == 1
    assert main(marker_args) == 1
    err = capsys.readouterr().err
    assert err.count(bridge_hint().strip()) == 2


def test_bare_tw_lists_the_sitting_desk(monkeypatch, tmp_path, capsys) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.tokens.resolve_desk_owner", lambda *_a, **_k: "tw-list"
    )
    _save(
        "tw-list",
        {
            "tw-done": {
                "pid": 0,
                "argv": ["tool"],
                "stop": False,
                "tw_pid": 0,
                "state": "finished",
                "exit_code": 0,
            }
        },
    )
    assert main([]) == 0
    assert capsys.readouterr().out.strip() == "tw-done 0 0"


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
