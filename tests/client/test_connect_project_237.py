"""connect asks the server about the project on its own /ws and refuses (#237)."""
from __future__ import annotations

import threading

from agent_coord.client import ws as ws_mod
from agent_coord.client.http import check_project_on_socket
from agent_coord.helpers.errors import CoordError
from agent_coord.helpers.projects import project_refusal


def test_refusal_sentence_edges() -> None:
    names = ["Office", "c237"]
    assert project_refusal("connect", "c237", names) is None
    unknown = project_refusal("connect", "c237-missing", names)
    assert unknown == "connect: no such roster c237-missing; rosters: Office, c237. list them: mill member"
    empty = project_refusal("connect", "  ", names)
    assert empty == "connect: no such roster; rosters: Office, c237. list them: mill member"
    retired = project_refusal("connect", "c237-gone", names)
    assert retired is not None
    listed = retired.split("rosters: ", 1)[1].split(". list them:", 1)[0]
    assert "c237-gone" not in [p.strip() for p in listed.split(",")]


def _run(monkeypatch, replies, project="c237"):
    sent = []

    def fake(who, body, **k):
        sent.append(body)
        r = replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r

    monkeypatch.setattr(ws_mod, "own_bridge_call", fake)
    stop = threading.Event()
    outcome: dict = {}
    ws_mod.hold_sync_lines()
    assert ws_mod.gate_line('{"kind": "sync", "sync": []}') is True
    check_project_on_socket("c237-desk", project, stop, outcome)
    return sent, stop, outcome


def test_unknown_refuses_and_drops_sync(monkeypatch, capsys) -> None:
    msg = "connect: no such project c237-missing; projects: Office, c237"
    sent, stop, outcome = _run(monkeypatch, [{"ok": False, "error": msg}], "c237-missing")
    cap = capsys.readouterr()
    assert sent == [{"verb": "project", "project": "c237-missing", "for": "connect"}]
    assert cap.err.strip() == msg
    assert '"sync"' not in cap.out
    assert outcome["exit"] == 1 and stop.is_set()
    assert ws_mod.gate_line("x") is False


def test_empty_and_retired_refuse(monkeypatch, capsys) -> None:
    for project, msg in (
        ("", "connect: no such project; projects: Office, c237"),
        ("c237-gone", "connect: no such project c237-gone; projects: Office, c237"),
    ):
        _, stop, outcome = _run(monkeypatch, [{"ok": False, "error": msg}], project)
        assert capsys.readouterr().err.strip() == msg
        assert outcome["exit"] == 1 and stop.is_set()


def test_valid_prints_held_sync(monkeypatch, capsys) -> None:
    sent, stop, outcome = _run(
        monkeypatch,
        [CoordError("socket not ready"), {"ok": True, "result": {"ok": True, "project": "c237"}}],
    )
    cap = capsys.readouterr()
    assert len(sent) == 2
    assert '"sync"' in cap.out
    assert cap.err == ""
    assert "exit" not in outcome and not stop.is_set()


def test_old_server_keeps_sitting(monkeypatch, capsys) -> None:
    _, stop, outcome = _run(monkeypatch, [{"ok": False, "error": "unknown mill command project"}])
    cap = capsys.readouterr()
    assert "does not check projects yet" in cap.err
    assert '"sync"' in cap.out
    assert "exit" not in outcome and not stop.is_set()


def test_lookup_failure_prints_reason(monkeypatch, capsys) -> None:
    _, stop, outcome = _run(monkeypatch, [ConnectionRefusedError("refused")])
    err = capsys.readouterr().err
    assert err.startswith("connect: could not check project c237: socket error:")
    assert "refused" in err
    assert outcome["exit"] == 1 and stop.is_set()
    _, stop, outcome = _run(monkeypatch, [{"ok": False, "error": "mill-wall 500: boom"}])
    err = capsys.readouterr().err
    assert err.strip() == "connect: could not check project c237: mill-wall 500: boom"
    assert outcome["exit"] == 1
