"""hold --peek with no resource lists held locks and refuses an unknown project (#234, #254)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import hold as rec_hold
from tests.server.records.conftest import take_hold, seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def _count(cn) -> int:
    cur = cn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM hold")
        return int(cur.fetchone()[0])
    finally:
        cur.close()


def test_unknown_project_and_no_holds_and_one_lock(cn) -> None:
    seed_names(cn, ("c234", "roster"), ("c234-desk", "desk"))
    book = _Book(cn)
    before = _count(cn)
    with pytest.raises(CoordError, match="c234-missing"):
        rpc._h_hold(book, {"peek": True}, "c234-missing", "c234-desk")
    assert _count(cn) == before

    empty = rpc._h_hold(book, {"peek": True}, "c234", "c234-desk")
    assert empty["ok"] is True
    assert empty["holds"] == []
    assert _count(cn) == before

    taken, key = take_hold(cn, "c234", "c234-desk", "c234-lock")
    assert int(taken[0]["ok"]) == 1
    listed = rpc._h_hold(book, {"peek": True}, "c234", "c234-desk")
    assert _count(cn) == before + 1
    assert len(listed["holds"]) == 1
    assert listed["holds"][0]["resource"] == "c234-lock"
    assert listed["holds"][0]["owner"] == "c234-desk"

    rec_hold.drop(cn, "c234", "c234-desk", "c234-lock", key)
    again = rpc._h_hold(book, {"peek": True}, "c234", "c234-desk")
    assert again["holds"] == []
    assert _count(cn) == before + 1
