# -*- coding: utf-8 -*-
"""Card 1140: the wake lease is recorded in the book (Auditor 5532 changes A-C).

On a real book: the ring records ring -> lease_live on the wake that rang it,
wake-done records lease_live -> done once (a second one records nothing and
says already_done), an older token says stale and ends nothing, the wake row
stays taken after take and is never handed out again, a lease that lapsed is
recorded expired at the next ring, and renewal stops at the cap.
"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from agent_coord.server import push, wake, wake_lease
from agent_coord.server.records import push as rec_push
from tests.server.test_desk_webhook_618 import _Resp
from tests.server.webhook_fixtures import arm

pytestmark = pytest.mark.sql


@pytest.fixture
def hook(cn, monkeypatch, request):
    from tests.server.records.conftest import admin_desk

    arm(monkeypatch)
    monkeypatch.setattr(wake, "_EPOCH", {}, raising=False)
    monkeypatch.setattr(wake, "_NOTE", {}, raising=False)
    monkeypatch.setattr(push.HUB, "rooms", {})
    bodies: list[dict] = []

    def receive(req, timeout=0):
        import json

        bodies.append(json.loads(req.data.decode("utf-8")))
        return _Resp()

    with patch("agent_coord.server.wake._open", receive):
        # One desk per test: the book keeps each test's leases.
        name = "l1140-" + request.node.name[5:30].replace("_", "-")
        yield {"cn": cn, "desk": admin_desk(cn, name), "posts": bodies}


def _ring(h, n: int) -> tuple[int, str]:
    """Queue one hint row as a real miss and ring for it: (wake id, outcome)."""
    cn, desk = h["cn"], h["desk"]
    frame = {"kind": "hint", "type": "todo", "id": n}
    wid = rec_push.row_id(rec_push.put(cn, desk, "hint", frame, "missed"))
    got = wake.post_desk(cn, desk, frame, hint_id=n, wake_id=wid)
    cn.commit()
    return wid, got


def _rows(cn, token: str) -> list[tuple[int, str, str, str]]:
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT activity_id, from_state, to_state, reason FROM transition"
            " WHERE join_key = %s ORDER BY id",
            (wake_lease.join_key(token),),
        )
        return [(int(a), str(b), str(c), str(d)) for a, b, c, d in cur.fetchall() or []]
    finally:
        cur.close()


def _state(cn, wid: int) -> str:
    cur = cn.cursor()
    try:
        cur.execute("SELECT state FROM wake WHERE id = %s", (wid,))
        return str((cur.fetchone() or [""])[0])
    finally:
        cur.close()


def _token(h) -> str:
    return str(h["posts"][-1]["wake"]["lease"])


def _lapse(desk: str) -> None:
    with wake._GATE_LOCK:
        wake._GATE[desk] -= wake.cap_s() + 1
        wake._UNTIL.pop(desk, None)


def test_one_wake_records_ring_and_done_and_row_stays_taken(hook) -> None:
    cn, desk = hook["cn"], hook["desk"]
    wid, got = _ring(hook, 114001)
    assert got == "sent"
    token = _token(hook)
    assert _rows(cn, token) == [(wid, "ring", "lease_live", "wake_sent")]
    taken = rec_push.take(cn, desk)
    cn.commit()
    assert [int(r["id"]) for r in taken] == [114001]
    assert _state(cn, wid) == "taken"
    assert wake.lease_done(cn, desk, lease=token) == "none"
    cn.commit()
    assert _rows(cn, token) == [
        (wid, "ring", "lease_live", "wake_sent"),
        (wid, "lease_live", "done", "wake_done"),
    ]
    # The row stays taken: a finished wake is never handed out again (I3/I4).
    assert _state(cn, wid) == "taken"
    assert rec_push.take(cn, desk) == []
    # Ring-to-done time is the ring row's at to the done row's at.
    cur = cn.cursor()
    cur.execute(
        "SELECT TIMESTAMPDIFF(MICROSECOND, MIN(at), MAX(at)) FROM transition WHERE join_key = %s",
        (wake_lease.join_key(token),),
    )
    assert int(cur.fetchone()[0]) >= 0
    cur.close()


def test_second_wake_done_is_already_done_and_records_nothing(hook) -> None:
    cn, desk = hook["cn"], hook["desk"]
    _ring(hook, 114002)
    token = _token(hook)
    assert wake.lease_done(cn, desk, lease=token) == "none"
    cn.commit()
    before = _rows(cn, token)
    assert wake.lease_done(cn, desk, lease=token) == "already_done"
    # The automatic wake-done (no token) ended it first: the run's own done is not stale.
    assert wake.lease_done(cn, desk, lease="") == "already_done"
    cn.commit()
    assert _rows(cn, token) == before


def test_older_token_is_stale_and_ends_nothing(hook) -> None:
    cn, desk = hook["cn"], hook["desk"]
    _ring(hook, 114003)
    old = _token(hook)
    _lapse(desk)
    _ring(hook, 114004)
    new = _token(hook)
    assert new != old
    # The lapsed lease is recorded expired at the next ring; the new one is live.
    assert [r[2] for r in _rows(cn, old)] == ["lease_live", "expired"]
    assert wake.lease_done(cn, desk, lease=old, note="late") == "stale"
    cn.commit()
    assert [r[2] for r in _rows(cn, new)] == ["lease_live"]
    with wake._GATE_LOCK:
        assert wake._EPOCH[desk] == new


def test_done_after_expiry_sends_no_post(hook) -> None:
    cn, desk = hook["cn"], hook["desk"]
    _ring(hook, 114005)
    token = _token(hook)
    _lapse(desk)
    n = len(hook["posts"])
    assert wake.lease_done(cn, desk, lease=token) == "already_done"
    assert len(hook["posts"]) == n


def test_row_rung_under_expired_lease_and_never_taken_comes_back(hook) -> None:
    cn, desk = hook["cn"], hook["desk"]
    wid, _ = _ring(hook, 114006)
    _lapse(desk)
    assert _state(cn, wid) == "missed"
    assert 114006 in [int(r["id"]) for r in rec_push.take(cn, desk)]
    cn.commit()
    assert _state(cn, wid) == "taken"


def test_two_racing_takes_leave_one_live_lease(hook) -> None:
    cn, desk = hook["cn"], hook["desk"]
    frame = {"kind": "hint", "type": "todo", "id": 114007}
    tokens: list[str] = []
    gate = threading.Barrier(8)

    def take():
        gate.wait()
        got = wake._hold_or_take(desk, frame, 114007, wake.ADDRESSED, None, take=True)
        if got:
            tokens.append(got)

    threads = [threading.Thread(target=take) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(tokens) == 1
    wid = rec_push.row_id(rec_push.put(cn, desk, "hint", frame, "missed"))
    wake._record_ring(cn, desk, tokens[0], wid)
    cn.commit()
    assert wake_lease.live_in_book(cn, desk, wake.lease_s())[0] == tokens[0]


def test_renewal_needs_the_live_token_and_stops_at_the_cap(hook) -> None:
    import time

    cn, desk = hook["cn"], hook["desk"]
    _ring(hook, 114008)
    old = _token(hook)
    _lapse(desk)
    _ring(hook, 114009)
    token = _token(hook)
    assert wake.lease_renew(cn, desk, old) == "refused"
    assert wake.lease_renew(cn, desk, token) == "renewed"
    with wake._GATE_LOCK:
        at = wake._GATE[desk]
        # Pretend the run has worked for almost the whole cap, renewing all along.
        wake._GATE[desk] = at - (wake.cap_s() - 10)
        wake._UNTIL[desk] = time.monotonic() + 5
    assert wake.lease_renew(cn, desk, token) == "renewed"
    with wake._GATE_LOCK:
        assert wake._UNTIL[desk] <= wake._GATE[desk] + wake.cap_s()
        wake._GATE[desk] -= 20  # past the cap
        wake._UNTIL[desk] = wake._GATE[desk] + wake.cap_s()
    assert wake.lease_renew(cn, desk, token) == "refused"


def test_live_lease_survives_a_wall_restart(hook) -> None:
    cn, desk = hook["cn"], hook["desk"]
    _ring(hook, 114010)
    token = _token(hook)
    n = len(hook["posts"])
    with wake._GATE_LOCK:  # a restart: wall memory is empty, the book is not
        wake._GATE.clear()
        wake._EPOCH.clear()
    _, got = _ring(hook, 114011)
    assert got == "coalesced"
    assert len(hook["posts"]) == n
    # The run's own done ends the adopted lease; the item it held rings once.
    assert wake.lease_done(cn, desk, lease=token) == "sent"
    cn.commit()
    assert [r[2] for r in _rows(cn, token)] == ["lease_live", "done"]
    assert len(hook["posts"]) == n + 1


def test_migrate_adds_the_lease_edges_once(cn):
    """Existing books get the 1140 edges from migrate; a second run adds nothing."""
    from agent_coord.install import migrate

    edges = (
        ("ring", "lease_live", "wake_sent"),
        ("lease_live", "done", "wake_done"),
        ("lease_live", "expired", "wake_expire"),
        ("lease_live", "cleared", "clear"),
    )
    cur = cn.cursor()
    try:
        cur.execute(
            "DELETE FROM transition_edge WHERE activity_type='wake' AND ("
            " (from_state, to_state, reason) IN "
            " (('ring','lease_live','wake_sent'),"
            "  ('lease_live','done','wake_done'),"
            "  ('lease_live','expired','wake_expire'),"
            "  ('lease_live','cleared','clear')))"
        )
        cn.commit()
    finally:
        cur.close()
    assert migrate._ensure_wake_lease_edges(cn) == ["transition_edge.wake_lease_1140"]
    assert migrate._ensure_wake_lease_edges(cn) == []
    cur = cn.cursor()
    try:
        cur.execute(
            "SELECT from_state, to_state, reason FROM transition_edge"
            " WHERE activity_type='wake' AND (from_state, to_state, reason) IN "
            " (('ring','lease_live','wake_sent'),"
            "  ('lease_live','done','wake_done'),"
            "  ('lease_live','expired','wake_expire'),"
            "  ('lease_live','cleared','clear'))"
        )
        got = {tuple(r) for r in cur.fetchall()}
    finally:
        cur.close()
    assert got == set(edges)
