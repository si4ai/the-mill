"""A refused hold names the desk that holds the resource (#174)."""
from __future__ import annotations

from unittest.mock import MagicMock

from agent_coord.server.api.mill import rpc


def test_refused_hold_names_holder(monkeypatch):
    def fake_upsert(cn, project, desk, resource, kh=None, *, old_kh=None):
        return [{"ok": 0, "id": 3, "desk_id": 7}]

    monkeypatch.setattr("agent_coord.server.records.hold.upsert", fake_upsert)
    monkeypatch.setattr("agent_coord.server.records.name.by_id", lambda cn, nid: "builder" if int(nid) == 7 else "")
    out = rpc._h_hold(MagicMock(), {"resource": "agent_coord/client/ws.py", "kh": "0" * 64}, "the-mill", "grok-tui")
    assert out["ok"] is False
    assert out["held"] is False
    assert out["owner"] == "builder"


def test_peek_does_not_call_upsert(monkeypatch):
    calls = {"upsert": 0}

    def fake_upsert(cn, project, desk, resource, kh=None, *, old_kh=None):
        calls["upsert"] += 1
        return [{"ok": 1, "id": 1, "desk_id": 1}]

    def fake_find(cn, **kw):
        return [{"resource": "f16-peek.res", "desk": "builder", "id": 9, "updated": "t0"}]

    monkeypatch.setattr("agent_coord.server.records.hold.upsert", fake_upsert)
    monkeypatch.setattr("agent_coord.server.records.hold.find", fake_find)
    out = rpc._h_hold(MagicMock(), {"resource": "f16-peek.res", "peek": True}, "the-mill", "grok-tui")
    assert calls["upsert"] == 0
    assert out["ok"] is True
    assert out["peek"] is True
    assert out["held"] is True
    assert out["owner"] == "builder"


def test_refused_hold_missing_name_is_empty(monkeypatch):
    def fake_upsert(cn, project, desk, resource, kh=None, *, old_kh=None):
        return [{"ok": 0, "id": 3, "desk_id": 7}]

    monkeypatch.setattr("agent_coord.server.records.hold.upsert", fake_upsert)
    monkeypatch.setattr("agent_coord.server.records.name.by_id", lambda cn, nid: "")
    out = rpc._h_hold(MagicMock(), {"resource": "agent_coord/client/ws.py", "kh": "0" * 64}, "the-mill", "grok-tui")
    assert out["owner"] == ""
