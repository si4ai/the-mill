"""F16: hold peek reads the holder and does not take or refresh (#223)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.records import hold
from tests.server.records.conftest import seed_names, take_hold


def _row(cn, resource: str) -> dict | None:
    for rec in hold.select(cn, ""):
        if str(rec.get("resource") or "") == resource:
            return rec
    return None


def test_peek_of_unknown_resource_inserts_nothing(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("f16-none", "desk"))
    before = len(hold.select(cn, ""))
    got = hold.peek(cn, "unit", "f16-missing.res")
    assert got["ok"] is True
    assert got["peek"] is True
    assert got["held"] is False
    assert got["owner"] is None
    assert got["id"] is None
    assert len(hold.select(cn, "")) == before


def test_peek_sees_the_holder_and_does_not_refresh_or_take(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("f16-holder", "desk"), ("f16-other", "desk"))
    taken = hold.upsert(cn, "unit", "f16-holder", "f16-peek.res")
    assert int(taken[0]["ok"]) == 1
    stored = _row(cn, "f16-peek.res")
    assert stored is not None
    seen = hold.peek(cn, "unit", "f16-peek.res")
    assert seen["owner"] == "f16-holder"
    assert seen["held"] is True
    assert seen["id"] == stored["id"]
    assert seen["since"] == stored["updated"]
    other = hold.peek(cn, "unit", "f16-peek.res")
    assert other["owner"] == "f16-holder"
    after = _row(cn, "f16-peek.res")
    assert after is not None
    assert after["desk"] == "f16-holder"
    assert after["updated"] == stored["updated"]
    blocked = hold.upsert(cn, "unit", "f16-other", "f16-peek.res")
    assert int(blocked[0]["ok"]) == 0
    assert _row(cn, "f16-peek.res")["desk"] == "f16-holder"


def test_peek_of_a_freed_row_is_free(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("f16-free", "desk"))
    taken, key = take_hold(cn, "unit", "f16-free", "f16-free.res")
    assert int(taken[0]["ok"]) == 1
    keyless = hold.drop(cn, "unit", "f16-free", "f16-free.res")
    assert keyless["ok"] is False
    still = hold.peek(cn, "unit", "f16-free.res")
    assert still["held"] is True
    assert still["owner"] == "f16-free"
    assert hold.drop(cn, "unit", "f16-free", "f16-free.res", key)["ok"] is True
    seen = hold.peek(cn, "unit", "f16-free.res")
    assert seen["held"] is False
    assert seen["owner"] is None
    assert seen["id"] is not None
