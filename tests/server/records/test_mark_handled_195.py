"""Inbox does not mark. Reply marks the parent only. mark takes several ids (#195).

A mail-thread read that prints a letter whole marks it (card 843, F129).
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import apply, connect, opened
from agent_coord.server.records.db import conn_kwargs as _conn_kwargs
from tests.server.records.conftest import seed_names
from tests.sql_isolate import throwaway_db

TEST_DB = throwaway_db("mill_mark_195")


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


def _stamped(cn, mid: int, desk: str) -> bool:
    return int(mid) in opened.read_ids(cn, [mid], desk)


def test_fetch_does_not_mark_and_reply_marks_the_parent_only(cn) -> None:
    book = _Book(cn)
    root = rpc._h_send(
        book, {"src": "asker", "dst": "other", "body": "parent"}, "unit", "asker"
    )
    mid = int(root["id"])
    listed = rpc._h_inbox(book, {"dst": "other", "limit": 20}, "unit", "other")
    assert mid in {int(r["id"]) for r in listed}
    assert _stamped(cn, mid, "other") is False
    rpc._h_mail_thread(book, {"mail_id": mid}, "unit", "other")
    # Card 843: a read that prints the letter whole marks it (F129); inbox still does not.
    assert _stamped(cn, mid, "other") is True
    reply = rpc._h_reply(book, {"mail_id": mid, "body": "answered"}, "unit", "other")
    child = int(reply["id"])
    assert _stamped(cn, mid, "other") is True
    assert _stamped(cn, child, "other") is False
    assert _stamped(cn, child, "asker") is False


def test_mark_several_ids_and_refuses_before_any_stamp(cn) -> None:
    book = _Book(cn)
    one = rpc._h_send(book, {"src": "other", "dst": "asker", "body": "one"}, "unit", "other")
    two = rpc._h_send(book, {"src": "other", "dst": "asker", "body": "two"}, "unit", "other")
    a, b = int(one["id"]), int(two["id"])
    with pytest.raises(CoordError, match="--state is not a flag"):
        rpc._h_mark(book, {"ids": [a, b], "state": "later"}, "unit", "asker")
    assert _stamped(cn, a, "asker") is False
    assert _stamped(cn, b, "asker") is False
    with pytest.raises(CoordError, match="no such mail"):
        rpc._h_mark(book, {"ids": [a, 999999]}, "unit", "asker")
    assert _stamped(cn, a, "asker") is False
    got = rpc._h_mark(book, {"ids": [a, b]}, "unit", "asker")
    assert got["state"] == "handled"
    assert got["ids"] == [a, b]
    assert _stamped(cn, a, "asker") is True
    assert _stamped(cn, b, "asker") is True


def test_mark_of_an_already_handled_id_stays_idempotent(cn) -> None:
    book = _Book(cn)
    letter = rpc._h_send(
        book, {"src": "other", "dst": "asker", "body": "once"}, "unit", "other"
    )
    mid = int(letter["id"])
    first = rpc._h_mark(book, {"ids": [mid]}, "unit", "asker")
    second = rpc._h_mark(book, {"ids": [mid]}, "unit", "asker")
    assert first["ok"] is True and second["ok"] is True
    assert first["ids"] == [mid] and second["ids"] == [mid]
    assert _stamped(cn, mid, "asker") is True


def test_reply_by_a_room_participant_with_no_mail_to_does_not_error(cn) -> None:
    """A desk on the room, but not a dest of this letter, can reply (#195)."""
    seed_names(cn, ("roomie", "desk"))
    book = _Book(cn)
    root = rpc._h_send(
        book, {"src": "asker", "dst": "other", "body": "root"}, "unit", "asker"
    )
    root_id = int(root["id"])
    joined = rpc._h_reply(book, {"mail_id": root_id, "body": "join roomie"}, "unit", "other")
    rpc._h_add_remove(
        book, {"verb": "add", "type": "mail", "id": int(joined["id"]), "who": "roomie"}, "unit", "other"
    )
    reply = rpc._h_reply(
        book, {"mail_id": root_id, "body": "from the room"}, "unit", "roomie"
    )
    assert int(reply["id"]) > root_id
    assert _stamped(cn, root_id, "roomie") is False


def test_mark_refuses_a_letter_this_desk_was_not_on(cn) -> None:
    book = _Book(cn)
    letter = rpc._h_send(
        book, {"src": "asker", "dst": "other", "body": "not yours"}, "unit", "asker"
    )
    mid = int(letter["id"])
    with pytest.raises(CoordError, match="not in this desk"):
        rpc._h_mark(book, {"ids": [mid]}, "unit", "asker")
    assert _stamped(cn, mid, "asker") is False
    assert _stamped(cn, mid, "other") is False
