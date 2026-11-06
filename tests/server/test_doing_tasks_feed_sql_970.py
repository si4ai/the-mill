"""Card 970: task summaries from doing rows, independent of the focus pointer."""
from types import SimpleNamespace

import pytest

from agent_coord.server.api.mill import rpc
from agent_coord.server.records import doing, join, todo
from agent_coord.server.records.db import call, rows_done
from tests import sql_book

pytestmark = pytest.mark.sql


@pytest.fixture
def feed(cn, monkeypatch):
    # cn is module-scoped; start each test from an empty book so one test's tasks never leak into the next.
    sql_book.reset_data(cn)
    monkeypatch.setattr("agent_coord.server.wake.post_desk", lambda *a, **k: None)
    join.upsert(cn, "Office", "Builder", "", "a" * 64, "reviewing")
    book = SimpleNamespace(_cn=cn)

    def event(wid, kind, **kw):
        return rpc._h_tw_event(book, {"watch_id": wid, "kind": kind, **kw}, "Office", "Builder")

    def read():
        return rpc._h_session(book, {"desk": "Builder", "all": True}, "", None)[0]

    return event, read


def test_live_tasks_card_wait_and_focus_pointer(cn, feed):
    event, read = feed
    card = todo.insert(cn, "Office", "Builder", body="card for feed")[0]["id"]
    doing.put(cn, "Builder", "reviewing", "todo", card)
    before = rows_done(cn, "SELECT doing_id FROM seat s JOIN name n ON n.id=s.desk_id WHERE n.name=%s", ("Builder",))
    assert event("a", "start", card=card)["ok"]
    assert event("b", "start")["ok"]
    assert event("a", "stall", cause="quiet")["ok"]
    tasks = {t["join_key"]: t for t in read()["tasks"]}
    assert tasks == {
        "task:Builder:a": {"state": "waiting", "join_key": "task:Builder:a", "waiting_on": "quiet", "card": f"todo-{card}"},
        "task:Builder:b": {"state": "active", "join_key": "task:Builder:b"},
    }
    assert read()["doing"] == "reviewing"
    assert rows_done(cn, "SELECT doing_id FROM seat s JOIN name n ON n.id=s.desk_id WHERE n.name=%s", ("Builder",)) == before
    assert doing.history(cn, "Builder")[0]["text"] == "reviewing"


@pytest.mark.parametrize("state", ["finished", "failed", "stale", "cleared"])
def test_terminal_task_is_not_listed(cn, feed, state):
    event, read = feed
    assert event("a", "start")["ok"]
    rows_done(cn, "UPDATE transition SET to_state=%s WHERE join_key=%s", (state, "task:Builder:a"))
    assert read()["tasks"] == []
    assert read()["doing"] == ""


def test_sql_caps_each_desk_and_idle_tasks_do_not_replace_focus(cn, feed):
    _, read = feed
    for i in range(12):
        call(cn, "mill_doing_task", ["Builder", f"task:Builder:w{i}", None, 1])
    join.upsert(cn, "Office", "Validator", "", "b" * 64, "reviewing")
    call(cn, "mill_doing_task", ["Validator", "task:Validator:a", None, 1])
    views = rpc._h_session(SimpleNamespace(_cn=cn), {"all": True}, "", None)
    tasks = {v["owner"]: v["tasks"] for v in views}
    assert len(tasks["Builder"]) == doing.TASK_CAP == 8
    assert tasks["Validator"] == [{"state": "idle"}]
    assert all(t == {"state": "idle"} for t in tasks["Builder"])
    assert read()["doing"] == ""
