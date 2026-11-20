"""Card 1223 part B: the office side of a mill call a tw run's descendant forwards.

tw stamps the run's watch id on the call. The office runs the command as the desk, keeps one tw_call row on
the run, refuses a call on an ended run, and `mill connected --run WATCH_ID` lists the run and its calls.
"""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server import records
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


def rows(cn, sql, args=()):
    cur = cn.cursor(dictionary=True)
    try:
        cur.execute(sql, args)
        return cur.fetchall()
    finally:
        cur.close()
        cn.commit()


@pytest.fixture
def desk(cn, monkeypatch):
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)

    def make():
        name = "builder-" + uuid4().hex[:8]
        join.upsert(cn, "Office", name, "", "a" * 64)
        cn.commit()

        def event(wid, kind, **kw):
            return rpc._h_tw_event(SimpleNamespace(_cn=cn), {"watch_id": wid, "kind": kind, **kw}, "Office", name)

        def ws(command, args, conn=None):
            return rpc.dispatch_ws(SimpleNamespace(_cn=conn or cn), name, command, dict(args))

        def calls(wid):
            out = rows(cn, "SELECT from_state, to_state, meta FROM transition WHERE join_key=%s AND reason='tw_call'"
                       " ORDER BY id", (f"task:{name}:{wid}",))
            return [dict(r, meta=json.loads(r["meta"])) for r in out]

        def hops(wid):
            return [r["reason"] for r in rows(cn, "SELECT reason FROM transition WHERE join_key=%s ORDER BY id",
                                               (f"task:{name}:{wid}",))]

        def tree(wid, **kw):
            return rpc._h_session(SimpleNamespace(_cn=cn), {"run": wid, **kw}, "Office", name)

        return SimpleNamespace(name=name, event=event, ws=ws, calls=calls, hops=hops, tree=tree)

    return make


def test_a_tagged_call_runs_as_the_desk_and_is_recorded_on_its_run(desk):
    d = desk()
    assert d.event("w1", "start")["ok"] is True
    out = d.ws("inbox", {"watch_id": "w1"})
    assert isinstance(out, list)
    got = d.calls("w1")
    assert len(got) == 1
    assert got[0]["from_state"] == got[0]["to_state"] == "active"
    assert got[0]["meta"] == {"watch_id": "w1", "verb": "inbox", "ok": True}


def test_a_refused_tagged_call_is_recorded_as_refused_and_still_refuses(desk):
    d = desk()
    d.event("w1", "start")
    with pytest.raises(CoordError):
        d.ws("todo", {"watch_id": "w1", "project": "the-mill", "need": "no-such-card-" + uuid4().hex[:6],
                      "progress": "1/2"})
    got = d.calls("w1")
    assert [c["meta"] for c in got] == [{"watch_id": "w1", "verb": "todo", "ok": False, "err": "refused"}]


def test_a_call_on_an_ended_run_is_refused_and_nothing_runs(desk, cn):
    d = desk()
    d.event("w1", "start")
    d.event("w1", "exit", exit_code=0)
    res = "r-" + uuid4().hex[:8]
    with pytest.raises(CoordError, match="has ended"):
        d.ws("hold", {"watch_id": "w1", "resource": res})
    assert d.calls("w1") == []
    held = rows(cn, "SELECT h.desk_id FROM hold h JOIN name n ON n.id=h.resource_id WHERE n.name=%s", (res,))
    assert not held or held[0]["desk_id"] is None


def test_a_bad_watch_id_is_refused_before_the_command(desk):
    d = desk()
    for bad in ("a b", "x" * 65, "", True, "w;1"):
        with pytest.raises(CoordError, match="not a tw watch id"):
            d.ws("inbox", {"watch_id": bad})


def test_a_call_that_beats_tw_start_opens_the_run_and_tw_start_is_a_repeat(desk):
    d = desk()
    d.ws("inbox", {"watch_id": "early"})
    assert d.event("early", "start")["ok"] is True
    assert d.hops("early").count("tw_start") == 1
    assert len(d.calls("early")) == 1
    assert d.tree("early")["runs"][0]["state"] == "active"


def test_a_call_past_the_task_cap_is_a_loud_refusal(desk):
    from agent_coord.server.records import doing

    d = desk()
    for i in range(doing.TASK_CAP):
        assert d.event(f"w{i}", "start")["ok"] is True
    with pytest.raises(CoordError, match="live tasks"):
        d.ws("inbox", {"watch_id": "one-too-many"})
    assert d.hops("one-too-many") == []


def test_tw_hops_keep_their_own_watch_id(desk):
    d = desk()
    out = d.ws("tw.event", {"watch_id": "hop", "kind": "start"})
    assert out["ok"] is True and out["watch_id"] == "hop"
    assert d.calls("hop") == []


def test_connected_run_lists_start_end_exit_code_and_each_call(desk):
    d = desk()
    d.event("w1", "start")
    d.ws("inbox", {"watch_id": "w1"})
    with pytest.raises(CoordError):
        d.ws("todo", {"watch_id": "w1", "project": "the-mill", "need": "missing-" + uuid4().hex[:6],
                      "progress": "1/2"})
    live = d.tree("w1")["runs"][0]
    assert live["end"] is None and live["exit_code"] is None and live["state"] == "active"
    d.event("w1", "exit", exit_code=3)
    run = d.tree("w1")["runs"][0]
    assert run["watch_id"] == "w1" and run["desk"] == d.name
    assert run["start"].endswith("Z") and run["end"].endswith("Z")
    assert run["ended_by"] == "failed" and run["exit_code"] == 3 and run["state"] == "failed"
    assert (run["calls_n"], run["ok_n"], run["failed_n"]) == (2, 1, 1)
    assert [(c["verb"], c["ok"]) for c in run["calls"]] == [("inbox", True), ("todo", False)]
    assert run["calls"][1]["err"] == "refused"


def test_connected_run_refuses_an_unknown_run_and_other_flags(desk):
    d = desk()
    with pytest.raises(CoordError, match="no tw run"):
        d.tree("nope")
    d.event("w1", "start")
    with pytest.raises(CoordError, match="takes only --who"):
        d.tree("w1", history=True)


def test_connected_run_reads_another_desks_run_with_who(desk):
    a, b = desk(), desk()
    a.event("w1", "start")
    assert b.tree("w1", desk=a.name)["runs"][0]["desk"] == a.name
    with pytest.raises(CoordError, match="no tw run"):
        b.tree("w1")


def test_a_call_does_not_move_the_runs_state_at(desk, cn):
    from agent_coord.server.records import doing

    d = desk()
    d.event("w1", "start")
    before = doing.live_doings(cn, [d.name])[d.name]["doings"][0]["state_at"]
    time.sleep(1.1)
    d.ws("inbox", {"watch_id": "w1"})
    after = doing.live_doings(cn, [d.name])[d.name]["doings"][0]
    assert after["state_at"] == before and after["state"] == "active"


def test_concurrent_calls_from_many_descendants_all_succeed_with_the_run_watch_id(desk, cn):
    d = desk()
    d.event("w1", "start")
    need = "load-" + uuid4().hex[:6]
    d.ws("open", {"project": "Office", "need": need})
    cn.commit()
    db = rows(cn, "SELECT DATABASE() d")[0]["d"]
    n = 32
    errors: list[BaseException] = []
    go = threading.Barrier(n)

    def one(i: int) -> None:
        conn = records.connect(db)
        try:
            go.wait()
            d.ws("todo", {"watch_id": "w1", "project": "Office", "need": need, "progress": f"{i}/{n}"}, conn)
            d.ws("inbox", {"watch_id": "w1"}, conn)
        except BaseException as e:  # noqa: BLE001 - every failure is reported below
            errors.append(e)
        finally:
            conn.close()

    threads = [threading.Thread(target=one, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert errors == []
    got = d.calls("w1")
    assert len(got) == 2 * n
    assert all(c["meta"]["watch_id"] == "w1" and c["meta"]["ok"] is True for c in got)
    assert sorted(c["meta"]["verb"] for c in got) == ["inbox"] * n + ["todo"] * n


def test_migrate_adds_the_tw_call_edges_once(cn):
    from agent_coord.install import migrate

    cur = cn.cursor()
    try:
        cur.execute("DELETE FROM transition_edge WHERE reason='tw_call'")
        cn.commit()
    finally:
        cur.close()
    assert migrate._ensure_tw_call_edges(cn) == ["transition_edge.tw_call_1223"]
    assert migrate._ensure_tw_call_edges(cn) == []
    got = rows(cn, "SELECT from_state, to_state FROM transition_edge WHERE reason='tw_call' ORDER BY from_state")
    assert [(r["from_state"], r["to_state"]) for r in got] == [("active", "active"), ("waiting", "waiting")]
