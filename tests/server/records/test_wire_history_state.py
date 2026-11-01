"""#92 live miss: Wire and History read role/station events, which carried no state.

/api/v1/events?lan= and ?role= go through floor_scope -> mill_floor_part events,
which has no state column. stamp_event_state adds the mill_activity_select state
(deleted any type, sent live letter, else None) so the Wall pill can paint.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import floor as rec_floor
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records import member as rec_member
from agent_coord.server.records import todo as rec_todo
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names

LAN = "203.0.113.92"

@pytest.fixture(scope="module")
def seeded(cn):
    seed_names(
        cn,
        ("ws_proj", "roster"),
        ("ws_a", "desk"),
        ("ws_b", "desk"),
        ("ws_role", "roster"),
    )
    rec_member.put(cn, "ws_proj", "ws_a")
    rec_member.put(cn, "ws_role", "ws_a", kind="roster")
    rec_join.upsert(cn, "ws_proj", "ws_a", "", "9" * 64, "present")
    rec_join.set_lan_ip(cn, "ws_a", LAN)
    live_mid = int(rec_mail.insert(cn, "ws_proj", "ws_a", "ws_b", "live letter")[0]["id"])
    gone_mid = int(rec_mail.insert(cn, "ws_proj", "ws_a", "ws_b", "gone letter")[0]["id"])
    live_tid = int(rec_todo.insert(cn, "ws_proj", "ws_a", "open", "live card")[0]["id"])
    gone_tid = int(rec_todo.insert(cn, "ws_proj", "ws_a", "open", "gone card")[0]["id"])
    rec_mail.delete(cn, gone_mid, "ws_a")
    rec_todo.delete(cn, gone_tid, "ws_a")
    return {
        ("mail", live_mid): "sent",
        ("mail", gone_mid): "deleted",
        ("todo", live_tid): None,
        ("todo", gone_tid): "deleted",
    }

def _by(events):
    return {(str(e.get("type") or e.get("kind")), int(e["id"])): e for e in events}

def _check(events, want):
    by = _by(events)
    for k, st in want.items():
        assert k in by, k
        assert "state" in by[k], by[k]
        assert by[k]["state"] == st, (k, by[k])

@pytest.mark.parametrize("kind,ident", [("lan", LAN), ("role", "ws_role")])
def test_floor_scope_events_carry_state(cn, seeded, kind, ident) -> None:
    view = rec_floor.floor_scope(cn, kind, ident, parts=["events"])
    _check(view["events"], seeded)
    assert all("state" in e for e in view["events"])

def test_scope_state_falls_back_per_desk(cn, seeded, monkeypatch) -> None:
    """A scoped row older than the office-wide read still gets its state."""
    monkeypatch.setattr(rec_floor, "LIST_PAGE_MAX", 1)
    view = rec_floor.floor_scope(cn, "lan", LAN, parts=["events"])
    _check(view["events"], seeded)

def _client(cn, monkeypatch):
    from fastapi.testclient import TestClient

    from agent_coord.lib.observe import parse_roots
    from agent_coord.server import middleware
    from agent_coord.server.asgi import make_asgi_app

    class _C:
        _cn = cn

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    monkeypatch.setattr(middleware, "_office", lambda: _C())
    middleware._floor_cache.clear()
    root = Path(__file__).resolve().parents[3]
    return TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))

@pytest.mark.parametrize(
    "query", [f"lan={LAN}&limit=50", "role=ws_role&limit=50", "project=ws_proj&limit=50"]
)
def test_api_v1_events_payload_has_state(cn, seeded, monkeypatch, query) -> None:
    client = _client(cn, monkeypatch)
    r = client.get(f"/api/v1/events?{query}")
    assert r.status_code == 200, r.text
    _check(r.json()["events"], seeded)

def test_api_activity_daily_is_evidence_and_between_has_state(cn, seeded, monkeypatch) -> None:
    """window=daily is the day chart (score_evidence: no type/updated/state per item).

    The History diary must paint per-item events (state above), not these rows;
    window=between stays the per-item activity read with state.
    """
    client = _client(cn, monkeypatch)
    daily = client.get(f"/api/activity?scope=lan&id={LAN}&window=daily&limit=50")
    assert daily.status_code == 200, daily.text
    assert daily.json()["source"] == "score_evidence"
    for row in daily.json()["rows"]:
        assert "type" not in row and "state" not in row
    between = client.get(f"/api/activity?scope=lan&id={LAN}&window=between&limit=50")
    assert between.status_code == 200, between.text
    by: dict = {}
    for row in between.json()["rows"]:
        by.setdefault((row["type"], int(row["id"])), set()).add(row["state"])
    for k, st in seeded.items():
        assert by[k] == {st}, k
