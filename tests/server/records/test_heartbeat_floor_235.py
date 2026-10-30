"""Session and floor follow join.updated (#235)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.sql

from agent_coord.lib.observe import HEARTBEAT_STALE_S
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join as rec_join
from agent_coord.server.records.floor import _glance, build_agents
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _set_updated(cn, desk: str, when) -> None:
    cur = cn.cursor()
    try:
        cur.execute(
            "UPDATE seat j JOIN name n ON n.id = j.desk_id "
            "SET j.updated = %s WHERE n.type = 'desk' AND n.name = %s",
            (when, desk),
        )
        cn.commit()
    finally:
        cur.close()


def _flags(cn, desk: str) -> tuple[bool, bool, bool, bool]:
    book = _Book(cn)
    session = rpc._h_session(book, {}, "c235", desk)
    hit = next(r for r in session if r["owner"] == desk)
    agents = build_agents(cn, ["c235"])
    agent = next(a for a in agents if a["owner"] == desk)
    desk_row = next(d for d in _glance(agents, [], [])["desks"] if d["owner"] == desk)
    assert (hit["alive"], hit["stale"]) == (agent["alive"], agent["stale"])
    assert (desk_row["alive"], desk_row["stale"]) == (agent["alive"], agent["stale"])
    return hit["alive"], hit["stale"], agent["alive"], agent["stale"]


def test_fresh_old_and_reconnect(cn) -> None:
    seed_names(cn, ("c235", "roster"), ("c235-desk", "desk"))
    rec_join.upsert(cn, "c235", "c235-desk", "", "c235", "working")
    assert _flags(cn, "c235-desk")[:2] == (True, False)

    _set_updated(cn, "c235-desk", datetime.now() - timedelta(seconds=HEARTBEAT_STALE_S + 30))
    assert _flags(cn, "c235-desk")[:2] == (False, True)

    rec_join.upsert(cn, "c235", "c235-desk", "", "c235", "working")
    assert _flags(cn, "c235-desk")[:2] == (True, False)
