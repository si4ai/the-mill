# -*- coding: utf-8 -*-
"""Pending mill invite -> host enable -> mill join. Unique-by-desk here + reset."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from agent_coord.server.records import apply, connect
from agent_coord.server.records import join as here
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_invite_install")


@pytest.fixture
def cn():
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
    c = connect(TEST_DB)
    apply(c, wipe=True)
    yield c
    c.close()


def test_invite_pending_then_enable(cn, monkeypatch) -> None:
    from agent_coord.server.admin import door

    monkeypatch.setenv("AGENT_COORD_DATABASE", TEST_DB)
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
