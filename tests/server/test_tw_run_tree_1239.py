"""Card 1239: a nested tw run keeps its parent, and connected --run lists that tree.

The parent link lives on the tw_start transition. No new column. A start that
arrives after open_call updates that one row instead of dropping the link.
"""
from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from agent_coord.helpers.errors import CoordError
from agent_coord.server.api.mill import rpc
from agent_coord.server.records import join

pytestmark = [pytest.mark.sql, pytest.mark.fresh_schema]


@pytest.fixture
def desk(cn, monkeypatch):
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)

    def make():
        name = "builder-" + uuid4().hex[:8]
        join.upsert(cn, "Office", name, "", "a" * 64)
        cn.commit()

        def event(wid, kind, **kw):
            return rpc._h_tw_event(SimpleNamespace(_cn=cn), {"watch_id": wid, "kind": kind, **kw}, "Office", name)

        def ws(command, args):
            return rpc.dispatch_ws(SimpleNamespace(_cn=cn), name, command, dict(args))

        def hops(wid):
            from agent_coord.server.records.db import rows_done

            return [r["reason"] for r in rows_done(
                cn, "SELECT reason FROM transition WHERE join_key=%s ORDER BY id", (f"task:{name}:{wid}",))]

        def tree(wid, **kw):
            return rpc._h_session(SimpleNamespace(_cn=cn), {"run": wid, **kw}, "Office", name)

        return SimpleNamespace(name=name, cn=cn, event=event, ws=ws, hops=hops, tree=tree)

    return make


def _ids(tree):
    return [r["watch_id"] for r in tree["runs"]]


def test_a_root_run_is_one_row_with_no_parent(desk):
    d = desk()
    d.event("root", "start")
    got = d.tree("root")
    assert got["n"] == 1
    run = got["runs"][0]
    assert run["watch_id"] == "root" and run["parent_watch_id"] is None
    assert run["end"] is None and run["ended_by"] is None and run["exit_code"] is None
    assert run["state"] == "active"


def test_a_nested_start_is_listed_under_its_parent_and_not_above_itself(desk):
    d = desk()
    d.event("p", "start")
    d.event("a", "start", parent_watch_id="p")
    d.event("g", "start", parent_watch_id="a")
    d.event("b", "start", parent_watch_id="p")
    assert _ids(d.tree("p")) == ["p", "a", "g", "b"]
    assert d.tree("p")["n"] == 4
    assert [r["parent_watch_id"] for r in d.tree("p")["runs"]] == [None, "p", "a", "p"]
    child = d.tree("a")
    assert child["n"] == 2 and _ids(child) == ["a", "g"]
    assert child["runs"][0]["parent_watch_id"] == "p"


def test_a_child_still_running_has_no_end_and_a_waiting_child_stays_waiting(desk):
    d = desk()
    d.event("p", "start")
    d.event("c", "start", parent_watch_id="p")
    live = d.tree("c")["runs"][0]
    assert live["state"] == "active" and live["end"] is None and live["exit_code"] is None
    d.event("c", "stall", cause="quiet")
    waiting = d.tree("c")["runs"][0]
    assert waiting["state"] == "waiting" and waiting["end"] is None and waiting["ended_by"] is None


def test_a_parent_can_end_while_its_child_is_still_live(desk):
    from agent_coord.server.records import doing

    d = desk()
    d.event("p", "start")
    d.event("c", "start", parent_watch_id="p")
    d.event("p", "exit", exit_code=0)
    got = d.tree("p")
    assert got["n"] == 2
    assert got["runs"][0]["end"] and got["runs"][0]["ended_by"] == "finished" and got["runs"][0]["exit_code"] == 0
    assert got["runs"][1]["watch_id"] == "c" and got["runs"][1]["end"] is None and got["runs"][1]["state"] == "active"
    live = doing.live_doings(d.cn, [d.name])[d.name]
    assert live["n"] == 1
    assert live["doings"][0]["watch_id"] == "c" and live["doings"][0]["parent_watch_id"] == "p"


def test_a_missing_parent_row_is_kept_and_is_not_an_error(desk):
    d = desk()
    d.event("orphan", "start", parent_watch_id="gone")
    got = d.tree("orphan")
    assert got["n"] == 1 and got["runs"][0]["parent_watch_id"] == "gone"
    with pytest.raises(CoordError, match="no tw run"):
        d.tree("gone")


def test_a_mill_call_is_not_a_run_and_does_not_change_the_tree(desk):
    d = desk()
    d.event("p", "start")
    d.event("c", "start", parent_watch_id="p")
    d.ws("inbox", {"watch_id": "p"})
    got = d.tree("p")
    assert _ids(got) == ["p", "c"]
    assert got["runs"][0]["calls_n"] == 1 and got["runs"][0]["state"] == "active"
    assert got["runs"][1]["calls_n"] == 0
    assert "inbox" not in _ids(got)


def test_a_start_after_open_call_keeps_one_tw_start_and_stores_the_parent(desk):
    d = desk()
    d.ws("inbox", {"watch_id": "early"})
    assert d.event("early", "start", parent_watch_id="root")["ok"] is True
    assert d.hops("early").count("tw_start") == 1
    assert d.tree("early")["runs"][0]["parent_watch_id"] == "root"
    d.event("early", "start")
    d.event("early", "start", parent_watch_id="other")
    assert d.hops("early").count("tw_start") == 1
    assert d.tree("early")["runs"][0]["parent_watch_id"] == "root"


def test_a_bad_parent_or_a_self_parent_is_refused_and_writes_nothing(desk):
    d = desk()
    for bad in ("has space", "x" * 65, 1, True, "early"):
        with pytest.raises(CoordError, match="parent_watch_id"):
            d.event("early", "start", parent_watch_id=bad)
    assert d.hops("early") == []


def test_a_parent_on_a_later_hop_is_ignored(desk):
    d = desk()
    d.event("c", "start")
    assert d.event("c", "exit", exit_code=0, parent_watch_id="p")["ok"] is True
    run = d.tree("c")["runs"][0]
    assert run["parent_watch_id"] is None and run["ended_by"] == "finished"


def test_an_unknown_field_on_the_start_is_ignored(desk):
    d = desk()
    out = d.event("c", "start", parent_watch_id="p", mystery="nope")
    assert out["ok"] is True and "mystery" not in out
    assert "mystery" not in d.tree("c")["runs"][0]


def test_a_cycle_stops(desk):
    d = desk()
    d.event("a", "start", parent_watch_id="b")
    d.event("b", "start", parent_watch_id="a")
    assert d.tree("a")["n"] == 2 and set(_ids(d.tree("a"))) == {"a", "b"}
