# -*- coding: utf-8 -*-
"""Card 970 step 1 server: accept tw.event hop; write no doing and no tw_*."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc


class _Book:
    _cn = object()


def _event_body(**extra):
    body = {
        "verb": "tw.event",
        "watch_id": "w1",
        "kind": "start",
        "card": 970,
        "desk": "builder",
    }
    body.update(extra)
    return body


@pytest.fixture
def locked(monkeypatch):
    """Any doing or transition write must refuse before touching the book."""
    from agent_coord.server.records import doing as rec_doing
    from agent_coord.server import transition_enums

    doing_n = {"n": 0}
    trans_n = {"n": 0}

    def boom_doing(*a, **k):
        doing_n["n"] += 1
        raise AssertionError("tw.event must not write a doing row")

    def boom_trans(*a, **k):
        trans_n["n"] += 1
        raise AssertionError("tw.event must not write a transition")

    monkeypatch.setattr(rec_doing, "put", boom_doing)
    monkeypatch.setattr(rec_doing, "finish", boom_doing)
    monkeypatch.setattr(transition_enums, "put", boom_trans, raising=False)
    if hasattr(transition_enums, "emit"):
        monkeypatch.setattr(transition_enums, "emit", boom_trans, raising=False)

    def boom_call(cn, name, args=()):
        if "doing" in str(name) or "transition" in str(name):
            if "doing" in str(name):
                doing_n["n"] += 1
            else:
                trans_n["n"] += 1
            raise AssertionError(f"tw.event must not call {name}")
        return []

    monkeypatch.setattr("agent_coord.server.records.db.call", boom_call)
    return rpc, doing_n, trans_n


def test_tw_event_handler_is_registered() -> None:
    assert "tw.event" in rpc.HANDLERS


def test_well_formed_event_returns_ok(locked) -> None:
    mod, doing_n, trans_n = locked
    before_d, before_t = doing_n["n"], trans_n["n"]
    out = mod._h_tw_event(_Book(), _event_body(), "the-mill", "builder")
    assert out["ok"] is True
    assert doing_n["n"] == before_d
    assert trans_n["n"] == before_t


def test_privacy_keys_are_not_echoed_or_stored(locked) -> None:
    mod, doing_n, trans_n = locked
    before_d, before_t = doing_n["n"], trans_n["n"]
    out = mod._h_tw_event(
        _Book(),
        _event_body(argv=["tw", "run"], title="secret", pattern="*.py", cause="exit", exit_code=0),
        "the-mill",
        "builder",
    )
    assert out["ok"] is True
    blob = repr(out)
    assert "argv" not in blob
    assert "secret" not in blob
    assert "*.py" not in blob
    assert "title" not in blob
    assert "pattern" not in blob
    assert doing_n["n"] == before_d
    assert trans_n["n"] == before_t


def test_dispatch_ws_accepts_tw_event_without_writes(locked, monkeypatch) -> None:
    mod, doing_n, trans_n = locked
    before_d, before_t = doing_n["n"], trans_n["n"]
    monkeypatch.setattr(mod, "_note_doing", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_doing_text", lambda *a, **k: "")
    book = MagicMock()
    book._cn = object()
    out = mod.dispatch_ws(book, "builder", "tw.event", _event_body())
    assert out["ok"] is True
    assert doing_n["n"] == before_d
    assert trans_n["n"] == before_t


def test_link_hops_before_ok(tmp_path, monkeypatch) -> None:
    from agent_coord.client.tw.link import Session, serve

    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)
    hops = []

    def fake_http(body):
        hops.append(dict(body))
        return {"ok": True, "result": {"ok": True}}

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", fake_http)
    link = serve("tw-hop")
    session = Session(link)
    try:
        got = session.request({
            "type": "event",
            "watch_id": "w9",
            "kind": "start",
            "card": 970,
            "argv": ["tw", "run"],
            "title": "secret",
            "pattern": "*.py",
        })
        assert got["type"] == "reply"
        assert got["ok"] is True
        assert got["watch_id"] == "w9"
        assert len(hops) == 1
        assert hops[0]["verb"] == "tw.event"
        assert hops[0]["watch_id"] == "w9"
        assert hops[0]["kind"] == "start"
        assert "argv" not in hops[0]
        assert "title" not in hops[0]
        assert "pattern" not in hops[0]
    finally:
        session.close()
        link.close()


def test_link_hop_failure_marks_and_keeps_sit(tmp_path, monkeypatch) -> None:
    from agent_coord.client.tw.link import Session, serve

    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)

    def boom(body):
        raise CoordError("office refused")

    monkeypatch.setattr("agent_coord.client.http.mill_http_call", boom)
    link = serve("tw-hop-fail")
    session = Session(link)
    try:
        got = session.request({"type": "event", "watch_id": "w2", "kind": "stall"})
        assert got["type"] == "reply"
        assert got["ok"] is False
        assert got["msg"] == "hop failed"
        assert "tw.event" in link.marks
        # sit stays up: another local frame still works
        bad = session.request({"type": "nope"})
        assert bad["ok"] is False
        assert bad["msg"] == "unknown type"
    finally:
        session.close()
        link.close()


def test_bad_line_and_unknown_type_do_not_hop(tmp_path, monkeypatch) -> None:
    from agent_coord.client.tw.link import Session, serve

    monkeypatch.setattr("agent_coord.config.mill_home", lambda: tmp_path)
    monkeypatch.setattr("agent_coord.client.offices.desk_local_file", lambda *a, **k: None)
    hops = []
    monkeypatch.setattr(
        "agent_coord.client.http.mill_http_call",
        lambda body: hops.append(body) or {"ok": True, "result": {"ok": True}},
    )
    link = serve("tw-nohop")
    session = Session(link)
    try:
        session.send_raw(b"not-json\n")
        bad = session.read()
        assert bad["ok"] is False
        unk = session.request({"type": "nope"})
        assert unk["ok"] is False
        assert hops == []
    finally:
        session.close()
        link.close()


def test_link_source_has_no_transition_or_doing_put() -> None:
    from agent_coord.client.tw import link as linkmod

    text = Path(linkmod.__file__).read_text(encoding="utf-8")
    assert "mill_transition_put" not in text
    assert "mill_doing_put" not in text
