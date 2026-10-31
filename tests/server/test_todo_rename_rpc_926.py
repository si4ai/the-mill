"""Card 926: rename todo who-may (asker or Admin) and next-command hint."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc


def _card(monkeypatch, *, asker: str, need: str = "old-need", aliases=None):
    payload = {"slug": need, "detail": "d", "aliases": list(aliases or [])}
    row = {
        "id": 926,
        "status": "open",
        "assigned": "",
        "creator": asker,
        "creator_id": 1,
        "body": json.dumps(payload),
        "roster": "r926",
    }
    renamed = {}

    def fake_find(cn, project, need_s):
        fields = json.loads(row["body"])
        if need_s == fields.get("slug") or need_s in (fields.get("aliases") or []) or str(need_s) == "926":
            return dict(row)
        return None

    def fake_rename(cn, todo_id, desk, old_need, new_need, *, why=""):
        renamed["desk"] = desk
        renamed["old"] = old_need
        renamed["new"] = new_need
        renamed["why"] = why
        fields = json.loads(row["body"])
        fields["aliases"] = [fields["slug"]] + list(fields.get("aliases") or [])
        fields["slug"] = new_need
        row["body"] = json.dumps(fields)
        return {"ok": True, "id": todo_id, "need_id": new_need, "was": old_need, "op": "renamed", "why": why}

    monkeypatch.setattr("agent_coord.server.records.todo.find", fake_find)
    monkeypatch.setattr("agent_coord.server.records.todo.rename", fake_rename)
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    monkeypatch.setattr(rpc, "_desk_slug", lambda cn, hit, *keys: asker)
    return row, renamed


def test_non_asker_refused_and_names_next_command(monkeypatch):
    _card(monkeypatch, asker="auditor")
    monkeypatch.setattr(
        "agent_coord.server.admin.guard.is_role_admin", lambda cn, desk: False
    )
    with pytest.raises(CoordError) as exc:
        rpc._h_rename(
            MagicMock(_cn=object()),
            {"name_type": "todo", "need": "old-need", "new": "new-need", "why": "x"},
            "r926",
            "other-desk",
        )
    msg = str(exc.value)
    assert "who-may: rename todo is the asker (auditor) or Admin" in msg
    assert "mill note r926 old-need --note TEXT" in msg


def test_asker_renames(monkeypatch):
    _row, renamed = _card(monkeypatch, asker="auditor")
    monkeypatch.setattr(
        "agent_coord.server.admin.guard.is_role_admin", lambda cn, desk: False
    )
    out = rpc._h_rename(
        MagicMock(_cn=object()),
        {"name_type": "todo", "need": "old-need", "new": "new-need", "why": "wider"},
        "r926",
        "auditor",
    )
    assert out["need_id"] == "new-need"
    assert renamed["desk"] == "auditor"
    assert renamed["why"] == "wider"


def test_admin_renames(monkeypatch):
    _row, renamed = _card(monkeypatch, asker="auditor")
    monkeypatch.setattr(
        "agent_coord.server.admin.guard.is_role_admin", lambda cn, desk: desk == "admin-desk"
    )
    out = rpc._h_rename(
        MagicMock(_cn=object()),
        {"name_type": "todo", "need": "old-need", "new": "new-need", "why": "admin"},
        "r926",
        "admin-desk",
    )
    assert out["need_id"] == "new-need"
    assert renamed["desk"] == "admin-desk"
