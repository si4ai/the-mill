"""A mail-thread read that prints letters whole marks them handled (card 843).

Unread is one state: mail_to.opened is NULL for this desk. `mark` and `reply`
set it; before this card a read never did, so a desk that read a room still
saw every letter in its inbox and kept being re-woken (2,070 such rows on the
cloud office). Now a branch read, `--full`, `--subtree` and `--after` mark the
letters they print for the reading desk, through the same path as `mark`.
A short-row `--room` read and a room summary print previews, so they do not.

Regression row F129 (thread-read-marks).
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import opened
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _open(cn, mid: int, desk: str) -> bool:
    return int(mid) in opened.read_ids(cn, [mid], desk)


def _unread(book, desk: str) -> set[int]:
    return {int(r["id"]) for r in rpc._h_inbox(book, {"dst": desk, "limit": 100}, "unit", desk)}


@pytest.fixture
def book(cn):
    seed_names(cn, ("unit", "roster"), ("a", "desk"), ("b", "desk"), ("c", "desk"))
    return _Book(cn)


def _room(book, name):
    root = int(rpc._h_send(book, {"project": "unit", "src": "a", "dst": "b,c", "body": "root",
                                  "name": name}, "unit", "a")["id"])
    r1 = int(rpc._h_reply(book, {"mail_id": root, "body": "one", "src": "a"}, "unit", "a")["id"])
    r2 = int(rpc._h_reply(book, {"mail_id": r1, "body": "two", "src": "c"}, "unit", "c")["id"])
    return root, r1, r2


def test_branch_read_marks_and_inbox_drops_it(cn, book) -> None:
    mid = int(rpc._h_send(book, {"src": "a", "dst": "b", "body": "hello"}, "unit", "a")["id"])
    assert mid in _unread(book, "b")
    out = rpc._h_mail_thread(book, {"mail_id": mid}, "unit", "b")
    assert out["marked"] == [mid]
    assert _open(cn, mid, "b") and mid not in _unread(book, "b")
    again = rpc._h_mail_thread(book, {"mail_id": mid, "scope": "full"}, "unit", "b")
    assert again["marked"] == []


def test_subtree_marks_every_letter_it_prints_for_the_reader_only(cn, book) -> None:
    root, r1, r2 = _room(book, "c843-subtree")
    out = rpc._h_mail_thread(book, {"mail_id": root, "scope": "subtree"}, "unit", "b")
    assert out["marked"] == [root, r1, r2]
    assert not ({root, r1, r2} & _unread(book, "b"))
    assert _open(cn, root, "c") is False  # c's own rows stay unread


def test_room_previews_and_summary_do_not_mark_but_after_does(cn, book) -> None:
    root, r1, r2 = _room(book, "c843-room")
    assert rpc._h_mail_thread(book, {"mail_id": root, "scope": "room"}, "unit", "b")["marked"] == []
    assert rpc._h_mail_thread(book, {"tree": "c843-room"}, "unit", "b")["marked"] == []
    assert {root, r1, r2} <= _unread(book, "b")
    out = rpc._h_mail_thread(book, {"mail_id": root, "after": root}, "unit", "b")
    assert out["marked"] == [r1, r2]
    assert root in _unread(book, "b") and not ({r1, r2} & _unread(book, "b"))


def test_a_reader_off_the_letter_marks_nothing(cn, book) -> None:
    mid = int(rpc._h_send(book, {"src": "a", "dst": "b", "body": "private-ish"}, "unit", "a")["id"])
    out = rpc._h_mail_thread(book, {"mail_id": mid}, "unit", "c")
    assert out["marked"] == []
    assert mid in _unread(book, "b")
