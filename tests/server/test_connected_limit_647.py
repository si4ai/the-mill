"""mill connected --limit N keeps the newest heartbeats (card 647, F199).

Before: the flag was accepted and ignored, so --limit 3 returned every desk.
With no --limit the list and its order stay as the book returned them.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

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
    kept = rpc._h_session(_Book(), {"limit": 2}, "", "probe")
    assert [row["owner"] for row in kept] == ["new", "mid"]
    one = rpc._h_session(_Book(), {"limit": "1"}, "", "probe")
    assert [row["owner"] for row in one] == ["new"]


def test_limit_below_one_and_with_history_are_refused(monkeypatch) -> None:
    monkeypatch.setattr("agent_coord.server.records.doing.now", lambda *a, **k: _rows())
    for bad in (0, -3, "no"):
        with pytest.raises(CoordError, match="at least 1"):
            rpc._h_session(_Book(), {"limit": bad}, "", "probe")
    with pytest.raises(CoordError, match="not --history"):
        rpc._h_session(_Book(), {"limit": 2, "history": True}, "", "probe")
