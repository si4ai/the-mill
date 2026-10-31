# -*- coding: utf-8 -*-
"""Explicit connect(database=) must not reuse a pool built for another schema.

Under pytest-xdist a worker often opens the pool on the default book, then a
suite sets AGENT_COORD_DATABASE to its throwaway name and calls connect(name).
When name matched the env, the old connect() returned the stale pool; apply and
invite SPs ran on the wrong schema so cmd_invite_create was missing on the
throwaway DB (release/0.8.3 pytest_sql). Row F233.
"""
from __future__ import annotations

import pytest

from agent_coord.server.records import db


def test_connect_explicit_database_skips_pool_even_when_env_matches(monkeypatch) -> None:
    calls: list[dict] = []

    class Pool:
        def get_connection(self):
            raise AssertionError("pool must not be used for an explicit database=")

    def fake_connect(**kw):
        calls.append(dict(kw))
        return object()

    monkeypatch.setattr(db, "_pool", lambda: Pool())
    monkeypatch.setattr(db, "conn_kwargs", lambda: {"database": "throwaway_gw0", "host": "127.0.0.1"})
    monkeypatch.setattr("mysql.connector.connect", fake_connect)

    cn = db.connect("throwaway_gw0")
    assert cn is not None
    assert calls and calls[0]["database"] == "throwaway_gw0"


def test_connect_without_database_still_uses_the_pool(monkeypatch) -> None:
    class Pool:
        def get_connection(self):
            return "pooled"

    monkeypatch.setattr(db, "_pool", lambda: Pool())
    monkeypatch.setattr(db, "_arm_pool_close", lambda cn: None)
    monkeypatch.setattr(db, "conn_kwargs", lambda: {"database": "throwaway"})
    assert db.connect() == "pooled"
