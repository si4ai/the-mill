# -*- coding: utf-8 -*-
"""Pending mill invite -> host enable -> mill join. Unique-by-desk here + reset."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records import join as here
from tests import sql_book

def test_invite_pending_then_enable(cn, monkeypatch) -> None:
    from agent_coord.server.admin import door

    monkeypatch.setenv("AGENT_COORD_DATABASE", sql_book.shared_db_name())
    monkeypatch.setenv("AGENT_COORD_DOOR", "invite")
    row = door.mint_key(label="sam laptop", created_by="build-performance", sync_legacy=False)
    assert row.get("status") == "pending"
    assert row.get("invite_path", "").startswith("/?invite=")
    tok = row["token"]
    assert door.invite_status(tok) == "pending"
    assert door.match_key(tok) is None
    assert door.check(tok) is False
    en = door.enable_key(row["key_id"])
    assert en.get("ok") is True
    assert door.invite_status(tok) == "active"
    assert door.match_key(tok) is not None
    assert door.check(tok) is True

def test_here_unique_desk_steal_and_reset(cn) -> None:
    p, d = "unit", "alice"
    here.upsert(cn, p, d, "builder", token_hash="a" * 64)
    with pytest.raises(Exception):
        here.upsert(cn, p, d, "builder", token_hash="b" * 64)
    here.reset(cn, p, d)
    here.upsert(cn, p, d, "builder", token_hash="b" * 64)
    rows = here.select(cn, p)
    assert any(r.get("token_hash") == "b" * 64 for r in rows)
    here.upsert(cn, p, d, "builder", token_hash="b" * 64)
    here.delete(cn, p, d)
    still = here.select(cn, p)
    assert still
    assert any(r.get("token_hash") == "b" * 64 for r in still)
