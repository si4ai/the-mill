# -*- coding: utf-8 -*-
from agent_coord.client.inbound import (
    ROUTES,
    classify,
    ignore,
    route_key,
)
from agent_coord.server.hint_buf import HintBuf


def test_skill_md_keys():
    for key in (
        "heartbeat:PING",
        "mail:MAIL",
        "todo:TODO",
        "hold:HOLD",
        "score:SCORE",
        "name:NAME",
        "doing:DOING",
    ):
        assert key in ROUTES


def test_route_key():
    assert route_key({"type": "mail", "id": 9, "hint": "MAIL"}) == "mail:MAIL"
    assert route_key({"type": "heartbeat", "id": 0, "hint": "PING"}) == "heartbeat:PING"
    assert route_key({"hint": "TODO"}) == "todo:TODO"


def test_ignore_ping_and_here():
    assert ignore({"type": "heartbeat", "id": 0, "hint": "PING"})
    assert ignore({"hint": "PING"})
    assert ignore({"type": "doing", "id": 1, "hint": "DOING"})
    assert not ignore({"type": "join", "id": 1, "hint": "JOIN"})  # #818: no join route left
    assert not ignore({"type": "mail", "id": 9, "hint": "MAIL"})


def test_classify_mail_inbox():
    got = classify({"type": "mail", "id": 9, "hint": "MAIL"})
    assert got["key"] == "mail:MAIL"
    assert got["verb"] == "inbox"
    assert got.get("unread") is True
    assert "limit" not in got
    assert not got["ignore"]


def test_hint_buf_drops_ping_queues_mail(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_COORD_MILL_HOME", str(tmp_path))
    buf = HintBuf("alice", maxsize=8)
    buf.put_recv({"type": "heartbeat", "id": 0, "hint": "PING"})
    buf.put_recv({"type": "doing", "id": 1, "hint": "DOING"})
    buf.put_recv({"type": "mail", "id": 9, "hint": "MAIL"})
    work = buf.get_work(timeout=0.1)
    assert work is not None
    assert work["hint"] == "MAIL"
    assert work["route"] == "mail:MAIL"
    assert work["verb"] == "inbox"
    assert buf.get_work(timeout=0.05) is None
