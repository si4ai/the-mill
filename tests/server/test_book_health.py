"""Health URL and a down book during /ws auth (#144). No live SQL."""
from __future__ import annotations

import json

import pytest

from agent_coord.server import asgi
from agent_coord.server.middleware import make_handler
from agent_coord.server.records import db


class OperationalError(Exception):
    def __init__(self, msg: str = "down", errno: int = 2003) -> None:
        super().__init__(msg)
        self.errno = errno


class InterfaceError(Exception):
    pass


class IntegrityError(Exception):
    errno = 1062


class PoolError(Exception):
    pass


def test_book_down_and_retry_split() -> None:
    assert db.book_down(OperationalError("can't connect"))
    assert db.book_down(InterfaceError("socket"))
    assert db.book_down(PoolError("pool exhausted"))
    wrapped = RuntimeError("wrap")
    wrapped.__cause__ = OperationalError("lost")
    assert db.book_down(wrapped)
    assert not db.book_down(IntegrityError("Duplicate entry '62-todo-24'"))
    assert not db.book_down(ValueError("no"))
    assert db.retryable_db(OperationalError("lost", errno=2006))
    assert db.retryable_db(InterfaceError("socket"))
    assert not db.retryable_db(IntegrityError("Duplicate entry"))
    assert not db.retryable_db(PoolError("pool exhausted"))
    assert not db.retryable_db(OperationalError("Duplicate entry 'x'", errno=1062))


def test_ws_auth_close_codes() -> None:
    assert asgi.ws_auth_close(OperationalError("down")) == (1013, "book unavailable")
    assert asgi.ws_auth_close(ValueError("parse")) == (1011, "")


def test_connect_waits_when_the_pool_is_full(monkeypatch) -> None:
    class Pool:
        def __init__(self) -> None:
            self.n = 0

        def get_connection(self):
            self.n += 1
            if self.n < 3:
                raise PoolError("pool exhausted")
            return object()

    pool = Pool()
    monkeypatch.setattr(db, "_pool", lambda: pool)
    monkeypatch.setattr(db, "_arm_pool_close", lambda cn: None)
    monkeypatch.setattr(db, "conn_kwargs", lambda: {"database": "throwaway"})
    monkeypatch.setattr(db.time, "sleep", lambda _s: None)
    monkeypatch.setattr(db.time, "monotonic", lambda: 0.0)
    assert db.connect() is not None
    assert pool.n == 3


def test_connect_does_not_wait_when_the_book_is_down(monkeypatch) -> None:
    sleeps: list[float] = []

    class Pool:
        def get_connection(self):
            raise OperationalError("can't connect", errno=2003)

    monkeypatch.setattr(db, "_pool", lambda: Pool())
    monkeypatch.setattr(db, "conn_kwargs", lambda: {"database": "throwaway"})
    monkeypatch.setattr(db.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(OperationalError):
        db.connect()
    assert sleeps == []


def test_connect_stops_waiting_after_the_cap(monkeypatch) -> None:
    clock = {"t": 0.0}

    class Pool:
        def __init__(self) -> None:
            self.n = 0

        def get_connection(self):
            self.n += 1
            raise PoolError("pool exhausted")

    pool = Pool()

    def sleep(_s: float) -> None:
        clock["t"] = 5.0

    monkeypatch.setattr(db, "_pool", lambda: pool)
    monkeypatch.setattr(db, "conn_kwargs", lambda: {"database": "throwaway"})
    monkeypatch.setattr(db.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(db.time, "sleep", sleep)
    with pytest.raises(PoolError):
        db.connect()
    assert pool.n == 2


def test_call_retries_a_dropped_connection_once(monkeypatch) -> None:
    calls = {"n": 0}

    class Cur:
        def callproc(self, name, args):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OperationalError("lost", errno=2006)

        def close(self):
            return None

    class Cn:
        def commit(self):
            return None

        def rollback(self):
            return None

    monkeypatch.setattr(db, "_cursor", lambda cn: Cur())
    monkeypatch.setattr(db, "drain_proc", lambda cur: [{"ok": 1}])
    monkeypatch.setattr(db, "finish_cursor", lambda cur: None)
    monkeypatch.setattr(db, "_perf", lambda *a, **k: None)
    assert db.call(Cn(), "mill_x", []) == [{"ok": 1}]
    assert calls["n"] == 2


def test_call_does_not_retry_duplicate_key(monkeypatch) -> None:
    calls = {"n": 0}

    class Cur:
        def callproc(self, name, args):
            calls["n"] += 1
            raise IntegrityError("Duplicate entry '62-todo-24' for key 'tree.PRIMARY'")

        def close(self):
            return None

    class Cn:
        def rollback(self):
            return None

    monkeypatch.setattr(db, "_cursor", lambda cn: Cur())
    monkeypatch.setattr(db, "finish_cursor", lambda cur: None)
    monkeypatch.setattr(db, "_perf", lambda *a, **k: None)
    with pytest.raises(IntegrityError):
        db.call(Cn(), "mill_todo_insert", [])
    assert calls["n"] == 1


def test_book_ping_is_false_without_a_connection(monkeypatch) -> None:
    def down():
        raise OperationalError("down")

    monkeypatch.setattr(db, "connect", down)
    assert db.book_ping() is False


class _Fake:
    def __init__(self, path: str) -> None:
        self.path = path
        self.headers: dict[str, str] = {}
        self._code = None
        self._hdrs: dict[str, str] = {}
        self._body = b""
        self.wfile = self

    def write(self, blob: bytes) -> None:
        self._body += blob

    def send_response(self, code: int) -> None:
        self._code = code

    def send_header(self, key: str, val: str) -> None:
        self._hdrs[key.lower()] = val

    def end_headers(self) -> None:
        return None

    def log_message(self, *args) -> None:
        return None


def _bind(handler, fake: _Fake) -> None:
    fake.do_GET = handler.do_GET.__get__(fake, _Fake)
    fake._send = handler._send.__get__(fake, _Fake)
    fake._send_health = handler._send_health.__get__(fake, _Fake)
    fake._door_ok = handler._door_ok.__get__(fake, _Fake)
    fake._do_GET_inner = handler._do_GET_inner.__get__(fake, _Fake)


def test_health_skips_the_door(monkeypatch) -> None:
    monkeypatch.setattr(db, "book_ping", lambda: True)
    monkeypatch.setattr(db, "book_sql_state", lambda: {"ok": True})

    def door_must_not_run():
        raise AssertionError("health called the door")

    monkeypatch.setattr("agent_coord.server.admin.door.mode", door_must_not_run)
    handler = make_handler({}, api_only=True)
    hit = _Fake("/health")
    _bind(handler, hit)
    hit.do_GET()
    assert hit._code == 200
    body = json.loads(hit._body.decode("ascii"))
    assert body["ok"] is True
    assert body["db_driver"] in ("c", "pure")


def test_health_503_when_the_book_is_down(monkeypatch) -> None:
    monkeypatch.setattr(db, "book_ping", lambda: False)
    handler = make_handler({}, api_only=True)
    hit = _Fake("/health")
    _bind(handler, hit)
    hit.do_GET()
    assert hit._code == 503
    assert json.loads(hit._body.decode("ascii")) == {
        "ok": False,
        "error": "book unavailable",
    }


def test_deadlock_and_lock_wait_retry_by_code_whatever_the_class() -> None:
    """#818: the connector raises InternalError for 1213 and DatabaseError for 1205."""
    from mysql.connector import errors

    dead = errors.get_mysql_exception(1213, "Deadlock found", "40001")
    wait = errors.get_mysql_exception(1205, "Lock wait timeout exceeded", "HY000")
    assert type(dead).__name__ == "InternalError" and type(wait).__name__ == "DatabaseError"
    assert db.retryable_db(dead) and db.retryable_db(wait)
    assert db.retryable_db(errors.DatabaseError("x", errno=1213))
    assert not db.retryable_db(errors.DatabaseError("x", errno=1146))
    assert not db.retryable_db(errors.IntegrityError("Duplicate entry 'a'", errno=1062))
