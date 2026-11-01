"""#34 mill_name_get vs mill_name_put: reads must not mint; puts still create."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records.db import call, conn_kwargs as _conn_kwargs, scalar
from agent_coord.server.records import name as rec_name

def _exists(cn, name: str, kind: str = "") -> bool:
    return rec_name.get(cn, name, kind) is not None

def test_mill_name_get_unknown_returns_null_no_insert(cn) -> None:
    name = "nope_gate_get"
    assert not _exists(cn, name, "roster")
    got = scalar(cn, "SELECT mill_name_get(%s, %s)", ("roster", name))
    assert got is None
    assert not _exists(cn, name, "roster")

def test_mill_name_put_inserts(cn) -> None:
    name = "gate_put_ok"
    assert not _exists(cn, name, "roster")
    nid = int(scalar(cn, "SELECT mill_name_put(%s, %s)", ("roster", name)))
    assert nid > 0
    assert rec_name.get(cn, name, "roster") == nid
    assert int(scalar(cn, "SELECT mill_name_put(%s, %s)", ("roster", name))) == nid

def test_deleted_todo_keeps_activity_and_next_id_is_new(cn) -> None:
    proj = "gate_act_proj"
    desk = "gate_act_desk"
    scalar(cn, "SELECT mill_name_put(%s, %s)", ("roster", proj))
    scalar(cn, "SELECT mill_name_put(%s, %s)", ("desk", desk))
    first = call(cn, "mill_todo_insert", [proj, desk, "open", "keep the id"])[0]
    tid = int(first["id"])
    call(cn, "mill_todo_delete", [tid, desk])
    assert scalar(cn, "SELECT id FROM todo WHERE id=%s", (tid,)) is None
    assert int(scalar(cn, "SELECT id FROM activity WHERE type='todo' AND id=%s", (tid,))) == tid
    second = call(cn, "mill_todo_insert", [proj, desk, "open", "next id"])[0]
    assert int(second["id"]) > tid

def test_todo_select_unknown_project_does_not_insert(cn) -> None:
    name = "todo_typo_gate"
    assert not _exists(cn, name, "roster")
    rows = call(cn, "mill_todo_select", [name, ""])
    assert isinstance(rows, list)
    assert rows == []
    assert not _exists(cn, name, "roster")

def test_hold_select_unknown_project_does_not_insert(cn) -> None:
    name = "hold_typo_gate"
    assert not _exists(cn, name, "roster")
    call(cn, "mill_hold_select", [name])
    assert not _exists(cn, name, "roster")

def test_score_select_unknown_project_does_not_insert(cn) -> None:
    name = "score_typo_gate"
    assert not _exists(cn, name, "roster")
    call(cn, "mill_score_select", [name])
    assert not _exists(cn, name, "roster")

def test_mail_list_unknown_project_does_not_insert(cn) -> None:
    name = "mail_typo_gate"
    assert not _exists(cn, name, "roster")
    call(cn, "mill_mail_list", [name])
    assert not _exists(cn, name, "roster")

def test_get_or_insert_uses_put(cn) -> None:
    name = "gate_goi"
    assert not _exists(cn, name, "desk")
    nid = rec_name.get_or_insert(cn, name, "desk")
    assert rec_name.get(cn, name, "desk") == nid

def test_ensure_roster_high_trust_still_creates(cn, monkeypatch) -> None:
    name = "gate_ensure"
    monkeypatch.setattr("agent_coord.config.mill_catalog_open", lambda s: True)
    assert not _exists(cn, name, "roster")
    nid = rec_name.ensure_roster(cn, name, "roster")
    assert rec_name.get(cn, name, "roster") == nid

def test_todo_insert_unknown_project_refuses_no_mint(cn) -> None:
    name = "insert_typo_gate"
    desk = "gate_insert"
    rec_name.get_or_insert(cn, desk, "desk")
    assert not _exists(cn, name, "roster")
    with pytest.raises(Exception, match="no such project"):
        call(cn, "mill_todo_insert", [name, desk, "open", "body"])
    assert not _exists(cn, name, "roster")

def test_label_put_still_mints_label(cn) -> None:
    lab = "gate_urgent"
    desk = "gate_label"
    assert not _exists(cn, lab, "label")
    rec_name.get_or_insert(cn, desk, "desk")
    rows = call(cn, "mill_todo_insert", ["Office", desk, "open", "label-me"])
    tid = int(rows[0]["id"])
    call(cn, "mill_label_put", ["todo", tid, lab, None])
    assert _exists(cn, lab, "label")
