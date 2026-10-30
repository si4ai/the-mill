"""label N-N tags. A label is a name of type label. You label activities, not desks.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import apply, connect
from agent_coord.server.records import label as rec_label
from agent_coord.server.records import mail as rec_mail
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


def test_label_todo_and_mail(cn) -> None:
    """Same label name on a todo and a letter."""
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"), ("urgent", "label"))
    rec_todo.insert(cn, "unit", "a", "open", "card")
    tid = int(rec_todo.select(cn, "unit", "open")[0]["id"])
    rec_label.put(cn, "todo", tid, "urgent")
    rec_mail.insert(cn, "unit", "a", "b", "hi")
    mid = int(rec_mail.insert(cn, "unit", "a", "b", "hi2")[0]["id"])
    rec_label.put(cn, "mail", mid, "urgent")
    tags = rec_label.select(cn, "todo", tid)
    assert any(str(t.get("label") or "") == "urgent" for t in tags)
    assert rec_name.get(cn, "urgent", "label")


def test_label_does_not_use_member_for_tags(cn) -> None:
    """member is group or role only. A label does not become a member."""
    seed_names(cn, ("unit", "roster"), ("b", "desk"))
    rec_name.host_put(cn, "v12", "label")
    rec_todo.insert(cn, "unit", "b", "open", "ship")
    tid = int(rec_todo.select(cn, "unit", "open")[0]["id"])
    rec_label.put(cn, "todo", tid, "v12")
    tags = rec_label.select(cn, "todo", tid)
    assert any(str(t.get("label") or "") == "v12" for t in tags)
