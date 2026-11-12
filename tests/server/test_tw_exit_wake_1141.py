# -*- coding: utf-8 -*-
"""Card 1141: a tw exit or crash hop is the desk's own run ending.

Step 1: it rings a webhook wake only when something waits for the desk (push
row, unread letter, unopened receipt), like every other wake. stall and match
stay mid-run alerts and ring on an empty queue. Invariants F1, F7, I1, I2, I3/I4.

Step 2 (F7 residual, V14/V15): pending() excludes rows already handed over
live (state sent), so a tw exit or wake-done trailing POST does not ring for
work the desk already has. Tests that pin this use a real sent row, not the
pending() stub in the desk fixture. The empty skip is re-checked under the
gate lock (V16/V17).
"""
from __future__ import annotations

import threading
import time

import pytest

from agent_coord.server import mail_push, push, wake


@pytest.fixture
def desk(monkeypatch):
    """One armed desk with a stubbed queue; POSTs are recorded, never sent."""
    from agent_coord.server.records import join as rec_join

    name = "tw-exit-1141"
    state = {"pending": 0, "unread": [], "receipt": False}
    posts: list[dict] = []
    lines: list[str] = []
    monkeypatch.setattr(push, "_bc_log", lines.append)
    monkeypatch.setattr(rec_join, "wake_target", lambda cn, d: ("https://hooks.example.test/x", "k"))
    monkeypatch.setattr(rec_join, "wake_state", lambda cn, d: {"armed": True, "wake_on": "addressed"})
    monkeypatch.setattr("agent_coord.server.records.push.pending", lambda cn, d: state["pending"])
    monkeypatch.setattr("agent_coord.server.records.push.pending_addressed", lambda cn, d: state["pending"] > 0)
    monkeypatch.setattr(push, "unread_mail_frames", lambda cn, d, limit=20: list(state["unread"]))
    monkeypatch.setattr(mail_push, "has_unopened_receipt", lambda cn, d: state["receipt"])
    monkeypatch.setattr(wake, "mail_picked_up", lambda cn, d, mid: False)
    monkeypatch.setattr(wake, "check_url", lambda u: (u, "hooks.example.test"))
    monkeypatch.setattr(wake, "public_host", lambda h: True)
    monkeypatch.setattr(wake, "desk_roster", lambda cn, d: "")
    monkeypatch.setattr(wake, "_schedule", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.wasted_wake.mark_lease", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.wasted_wake.finish_lease", lambda *a, **k: None)

    def fake_post(url, body, **kw):
        posts.append(dict(body))
        return 200, None

    monkeypatch.setattr(wake, "_post_status", fake_post)
    wake.gate_clear(name)
    yield name, state, posts, lines
    wake.gate_clear(name)


def _tw(kind: str, **extra) -> dict:
    return {"watch_id": "w1", "desk": "tw-exit-1141", "kind": kind, **extra}


@pytest.mark.parametrize("kind,extra", [("exit", {"exit_code": 0}), ("exit", {"exit_code": 3}), ("crash", {})])
def test_exit_with_nothing_pending_rings_no_wake_and_takes_no_lease(desk, kind, extra) -> None:
    """F1/F7: the run's own tw exit, nothing waiting: no POST, no lease."""
    name, _, posts, lines = desk
    assert wake.post_desk(object(), name, _tw(kind, **extra)) == "skipped"
    assert posts == []
    assert any("skipped reason=empty" in ln for ln in lines)
    assert wake._gate_open(name, time.monotonic())


@pytest.mark.parametrize("waiting", ["pending", "unread", "receipt"])
def test_exit_while_something_waits_still_rings(desk, waiting) -> None:
    """I3/I4: an exit hop never hides waiting work; it rings like any wake."""
    name, state, posts, _ = desk
    if waiting == "pending":
        state["pending"] = 1
    elif waiting == "unread":
        state["unread"] = [{"kind": "mail", "id": 77}]
    else:
        state["receipt"] = True
    assert wake.post_desk(object(), name, _tw("exit", exit_code=0)) == "sent"
    assert len(posts) == 1


@pytest.mark.parametrize("kind", ["stall", "match"])
def test_stall_and_match_still_ring_on_empty_queue(desk, kind) -> None:
    """Card 970 alert path kept: a mid-run stall or match rings on its own."""
    name, _, posts, _ = desk
    assert wake.post_desk(object(), name, _tw(kind, cause="quiet")) == "sent"
    assert len(posts) == 1


def test_twenty_short_tw_runs_ring_nothing(desk) -> None:
    """The live finding: one exit per tw command, about 20 in 23 minutes, all empty."""
    name, _, posts, _ = desk
    for n in range(20):
        frame = {"watch_id": f"w{n}", "desk": name, "kind": "exit", "exit_code": 0}
        assert wake.post_desk(object(), name, frame) == "skipped"
    assert posts == []


def test_exit_racing_a_letter_wake_posts_once(desk) -> None:
    """I1 under concurrency: exit hops and a letter wake race on a free desk with
    one item waiting; exactly one POST goes out and the rest coalesce."""
    name, state, posts, _ = desk
    state["pending"] = 1
    barrier = threading.Barrier(9)
    got: list[str] = []
    lock = threading.Lock()

    def run(frame):
        barrier.wait()
        out = wake.post_desk(object(), name, frame)
        with lock:
            got.append(out)

    frames = [{"kind": "mail", "id": 501}] + [_tw("exit", exit_code=0) | {"watch_id": f"w{n}"} for n in range(8)]
    threads = [threading.Thread(target=run, args=(f,)) for f in frames]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(posts) == 1
    assert sorted(got) == ["coalesced"] * 8 + ["sent"]


def test_old_done_after_expiry_does_not_end_exit_lease(desk, monkeypatch) -> None:
    """I2 with lease expiry during the run: an exit-triggered wake takes a new
    lease after the first one lapsed; the first run's late wake-done is stale."""
    name, state, posts, _ = desk
    monkeypatch.setattr(wake, "lease_s", lambda: 0.05)
    state["pending"] = 1
    assert wake.post_desk(object(), name, {"kind": "mail", "id": 1}) == "sent"
    first = posts[-1].get("wake", {}).get("lease") or wake._EPOCH.get(name)
    time.sleep(0.08)  # lease 1 lapses while its run is still working
    assert wake.post_desk(object(), name, _tw("exit", exit_code=0)) == "sent"
    second = wake._EPOCH.get(name)
    assert second and second != first
    monkeypatch.setattr(wake, "lease_s", lambda: 900.0)
    assert wake.lease_done(None, name, lease=first) == "stale"
    assert wake._EPOCH.get(name) == second
    assert wake.post_desk(object(), name, _tw("exit", exit_code=0)) == "coalesced"
    assert len(posts) == 2

# --- Card 1141 step 2 (F7 / V14 / V15 / V16 / V17): real sent rows, no pending() stub. ---


def _sql_desk(cn, name: str) -> str:
    from tests.server.records.conftest import admin_desk

    return admin_desk(cn, name)


def _arm_http(monkeypatch, posts: list, lines: list) -> None:
    """Stub only the HTTP side. pending() and the book stay real."""
    from agent_coord.server.records import join as rec_join

    monkeypatch.setattr(push, "_bc_log", lines.append)
    monkeypatch.setattr(rec_join, "wake_target", lambda cn, d: ("https://hooks.example.test/x", "k"))
    monkeypatch.setattr(rec_join, "wake_state", lambda cn, d: {"armed": True, "wake_on": "addressed"})
    monkeypatch.setattr(wake, "check_url", lambda u: (u, "hooks.example.test"))
    monkeypatch.setattr(wake, "public_host", lambda h: True)
    monkeypatch.setattr(wake, "desk_roster", lambda cn, d: "")
    monkeypatch.setattr(wake, "_schedule", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.wasted_wake.mark_lease", lambda *a, **k: None)
    monkeypatch.setattr("agent_coord.server.wasted_wake.finish_lease", lambda *a, **k: None)
    monkeypatch.setattr(wake, "_post_status", lambda url, body, **kw: posts.append(dict(body)) or (200, None))


def _put_missed(cn, desk: str, item_id: int) -> int:
    from agent_coord.server.records import push as rec_push

    rows = rec_push.put(cn, desk, "hint", {"type": "todo", "id": item_id}, "missed")
    cn.commit()
    return int(rows[0]["id"])


def _mark_sent(cn, wid: int) -> None:
    from agent_coord.server.records import push as rec_push

    assert rec_push.mark(cn, wid, "sent") == 1
    cn.commit()


def _second_cn():
    """A second connection to the shared tip book (not the test's cn)."""
    import mysql.connector
    from tests import sql_book
    from agent_coord.server.records.db import conn_kwargs

    kw = dict(conn_kwargs())
    kw["database"] = sql_book.shared_db_name()
    return mysql.connector.connect(**kw)


@pytest.mark.sql
def test_pending_excludes_a_real_sent_row(cn) -> None:
    """V14/V15 root: a row handed over live is not waiting work."""
    from agent_coord.server.records import push as rec_push

    desk = _sql_desk(cn, "s2-pend-1141")
    assert rec_push.pending(cn, desk) == 0
    wid = _put_missed(cn, desk, 114101)
    assert rec_push.pending(cn, desk) == 1
    _mark_sent(cn, wid)
    assert rec_push.pending(cn, desk) == 0
    _put_missed(cn, desk, 114102)
    assert rec_push.pending(cn, desk) == 1


@pytest.mark.sql
def test_exit_after_a_real_sent_row_rings_no_wake(cn, monkeypatch) -> None:
    """V14: a tw exit after a live item does not ring for work the desk already has."""
    from agent_coord.server.records import push as rec_push

    desk = _sql_desk(cn, "s2-exit-1141")
    posts: list[dict] = []
    lines: list[str] = []
    _arm_http(monkeypatch, posts, lines)
    wake.gate_clear(desk)
    try:
        wid = _put_missed(cn, desk, 114111)
        _mark_sent(cn, wid)
        assert rec_push.pending(cn, desk) == 0
        frame = {"watch_id": "w-sent", "desk": desk, "kind": "exit", "exit_code": 0}
        assert wake.post_desk(cn, desk, frame) == "skipped"
        assert posts == []
        assert any("skipped reason=empty" in ln for ln in lines)
        assert wake._gate_open(desk, time.monotonic())
    finally:
        wake.gate_clear(desk)


@pytest.mark.sql
def test_trailing_after_a_real_sent_row_sends_no_wake(cn, monkeypatch) -> None:
    """V15: wake-done's trailing POST does not ring for a row already sent live."""
    from agent_coord.server.records import push as rec_push

    desk = _sql_desk(cn, "s2-trail-1141")
    posts: list[dict] = []
    lines: list[str] = []
    _arm_http(monkeypatch, posts, lines)
    wake.gate_clear(desk)
    try:
        wid1 = _put_missed(cn, desk, 114121)
        assert rec_push.pending(cn, desk) == 1
        assert wake.post_desk(cn, desk, {"kind": "hint", "type": "todo", "id": 114121}, hint_id=wid1) == "sent"
        assert len(posts) == 1
        wid2 = _put_missed(cn, desk, 114122)
        assert wake.post_desk(cn, desk, {"kind": "hint", "type": "todo", "id": 114122}, hint_id=wid2) == "coalesced"
        _mark_sent(cn, wid1)
        _mark_sent(cn, wid2)
        assert rec_push.pending(cn, desk) == 0
        assert wake.lease_done(cn, desk) == "none"
        assert len(posts) == 1
        assert any("wake=none reason=drained" in ln for ln in lines)
    finally:
        wake.gate_clear(desk)


@pytest.mark.sql
def test_empty_recheck_under_gate_lock_skips_when_row_is_sent(cn, monkeypatch) -> None:
    """V16/V17: if another connection marks the row sent between the empty
    skip and the take, the re-check under the gate lock skips and takes no
    lease. The mark is committed on a second connection, not post_desk's cn,
    so a stale REPEATABLE READ snapshot cannot hide the hand-over (D1/T1).
    """
    from agent_coord.server.records import push as rec_push

    desk = _sql_desk(cn, "s2-race-1141")
    posts: list[dict] = []
    lines: list[str] = []
    _arm_http(monkeypatch, posts, lines)
    wake.gate_clear(desk)
    wid = _put_missed(cn, desk, 114131)

    def mark_sent_from_other(url):
        # After the first empty check, before the take: same window as
        # _settle_row, which marks sent on its own Book() connection.
        c2 = _second_cn()
        try:
            rec_push.mark(c2, wid, "sent")
            c2.commit()
        finally:
            c2.close()
        return (url, "hooks.example.test")

    monkeypatch.setattr(wake, "check_url", mark_sent_from_other)
    try:
        frame = {"watch_id": "w-race", "desk": desk, "kind": "exit", "exit_code": 0}
        assert wake.post_desk(cn, desk, frame) == "skipped"
        assert posts == []
        assert any("skipped reason=empty" in ln for ln in lines)
        assert wake._gate_open(desk, time.monotonic())
    finally:
        wake.gate_clear(desk)
