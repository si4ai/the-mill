# -*- coding: utf-8 -*-
"""Bare connect() must use a pool built for the current AGENT_COORD_DATABASE.

Under pytest-xdist a worker builds the pool on one throwaway schema, then a
later file sets AGENT_COORD_DATABASE to another and opens Book() / connect()
with no database=. The old pool stayed on the first schema, so ws auth saw an
empty join table (4401 bad token on release/0.8.3). Row F-pool-follows-database.
"""
from __future__ import annotations

from agent_coord.server.records import db


def test_pool_rebuilds_when_configured_database_changes(monkeypatch) -> None:
    built: list[str] = []

    class Pool:
        def __init__(self, database: str):
            self.database = database

        def get_connection(self):
            return f"pooled:{self.database}"

    def fake_pool_ctor(*, pool_name, pool_size, pool_reset_session, **kw):
        built.append(str(kw.get("database") or ""))
        return Pool(built[-1])

    state = {"database": "book_a"}

    monkeypatch.setattr(db, "_POOL", None)
    monkeypatch.setattr(db, "_POOL_DB", None)
    monkeypatch.setattr(db, "_POOL_SEQ", 0)
    monkeypatch.setattr(db, "conn_kwargs", lambda: dict(state))
    monkeypatch.setattr(db, "_arm_pool_close", lambda cn: None)
    monkeypatch.setattr(
        "mysql.connector.pooling.MySQLConnectionPool",
        fake_pool_ctor,
    )

    assert db.connect() == "pooled:book_a"
    assert built == ["book_a"]

    state["database"] = "book_b"
    assert db.connect() == "pooled:book_b"
    assert built == ["book_a", "book_b"]

    # same name keeps the rebuilt pool
    assert db.connect() == "pooled:book_b"
    assert built == ["book_a", "book_b"]


def test_connect_without_database_still_uses_the_pool_when_db_matches(monkeypatch) -> None:
    class Pool:
        def get_connection(self):
            return "pooled"

    monkeypatch.setattr(db, "_POOL", Pool())
    monkeypatch.setattr(db, "_POOL_DB", "throwaway")
    monkeypatch.setattr(db, "_arm_pool_close", lambda cn: None)
    monkeypatch.setattr(db, "conn_kwargs", lambda: {"database": "throwaway"})
    assert db.connect() == "pooled"
