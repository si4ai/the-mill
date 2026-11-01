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


def test_pool_hit_takes_the_lock(monkeypatch) -> None:
    """A cache hit must still decide under _POOL_LOCK (no unlocked return)."""
    held: list[str] = []

    class SpyLock:
        def __enter__(self):
            held.append("enter")
            return self

        def __exit__(self, *exc):
            held.append("exit")

    class Pool:
        def __init__(self, database: str):
            self.database = database

        def get_connection(self):
            return f"pooled:{self.database}"

    monkeypatch.setattr(db, "_POOL_LOCK", SpyLock())
    monkeypatch.setattr(db, "_POOL", Pool("book_a"))
    monkeypatch.setattr(db, "_POOL_DB", "book_a")
    monkeypatch.setattr(db, "conn_kwargs", lambda: {"database": "book_a"})
    monkeypatch.setattr(db, "_arm_pool_close", lambda cn: None)
    assert db.connect() == "pooled:book_a"
    assert "enter" in held, "unlocked fast path returned without the lock"


def test_concurrent_database_flip_never_cross_wires(monkeypatch) -> None:
    """Deterministic repro: unlocked match-then-return can hand back another DB's pool.

    Pause inside `_POOL_DB == want` on a match. A second thread tries a non-blocking
    lock acquire and rebuilds for book_b only if the lock is free (unlocked fast
    path). Match-and-return under `_POOL_LOCK` keeps the lock held, so the writer
    cannot cross-wire.
    """
    import threading

    pause = threading.Event()
    allow = threading.Event()
    built: list[str] = []

    class PausingStr(str):
        def __eq__(self, other):
            ok = str.__eq__(self, other)
            if ok and not allow.is_set():
                pause.set()
                allow.wait(timeout=1)
            return ok

        def __hash__(self):
            return str.__hash__(self)

    class Pool:
        def __init__(self, database: str):
            self.database = database

        def get_connection(self):
            return f"pooled:{self.database}"

    def fake_pool_ctor(*, pool_name, pool_size, pool_reset_session, **kw):
        name = str(kw.get("database") or "")
        built.append(name)
        return Pool(name)

    state = {"database": "book_a"}

    monkeypatch.setattr(db, "_POOL", Pool("book_a"))
    monkeypatch.setattr(db, "_POOL_DB", PausingStr("book_a"))
    monkeypatch.setattr(db, "_POOL_SEQ", 1)
    monkeypatch.setattr(db, "conn_kwargs", lambda: dict(state))
    monkeypatch.setattr(db, "_arm_pool_close", lambda cn: None)
    monkeypatch.setattr("mysql.connector.pooling.MySQLConnectionPool", fake_pool_ctor)

    result: list[Pool] = []

    def reader() -> None:
        result.append(db._pool())

    def writer() -> None:
        assert pause.wait(timeout=2), "reader never entered match"
        state["database"] = "book_b"
        got = db._POOL_LOCK.acquire(blocking=False)
        try:
            if got:
                # Lock free during match => unlocked fast path; cross-wire.
                db._POOL = fake_pool_ctor(
                    pool_name="mill_wall_race",
                    pool_size=1,
                    pool_reset_session=True,
                    database="book_b",
                )
                db._POOL_DB = "book_b"
        finally:
            if got:
                db._POOL_LOCK.release()
        allow.set()

    t_r = threading.Thread(target=reader)
    t_w = threading.Thread(target=writer)
    t_r.start()
    t_w.start()
    t_r.join(timeout=3)
    t_w.join(timeout=3)
    assert result, "reader returned nothing"
    assert result[0].database == "book_a", (
        f"cross-wired: reader wanted book_a but got {result[0].database!r} (built={built})"
    )
