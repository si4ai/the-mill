"""Membership does not plant a name watcher. Name is not a watcher type.

Use cases: USECASES.md Watchers chart.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import watcher as rec_w
from tests.server.records.conftest import seed_names

from tests.server.records.conftest import admin_desk

def _types(cn) -> set[str]:
    cur = cn.cursor()
    try:
        cur.execute("SELECT DISTINCT type FROM watcher")
        return {str(r[0]) for r in cur.fetchall()}
    finally:
        cur.close()

def _members(cn, slot: str, kind: str = "") -> set[int]:
    return {int(r["desk_id"]) for r in rec_member.select(cn, slot, kind=kind)}

def _reject_name(cn, nid: int) -> None:
    with pytest.raises(Exception):
        rec_w.select(cn, "name", int(nid))

def test_w2_join_does_not_watch_the_name(cn) -> None:
    """Join and leave a project change membership only. No name watcher."""
    seed_names(cn, ("alice", "desk"), ("bob", "desk"))
    rec_name.host_put(cn, "watched", "roster")
    rec_member.put(cn, "watched", "alice")
    gid = rec_name.get(cn, "watched", "roster")
    alice = rec_name.get(cn, "alice", "desk")
    assert alice in _members(cn, "watched")
    assert "name" not in _types(cn)
    _reject_name(cn, gid)
    rec_member.put(cn, "watched", "bob")
    bob = rec_name.get(cn, "bob", "desk")
    assert {alice, bob} <= _members(cn, "watched")
    rec_member.delete(cn, "watched", "bob")
    desks = _members(cn, "watched")
    assert bob not in desks
    assert alice in desks
    assert "name" not in _types(cn)
    _reject_name(cn, gid)

def test_w2_office_join_does_not_watch_the_name(cn) -> None:
    """Office membership does not plant a name watcher."""
    seed_names(cn, ("carol", "desk"))
    rec_member.put_office(cn, "carol")
    carol = rec_name.get(cn, "carol", "desk")
    assert carol in _members(cn, "Office")
    assert "name" not in _types(cn)
    _reject_name(cn, 1)

def test_w1_rename_keeps_the_name_id(cn) -> None:
    """Rename keeps the name id. It does not create a name watcher."""
    seed_names(cn, ("dave", "desk"))
    rec_name.host_put(cn, "ren", "roster")
    rec_member.put(cn, "ren", "dave")
    gid = rec_name.get(cn, "ren", "roster")
    rec_name.rename(cn, "ren", "renamed", "roster", by=admin_desk(cn))
    assert rec_name.get(cn, "renamed", "roster") == gid
    dave = rec_name.get(cn, "dave", "desk")
    assert dave in _members(cn, "renamed")
    assert "name" not in _types(cn)
    _reject_name(cn, gid)

def test_w4_todo_roster_members_watch(cn) -> None:
    """Todo watches the acting desk. Another project member is not a watcher."""
    seed_names(cn, ("alice", "desk"), ("eve", "desk"))
    rec_name.host_put(cn, "cards", "roster")
    rec_member.put(cn, "cards", "alice")
    rec_member.put(cn, "cards", "eve")
    from agent_coord.server.records import todo as rec_todo

    rec_todo.insert(cn, "cards", "alice", "open", "work")
    tid = int(rec_todo.select(cn, "cards", "open")[0]["id"])
    alice = rec_name.get(cn, "alice", "desk")
    eve = rec_name.get(cn, "eve", "desk")
    desks = {int(r["desk_id"]) for r in rec_w.select(cn, "todo", tid)}
    assert alice in desks
    assert eve not in desks

def test_w8_score_roster_members_watch(cn) -> None:
    """Score watches the acting desk. Another project member is not a watcher."""
    seed_names(cn, ("alice", "desk"), ("eve", "desk"))
    rec_name.host_put(cn, "kpi", "roster")
    rec_member.put(cn, "kpi", "alice")
    rec_member.put(cn, "kpi", "eve")
    from agent_coord.server.records import score as rec_score

    rec_score.upsert(cn, "kpi", "alice", "spend", "1", "2", "")
    rows = rec_score.select(cn, "kpi")
    sid = int(rows[0]["id"])
    alice = rec_name.get(cn, "alice", "desk")
    eve = rec_name.get(cn, "eve", "desk")
    desks = {int(r["desk_id"]) for r in rec_w.select(cn, "score", sid)}
    assert alice in desks
    assert eve not in desks

def test_w2_role_join_does_not_watch_the_name(cn) -> None:
    """Role membership is a member row, not a watcher on that name id."""
    seed_names(cn, ("eve", "desk"))
    rec_name.host_put(cn, "builder", "roster")
    rec_member.put(cn, "builder", "eve", kind="roster")
    rid = rec_name.get(cn, "builder", "roster")
    eve = rec_name.get(cn, "eve", "desk")
    assert eve in _members(cn, "builder", kind="roster")
    assert "name" not in _types(cn)
    _reject_name(cn, rid)
