"""Card 1090 step 4 (server half): at the cap, sweep this desk's stale task rows.

A live act=task row is stale only once its desk has been offline (no connected
seat) for STALE_AFTER_S; a connected desk's rows are never stale, at any age.
A start that would hit TASK_CAP first closes the stale rows (one tw_stale edge
each, meta cause=sweep). When the desk is still at the cap, the cap reply names
the oldest live watch ids. Below the cap nothing is swept. Glance alerts report
offline desks with live rows (a fact, not a gate). Dwell uses tw's ts_ms.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing, join


def test_stale_after_is_one_named_constant_of_a_day():
    assert doing.STALE_AFTER_S == 24 * 3600


def test_cap_msg_names_the_oldest_watch_ids_with_ages():
    msg = doing.cap_msg([("w0", 90061), ("w1", 7200), ("w2", 59)])
    assert msg.startswith(f"tw.event: desk already has {doing.TASK_CAP} live tasks")
    assert "w0 (1d1h)" in msg and "w1 (2h)" in msg and "w2 (59s)" in msg
    assert msg.index("w0") < msg.index("w1") < msg.index("w2")
    assert "tw stop" in msg


def test_cap_msg_with_no_rows_keeps_the_plain_line():
    assert doing.cap_msg([]) == f"tw.event: desk already has {doing.TASK_CAP} live tasks"


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
        join.upsert(cn, "Office", name, "", "a" * 64, "reviewing")

        def event(wid, kind, **kw):
            return rpc._h_tw_event(SimpleNamespace(_cn=cn), {"watch_id": wid, "kind": kind, **kw}, "Office", name)

        def tasks():
            return rows(cn, "SELECT g.id FROM doing g JOIN name n ON n.id=g.desk_id WHERE n.name=%s AND g.act='task'", (name,))

        def edges(wid=None):
            if wid is None:
                return rows(cn, "SELECT * FROM transition WHERE join_key LIKE %s ORDER BY id", (f"task:{name}:%",))
            return rows(cn, "SELECT * FROM transition WHERE join_key=%s ORDER BY id", (f"task:{name}:{wid}",))

        def age(wid, hours):
            """Backdate a watch's doing transitions, as if its last hop was hours ago."""
            cur = cn.cursor()
            try:
                cur.execute(
                    "UPDATE transition SET at = at - INTERVAL %s HOUR"
                    " WHERE activity_type='doing' AND join_key=%s",
                    (hours, f"task:{name}:{wid}"),
                )
                cn.commit()  # the next hop opens its own request tx
            finally:
                cur.close()

        def seat(offline_h=None):
            """Connected now (None), or offline since offline_h hours ago."""
            cur = cn.cursor()
            try:
                if offline_h is None:
                    cur.execute(
                        "UPDATE seat j JOIN name n ON n.id=j.desk_id SET j.time_connect=MILL_NOW(),"
                        " j.time_disconnect=NULL WHERE n.name=%s AND n.type='desk'", (name,))
                else:
                    cur.execute(
                        "UPDATE seat j JOIN name n ON n.id=j.desk_id"
                        " SET j.time_connect=MILL_NOW() - INTERVAL %s HOUR,"
                        " j.time_disconnect=MILL_NOW() - INTERVAL %s MINUTE"
                        " WHERE n.name=%s AND n.type='desk'",
                        (offline_h + 1, int(offline_h * 60), name))
                assert cur.rowcount == 1
                cn.commit()
            finally:
                cur.close()

        def scores():
            return rows(cn, "SELECT kpi, value FROM score JOIN name ON name.id=score.desk_id WHERE name.name=%s ORDER BY kpi", (name,))

        return SimpleNamespace(name=name, event=event, tasks=tasks, edges=edges, age=age, seat=seat,
                               scores=scores, pings=pings)

    return make


def fill(d, n=8):
    for i in range(n):
        assert d.event(f"w{i}", "start")["ok"] is True


def stale_edges(d, wid=None):
    return [e for e in d.edges(wid) if e["reason"] == "tw_stale"]


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_s1_start_at_cap_on_a_desk_offline_a_day_sweeps_its_live_rows(desk):
    d = desk()
    fill(d)
    d.event("w2", "stall", cause="quiet")  # a waiting row is swept too
    d.age("w0", 1)  # row age does not matter; only the desk's offline time does
    d.seat(offline_h=25)
    reply = d.event("new", "start")
    assert reply["ok"] is True
    assert [e["reason"] for e in d.edges("new")] == ["tw_start", "score_point"]
    for i in range(8):
        wid = f"w{i}"
        swept = stale_edges(d, wid)
        assert len(swept) == 1, wid
        e = swept[0]
        assert e["to_state"] == "stale"
        assert e["from_state"] == ("waiting" if wid == "w2" else "active")
        meta = json.loads(e["meta"])
        assert meta["cause"] == "sweep" and meta["watch_id"] == wid
        assert meta["offline_s"] >= 25 * 3600 - 5
    assert len(d.tasks()) == 9
    assert len(stale_edges(d)) == 8
    # A second start does not re-sweep the already stale rows.
    assert d.event("a", "start")["ok"] is True
    assert len(stale_edges(d)) == 8


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_s1b_connected_desk_is_never_stale_at_any_age(desk):
    d = desk()
    fill(d)
    for i in range(8):
        d.age(f"w{i}", 24 * 30)
    d.seat()  # connected now
    reply = d.event("w8", "start")
    assert reply["ok"] is False and reply["code"] == "cap"
    assert stale_edges(d) == []
    assert "offline" in reply["msg"]


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_s1c_desk_offline_under_a_day_is_not_stale(desk):
    d = desk()
    fill(d)
    for i in range(8):
        d.age(f"w{i}", 48)
    d.seat(offline_h=23)
    assert d.event("w8", "start")["code"] == "cap"
    assert stale_edges(d) == []


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_s2_at_cap_with_no_old_rows_names_oldest_watch_ids_and_writes_nothing(desk):
    d = desk()
    fill(d)
    d.age("w3", 5)
    d.age("w6", 3)
    before = (d.tasks(), d.edges(), d.scores(), len(d.pings))
    reply = d.event("w8", "start", title="SECRET")
    assert reply["ok"] is False and reply["code"] == "cap"
    msg = reply["msg"]
    assert msg.startswith(f"tw.event: desk already has {doing.TASK_CAP} live tasks")
    assert "w3 (5h)" in msg and "w6 (3h)" in msg
    assert msg.index("w3") < msg.index("w6")
    assert "SECRET" not in repr(reply)
    assert (d.tasks(), d.edges(), d.scores(), len(d.pings)) == before


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_s3_below_cap_old_rows_are_not_swept(desk):
    d = desk()
    fill(d, 7)
    for i in range(7):
        d.age(f"w{i}", 48)
    d.seat(offline_h=48)
    assert d.event("w7", "start")["ok"] is True  # 8th live: still fits, no sweep
    assert stale_edges(d) == []
    assert len(d.tasks()) == 8


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_s4_replayed_start_and_exit_write_one_row_and_one_score_point_per_phase(desk):
    d = desk()
    for _ in range(2):  # the second pass is a client spool replay
        assert d.event("r", "start", counts={"replay": 1})["ok"] is True
        assert d.event("r", "exit", exit_code=0, counts={"replay": 1})["ok"] is True
    assert len(d.tasks()) == 1
    reasons = [e["reason"] for e in d.edges("r")]
    assert reasons.count("tw_start") == 1 and reasons.count("tw_finished") == 1
    phases = [json.loads(e["meta"])["phase"] for e in d.edges("r") if e["reason"] == "score_point"]
    assert phases == ["start", "finished"]
    assert len(d.pings) == 1


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_s5_exit_on_a_swept_watch_is_a_noop(desk):
    d = desk()
    fill(d)
    d.seat(offline_h=30)
    assert d.event("new", "start")["ok"] is True
    assert len(stale_edges(d, "w0")) == 1
    before = (d.edges(), d.scores(), len(d.pings))
    for kind, kw in (("exit", {"exit_code": 0}), ("crash", {}), ("stall", {"cause": "quiet"}), ("start", {})):
        assert d.event("w0", kind, **kw)["ok"] is True
    assert (d.edges(), d.scores(), len(d.pings)) == before


def test_offline_tasks_shapes_a_fact_per_desk():
    got = doing.offline_tasks([("builder", 90061, 3), ("tui", 60, 1), ("bad", None, 1)])
    assert got == [
        {"desk": "builder", "offline_s": 90061, "offline": "1d1h", "live_n": 3, "sweepable": True},
        {"desk": "tui", "offline_s": 60, "offline": "1m", "live_n": 1, "sweepable": False},
    ]
    assert doing.offline_tasks(None) == []


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_h1_glance_reports_offline_desks_with_live_rows(desk, cn):
    from agent_coord.server import glance

    off, on, done = desk(), desk(), desk()
    fill(off, 2)
    off.seat(offline_h=25)
    fill(on, 2)
    on.seat()
    assert done.event("x", "start")["ok"] is True
    assert done.event("x", "exit", exit_code=0)["ok"] is True
    done.seat(offline_h=30)
    by = {r["desk"]: r for r in glance._tw_offline(cn)}
    assert on.name not in by and done.name not in by
    row = by[off.name]
    assert row["live_n"] == 2 and row["sweepable"] is True
    assert row["offline_s"] >= 25 * 3600 - 5 and row["offline"].startswith("1d")
    assert stale_edges(off) == []  # reporting writes nothing


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_d1_dwell_uses_tw_ts_ms_not_host_receive_time(desk):
    d = desk()
    assert d.event("r", "start", ts_ms=1_000)["ok"] is True
    d.age("r", 5)  # host stamps say hours; tw's own clock says one minute
    assert d.event("r", "exit", exit_code=0, ts_ms=61_000)["ok"] is True
    finished = [json.loads(e["meta"]) for e in d.edges("r") if e["reason"] == "score_point"][-1]
    assert finished["phase"] == "finished"
    assert finished["dwell_active_ms"] == 60_000


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_d2_dwell_without_ts_ms_falls_back_to_host_time(desk):
    d = desk()
    assert d.event("r", "start")["ok"] is True
    d.age("r", 1)
    assert d.event("r", "exit", exit_code=0)["ok"] is True
    finished = [json.loads(e["meta"]) for e in d.edges("r") if e["reason"] == "score_point"][-1]
    assert finished["dwell_active_ms"] >= 3600 * 1000 - 5000


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_d3_ts_ms_must_be_a_non_negative_integer(desk):
    from agent_coord.helpers.errors import CoordError

    d = desk()
    for bad in (-1, "5", 1.5, True):
        with pytest.raises(CoordError):
            d.event("r", "start", ts_ms=bad)
