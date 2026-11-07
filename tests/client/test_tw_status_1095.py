# -*- coding: utf-8 -*-
"""Status follows a live local run when the sit link is down or has no row."""
from __future__ import annotations

import os

from agent_coord.client.tw.link import serve
from agent_coord.client.tw.proc import _save, query_status


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)


def test_status_reports_a_live_run_when_the_link_is_down(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    _save("tw-local", {"tw-live": {"pid": os.getpid(), "argv": ["tool"], "stop": False}})
    reply = query_status("tw-local", "tw-live")
    assert reply["ok"] is True
    assert reply["snapshot"]["pid"] == os.getpid()
    assert reply["snapshot"]["watch_id"] == "tw-live"
    assert "argv" not in reply["snapshot"]


def test_status_stays_down_when_nothing_is_running(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    reply = query_status("tw-local", "tw-gone")
    assert reply["ok"] is False
    assert reply["msg"] == "down"


def test_status_uses_the_local_run_when_the_link_says_missing(tmp_path, monkeypatch) -> None:
    _home(monkeypatch, tmp_path)
    link = serve("tw-local")
    try:
        _save("tw-local", {"tw-live": {"pid": os.getpid(), "argv": ["tool"], "stop": False}})
        reply = query_status("tw-local", "tw-live")
        assert reply["ok"] is True
        assert reply["snapshot"]["pid"] == os.getpid()
    finally:
        link.close()
