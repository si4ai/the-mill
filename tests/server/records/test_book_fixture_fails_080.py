"""0.8.0 (F168): the records book fixture skips only when MySQL does not answer.

When MySQL answers but the schema or a routine fails to apply, every SQL suite
must fail, not skip: a skip hid a broken beta apply behind a green run.
"""
from __future__ import annotations

import pytest

from tests.server.records import conftest as rc


class _Admin:
    def cursor(self):
        return self

    def execute(self, *_a):
        return None

    def close(self):
        return None


def test_apply_error_fails_the_fixture(monkeypatch):
    import mysql.connector

    import agent_coord.server.records as records

    monkeypatch.setattr(mysql.connector, "connect", lambda **kw: _Admin())
    monkeypatch.setattr(records, "connect", lambda db: _Admin())

    def boom(cn, wipe=False):
        raise RuntimeError("1064 bad routine")

    monkeypatch.setattr(records, "apply", boom)
    with pytest.raises(pytest.fail.Exception) as ei:
        rc.open_book("mill_fixture_080")
    assert "1064 bad routine" in str(ei.value)


def test_no_mysql_skips(monkeypatch):
    import mysql.connector

    def refused(**kw):
        raise mysql.connector.errors.InterfaceError("2003: Can't connect")

    monkeypatch.setattr(mysql.connector, "connect", refused)
    with pytest.raises(pytest.skip.Exception):
        rc.open_book("mill_fixture_080")
