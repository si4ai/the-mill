"""label N-N tags. A label is a name of type label. You label activities, not desks.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import label as rec_label
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

from tests.server.records.conftest import admin_desk

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
