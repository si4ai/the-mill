"""Card 1255: the Wall's roster list hides a trashed roster until mill restore.

GET /api/pov?part=rosters (the Wall's left pane) and mill member --all read
records.member.list_rosters. A roster trashed by mill delete (card 879,
name.trashed) is not listed. After mill restore it lists again. Card 1241
removed its members, and restore does not put them back.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from agent_coord.server.records import join
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import admin_desk
from tests.server.test_wall_scope_filters_1193 import _client

pytestmark = pytest.mark.sql


def _seed(cn) -> tuple[str, list[str], str]:
    tag = uuid4().hex[:6]
    roster = "r1255-" + tag
    keep = "r1255-keep-" + tag
    desks = sorted("d1255-" + uuid4().hex[:6] for _ in range(2))
    for d in desks:
        join.upsert(cn, roster, d, "", "b" * 64)
    join.upsert(cn, keep, desks[0], "", "b" * 64)
    cn.commit()
    return roster, desks, keep


def _names(rows: list[dict]) -> set[str]:
    return {r["name"] for r in rows}


def test_list_rosters_omits_trashed_and_lists_it_after_restore(cn) -> None:
    roster, desks, keep = _seed(cn)
    admin = admin_desk(cn)
    assert roster in _names(rec_member.list_rosters(cn))

    rec_name.trash(cn, roster, "roster", by=admin)
    cn.commit()
    rows = rec_member.list_rosters(cn)
    assert roster not in _names(rows)
    assert keep in _names(rows)  # a live roster sharing a member still lists

    rec_name.restore_trashed(cn, roster, "roster", by=admin)
    cn.commit()
    by_name = {r["name"]: r for r in rec_member.list_rosters(cn)}
    assert by_name[roster] == {"name": roster, "desks": 0, "members": []}


def test_pov_rosters_route_hides_trashed_until_restore(cn, monkeypatch) -> None:
    roster, desks, _keep = _seed(cn)
    admin = admin_desk(cn)
    client = _client(monkeypatch, cn)

    rec_name.trash(cn, roster, "roster", by=admin)
    cn.commit()
    rows = client.get("/api/pov?part=rosters").json()["rows"]
    assert roster not in _names(rows)

    rec_name.restore_trashed(cn, roster, "roster", by=admin)
    cn.commit()
    rows = client.get("/api/pov?part=rosters").json()["rows"]
    assert [r for r in rows if r["name"] == roster] == [
        {"name": roster, "desks": 0, "members": []}
    ]
