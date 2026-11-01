"""Install trust=high|limited. Reclaim always mill host.

high: mill_name LABEL_/ROLE_ on first use. PROJ_ still mill host mill group.
limited: mill_name only DESK_; mill host mill group/role/label.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import label as rec_label
from agent_coord.server.records import name as rec_name
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

from tests.server.records.conftest import admin_desk

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
