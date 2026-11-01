# -*- coding: utf-8 -*-
"""#818: a client older than the office (0.7.15) still sends TYPE join.

The migrated office has no join type. Such a request gets one plain refusal that
names the upgrade: not a 500, and nothing is written (no watcher, no doing row).
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.sql

from fastapi.testclient import TestClient

from agent_coord.client.tokens import token_hash
from agent_coord.lib.observe import parse_roots
from agent_coord.server.asgi import make_asgi_app
from agent_coord.server.push import HUB
from agent_coord.server.records import join as here
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs, scalar

TOKEN = "old-client-818-token"
UPGRADE = "pip install -U the-mill"

def _client(monkeypatch) -> TestClient:
    monkeypatch.setattr("agent_coord.server.admin.door.mode", lambda: "path")
    monkeypatch.setattr("agent_coord.server.allow.allowed", lambda *a, **k: True)
    root = Path(__file__).resolve().parents[2]
    return TestClient(make_asgi_app(parse_roots(cwd=root), api_only=True))

def _counts(cn) -> tuple[int, int]:
    return (
        int(scalar(cn, "SELECT COUNT(*) FROM watcher") or 0),
        int(scalar(cn, "SELECT COUNT(*) FROM doing") or 0),
    )

# What a 0.7.15 client sends for `mill watch join ID`, `mill add join:ID`,
# `mill unwatch join ID`, and a label or a move on a join row.
OLD_BODIES = [
    ("add", {"type": "join"}),
    ("remove", {"type": "join"}),
    ("label-add", {"type": "join", "label": "x"}),
    ("label-remove", {"type": "join", "label": "x"}),
    ("move", {"type": "join", "type_b": "join"}),
]

@pytest.mark.parametrize("command,extra", OLD_BODIES)
def test_old_client_join_type_over_http_is_refused_with_upgrade(cn, monkeypatch, command, extra) -> None:
    monkeypatch.setattr(HUB, "rooms", {})
    rec = here.upsert(cn, "unit", "alice", "builder", token_hash=token_hash(TOKEN), doing="present")
    jid = int(rec[0]["id"])
    before = _counts(cn)
    body = {"project": "unit", "owner": "alice", "id": jid, **extra}
    r = _client(monkeypatch).post(
        f"/mill/v1/{command}", json=body, headers={"authorization": f"Bearer {TOKEN}"}
    )
    assert r.status_code < 500, r.text
    assert r.status_code != 200, r.text
    assert UPGRADE in r.text and "doing" in r.text, r.text
    assert _counts(cn) == before

