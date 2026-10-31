"""mill connected --limit N keeps the newest heartbeats (card 647, F199).

The wire key is connected_limit. A released client sends limit=10 on every
connected call, including history, and that key must not cap or refuse.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from agent_coord.client.outbound import body_from_args
from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc


class _Book:
    _cn = None


def _rows():
    now = datetime(2026, 10, 31, 12, 0, 0)
    out = []
    for name, minutes in (("old", 30), ("mid", 10), ("new", 1), ("quiet", None)):
        hb = None if minutes is None else now - timedelta(minutes=minutes)
        out.append({"part": "desk", "desk": name, "heartbeat": hb, "cur_id": None, "cur_text": ""})
    return out


def test_limit_keeps_the_newest_heartbeats(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.server.records.doing.now", lambda *a, **k: _rows())
    whole = rpc._h_session(_Book(), {}, "", "probe")
    assert [row["owner"] for row in whole] == ["old", "mid", "new", "quiet"]
    kept = rpc._h_session(_Book(), {"connected_limit": 2}, "", "probe")
    assert [row["owner"] for row in kept] == ["new", "mid"]
    one = rpc._h_session(_Book(), {"connected_limit": "1"}, "", "probe")
    assert [row["owner"] for row in one] == ["new"]


def test_limit_below_one_and_with_history_are_refused(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.server.records.doing.now", lambda *a, **k: _rows())
    for bad in (0, -3, "no"):
        with pytest.raises(CoordError, match="at least 1"):
            rpc._h_session(_Book(), {"connected_limit": bad}, "", "probe")
    with pytest.raises(CoordError, match="not --history"):
        rpc._h_session(_Book(), {"connected_limit": 2, "history": True}, "", "probe")


def test_a_released_client_limit_does_not_cap_or_refuse_history(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.server.records.doing.now", lambda *a, **k: _rows())
    plain = rpc._h_session(_Book(), {"limit": 10}, "", "probe")
    assert [row["owner"] for row in plain] == ["old", "mid", "new", "quiet"]
    monkeypatch.setattr(rpc, "_doing_history", lambda *a, **k: ["hist"])
    assert rpc._h_session(_Book(), {"limit": 10, "history": True}, "", "probe") == ["hist"]


def test_mixed_heartbeat_types_still_sort(monkeypatch) -> None:
    now = datetime(2026, 10, 31, 12, 0, 0)
    rows = [
        {"part": "desk", "desk": "text", "heartbeat": "not-a-time", "cur_id": None, "cur_text": ""},
        {"part": "desk", "desk": "clock", "heartbeat": now, "cur_id": None, "cur_text": ""},
    ]
    monkeypatch.setattr("agent_coord.server.records.doing.now", lambda *a, **k: rows)
    got = rpc._h_session(_Book(), {"connected_limit": 1}, "", "probe")
    assert [row["owner"] for row in got] == ["clock"]


def test_typed_limit_moves_onto_connected_limit(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.client.tokens.resolve_desk_owner", lambda _desk: "probe")
    plain = body_from_args(SimpleNamespace(cmd="session", project="the-mill", history=False, page=0))
    assert "limit" not in plain
    assert "connected_limit" not in plain
    capped = body_from_args(
        SimpleNamespace(cmd="session", project="the-mill", limit=3, history=False, page=0)
    )
    assert "limit" not in capped
    assert capped["connected_limit"] == 3
    with pytest.raises(CoordError, match="at least 1"):
        body_from_args(SimpleNamespace(cmd="session", project="the-mill", limit=0, history=False, page=0))
    with pytest.raises(CoordError, match="not --history"):
        body_from_args(SimpleNamespace(cmd="session", project="the-mill", limit=2, history=True, page=0))
