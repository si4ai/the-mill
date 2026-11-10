# -*- coding: utf-8 -*-
"""Card 970: metadata boundary and local hop privacy (task writes tested separately)."""
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
    """Capture the sanitized record boundary; real writes have their own SQL tests."""
    stored = []
    monkeypatch.setattr("agent_coord.server.records.doing.task_event",
                        lambda cn, desk, meta, **kw: stored.append(dict(meta)))
    monkeypatch.setattr("agent_coord.server.records.db.request_tx", lambda cn, run: run())
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **kw: None)
    return rpc, stored


def test_tw_event_handler_is_registered() -> None:
    assert "tw.event" in rpc.HANDLERS


def test_well_formed_event_returns_ok(locked) -> None:
    mod, stored = locked
    out = mod._h_tw_event(_Book(), _event_body(), "the-mill", "builder")
    assert out["ok"] is True


def test_privacy_keys_are_not_echoed_or_stored(locked) -> None:
    mod, stored = locked
    out = mod._h_tw_event(
        _Book(),
        _event_body(argv=["tw", "run"], title="secret", pattern="*.py", cause="exit", exit_code=0),
        "the-mill",
        "builder",
    )
    assert out["ok"] is True
    blob = repr((out, stored))
    assert "argv" not in blob
    assert "secret" not in blob
    assert "*.py" not in blob
    assert "title" not in blob
    assert "pattern" not in blob


_STREAM_BODIES = {
    "stdout": "STDOUT-BODY line one\nline two",
    "stderr": "STDERR-BODY traceback",
    "log": "LOG-BODY /tmp/run.log contents",
    "sample": {"tree": [{"pid": 4242, "cmd": "SAMPLE-BODY python"}], "cpu": 12},
    "pid": 4242,
}


def test_tw_event_privacy_includes_stream_and_sample_keys() -> None:
    """Privacy drop list must name stream/sample/pid keys (defense in depth).

    The reply allow-list already omits them; this pins the signed-plan drop list
    itself so removing those entries fails even when meta_keys is unchanged.
    """
    privacy = rpc._TW_EVENT_PRIVACY
    for key in ("stdout", "stderr", "log", "sample", "pid"):
        assert key in privacy
    # Apply only the drop (not the allow-list copy) to a payload that has them.
    payload = {
        "ok": True,
        "watch_id": "w1",
        "kind": "start",
        "card": 970,
        **_STREAM_BODIES,
    }
    out = dict(payload)
    for key in privacy:
        out.pop(key, None)
    for key in ("stdout", "stderr", "log", "sample", "pid"):
        assert key not in out
    assert out["watch_id"] == "w1"
    assert out["kind"] == "start"
    assert out["card"] == 970


def test_stream_and_sample_bodies_are_dropped(locked) -> None:
    mod, stored = locked
    out = mod._h_tw_event(
        _Book(),
        _event_body(cause="exit", exit_code=1, counts={"lines": 2}, **_STREAM_BODIES),
        "the-mill",
        "builder",
    )
    assert out["ok"] is True
    for key in ("stdout", "stderr", "log", "sample", "pid"):
        assert key not in out
    blob = repr((out, stored))
    for marker in ("STDOUT-BODY", "STDERR-BODY", "LOG-BODY", "SAMPLE-BODY", "4242"):
        assert marker not in blob
    assert out["watch_id"] == "w1"
    assert out["kind"] == "start"
    assert out["card"] == 970
    assert out["cause"] == "exit"
    assert out["exit_code"] == 1
    assert out["counts"] == {"lines": 2}


def test_meta_only_event_still_accepts(locked) -> None:
    mod, stored = locked
    out = mod._h_tw_event(
        _Book(), _event_body(kind="exit", cause="exit", exit_code=0), "the-mill", "builder"
    )
    assert out == {
        "ok": True,
        "watch_id": "w1",
        "desk": "builder",
        "kind": "exit",
        "card": 970,
        "cause": "exit",
        "exit_code": 0,
    }


def test_dispatch_ws_drops_stream_bodies(locked, monkeypatch) -> None:
    mod, stored = locked
    monkeypatch.setattr(mod, "_note_doing", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_doing_text", lambda *a, **k: "")
    book = MagicMock()
    book._cn = object()
    out = mod.dispatch_ws(book, "builder", "tw.event", _event_body(**_STREAM_BODIES))
    assert out["ok"] is True
    blob = repr((out, stored))
    for marker in ("STDOUT-BODY", "STDERR-BODY", "LOG-BODY", "SAMPLE-BODY", "4242"):
        assert marker not in blob


def test_dispatch_ws_accepts_tw_event(locked, monkeypatch) -> None:
    mod, stored = locked
    monkeypatch.setattr(mod, "_note_doing", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_doing_text", lambda *a, **k: "")
    book = MagicMock()
    book._cn = object()
    out = mod.dispatch_ws(book, "builder", "tw.event", _event_body())
    assert out["ok"] is True


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
        assert link.drain() == "empty"
        events = [item for item in hops if item.get("verb") == "tw.event"]
        assert len(events) == 1
        assert events[0]["verb"] == "tw.event"
        assert events[0]["watch_id"] == "w9"
        assert events[0]["kind"] == "start"
        assert [item for item in hops if item.get("verb") == "tw.reconcile"] == [
            {"verb": "tw.reconcile", "live": []}
        ]
        assert "argv" not in events[0]
        assert "title" not in events[0]
        assert "pattern" not in events[0]
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
        assert got["ok"] is True
        assert link.drain() == "down"
        assert link._outbox is not None and link._outbox.peek() is not None
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
        assert hops == [{"verb": "tw.reconcile", "live": []}]
    finally:
        session.close()
        link.close()


def test_link_source_has_no_transition_or_doing_put() -> None:
    from agent_coord.client.tw import link as linkmod

    text = Path(linkmod.__file__).read_text(encoding="utf-8")
    assert "mill_transition_put" not in text
    assert "mill_doing_put" not in text
