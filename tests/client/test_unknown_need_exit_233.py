"""An unknown-need error exits 1 on stderr (#233)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent_coord.client import http


@pytest.mark.parametrize("cmd", ["pass", "unclaim", "unpark"])
def test_no_such_need_exits_1_on_stderr(cmd, capsys) -> None:
    reply = {"ok": False, "error": "no such need: unit/missing"}
    with patch.object(http, "mill_http_call", return_value=reply), patch(
        "agent_coord.client.outbound.body_from_args", return_value={"verb": cmd}
    ):
        rc = http.mill_http_from_args(SimpleNamespace(cmd=cmd))
    captured = capsys.readouterr()
    assert rc == 1
    obj = json.loads(captured.out)
    assert obj["code"] == "refused"
    assert obj["refusal"] == "no such need: unit/missing"
    assert "no such need" not in captured.err
    assert captured.err.strip() == "%s %s" % (obj["code"], obj["id"])
    captured.err.encode("ascii")
