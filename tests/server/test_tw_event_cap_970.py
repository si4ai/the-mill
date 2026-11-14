"""Card 970 step 4: per-desk cap of live task doing rows on tw.event start."""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_coord.server import records
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing, join
from agent_coord.server.records.db import request_tx

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


def rows(cn, sql, args=()):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()


@pytest.fixture
def desk(cn, monkeypatch):
    pings = []
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: pings.append((a, k)))

    def make():
        name = "builder-" + uuid4().hex[:8]
        join.upsert(cn, "Office", name, "", "a" * 64)

        def event(wid, kind, conn=None, **kw):
            return rpc._h_tw_event(SimpleNamespace(_cn=conn or cn), {"watch_id": wid, "kind": kind, **kw}, "Office", name)

        def tasks(conn=None):
            return rows(conn or cn, "SELECT g.id FROM doing g JOIN name n ON n.id=g.desk_id WHERE n.name=%s", (name,))

        def edges(wid=None):
            if wid is None:
                return rows(cn, "SELECT * FROM transition WHERE join_key LIKE %s ORDER BY id", (f"task:{name}:%",))
            return rows(cn, "SELECT * FROM transition WHERE join_key=%s ORDER BY id", (f"task:{name}:{wid}",))

        def score_rows():
            return rows(cn, "SELECT s.kpi, JSON_UNQUOTE(JSON_EXTRACT(s.meta, '$.reading')) AS value FROM score s JOIN name ON name.id=s.desk_id WHERE name.name=%s ORDER BY s.kpi", (name,))

        return SimpleNamespace(name=name, event=event, tasks=tasks, edges=edges, scores=score_rows, pings=pings)

    return make


def fill(d, n=8):
    for i in range(n):
        assert d.event(f"w{i}", "start")["ok"] is True


def test_cap_is_eight(desk):
    assert doing.TASK_CAP == 8


def test_eight_live_starts_birth_and_ninth_is_refused_with_nothing_written(desk):
    d = desk()
    fill(d)
    d.event("w1", "stall", cause="quiet")  # waiting rows are still live
    assert len(d.tasks()) == 8
    assert len({e["activity_id"] for e in d.edges() if e["reason"] == "tw_start"}) == 8
    before = (d.tasks(), d.edges(), d.scores(), len(d.pings))
    reply = d.event("w8", "start", card=970, title="SECRET", argv=["SECRET"])
    assert reply["ok"] is False and reply["code"] == "cap"
    assert isinstance(reply["msg"], str) and reply["msg"]
    assert "SECRET" not in repr(reply)
    assert d.edges("w8") == []
    assert (d.tasks(), d.edges(), d.scores(), len(d.pings)) == before


def test_retried_start_of_existing_watch_at_cap_is_not_a_new_row(desk):
    d = desk()
    fill(d)
    n = len(d.edges())
    assert d.event("w0", "start")["ok"] is True
    assert len(d.tasks()) == 8 and len(d.edges()) == n


@pytest.mark.parametrize("end,extra", [("exit", {"exit_code": 0}), ("exit", {"exit_code": 2}), ("crash", {})])
def test_finished_or_failed_frees_a_slot_for_a_new_watch(desk, end, extra):
    d = desk()
    fill(d)
    assert d.event("late", "start")["code"] == "cap"
    assert d.event("w0", end, **extra)["ok"] is True
    # The refused start retries on reconnect and is now born.
    assert d.event("late", "start")["ok"] is True
    assert [e["reason"] for e in d.edges("late")] == ["tw_start", "score_point"]
    assert len(d.tasks()) == 9
    assert d.event("another", "start")["code"] == "cap"


def test_cap_is_per_desk(desk):
    a, b = desk(), desk()
    fill(a)
    assert a.event("w8", "start")["code"] == "cap"
    assert b.event("w8", "start")["ok"] is True


def test_refused_watch_has_no_row_for_later_hops(desk):
    d = desk()
    fill(d)
    assert d.event("w8", "start")["code"] == "cap"
    from agent_coord.helpers.errors import CoordError

    with pytest.raises(CoordError, match="start required"):
        d.event("w8", "stall", cause="quiet")
    assert d.edges("w8") == []


def test_cap_counts_only_task_rows_not_stale_or_cleared_states(desk, cn):
    d = desk()
    fill(d, 7)
    assert doing.live_tasks(cn, rows(cn, "SELECT id FROM name WHERE name=%s AND type='desk'", (d.name,))[0]["id"]) == 7
    assert not {"tw_stale", "wait_cycle", "clear"} & {e["reason"] for e in d.edges()}


def test_retried_start_of_waiting_watch_at_cap_is_a_noop(desk):
    d = desk()
    fill(d)
    assert d.event("w3", "stall", cause="quiet")["ok"] is True
    n, w = len(d.edges("w3")), len(d.pings)
    assert d.event("w3", "start")["ok"] is True
    assert len(d.edges("w3")) == n and len(d.pings) == w and len(d.tasks()) == 8
    assert d.event("w3", "exit", exit_code=1)["ok"] is True
    reasons = [e["reason"] for e in d.edges("w3")]
    assert "tw_failed" in reasons and reasons[-1] == "score_point"
    assert len(d.pings) == w + 1


def test_concurrent_starts_at_seven_live_birth_only_one(desk, cn):
    d = desk()
    fill(d, 7)
    cn.commit()
    db = rows(cn, "SELECT DATABASE() d")[0]["d"]
    ca, cb = records.connect(db), records.connect(db)
    out = {}

    def run_a():
        def body():
            out["a"] = d.event("A", "start", conn=ca)
            time.sleep(1.5)  # hold the seat lock while B arrives
            return out["a"]
        request_tx(ca, body)

    def run_b():
        time.sleep(0.4)
        t0 = time.monotonic()
        out["b"] = request_tx(cb, lambda: d.event("B", "start", conn=cb))
        out["b_wait_s"] = time.monotonic() - t0

    try:
        ta, tb = threading.Thread(target=run_a), threading.Thread(target=run_b)
        ta.start(); tb.start(); ta.join(); tb.join()
        cc = records.connect(db)
        try:
            n = len(d.tasks(cc))
        finally:
            cc.close()
    finally:
        ca.close(); cb.close()
    assert out["a"]["ok"] is True
    assert out["b_wait_s"] > 0.8, out  # B really blocked on the seat lock
    assert out["b"].get("code") == "cap", out
    assert n == 8
