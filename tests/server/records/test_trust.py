"""Install trust=high|limited. Reclaim always mill host.

high: mill_name LABEL_/ROLE_ on first use. PROJ_ still mill host mill group.
limited: mill_name only DESK_; mill host mill group/role/label.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import apply, connect
from agent_coord.server.records import label as rec_label
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

from tests.sql_isolate import throwaway_db
from tests.server.records.conftest import admin_desk

TEST_DB = throwaway_db("mill_records_test")


def _cn():
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
    cn = connect(TEST_DB)
    apply(cn, wipe=True)
    return cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = _cn()
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    yield c
    c.close()


def test_high_trust_does_not_mint_label(cn, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", "high")
    seed_names(cn, ("unit", "roster"), ("a", "desk"))
    rec_todo.insert(cn, "unit", "a", "open", "x")
    tid = int(rec_todo.select(cn, "unit", "open")[0]["id"])
    with pytest.raises(Exception, match="mill create label urgent"):
        rec_label.put(cn, "todo", tid, "urgent")
    assert rec_name.get(cn, "urgent", "label") is None


def test_limited_trust_refuses_new_label(cn, monkeypatch) -> None:
    monkeypatch.setenv("AGENT_COORD_TRUST", "limited")
    seed_names(cn, ("unit", "roster"), ("a", "desk"))
    rec_todo.insert(cn, "unit", "a", "open", "y")
    tid = int(rec_todo.select(cn, "unit", "open")[0]["id"])
    with pytest.raises(Exception, match="mill create label secret"):
        rec_label.put(cn, "todo", tid, "secret")
    rec_name.host_put(cn, "secret", "label")
    rec_label.put(cn, "todo", tid, "secret")
    assert rec_name.get(cn, "secret", "label")
