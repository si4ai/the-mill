"""Heartbeat age for session and the floor (#235)."""
from __future__ import annotations

from datetime import datetime, timedelta

from agent_coord.lib.observe import HEARTBEAT_STALE_S, heartbeat_flags
from agent_coord.server.api.mill import rpc
from agent_coord.server.records.floor import _glance, build_agents


def test_flags_fresh_threshold_old_null_and_revive() -> None:
    now = datetime(2026, 10, 13, 12, 0, 0)
    assert heartbeat_flags(now, now=now) == (True, False)
    at = now - timedelta(seconds=HEARTBEAT_STALE_S)
    assert heartbeat_flags(at, now=now) == (True, False)
    old = now - timedelta(seconds=HEARTBEAT_STALE_S + 1)
    assert heartbeat_flags(old, now=now) == (False, True)
    assert heartbeat_flags(None, now=now) == (False, True)
    assert heartbeat_flags("", now=now) == (False, True)
    assert heartbeat_flags(now, now=now) == (True, False)


def test_null_heartbeat_on_session_and_floor(monkeypatch) -> None:
    row = {
        "id": 1,
        "desk": "c235",
        "updated": None,
        "doing": "",
        "token_hash": "c235",
    }
    # #818: `connected` reads mill_doing_now; a desk row with no seat time.
    monkeypatch.setattr(
        "agent_coord.server.records.doing.now",
        lambda cn, desk="", roster="", all_desks=False: [
            {"part": "desk", "desk": "c235", "heartbeat": None, "cur_id": None, "cur_text": ""}
        ],
    )
    monkeypatch.setattr(
        "agent_coord.server.records.floor.rec_join.select",
        lambda cn, project: [row],
    )

    class _Book:
        _cn = None

    session = rpc._h_session(_Book(), {}, "c235", "c235")
    assert session[0]["alive"] is False
    assert session[0]["stale"] is True
    agents = build_agents(None, ["c235"])
    assert agents[0]["alive"] is False
    assert agents[0]["stale"] is True
    desks = _glance(agents, [], [])["desks"]
    assert desks[0]["alive"] is False
    assert desks[0]["stale"] is True
