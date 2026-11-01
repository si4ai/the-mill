"""#220: mill_mail_select carries this desk's opened flag. Inbox does not read it again."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from tests import sql_book

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import opened
from agent_coord.server.records import mail as rec_mail
from tests.server.records.conftest import seed_names

class _Book:
    def __init__(self, cn):
        self._cn = cn

@pytest.fixture(scope="module")
def cn():
    try:
        c = sql_book.connect_shared(reset=True)
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
