"""Card 1238: failed-command stdout, stderr, and the server log line."""
from __future__ import annotations

import json
import logging

import pytest

from agent_coord.client.fail_out import emit_failure
from agent_coord.client.session_errors import SESSION_CONNECT_DIED, SESSION_WS_BRIDGE_REQUIRED
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill.rpc import dispatch_ws


def test_server_refusal_keeps_sync_and_label_warnings(capsys, monkeypatch):
    monkeypatch.setenv("MILL_PLANTED_SECRET", "super-secret-value")
    env = {
        "ok": False,
        "id": "req-1238",
        "error": "refused super-secret-value",
        "mill": "0.8.16",
        "sync": [{"type": "todo", "id": 1}],
        "label_warnings": ["unknown label"],
        "time": "2026-11-21T06:00:00Z",
    }
    assert emit_failure(CoordError("refused super-secret-value", envelope=env), args=None) == 1
    cap = capsys.readouterr()
    raw = cap.out.encode("utf-8")
    assert not raw.startswith(b"\xef\xbb\xbf")
    obj = json.loads(cap.out)
    assert obj["ok"] is False and obj["code"] == "refused" and obj["class"] == "refusal"
    assert obj["applied"] is False and obj["id"] == "req-1238" and obj["mill"] == "0.8.16"
    assert obj["sync"] == [{"type": "todo", "id": 1}]
    assert obj["label_warnings"] == ["unknown label"]
    assert obj["time"] == "2026-11-21T06:00:00Z"
    assert "super-secret-value" not in cap.out and "super-secret-value" not in cap.err
    assert cap.err == "refused req-1238\n"


def test_transport_and_tw_omit_sync_and_server_mill(capsys):
    emit_failure(CoordError(SESSION_CONNECT_DIED))
    cap = capsys.readouterr()
    obj = json.loads(cap.out)
    assert obj["code"] == "transport" and obj["class"] == "transport"
    assert "sync" not in obj and "mill" not in obj
    assert cap.err.startswith("transport ")
    emit_failure(CoordError(SESSION_WS_BRIDGE_REQUIRED))
    cap = capsys.readouterr()
    obj = json.loads(cap.out)
    assert obj["code"] == "tw_refused" and "sync" not in obj and "mill" not in obj
    assert "same parent process" not in cap.out


def test_busy_is_retryable_class(capsys):
    emit_failure(text="seat busy", envelope={"ok": False, "id": "b1", "error": "busy", "mill": "0.8.16"})
    obj = json.loads(capsys.readouterr().out)
    assert obj["code"] == "busy" and obj["class"] == "busy" and obj["applied"] is False


def test_internal_omits_applied(capsys):
    emit_failure(RuntimeError("db went away"))
    cap = capsys.readouterr()
    obj = json.loads(cap.out)
    assert obj["code"] == "internal" and "applied" not in obj
    assert "db went away" not in cap.out and "db went away" not in cap.err


def test_failed_rpc_logs_id_command_and_class(caplog):
    caplog.set_level(logging.WARNING, logger="mill.rpc")
    # An empty command fails inside slug as bad id before the command-required check.
    with pytest.raises(CoordError, match="bad id"):
        dispatch_ws(object(), "desk", "", req_id="abc-1238")
    text = caplog.text
    assert "failed rpc" in text and "abc-1238" in text and "CoordError" in text
    assert "bad id" not in text
