"""A failed command is one stdout object and one stderr line (card 1238)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_coord.client import http
from agent_coord.helpers.errors import CoordError


@pytest.mark.parametrize(
    "reply",
    [
        {"ok": False, "error": "mail-thread: Bearer desk is not sender or recipient"},
        {"error": "send: room 'x' exists; post with: mill reply 7"},
    ],
)
def test_error_row_on_stdout_exit_1(reply, capsys):
    with patch.object(http, "mill_http_call", return_value=reply), patch(
        "agent_coord.client.outbound.body_from_args", return_value={"verb": "send"}
    ):
        assert http.mill_http_from_args(SimpleNamespace(cmd="send")) == 1
    cap = capsys.readouterr()
    obj = json.loads(cap.out)
    assert obj["ok"] is False and obj["code"] == "refused" and obj["applied"] is False
    assert obj["refusal"] == reply["error"]
    assert reply["error"] not in cap.err
    assert cap.err.strip() == "%s %s" % (obj["code"], obj["id"])
    assert not cap.out.startswith("\ufeff")


def test_success_row_on_stdout(capsys):
    reply = {"ok": True, "result": {"id": 9}}
    with patch.object(http, "mill_http_call", return_value=reply), patch(
        "agent_coord.client.outbound.body_from_args", return_value={"verb": "send"}
    ):
        assert http.mill_http_from_args(SimpleNamespace(cmd="send")) == 0
    cap = capsys.readouterr()
    assert cap.err == "" and json.loads(cap.out)["result"]["id"] == 9


def test_main_coord_error_on_stderr(capsys):
    from agent_coord import __main__ as m

    with patch("agent_coord.client.http.mill_url", return_value="https://wall"), patch(
        "agent_coord.client.http.mill_http_from_args", side_effect=CoordError("send: To required")
    ):
        rc = m.main(["send", "--to-desk", "x", "--body-file", "b.txt"])
    cap = capsys.readouterr()
    assert rc == 1
    obj = json.loads(cap.out)
    assert obj["code"] == "refused" and obj["command"] == "send --to-desk --body-file"
    assert obj["refusal"] == "send: To required"
    assert "send: To required" not in cap.err
    assert cap.err.strip() == "refused %s" % obj["id"]
