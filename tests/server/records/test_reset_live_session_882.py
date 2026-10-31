"""Card 882 / F216: after reset, a still-running session cannot refresh or take holds.

SPIN gap: reset frees the desk's holds while the session may still believe it
holds them. Stated behaviour: the seat token is cleared, so the next hold
take/refresh/drop is refused with `hold: desk has no live seat` until the desk
joins again. Retire of the desk has the same seat effect.
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
    cn = book
    # Session believed it held h882/lock; reset frees it and clears the token.
    out = rec_join.reset(cn, R, LIVE)
    assert int(out[0]["released"]) == 1
    assert rec_hold.own(cn, LIVE) == []
    # Same desk's next hold (refresh or re-take) is refused: no live seat.
    with pytest.raises(mysql.connector.Error) as ei:
        rec_hold.upsert(cn, R, LIVE, "h882/lock")
        cn.commit()
    cn.rollback()
    assert "no live seat" in str(ei.value).lower()
    # Another live desk can take the freed resource.
    assert int(rec_hold.upsert(cn, R, OTHER, "h882/lock")[0]["ok"]) == 1
    # Free it so a later test's fixture can seat LIVE again on a clean book.
    assert int(rec_hold.delete(cn, int(rec_hold.find(cn, resource="h882/lock")[0]["id"]), OTHER)[0]["ok"]) == 1


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
    assert "no live seat" in str(ei.value).lower()
