"""A connect that stops because its shell ended says what to do; the bridge hint names wrappers (#361).

Regression row F55 (connect-one-call-hint).
"""
from __future__ import annotations

import inspect
import json

import pytest

from agent_coord.client import http, ws
from agent_coord.client.session_errors import (
    ONE_LINER,
    PS_ONE_LINER,
    SESSION_CONNECT_DIED,
    bridge_hint,
    parent_exited_notice,
)


def test_parent_exited_posix_names_the_one_call_recipe():
    row = parent_exited_notice("builder", "posix")
    assert list(row)[:4] == ["ok", "mode", "reason", "desk"]
    assert row["ok"] is True and row["reason"] == "parent exited" and row["desk"] == "builder"
    assert ONE_LINER in row["hint"] and "one tool call" in row["hint"]
    assert "Start-Process" not in row["hint"]
    json.dumps(row).encode("ascii")


def test_parent_exited_windows_names_start_process_and_no_bash():
    row = parent_exited_notice("builder", "nt")
    assert PS_ONE_LINER in row["hint"] and "one tool call" in row["hint"]
    assert "bash" not in row["hint"] and "/dev/null" not in row["hint"]
    row["hint"].encode("ascii")


def test_parent_exited_keeps_extra_fields():
    row = parent_exited_notice("builder", "posix", url="wss://192.0.2.1/ws/builder")
    assert row["url"] == "wss://192.0.2.1/ws/builder" and "hint" in row


def test_both_connect_loops_print_the_notice():
    # The seat hold (mill connect) and the ws sit loop both stop on parent exit (#192).
    from agent_coord.client.seat import session as seat_session

    assert "parent_exited_notice(desk)" in inspect.getsource(seat_session)
    assert "parent_exited_notice(who, url=sit_url)" in inspect.getsource(ws)
    assert '"reason": "parent exited"' not in inspect.getsource(seat_session)
    assert '"reason": "parent exited"' not in inspect.getsource(http)
    assert '"reason": "parent exited"' not in inspect.getsource(ws)


def test_bridge_hint_posix_names_wrappers_and_one_call():
    text = bridge_hint("posix")
    for word in ("ONE tool call", "timeout", "nohup", "( ) subshell", "second bash -c", "direct child"):
        assert word in text
    assert "redirecting its output to a file is fine" in text


def test_bridge_hint_windows_names_start_process_lifetime():
    text = bridge_hint("nt")
    assert "ONE tool call" in text and "Start-Process connect stops" in text and "cmd /c" in text
    assert "bash" not in text and "/dev/null" not in text and "nohup" not in text


@pytest.mark.parametrize("word", ["new tool call is a new shell", "Start-Process", "one tool call"])
def test_connect_died_says_why_and_what(word):
    assert word in SESSION_CONNECT_DIED
    assert "bash" not in SESSION_CONNECT_DIED
    SESSION_CONNECT_DIED.encode("ascii")
