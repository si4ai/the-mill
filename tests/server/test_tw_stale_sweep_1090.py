"""Card 1090 step 4 (server half): at the cap, sweep this desk's stale task rows.

A start that would hit TASK_CAP first closes the desk's live act=task rows whose
latest transition is older than STALE_AFTER_S (one tw_stale edge each, meta
cause=sweep). When the desk is still at the cap, the cap reply names the oldest
live watch ids. Below the cap nothing is swept.
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

        def scores():
            return rows(cn, "SELECT kpi, value FROM score JOIN name ON name.id=score.desk_id WHERE name.name=%s ORDER BY kpi", (name,))

        return SimpleNamespace(name=name, event=event, tasks=tasks, edges=edges, age=age, scores=scores, pings=pings)

    return make


def fill(d, n=8):
    for i in range(n):
        assert d.event(f"w{i}", "start")["ok"] is True


def stale_edges(d, wid=None):
    return [e for e in d.edges(wid) if e["reason"] == "tw_stale"]


@pytest.mark.sql
@pytest.mark.fresh_schema
def test_s1_start_at_cap_sweeps_only_old_rows_and_is_accepted(desk):
    d = desk()
    fill(d)
    d.event("w2", "stall", cause="quiet")  # an old waiting row is swept too
    old = ("w0", "w2", "w5")
    for wid in old:
        d.age(wid, 25)
    young_before = {w: d.edges(w) for w in (f"w{i}" for i in range(8)) if w not in old}
    reply = d.event("new", "start")
    assert reply["ok"] is True
    assert [e["reason"] for e in d.edges("new")] == ["tw_start", "score_point"]
    for wid in old:
        swept = stale_edges(d, wid)
        assert len(swept) == 1, wid
        e = swept[0]
        assert e["to_state"] == "stale"
        assert e["from_state"] == ("waiting" if wid == "w2" else "active")
        meta = json.loads(e["meta"])
        assert meta["cause"] == "sweep" and meta["watch_id"] == wid
        assert meta["age_s"] >= 25 * 3600 - 5
    assert {w: d.edges(w) for w in young_before} == young_before
    assert len(d.tasks()) == 9
    # Live now: 5 young + new = 6; two more fit, the third hits the cap again.
    assert d.event("a", "start")["ok"] is True
    assert d.event("b", "start")["ok"] is True
    assert d.event("c", "start")["code"] == "cap"
    assert len(stale_edges(d)) == 3  # a second sweep finds nothing old


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
    d.age("w0", 30)
    assert d.event("new", "start")["ok"] is True
    assert len(stale_edges(d, "w0")) == 1
    before = (d.edges(), d.scores(), len(d.pings))
    for kind, kw in (("exit", {"exit_code": 0}), ("crash", {}), ("stall", {"cause": "quiet"}), ("start", {})):
        assert d.event("w0", kind, **kw)["ok"] is True
    assert (d.edges(), d.scores(), len(d.pings)) == before
