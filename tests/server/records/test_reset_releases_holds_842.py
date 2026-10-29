"""A reset or retired desk releases its holds (card 842, F135, SPIN H11).

`mill reset` (mill_join_reset) and `mill retire` of a desk (mill_name_delete)
free every hold that desk owns in the same call, stamp each freed hold's
activity row, and say how many they freed. Holds of other desks stay held.
A clock-out (mill_join_delete) keeps the desk's holds: holds do not expire.
"""
from __future__ import annotations

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from agent_coord.server.records.db import rows_done
from tests.server.records.conftest import seed_names
from tests.server.records.conftest import admin_desk

pytestmark = pytest.mark.sql

R = "r842"
GONE = "d842-gone"
DEAD = "d842-dead"
OTHER = "d842-other"
OUT = "d842-out"


@pytest.fixture(scope="module")
def book(cn):
    seed_names(cn, (R, "roster"), (GONE, "desk"), (DEAD, "desk"), (OTHER, "desk"), (OUT, "desk"))
    for d in (GONE, DEAD, OTHER, OUT):
        rec_join.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    for desk, res in (
        (GONE, "h842/a"), (GONE, "h842/b"), (DEAD, "h842/c"), (OTHER, "h842/d"), (OUT, "h842/e"),
    ):
        assert int(rec_hold.upsert(cn, R, desk, res)[0]["ok"]) == 1
    return cn


def _holder(cn, res: str) -> str | None:
    rows = rec_hold.find(cn, resource=res)
    assert len(rows) == 1, rows
    return rows[0].get("desk") or None


def _activity_act(cn, res: str) -> str:
    return rows_done(
        cn,
        "SELECT a.act FROM hold h JOIN name r ON r.id = h.resource_id"
        " JOIN activity a ON a.type = 'hold' AND a.id = h.id WHERE r.name = %s",
        (res,),
    )[0]["act"]


def test_reset_frees_the_desks_holds_only(book) -> None:
    cn = book
    act_a = _activity_act(cn, "h842/a")
    out = rec_join.reset(cn, R, GONE)
    assert _holder(cn, "h842/a") is None
    assert _holder(cn, "h842/b") is None
    assert int(out[0]["released"]) == 2
    assert _activity_act(cn, "h842/a") == "drop"
    assert _holder(cn, "h842/d") == OTHER
    assert rec_hold.own(cn, GONE) == []
    # The freed resource can be taken by another desk.
    assert int(rec_hold.upsert(cn, R, OTHER, "h842/a")[0]["ok"]) == 1


def test_retire_frees_the_desks_holds(book) -> None:
    cn = book
    out = rec_name.retire(cn, DEAD, "desk", by=admin_desk(cn))
    assert _holder(cn, "h842/c") is None
    assert int(out[0]["released"]) == 1
    assert _holder(cn, "h842/d") == OTHER


def test_clock_out_keeps_holds(book) -> None:
    cn = book
    rec_join.delete(cn, R, OUT)
    assert _holder(cn, "h842/e") == OUT


def test_reset_with_no_holds_frees_none(book) -> None:
    out = rec_join.reset(book, R, GONE)
    assert int(out[0].get("released", -1)) == 0
