"""Watchers + fanout for every mill use case (W1-W10, N1 reclaim). mill_records_test."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import apply, connect
from agent_coord.server.records import hold, join as here, label, member, name, score, todo, watcher as watchers
from agent_coord.server.push import fanout

from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_records_test")


@pytest.fixture
def cn():
    import mysql.connector

    kw = _conn_kwargs()
    kw.pop("database", None)
    kw["autocommit"] = True
    admin = mysql.connector.connect(**kw)
    cur = admin.cursor()
    cur.execute(
        f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
        "DEFAULT CHARACTER SET utf8mb4 DEFAULT COLLATE utf8mb4_0900_ai_ci"
    )
    cur.close()
    admin.close()
    os.environ["AGENT_COORD_DATABASE"] = TEST_DB
    c = connect(TEST_DB)
    apply(c, wipe=True)
    yield c
    c.close()


def _sit(cn, who: str = "alice"):
    p = "unit"
    d = who
    rec = here.upsert(cn, p, d, "builder", token_hash="a" * 64, doing="present")
    return p, d, rec


def _watched(cn, typ: str, nid: int) -> list:
    rows = watchers.select(cn, typ, int(nid))
    assert rows, f"no watchers type={typ} id={nid}"
    fanout(cn, typ, int(nid), typ.upper())
    return rows


def test_w4_todo_watchers(cn) -> None:
    p, alice, _ = _sit(cn)
    tid = int(todo.insert(cn, p, alice, "open", '{"slug":"w4"}')[0]["id"])
    _watched(cn, "todo", tid)
    todo.update(cn, tid, alice, status="claimed", volunteer=alice)
    _watched(cn, "todo", tid)


def test_w5_here_watchers(cn) -> None:
    p, alice, rec = _sit(cn)
    hid = int(rec[0]["id"])
    _watched(cn, "doing", hid)


def test_w7_hold_watchers(cn) -> None:
    p, alice, _ = _sit(cn)
    hid = int(hold.upsert(cn, p, alice, "board.html")[0]["id"])
    _watched(cn, "hold", hid)


def test_w8_score_watchers(cn) -> None:
    p, alice, _ = _sit(cn)
    sid = int(score.upsert(cn, p, alice, "wall_up", "1", "1", "ok")[0]["id"])
    _watched(cn, "score", sid)


def test_w10_label_keeps_todo_watchers(cn) -> None:
    p, alice, _ = _sit(cn)
    tid = int(todo.insert(cn, p, alice, "open", '{"slug":"lab"}')[0]["id"])
    name.host_put(cn, "urgent", "label")
    label.put(cn, "todo", tid, "urgent")
    _watched(cn, "todo", tid)


def _no_name_watcher(cn, nid: int) -> None:
    cur = cn.cursor()
    try:
        cur.execute("SELECT DISTINCT type FROM watcher")
        types = {str(r[0]) for r in cur.fetchall()}
    finally:
        cur.close()
    assert "name" not in types
    with pytest.raises(Exception):
        watchers.select(cn, "name", int(nid))


def test_w2_member_add_group_does_not_watch_the_name(cn) -> None:
    p, alice, _ = _sit(cn)
    bob = "bob"
    here.upsert(cn, p, bob, "builder", token_hash="b" * 64)
    name.host_put(cn, "east", "roster")
    member.put(cn, "east", alice)
    member.put(cn, "east", bob)
    nid = name.get(cn, "east", "roster")
    assert nid and int(nid) != 1
    desks = {int(r["desk_id"]) for r in member.select(cn, "east")}
    assert desks
    _no_name_watcher(cn, int(nid))


def test_w1_rename_retire_reclaim_keeps_the_name_id(cn) -> None:
    """Retire holds the unique name. Reclaim keeps the same id. No name watcher."""
    p, alice, _ = _sit(cn)
    name.host_put(cn, "west", "roster")
    member.put(cn, "west", alice)
    nid = int(name.get(cn, "west", "roster"))
    name.rename(cn, "west", "west2", "roster")
    assert name.get(cn, "west2", "roster") == nid
    _no_name_watcher(cn, nid)
    name.retire(cn, "west2", "roster")
    assert name.get(cn, "west2", "roster") is None
    _no_name_watcher(cn, nid)
    with pytest.raises(Exception, match="retired"):
        name.get_or_insert(cn, "west2", "roster")
    here.reset(cn, p, alice)
    name.reclaim(cn, "west2", "roster")
    assert name.get(cn, "west2", "roster") == nid
    _no_name_watcher(cn, nid)


def test_n4_n5_office_admin_never_retire(cn) -> None:
    assert name.get(cn, "Office", "roster") == 1
    with pytest.raises(Exception, match="Office"):
        name.retire(cn, "Office", "roster")
    assert name.get(cn, "Admin", "roster") is not None
    with pytest.raises(Exception, match="Admin"):
        name.retire(cn, "Admin", "roster")


def test_office_join_does_not_watch_name_id_1(cn) -> None:
    """Office join does not write a watcher on name id 1."""
    _sit(cn)
    _no_name_watcher(cn, 1)
