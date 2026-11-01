"""M1-M4 members. Throwaway SQL DB via tests.sql_isolate.

Use cases: docs/protocol/usecases.md Members chart.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import seed_names

from tests.server.records.conftest import admin_desk

def test_m1_office_join_never_leave(cn) -> None:
    """M1: mill join writes Office. cannot mill member-remove Office."""
    seed_names(cn, ("alice", "desk"))
    rec_member.put_office(cn, "alice")
    rows = rec_member.select(cn, desk="alice")
    nids = {int(r["name_id"]) for r in rows}
    assert 1 in nids
    with pytest.raises(Exception, match="Office"):
        rec_member.delete(cn, "Office", "alice")

def test_m2_add_self_creates_missing_group(cn) -> None:
    """M2: member-add creates a missing project and seats the desk."""
    seed_names(cn, ("alice", "desk"))
    rec_member.put(cn, "east-coast", "alice")
    rows = rec_member.select(cn, group="east-coast")
    assert any(int(r["desk_id"]) == rec_name.get(cn, "alice", "desk") for r in rows)
    cur = cn.cursor()
    cur.execute(
        "SELECT type, name, n FROM name WHERE type = 'roster' AND name=%s",
        ("east-coast",),
    )
    row = cur.fetchone()
    cur.close()
    assert row is not None
    assert row[0] == "roster"
    assert row[1] == "east-coast"
    assert int(row[2]) >= 1

def test_m3_remove_self_not_office(cn) -> None:
    """M3: mill member-remove this desk from a group. Office stays."""
    seed_names(cn, ("bob", "desk"))
    rec_member.put_office(cn, "bob")
    rec_name.host_put(cn, "west", "roster")
    rec_member.put(cn, "west", "bob")
    rec_member.delete(cn, "west", "bob")
    west = rec_member.select(cn, group="west")
    assert not any(int(r.get("desk_id") or 0) == rec_name.get(cn, "bob", "desk") for r in west)
    with pytest.raises(Exception, match="Office"):
        rec_member.delete(cn, "Office", "bob")

def test_m4_retire_keeps_member_rows_reclaim_warns(cn) -> None:
    """M4: mill retire name; member rows stay. mill reclaim returns members count."""
    seed_names(cn, ("carol", "desk"))
    rec_name.host_put(cn, "keep-roster", "roster")
    rec_member.put(cn, "keep-roster", "carol")
    rec_name.retire(cn, "keep-roster", "roster", by=admin_desk(cn))
    rows = rec_member.select(cn, group="keep-roster")
    assert rows
    out = rec_name.reclaim(cn, "keep-roster", "roster", by=admin_desk(cn))
    hit = out[0] if out else {}
    assert int(hit.get("members") or 0) >= 1
