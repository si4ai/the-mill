"""Card 882 / F216: after reset, a still-running session cannot keep the lock.

SPIN gap: reset frees the desk's holds while the session may still believe it
holds them. Stated behaviour: after reset the seat token is cleared, so the
session's next command is refused at the door with
`invalid or expired Bearer; mill connect DESK to rejoin`. The SQL message
`hold: desk has no live seat` is only the F186 backstop for a request that
already passed auth. A drop of the freed hold returns released false
(`not held by you`). After retire the desk name is gone, so the next hold is
refused (`name retired`); either way a live session cannot keep writing the
resource.
"""
from __future__ import annotations

import pytest
import mysql.connector

from agent_coord.client.tokens import token_hash
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import join as rec_join
from agent_coord.server.records import name as rec_name
from tests.server.records.conftest import admin_desk, seed_names

pytestmark = pytest.mark.sql

R = "r882"
LIVE = "d882-live"
OTHER = "d882-other"


@pytest.fixture()
def book(cn):
    seed_names(cn, (R, "roster"), (LIVE, "desk"), (OTHER, "desk"))
    for d in (LIVE, OTHER):
        rec_join.upsert(cn, R, d, "builder", token_hash=token_hash("tok-" + d), doing="present")
    assert int(rec_hold.upsert(cn, R, LIVE, "h882/lock")[0]["ok"]) == 1
    return cn


def test_after_reset_hold_refresh_and_take_are_refused(book) -> None:
    """F186 SP backstop: a hold after reset (past auth) is refused with no live seat."""
    cn = book
    out = rec_join.reset(cn, R, LIVE)
    assert int(out[0]["released"]) == 1
    assert rec_hold.own(cn, LIVE) == []
    with pytest.raises(mysql.connector.Error) as ei:
        rec_hold.upsert(cn, R, LIVE, "h882/lock")
        cn.commit()
    cn.rollback()
    assert "no live seat" in str(ei.value).lower()
    # Another live desk can take the freed resource.
    assert int(rec_hold.upsert(cn, R, OTHER, "h882/lock")[0]["ok"]) == 1
    assert rec_hold.drop(cn, R, OTHER, "h882/lock").get("released") is True


def test_after_reset_drop_of_freed_hold_is_released_false(book) -> None:
    """Drop of a hold freed by reset answers released false, not no live seat."""
    cn = book
    assert int(rec_join.reset(cn, R, LIVE)[0]["released"]) == 1
    out = rec_hold.drop(cn, R, LIVE, "h882/lock")
    assert out.get("released") is False
    assert out.get("reason") == "not held by you"
    # If another desk took it, drop by the reset desk still says released false.
    assert int(rec_hold.upsert(cn, R, OTHER, "h882/lock")[0]["ok"]) == 1
    out2 = rec_hold.drop(cn, R, LIVE, "h882/lock")
    assert out2.get("released") is False
    assert "not you" in str(out2.get("reason") or "").lower()
    assert rec_hold.drop(cn, R, OTHER, "h882/lock").get("released") is True


def test_after_retire_hold_is_refused(cn) -> None:
    # Own setup: do not reuse the reset desk from the other test (token cleared).
    seed_names(cn, (R, "roster"), ("d882-ret", "desk"))
    desk = "d882-ret"
    rec_join.upsert(cn, R, desk, "builder", token_hash=token_hash("tok-ret"), doing="present")
    assert int(rec_hold.upsert(cn, R, desk, "h882/ret")[0]["ok"]) == 1
    rec_name.retire(cn, desk, "desk", by=admin_desk(cn))
    with pytest.raises(mysql.connector.Error) as ei:
        rec_hold.upsert(cn, R, desk, "h882/ret")
        cn.commit()
    cn.rollback()
    # Retire deletes the desk name; the next hold is refused (name retired).
    msg = str(ei.value).lower()
    assert "no live seat" in msg or "name retired" in msg, msg
