# -*- coding: utf-8 -*-
"""Card 1242: a webhook desk is visible to peers.

1. A --desk borrow (no sitting connect) by a desk whose webhook is armed gets one
   PRESENCE hint in its reply sync, once per wake lease (with no live lease, once
   per lease window). A sitting connect or a desk with no webhook gets none.
2. mill connected (the same object is GET /api/v1/doing, the Wall's feed) shows a
   desk with no /ws and a healthy armed webhook as reach "wake" with last_wake,
   a failing webhook (#838) as "offline", and a live /ws as "connect".
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from types import SimpleNamespace

import pytest

from agent_coord.server import asgi as asgi_mod
from agent_coord.server import wake
from agent_coord.server.api.mill import rpc
from agent_coord.server.push import HUB
from agent_coord.server.records import doing
from agent_coord.server.records import join as rec_join


class _WS:
    async def send_text(self, text: str) -> None:
        return None


class _Book:
    def __init__(self) -> None:
        self._cn = object()


@pytest.fixture
def office(monkeypatch):
    """No MySQL: Book is a stub; wake state comes from `armed`."""

    class _Ctx:
        def __enter__(self):
            return _Book()

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.book.Book", lambda *a, **k: _Ctx())
    monkeypatch.setitem(rpc.HANDLERS, "inbox", lambda c, body, project, owner: [])
    monkeypatch.setattr(wake, "_GATE", {})
    monkeypatch.setattr(wake, "_EPOCH", {})
    monkeypatch.setattr(wake, "_UNTIL", {})
    monkeypatch.setattr(wake, "_LAPSED", {})
    monkeypatch.setattr(wake, "_LEASE_MAIL", {})
    monkeypatch.setattr(wake, "_FAILS", {})
    monkeypatch.setattr(wake, "_PRESENCE", {}, raising=False)
    armed = {"hookdesk": True, "plaindesk": False}
    monkeypatch.setattr(
        rec_join, "wake_state",
        lambda cn, desk: {"armed": armed.get(desk, False), "host": "hooks.example.test", "wake_on": "addressed"},
    )
    HUB.rooms.clear()
    yield armed
    HUB.rooms.clear()


def _call(desk: str, *, borrow: bool, n: int = 1) -> dict:
    ws = _WS()
    HUB.rooms.setdefault(desk, set()).add(ws)
    # a fresh id per call: a repeated req_id returns the remembered reply (#137)
    frame = {"id": f"r{n}-{uuid.uuid4().hex[:8]}", "verb": "inbox", "args": {}}
    if borrow:
        frame["borrow"] = 1
    try:
        return asyncio.run(asgi_mod._ws_handle_client_text(desk, ws, json.dumps(frame)))
    finally:
        HUB.rooms.get(desk, set()).discard(ws)


def _presence(reply: dict) -> list[dict]:
    return [s for s in reply.get("sync") or [] if s.get("hint") == "PRESENCE"]


def _ring(desk: str) -> str:
    with wake._GATE_LOCK:
        return wake._new_lease(desk, time.monotonic())


def test_borrow_by_webhook_desk_gets_one_presence_hint(office):
    reply = _call("hookdesk", borrow=True)
    assert reply["ok"] is True
    got = _presence(reply)
    assert len(got) == 1
    hint = got[0]
    assert hint["kind"] == "hint"
    assert "offline" in hint["detail"]
    assert "sit a connect for the whole wake run" in hint["detail"].lower()
    assert "models/grok-bot/SKILL.md" in hint["detail"]


def test_once_per_lease_then_again_on_the_next_lease(office):
    _ring("hookdesk")
    assert len(_presence(_call("hookdesk", borrow=True, n=1))) == 1
    assert _presence(_call("hookdesk", borrow=True, n=2)) == []
    assert _presence(_call("hookdesk", borrow=True, n=3)) == []
    _ring("hookdesk")  # the next wake
    assert len(_presence(_call("hookdesk", borrow=True, n=4))) == 1
    assert _presence(_call("hookdesk", borrow=True, n=5)) == []


def test_no_live_lease_hints_once_per_lease_window(office, monkeypatch):
    monkeypatch.setattr(wake, "lease_s", lambda: 0.4)
    assert len(_presence(_call("hookdesk", borrow=True, n=1))) == 1
    assert _presence(_call("hookdesk", borrow=True, n=2)) == []
    time.sleep(0.5)
    assert len(_presence(_call("hookdesk", borrow=True, n=3))) == 1


def test_sitting_connect_gets_no_hint(office):
    _ring("hookdesk")
    assert _presence(_call("hookdesk", borrow=False)) == []
    # and the sit did not use up the lease's one hint
    assert len(_presence(_call("hookdesk", borrow=True, n=2))) == 1


def test_desk_without_webhook_gets_no_hint(office):
    assert _presence(_call("plaindesk", borrow=True)) == []


def test_refused_command_still_carries_the_hint(office, monkeypatch):
    from agent_coord.helpers.errors import CoordError

    def refuse(c, body, project, owner):
        raise CoordError("inbox: refused")

    monkeypatch.setitem(rpc.HANDLERS, "inbox", refuse)
    reply = _call("hookdesk", borrow=True)
    assert "refused" in json.dumps(reply)
    assert len(_presence(reply)) == 1


# ---- part 2: reach on the connected view (the Wall reads the same object) ----

LAST = "2026-11-20T21:00:00Z"


@pytest.fixture
def views(monkeypatch, office):
    monkeypatch.setattr(doing, "now", lambda *a: [
        {"part": "desk", "desk": "hookdesk", "heartbeat": None},
        {"part": "desk", "desk": "plaindesk", "heartbeat": None},
        {"part": "desk", "desk": "sitdesk", "heartbeat": None},
    ])
    monkeypatch.setattr(doing, "live_doings", lambda cn, desks: {})
    monkeypatch.setattr(rec_join, "wake_reach", lambda cn, desks: {
        "hookdesk": {"armed": True, "last_wake": LAST},
        "plaindesk": {"armed": False, "last_wake": None},
        "sitdesk": {"armed": True, "last_wake": LAST},
    })
    monkeypatch.setattr("agent_coord.server.push.desk_sitting", lambda desk: desk == "sitdesk")

    def read():
        got = rpc._h_session(SimpleNamespace(_cn=None), {"all": True}, "", None)
        return {v["owner"]: v for v in got}

    return read


def test_armed_healthy_webhook_desk_is_reachable_by_wake(views):
    got = views()
    assert got["hookdesk"]["reach"] == "wake"
    assert got["hookdesk"]["last_wake"] == LAST


def test_no_webhook_and_no_connect_is_offline(views):
    got = views()
    assert got["plaindesk"]["reach"] == "offline"
    assert got["plaindesk"]["last_wake"] is None


def test_live_connect_is_reach_connect(views):
    assert views()["sitdesk"]["reach"] == "connect"


def test_a_failing_webhook_shows_offline(views):
    wake._FAILS["hookdesk"] = {"n": wake.FAIL_ALERT_N, "since": "2026-11-20T20:00Z", "status": 404, "err": ""}
    assert views()["hookdesk"]["reach"] == "offline"


def test_one_failed_wake_is_not_yet_failing(views):
    wake._FAILS["hookdesk"] = {"n": 1, "since": "2026-11-20T20:00Z", "status": 503, "err": ""}
    assert views()["hookdesk"]["reach"] == "wake"
