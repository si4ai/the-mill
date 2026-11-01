"""mill_activity_get: one activity by (type, id), state like mill_activity_select."""
from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import activity, mail, todo
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

def test_old_activity_found_past_newest_40(cn):
    from agent_coord.server import push

    seed_names(cn, ("ag_proj", "roster"), ("ag_d", "desk"))
    old = int(todo.insert(cn, "ag_proj", "ag_d", "open", "old card")[0]["id"])
    for i in range(45):
        todo.insert(cn, "ag_proj", "ag_d", "open", f"newer {i}")
    assert all(int(r["id"]) != old for r in activity.select(cn, 0, 40) if r["type"] == "todo")
    d = json.loads(push._cheap_detail(cn, "todo", old, []))
    assert d["when"], "an activity older than the newest 40 still has its when"
    assert d["state"] is None

def test_states_match_select(cn):
    seed_names(cn, ("ag_p2", "roster"), ("ag_s", "desk"), ("ag_r", "desk"))
    mid = int(mail.insert(cn, "ag_p2", "ag_s", "ag_r", "hi")[0]["id"])
    tid = int(todo.insert(cn, "ag_p2", "ag_s", "open", "c")[0]["id"])
    assert activity.get(cn, "mail", mid)["state"] == "sent"
    assert activity.get(cn, "todo", tid)["state"] is None
    todo.delete(cn, tid, "ag_s")
    mail.delete(cn, mid, "ag_s")
    assert activity.get(cn, "todo", tid)["state"] == "deleted"
    assert activity.get(cn, "mail", mid)["state"] == "deleted"

def test_absent_and_wrong_type(cn):
    seed_names(cn, ("ag_p3", "roster"), ("ag_x", "desk"))
    tid = int(todo.insert(cn, "ag_p3", "ag_x", "open", "c")[0]["id"])
    assert activity.get(cn, "todo", 99999999) is None
    assert activity.get(cn, "hold", tid) is None  # same id, other type: no row
    assert activity.get(cn, "", 0) is None

def test_lookup_is_a_primary_key_read(cn):
    seed_names(cn, ("ag_p4", "roster"), ("ag_e", "desk"))
    tid = int(todo.insert(cn, "ag_p4", "ag_e", "open", "c")[0]["id"])
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(
            "EXPLAIN SELECT a.created FROM activity a"
            " LEFT JOIN mail m ON a.type = 'mail' AND m.id = a.id"
            " WHERE a.type = %s AND a.id = %s",
            ("todo", tid),
        )
        row = [r for r in cur.fetchall() if r["table"] == "a"][0]
    finally:
        cur.close()
    assert row["key"] == "PRIMARY"
    assert row["type"] == "const"
