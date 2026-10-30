"""pass --done and pass --back need an asker that resolves (#655). Row F99.

Seen in review: the who-may check on pass --done read
`if ask and who and ask != who and vol != who`. When the asker name did not
resolve, `ask` was empty, the check was skipped, and any desk could accept a
shipped card. pass --back had the same shape. Now an asker that does not
resolve refuses both steps for every desk but the volunteer.
"""
from __future__ import annotations

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import todo as rec_todo
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

ASKER, VOL, OTHER = "a655", "v655", "o655"


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _status(cn, need):
    return rec_todo.find(cn, "unit", need)["status"]


def _ask(cn, need):
    return rpc._desk_slug(cn, rec_todo.find(cn, "unit", need), "asker", "creator")


def _shipped(cn, need):
    seed_names(cn, ("unit", "roster"), (ASKER, "desk"), (VOL, "desk"), (OTHER, "desk"))
    book = _Book(cn)
    rpc._h_open(book, {"need": need}, "unit", ASKER)
    rpc._h_claim(book, {"need": need}, "unit", VOL)
    assert rpc._h_pass(book, {"need": need}, "unit", VOL)["status"] == "shipped"
    return book


_NO_NAME = 2**40


def _lose_asker(cn, monkeypatch, need):
    """The card's asker does not resolve: no asker or creator name on the row
    and no creator_id the name table answers for (the shape `_desk_slug`
    returns "" for). #867: cmd_pass reads the asker in SQL, so the row itself
    points at a creator_id with no name (foreign key checks off for the one write)."""
    real = rpc._desk_slug

    def desk_slug(c, hit, *keys):
        if set(keys) & {"asker", "creator"}:
            return ""
        return real(c, hit, *keys)

    monkeypatch.setattr(rpc, "_desk_slug", desk_slug)
    _creator(cn, need, _NO_NAME)


def _creator(cn, need, nid):
    cur = cn.cursor()
    try:
        cur.execute("SET FOREIGN_KEY_CHECKS = 0")
        cur.execute("UPDATE todo SET creator_id = %s WHERE id = %s", (nid, rec_todo.find(cn, "unit", need)["id"]))
        cur.execute("SET FOREIGN_KEY_CHECKS = 1")
        cn.commit()
    finally:
        cur.close()


@pytest.fixture(autouse=True)
def _asker_back(cn):
    """Put every lost asker back, so no row is left pointing at a missing name."""
    yield
    cur = cn.cursor()
    try:
        cur.execute(
            "UPDATE todo SET creator_id = (SELECT id FROM name WHERE type = 'desk' AND name = %s)"
            " WHERE creator_id = %s",
            (ASKER, _NO_NAME),
        )
        cn.commit()
    finally:
        cur.close()


def test_done_by_a_third_desk_is_refused_when_the_asker_is_missing(cn, monkeypatch):
    book = _shipped(cn, "p655-a")
    _lose_asker(cn, monkeypatch, "p655-a")
    assert _ask(cn, "p655-a") == ""
    with pytest.raises(CoordError) as e:
        rpc._h_pass(book, {"need": "p655-a", "step": "done"}, "unit", OTHER)
    assert str(e.value).startswith("who-may: pass shipped->done is the asker")
    assert _status(cn, "p655-a") == "shipped"


def test_back_by_a_third_desk_is_refused_when_the_asker_is_missing(cn, monkeypatch):
    book = _shipped(cn, "p655-b")
    _lose_asker(cn, monkeypatch, "p655-b")
    with pytest.raises(CoordError) as e:
        rpc._h_pass(book, {"need": "p655-b", "step": "back"}, "unit", OTHER)
    assert str(e.value).startswith("who-may: pass --back is the asker or the volunteer")
    assert _status(cn, "p655-b") == "shipped"


def test_the_volunteer_still_finishes_when_the_asker_is_missing(cn, monkeypatch):
    book = _shipped(cn, "p655-c")
    _lose_asker(cn, monkeypatch, "p655-c")
    assert rpc._h_pass(book, {"need": "p655-c", "step": "done"}, "unit", VOL)["status"] == "done"
    assert rpc._h_pass(book, {"need": "p655-c", "step": "back"}, "unit", VOL)["status"] == "shipped"
    assert _status(cn, "p655-c") == "shipped"


def test_a_third_desk_is_still_refused_when_the_asker_resolves(cn):
    book = _shipped(cn, "p655-d")
    assert _ask(cn, "p655-d") == ASKER
    with pytest.raises(CoordError, match="who-may"):
        rpc._h_pass(book, {"need": "p655-d", "step": "done"}, "unit", OTHER)
    with pytest.raises(CoordError, match="who-may"):
        rpc._h_pass(book, {"need": "p655-d", "step": "back"}, "unit", OTHER)
    assert _status(cn, "p655-d") == "shipped"
    assert rpc._h_pass(book, {"need": "p655-d", "step": "done"}, "unit", ASKER)["status"] == "done"


def test_a_row_whose_creator_id_has_no_name_does_not_resolve(cn):
    # The shape the guard now refuses on: no creator name, creator_id unknown.
    assert rpc._desk_slug(cn, {"creator": None, "creator_id": 2**40}, "asker", "creator") == ""
