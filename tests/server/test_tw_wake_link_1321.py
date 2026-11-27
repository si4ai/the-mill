# -*- coding: utf-8 -*-
"""Card 1321: the tw.event start stores the lease and wake of the wake that started the run (no SQL)."""
from __future__ import annotations

import pytest

from agent_coord.server.api.mill import rpc


class _Book:
    _cn = object()


class _Stored(list):
    renews: list


@pytest.fixture
def stored(monkeypatch):
    got = _Stored()
    rings = {"abc123def456": {"wake_id": 77, "desk_id": 5, "at": None, "end": None},
             "ended0000001": {"wake_id": 78, "desk_id": 5, "at": None, "end": "done"},
             "otherdesk001": {"wake_id": 99, "desk_id": 6, "at": None, "end": None}}
    monkeypatch.setattr("agent_coord.server.records.doing.task_event",
                        lambda cn, desk, meta, **kw: got.append(dict(meta)))
    monkeypatch.setattr("agent_coord.server.records.db.request_tx", lambda cn, run: run())
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **kw: None)
    monkeypatch.setattr("agent_coord.server.wake_lease.ring_row", lambda cn, token: rings.get(token))
    monkeypatch.setattr("agent_coord.server.mail_activity.desk_id_for", lambda cn, desk: 5)
    renews = []
    monkeypatch.setattr("agent_coord.server.wake.lease_renew", lambda *a: renews.append(a) or "renewed")
    got.renews = renews
    return got


def _send(kind, **extra):
    body = {"verb": "tw.event", "watch_id": "w1", "kind": kind, **extra}
    return rpc._h_tw_event(_Book(), body, "the-mill", "builder")


def test_woken_start_stores_the_lease_and_its_wake(stored):
    out = _send("start", wake_lease="abc123def456")
    assert out["ok"] is True
    assert stored[-1]["lease"] == "abc123def456"
    assert stored[-1]["wake_id"] == 77
    assert "dropped" not in stored[-1]
    assert "wake_lease" not in stored[-1]


def test_manual_start_stores_neither(stored):
    _send("start", card=1321)
    assert not {"lease", "wake_id", "dropped"} & set(stored[-1])


def test_a_lease_the_book_has_not_rung_keeps_the_token_only(stored):
    # The ring write is instrumentation and may be missing: the token is still the link.
    _send("start", wake_lease="notrung00001")
    assert stored[-1]["lease"] == "notrung00001"
    assert "wake_id" not in stored[-1]


def test_a_lease_that_ended_after_the_start_still_names_its_wake(stored):
    # A queued start can reach the office after wake-done; the run was still started by that wake.
    _send("start", wake_lease="ended0000001")
    assert (stored[-1]["lease"], stored[-1]["wake_id"]) == ("ended0000001", 78)


@pytest.mark.parametrize("bad", ["otherdesk001", "a b", "x" * 65, 12, True, ""])
def test_a_bad_or_foreign_lease_is_dropped_and_the_start_still_stored(stored, bad):
    out = _send("start", card=1321, wake_lease=bad)
    assert out["ok"] is True
    meta = stored[-1]
    assert not {"lease", "wake_id"} & set(meta)
    assert meta["card"] == 1321
    assert meta["dropped"] == ["wake_lease"]


@pytest.mark.parametrize("kind,extra", [("exit", {"exit_code": 0}), ("crash", {}), ("stall", {"cause": "quiet"})])
def test_other_hops_never_store_a_lease(stored, kind, extra):
    _send(kind, wake_lease="abc123def456", **extra)
    assert not {"lease", "wake_id", "dropped"} & set(stored[-1])


def test_the_start_link_does_not_renew_the_lease(stored):
    # wake_lease is a record on the run; renewal stays with the lease key on desk commands (card 1140).
    rpc._renew_lease(_Book(), "builder", "tw.event", {"verb": "tw.event", "wake_lease": "abc123def456"})
    assert stored.renews == []
