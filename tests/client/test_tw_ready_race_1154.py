# -*- coding: utf-8 -*-
"""Card 1154: tw refused with the no-sitting-connect text while the desk's connect was up."""
from __future__ import annotations

import os
import sys
import time

import pytest

from agent_coord.client import session_errors
from agent_coord.client.tw.cli import main
from agent_coord.client.tw.link import Session, open_session, pointer_path, serve


def _home(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.client.http.mill_http_call", lambda body: {"ok": True})


def _register(session: Session, key: str) -> dict:
    return session.request({"type": "register", "key": key, "argv": ["true"]})


def _until(check, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met")


@pytest.mark.skipif(os.name == "nt", reason="unix socket transport")
def test_second_connect_leaves_the_sitting_link(tmp_path, monkeypatch) -> None:
    # A busy second connect for the same desk opens its link before the seat check,
    # then exits. It must not take or delete the sitting connect's socket and pointer.
    _home(monkeypatch, tmp_path)
    sitting = serve("tw-two")
    try:
        busy = serve("tw-two")
        busy.close()
        assert pointer_path("tw-two").is_file()
        session = open_session("tw-two")
        try:
            assert _register(session, "tw:after-busy")["ok"] is True
        finally:
            session.close()
    finally:
        sitting.close()
    assert not pointer_path("tw-two").exists()


@pytest.mark.skipif(os.name == "nt", reason="unix socket transport")
def test_taking_connect_serves_once_the_holder_leaves(tmp_path, monkeypatch) -> None:
    # connect --take: the old link answers until its connect exits, then the new one serves.
    _home(monkeypatch, tmp_path)
    old = serve("tw-take")
    new = serve("tw-take")
    try:
        old.close()

        def served() -> bool:
            try:
                session = open_session("tw-take")
            except OSError:
                return False
            try:
                return _register(session, "tw:after-take")["ok"] is True
            except OSError:
                return False
            finally:
                session.close()

        _until(served)
    finally:
        new.close()
    assert not pointer_path("tw-take").exists()


def test_tw_waits_for_a_starting_connect(tmp_path, monkeypatch, capsys) -> None:
    # The one-liner starts tw before connect prints ready. tw waits for the starting
    # connect like a mill command does, instead of refusing at its first look.
    _home(monkeypatch, tmp_path)
    from agent_coord.client import ws

    looks = {"n": 0}

    def bridge(parent_pid=None):
        looks["n"] += 1
        return {"desk": "tw-ready", "pid": os.getpid()} if looks["n"] > 2 else None

    monkeypatch.setattr(ws, "bridge_for_parent", bridge)
    monkeypatch.setattr(
        ws, "starting_for_parent", lambda parent_pid=None: {"desk": "tw-ready", "pid": os.getpid()}
    )
    monkeypatch.setattr(ws, "CONNECT_START_POLL_S", 0.0)
    link = serve("tw-ready")
    looks["n"] = 0  # count only tw's own looks
    try:
        code = main([sys.executable, "-c", "print('ran', flush=True)"])
    finally:
        link.close()
    out = capsys.readouterr()
    assert code == 0, out.err
    assert "ran" in out.out
    assert session_errors.tw_bridge_hint().strip() not in out.err


def test_tw_refusal_names_the_tw_form(monkeypatch, capsys) -> None:
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda *_a, **_k: "")
    monkeypatch.setattr("agent_coord.client.ws.wait_for_sitting_desk", lambda: "")
    assert main([sys.executable, "-c", "pass"]) == 1
    err = capsys.readouterr().err
    assert "tw CMD ARGS" in err
    assert "mill COMMAND" not in err
    for name in ("posix", "nt"):
        text = session_errors.tw_bridge_hint(name)
        assert "tw CMD ARGS" in text
        assert "mill COMMAND" not in text
    # mill commands keep their own form; the ws retry compares this exact string.
    assert "mill COMMAND ARGS" in session_errors.SESSION_WS_BRIDGE_REQUIRED
    assert session_errors.SESSION_WS_BRIDGE_REQUIRED == session_errors.bridge_hint()


def test_link_lost_mid_run_is_not_the_no_sit_refusal() -> None:
    text = session_errors.tw_link_lost()
    assert "no sitting mill connect" not in text
    assert "keeps running" in text
