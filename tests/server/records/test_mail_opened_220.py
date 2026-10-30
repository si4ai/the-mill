"""#220: mill_mail_select carries this desk's opened flag. Inbox does not read it again."""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import apply, connect, opened
from agent_coord.server.records import mail as rec_mail
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_mail_open_220")


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _cn():
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
    cn = connect(TEST_DB)
    apply(cn, wipe=True)
    return cn


@pytest.fixture(scope="module")
def cn():
    try:
        c = _cn()
    except Exception as e:
        pytest.skip(f"mysql mill records: {e}")
    seed_names(c, ("unit", "roster"), ("asker", "desk"), ("other", "desk"))
    yield c
    c.close()


def _row(cn, desk: str, mid: int) -> dict:
    return next(r for r in rec_mail.select(cn, desk) if int(r["id"]) == mid)


def test_opened_is_on_the_inbox_row_and_unread_skips_it(cn, monkeypatch) -> None:
    book = _Book(cn)
    first = rpc._h_send(
        book, {"src": "asker", "dst": "other", "body": "one"}, "unit", "asker"
    )
    second = rpc._h_send(
        book, {"src": "asker", "dst": "other", "body": "two"}, "unit", "asker"
    )
    one = int(first["id"])
    two = int(second["id"])
    assert _row(cn, "other", one).get("opened") is None
    assert _row(cn, "other", two).get("opened") is None

    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("inbox must not read opened again")

    monkeypatch.setattr("agent_coord.server.records.opened.read_ids", _boom)

    fresh = rpc._h_inbox(book, {"dst": "other", "all": True}, "unit", "other")
    assert {int(r["id"]) for r in fresh} >= {one, two}
    assert all("opened" not in r for r in fresh)

    opened.insert(cn, one, "other")
    assert _row(cn, "other", one).get("opened") is not None
    assert _row(cn, "other", two).get("opened") is None

    unread = rpc._h_inbox(book, {"dst": "other"}, "unit", "other")
    unread_ids = {int(r["id"]) for r in unread}
    assert one not in unread_ids
    assert two in unread_ids
    whole = rpc._h_inbox(book, {"dst": "other", "all": True}, "unit", "other")
    assert one in {int(r["id"]) for r in whole}
    assert all("opened" not in r for r in whole)
    assert calls["n"] == 0
