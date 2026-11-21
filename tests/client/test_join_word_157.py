"""mill join word and failure shapes (#157). join_argv is gone with #620: the link is never argv."""
from __future__ import annotations

import base64
import json

from agent_coord.__main__ import main

_PEM = (
    "-----BEGIN CERTIFICATE-----\n"
    "MIIBTESTCA\n"
    "-----END CERTIFICATE-----\n"
)
_PEM_B64 = base64.b64encode(_PEM.encode("utf-8")).decode("ascii")
_WELCOME = (
    "https://office.example/welcome?desk=grok-tui&seat=abc&project=the-mill&pem="
    + _PEM_B64
)



import pytest


@pytest.fixture(autouse=True)
def _clear_cli_office():
    from agent_coord.client.offices import bind_cli_office

    bind_cli_office("")
    yield
    bind_cli_office("")



def test_join_join_url_exits_1_on_stderr(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))

    def fake(*_a, **_k):
        raise AssertionError("join")

    monkeypatch.setattr("agent_coord.client.offices.join_office", fake)
    # link positional is "join"; handler refuses the doubled word (#157).
    rc = main(["join", "join", "--office", "home"])
    out = capsys.readouterr()
    assert rc == 1
    obj = json.loads(out.out)
    assert obj["code"] == "refused"
    assert "extra join word" in obj["refusal"]
    assert "extra join word" not in out.err
    assert out.err.strip() == "refused %s" % obj["id"]
    assert list(tmp_path.iterdir()) == []


def test_join_failure_json_is_stderr_exit_1(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))

    def fake(*_a, **_k):
        return {"ok": False, "error": "wall unreachable"}

    monkeypatch.setattr("agent_coord.client.offices.join_office", fake)
    link = tmp_path / "w.link"
    link.write_text(_WELCOME, encoding="utf-8")
    rc = main(["join", "--office", "home", "--link-file", str(link)])
    out = capsys.readouterr()
    assert rc == 1
    obj = json.loads(out.out)
    assert obj["code"] == "refused"
    assert obj["refusal"] == "wall unreachable"
    assert "wall unreachable" not in out.err
    assert out.err.strip() == "refused %s" % obj["id"]
