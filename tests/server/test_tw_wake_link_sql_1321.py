# -*- coding: utf-8 -*-
"""Card 1321: on a real book, a woken run's tw_start names the wake that rang it; a manual run names none."""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_coord.server import wake_lease
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join
from agent_coord.server.records import push as rec_push

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


@pytest.fixture
def desk(cn, monkeypatch):
    name = "builder-" + uuid4().hex[:8]
    join.upsert(cn, "Office", name, "", "a" * 64)
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)
    return name


def _start_meta(cn, desk, wid):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute("SELECT meta FROM transition WHERE activity_type='doing' AND join_key=%s AND reason='tw_start'",
                    (f"task:{desk}:{wid}",))
        rows = cur.fetchall()
    finally:
        cur.close()
    assert len(rows) == 1
    return json.loads(rows[0]["meta"])


def _ring(cn, desk) -> tuple[str, int]:
    """One wake row for the desk and its lease ring, as wake.post_desk records them."""
    frame = {"kind": "hint", "type": "todo", "id": 1321}
    wake_id = rec_push.row_id(rec_push.put(cn, desk, "hint", frame, "missed"))
    token = uuid4().hex[:12]
    assert wake_lease.record_ring(cn, desk, token, wake_id) == wake_id
    return token, wake_id


def _event(cn, desk, wid, kind, **kw):
    return rpc._h_tw_event(SimpleNamespace(_cn=cn), {"watch_id": wid, "kind": kind, **kw}, "Office", desk)


def test_woken_start_carries_the_lease_and_wake_and_manual_start_carries_none(cn, desk):
    token, wake_id = _ring(cn, desk)
    _event(cn, desk, "woken", "start", wake_lease=token)
    _event(cn, desk, "hand", "start")
    woken = _start_meta(cn, desk, "woken")
    assert (woken["lease"], woken["wake_id"]) == (token, wake_id)
    hand = _start_meta(cn, desk, "hand")
    assert not {"lease", "wake_id", "dropped"} & set(hand)


def test_another_desks_lease_is_dropped(cn, desk):
    other = "builder-" + uuid4().hex[:8]
    join.upsert(cn, "Office", other, "", "b" * 64)
    token, _wake_id = _ring(cn, other)
    _event(cn, desk, "borrowed", "start", wake_lease=token)
    meta = _start_meta(cn, desk, "borrowed")
    assert not {"lease", "wake_id"} & set(meta)
    assert meta["dropped"] == ["wake_lease"]


def test_a_repeat_start_adds_the_link_to_the_one_start(cn, desk):
    from agent_coord.server.records import doing

    token, wake_id = _ring(cn, desk)
    doing.open_call(cn, desk, "early")  # a child's mill call opens the run first (card 1223)
    _event(cn, desk, "early", "start", wake_lease=token)
    meta = _start_meta(cn, desk, "early")
    assert (meta["lease"], meta["wake_id"]) == (token, wake_id)
