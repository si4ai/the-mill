"""Card 853 / F214: a re-hold by the holder reports refreshed true and keeps since.

A first hold prints refreshed false and a since. A second hold of the same
resource by the same desk prints refreshed true and the same since (the take
time), so two wake runs can dedupe on the flag. #194 still bumps hold.updated.
"""
from __future__ import annotations

import pytest

from agent_coord.client.tokens import token_hash
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import hold as rec_hold
from agent_coord.server.records import join as rec_join
from tests.server.records.conftest import seed_names

pytestmark = pytest.mark.sql

R = "r853"
ME = "d853-me"


@pytest.fixture()
def book(cn):
    seed_names(cn, (R, "roster"), (ME, "desk"))
    rec_join.upsert(cn, R, ME, "builder", token_hash=token_hash("tok-853"), doing="present")
    return cn


class _B:
    def __init__(self, cn):
        self._cn = cn


def test_rehold_reports_refreshed_and_keeps_since(book, monkeypatch):
    monkeypatch.setattr(rpc, "_poke", lambda *a, **k: None)
    c = _B(book)
    first = rpc._h_hold(c, {"resource": "h853/lock"}, R, ME)
    assert first["ok"] is True and first["held"] is True
    assert first.get("refreshed") is False, first
    since = first.get("since")
    assert since, first
    second = rpc._h_hold(c, {"resource": "h853/lock"}, R, ME)
    assert second["ok"] is True and second["held"] is True
    assert second.get("refreshed") is True, second
    assert second.get("since") == since, (since, second.get("since"))
    assert int(second["id"]) == int(first["id"])
    # #194 still bumps the row's updated clock.
    rows = rec_hold.find(book, resource="h853/lock")
    assert rows and str(rows[0]["updated"])[:19] >= str(since)[:19]
