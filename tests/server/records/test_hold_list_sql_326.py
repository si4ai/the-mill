"""Bare hold lists every lock; a peek at a roster name hints, on a real book (#326)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.sql

from agent_coord.server.api.mill import rpc
from tests.server.records.conftest import seed_names


class _Book:
    def __init__(self, cn):
        self._cn = cn


def test_bare_hold_lists_and_roster_peek_hints(cn) -> None:
    seed_names(cn, ("unit", "roster"), ("c326-test", "roster"), ("c326-w3", "desk"))
    book = _Book(cn)
    took = rpc._h_hold(book, {"kh": "0" * 64, "resource": "c326-deploy"}, "unit", "c326-w3")
    assert took["held"] is True

    listed = rpc._h_hold(book, {}, "unit", "c326-w3")
    assert "c326-deploy" in [h["resource"] for h in listed["holds"]]

    peek = rpc._h_hold(book, {"peek": True, "resource": "c326-test"}, "unit", "c326-w3")
    assert peek["held"] is False
    assert "no hold named c326-test (c326-test is a roster)" in peek["hint"]

    held = rpc._h_hold(book, {"peek": True, "resource": "c326-deploy"}, "unit", "c326-w3")
    assert held["owner"] == "c326-w3" and "hint" not in held
