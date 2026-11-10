# -*- coding: utf-8 -*-
"""Card 1090 step 3: a finished run stays listed, and the log keeps stderr."""
from __future__ import annotations

import sys

from agent_coord.client.tw.link import serve
from agent_coord.client.tw.proc import list_runs, query_status, run_argv


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)


def test_stderr_only_child_is_in_the_log(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-err-log")
    log_path = tmp_path / "push.log"
    try:
        code = run_argv(
            "tw-err-log",
            [sys.executable, "-c", "import sys; sys.stderr.write('pushed-tip\\n')"],
            log_path=str(log_path),
        )
        assert code == 0
        assert b"pushed-tip" in log_path.read_bytes()
    finally:
        link.close()


def test_finished_run_stays_on_list_and_status_without_a_sit(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-done")
    try:
        code = run_argv(
            "tw-done",
            [sys.executable, "-c", "import sys; sys.stderr.write('ok\\n')"],
        )
        assert code == 0
    finally:
        link.close()

    def down(*_a, **_k):
        raise OSError("down")

    monkeypatch.setattr("agent_coord.client.tw.proc.open_session", down)
    rows = list_runs("tw-done")
    assert len(rows) == 1
    assert rows[0]["exit_code"] == 0
    reply = query_status("tw-done", rows[0]["watch_id"])
    assert reply["ok"] is True
    assert reply["snapshot"]["exit_code"] == 0
    assert reply["snapshot"]["kind"] == "exit"
